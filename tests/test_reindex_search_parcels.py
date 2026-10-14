import copy
import json
import pytest
from scripts.reindex_search_parcels import repair
from test_search_catalog import row, record
from src.search_catalog import Catalog


class Snapshots:
    def __init__(self, data): self.data = data
    def get(self, reg, original=False): return copy.deepcopy(self.data.get(reg))


def test_repair_classifies_legacy_duplicates_and_preserves_other_data(tmp_path):
    catalog = Catalog(tmp_path / 'search.sqlite');catalog.initialize()
    summary = row('UPRERAPRJ1')
    source = record(summary, 'Sector 22D Noida', number='GH-13, SECTOR-22D')
    source['property_data']['search_parcels'][0]['kinds'] = ['plot', 'khasra']
    catalog.import_rows([summary], '2026-10-10', {'UPRERAPRJ1': source})
    assert catalog.search('Khasra GH-13 Noida')['total'] == 1
    with catalog.connection(write=True) as conn:
        conn.execute('CREATE TABLE collaborator_data (value TEXT)')
        conn.execute("INSERT INTO collaborator_data VALUES ('keep')")
    saved = {'project_details_url': summary['details_url'], 'scraped_at': '2026-10-14',
             'property_data': {'land_details': {'khasra_plot_details': [
                 {'khasra_plot_number': 'GH-13, SECTOR-22D', 'type': 'Plot'}]}}}
    snapshots = Snapshots({'UPRERAPRJ1': saved});original = copy.deepcopy(snapshots.data)
    assert repair(catalog, snapshots) == 1
    assert catalog.search('Khasra GH-13 Noida')['total'] == 0
    result = catalog.search('Plot GH-13 Noida')
    assert result['total'] == 1
    assert result['projects'][0]['matched_parcels'][0]['published_number'] == 'GH-13, SECTOR-22D'
    for query in ['Plot SECTOR-22D Noida', 'Plot 22D Noida', 'Khasra 22D Noida']:
        assert catalog.search(query)['total'] == 0
    assert catalog.search('Sector 22D Noida')['total'] == 1
    assert snapshots.data == original
    with catalog.connection() as conn:
        assert conn.execute('SELECT value FROM collaborator_data').fetchone()['value'] == 'keep'
        first = conn.execute('SELECT parcels_json FROM rera_search_projects').fetchone()['parcels_json']
    repair(catalog, snapshots)
    with catalog.connection() as conn:
        assert conn.execute('SELECT parcels_json FROM rera_search_projects').fetchone()['parcels_json'] == first
    # A newer saved source type overrides the previous repair, not a union of stale types.
    snapshots.data['UPRERAPRJ1']['property_data']['land_details']['khasra_plot_details'][0]['type'] = 'Khasra'
    repair(catalog, snapshots)
    assert catalog.search('Plot GH-13 Noida')['total'] == 0
    assert catalog.search('Khasra GH-13 Noida')['total'] == 1


def test_missing_snapshot_aborts_without_partial_index_changes(tmp_path):
    catalog = Catalog(tmp_path / 'search.sqlite');catalog.initialize()
    summary = row('UPRERAPRJ1')
    catalog.import_rows([summary], '2026-10-10', {'UPRERAPRJ1': record(summary, 'Lucknow')})
    with pytest.raises(ValueError, match='Missing source snapshot'):
        repair(catalog, Snapshots({}))
    assert catalog.search('Khasra 123/4')['total'] == 1
    assert repair(catalog, Snapshots({}), require_snapshots=False) == 1
