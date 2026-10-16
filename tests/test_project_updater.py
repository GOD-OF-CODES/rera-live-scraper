import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

import pytest

from src.project_snapshots import ProjectSnapshots
from src.project_updater import UpdateStore, content_hash, parse_candidate
from src.search_catalog import Catalog
from scripts.update_rera_database import run

REG = 'UPRERAPRJ123/10/2026'
URL = 'https://up-rera.in/Frm_View_Project_Details.aspx?id=12345'


def candidate(stamp='2026-10-16T00:00:00+00:00', number='123/4', address='Sector 150 Noida'):
    row = dict(registration_number=REG, details_url=URL, project_name='Example',
               promoter_name='Example Builder', district='Gautam Buddha Nagar', project_type='Residential',
               directory_at='2026-10-14T00:00:00+00:00')
    data = {'page': {'url': URL, 'title': 'RERA'},
            'identification': {'project_id': REG, 'project_name': 'Example'},
            'basic_details': {'district': row['district'], 'address': address},
            'documents': [{'document_name': 'Deed', 'download_url': 'https://up-rera.in/example.pdf'}],
            'land_details': {'khasra_plot_details': [{'type': 'Khasra', 'khasra_plot_number': number}]},
            'unknown_field': {'keep': ['हिन्दी', '001', '1.00', None, False]}}
    result = dict(source='UP-RERA', fetch_mode='live', from_cache=False, persisted=False,
                  registration_number=REG, project_found=True, project_details_available=True,
                  requested_at=stamp, scraped_at=stamp, project_details_url=URL, property_data=data)
    record = dict(row, indexed_source_at=stamp, property_data={'basic_details': data['basic_details'],
        'search_parcels': [{'number': number, 'kinds': ['khasra'], 'explicit_type': True,
                           'source': 'Published RERA land record: Khasra'}]})
    return {'result': result, 'row': row, 'record': record}


@pytest.fixture(params=['sqlite', 'postgres'])
def catalog(request, tmp_path):
    if request.param == 'sqlite':
        db = Catalog(tmp_path / 'data.sqlite')
        db.initialize()
        yield db
        return
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL for real PostgreSQL updater transactions')
    import psycopg
    from psycopg import sql
    schema = 'updater_' + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        parts = urlsplit(url)
        scoped = urlunsplit(parts._replace(query=urlencode(parse_qsl(parts.query) + [('options', '-csearch_path=' + schema)])))
        try:
            db = Catalog(scoped)
            db.initialize()
            yield db
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def seed(catalog):
    old = candidate('2026-10-14T00:00:00+00:00')
    catalog.import_rows([old['row']], old['row']['directory_at'], {REG: old['record']})
    ProjectSnapshots(catalog).put_many([old['result']])
    return old


def state(catalog):
    with catalog.connection() as conn:
        return dict(conn.execute('SELECT * FROM rera_update_state').fetchone())


def test_hash_ignores_delivery_metadata_but_preserves_every_source_value():
    old = candidate()['result'];new = copy.deepcopy(old)
    new.update(scraped_at='2027-01-01T00:00:00Z', requested_at='changed', fetch_mode='database', persisted=True)
    new['property_data'] = dict(reversed(list(new['property_data'].items())))
    assert content_hash(new) == content_hash(old)
    for value in ['001 ', 1, True, '1']:
        changed = copy.deepcopy(new);changed['property_data']['unknown_field']['keep'][1] = value
        assert content_hash(changed) != content_hash(old)
    new['property_data']['unknown_field']['keep'].reverse()
    assert content_hash(new) != content_hash(old)


def test_changes_publish_exact_details_and_new_search_tokens_atomically(catalog):
    seed(catalog);store = UpdateStore(catalog);store.initialize()
    new = candidate(number='678/9', address='Sector 160 Noida')
    outcome = store.apply(new)
    assert outcome['status'] == 'changed' and outcome['index_updated']
    assert outcome['sections'] == ['basic_details', 'land_details']
    assert store.snapshots.get(REG, original=True) == new['result']
    assert catalog.search('Khasra 123/4')['total'] == 0
    assert catalog.search('Khasra 678/9')['total'] == 1
    assert catalog.search('Sector 150 Noida')['total'] == 0
    assert catalog.search('Sector 160 Noida')['total'] == 1
    assert state(catalog)['last_changed_at'] == new['result']['scraped_at']


def test_unchanged_check_keeps_compressed_payload_and_original_timestamp(catalog):
    old = seed(catalog);store = UpdateStore(catalog);store.initialize()
    first = store.apply(candidate())
    assert first['status'] == 'unchanged'
    second = store.apply(candidate('2026-10-17T00:00:00+00:00'))
    assert second == {'status': 'unchanged', 'sections': [], 'index_updated': False}
    assert store.snapshots.get(REG, original=True) == old['result']
    assert state(catalog)['last_checked_at'] == '2026-10-17T00:00:00+00:00'
    assert state(catalog)['last_changed_at'] is None


def test_failure_invalid_page_and_old_worker_preserve_good_data(catalog):
    old = seed(catalog);store = UpdateStore(catalog);store.initialize()
    store.apply(candidate('2026-10-18T00:00:00+00:00'))
    # A stale changed result must not replace a more recent unchanged check.
    assert store.apply(candidate(number='stale'))['status'] == 'superseded'
    invalid = candidate('2026-10-19T00:00:00+00:00');invalid['result']['property_data'] = {}
    with pytest.raises(ValueError): store.apply(invalid)
    wrong = candidate();wrong['row']['registration_number'] = 'UPRERAPRJ456'
    with pytest.raises(ValueError): store.apply(wrong)
    store.failed(REG, [{'type': 'HTTPError', 'http_status': 503}])
    assert store.snapshots.get(REG, original=True) == old['result']
    assert catalog.search('Khasra 123/4')['total'] == 1
    assert state(catalog)['last_checked_at'] == '2026-10-18T00:00:00+00:00'


def test_index_write_failure_rolls_back_snapshot_and_state(catalog, monkeypatch):
    old = seed(catalog);store = UpdateStore(catalog);store.initialize()
    def broken(*args, **kwargs): raise RuntimeError('injected index failure')
    monkeypatch.setattr(catalog, 'import_rows', broken)
    with pytest.raises(RuntimeError): store.apply(candidate(number='678/9'))
    assert store.snapshots.get(REG, original=True) == old['result']
    assert catalog.search('Khasra 123/4')['total'] == 1
    with catalog.connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM rera_update_state').fetchone()['n'] == 0


def test_dry_run_writes_no_database_tables_or_data(catalog, tmp_path):
    old = seed(catalog)
    report = run(UpdateStore(catalog), workers=1, dry_run=True, report_path=tmp_path/'report.json',
                 fetcher=lambda row: (candidate(number='678/9'), []), executor=ThreadPoolExecutor)
    assert report['status'] == 'success' and report['changed'] == 1
    assert ProjectSnapshots(catalog).get(REG, original=True) == old['result']
    with catalog.connection() as conn:
        if catalog.postgres:
            assert conn.execute("SELECT to_regclass('rera_update_state') AS name").fetchone()['name'] is None
        else:
            assert conn.execute("SELECT name FROM sqlite_master WHERE name='rera_update_state'").fetchone() is None


def test_missing_snapshot_is_created_and_rerun_is_unchanged(catalog, tmp_path):
    c = candidate();catalog.import_rows([c['row']], c['row']['directory_at'])
    report = run(UpdateStore(catalog), workers=1, report_path=tmp_path/'report.json',
                 fetcher=lambda row: (c, [{'type': 'ReadTimeout'}]), executor=ThreadPoolExecutor)
    assert report['status'] == 'success' and report['created'] == 1 and report['retried'] == 1
    assert ProjectSnapshots(catalog).get(REG, original=True) == c['result']
    report = run(UpdateStore(catalog), workers=1, report_path=tmp_path/'report.json',
                 fetcher=lambda row: (candidate('2026-10-17T00:00:00+00:00'), []), executor=ThreadPoolExecutor)
    assert report['unchanged'] == 1 and report['changed'] == 0


def test_source_outage_stops_scan_and_reports_unattempted(tmp_path):
    db = Catalog(tmp_path/'scan.sqlite');db.initialize();rows=[]
    for n in range(20):
        c = candidate();r=dict(c['row'], registration_number='UPRERAPRJ'+str(n), details_url=URL.replace('12345',str(n)))
        rows.append(r)
    db.import_rows(rows, '2026-10-14T00:00:00+00:00')
    report = run(UpdateStore(db), workers=2, report_path=tmp_path/'report.json',
                 fetcher=lambda row: (None, [{'type':'HTTPError','http_status':503}]), executor=ThreadPoolExecutor)
    assert report['status'] == 'partial' and report['stop_reason'] == 'source_unavailable'
    assert 3 <= report['attempted'] <= 5
    assert report['unattempted'] == 20-report['attempted'] and report['failed'] == report['attempted']
    assert db.coverage()['projects'] == 20


def test_budget_does_not_silently_report_unchecked_projects_as_success(tmp_path):
    db=Catalog(tmp_path/'time.sqlite');db.initialize();seed(db)
    times=iter([0, 1000])
    report=run(UpdateStore(db), workers=1, max_minutes=1, clock=lambda: next(times),
               report_path=tmp_path/'report.json', executor=ThreadPoolExecutor)
    assert report['status']=='partial' and report['stop_reason']=='time_budget' and report['unattempted']==1


def test_same_response_drives_complete_payload_and_typed_search():
    from test_parcel_search import page
    heading='<span id="ctl00_ContentPlaceHolder1_lblProjectNameHeading">Project Name: Test project</span>'
    html='<html><title>RERA</title><body>'+heading+page(REG, 'GH-13, SECTOR-22D', modern=True, kind='Plot')+'</body></html>'
    c=parse_candidate(html, candidate()['row'], '2026-10-16T00:00:00Z', '2026-10-16T00:01:00Z')
    assert c['result']['property_data']['identification']['project_id']==REG
    assert c['result']['property_data']['land_details']['khasra_plot_details'][0]['type']=='Plot'
    assert all(r['kinds']==['plot'] for r in c['record']['property_data']['search_parcels'])
    assert c['record']['indexed_source_at']==c['result']['scraped_at']


def test_captcha_is_reported_as_source_block_without_accepting_data():
    from src.project_updater import SourceBlocked
    with pytest.raises(SourceBlocked):
        parse_candidate('<html><img src="CaptchaImage.aspx"></html>', candidate()['row'],
                        '2026-10-16T00:00:00Z', '2026-10-16T00:01:00Z')


def test_failure_retries_use_new_sessions_and_never_log_secret_text(monkeypatch):
    import requests
    import src.project_updater as updater
    created=[]
    class HTTP:
        def __init__(self): self.closed=False;created.append(self)
        def get(self,*args,**kwargs): raise requests.ConnectionError('secret credentials must not enter logs')
        def close(self): self.closed=True
    monkeypatch.setattr(updater,'_http',None)
    monkeypatch.setattr(updater.requests,'Session',HTTP)
    c, errors=updater.fetch_candidate(candidate()['row'], sleep=lambda seconds: None)
    assert c is None and len(errors)==3 and all(h.closed for h in created)
    assert errors==[{'type':'ConnectionError'}]*3


def test_timezone_equivalent_old_result_cannot_override_newer_check(catalog):
    seed(catalog);store=UpdateStore(catalog);store.initialize()
    store.apply(candidate('2026-10-16T01:00:00Z'))
    assert store.apply(candidate('2026-10-16T02:00:00+02:00', number='old'))['status']=='superseded'
