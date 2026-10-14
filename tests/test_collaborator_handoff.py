"""Collaborator imports; PostgreSQL checks run when TEST_DATABASE_URL is set.

Use a disposable development DB. Each test creates and drops its own schema.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'db_schema'))
from db import connection, loader
sys.path.remove(str(ROOT / 'db_schema'))


@pytest.fixture
def full_result():
    reg = 'UPRERAPRJ999991/10/2026'
    return {'registration_number': reg, 'project_found': True, 'project_details_available': True,
            'source': 'UP-RERA', 'property_data': {
                'identification': {'project_id': reg, 'project_name': 'Example ' + 'x' * 260},
                'basic_details': {'district': 'Lucknow', 'project_category': 'Residential', 'total_area_sq_m': '1,250.50'},
                'promoter': {'name': 'Example promoter', 'promoter_id': 'UPRERAPRM999991'},
                'documents': [{'serial_number': 1, 'document_name': 'Deed', 'download_url': 'https://example.com/deed.pdf'}],
                'land_details': {'khasra_plot_details': [{'khasra_plot_number': '123/4', 'type': 'Khasra'}]},
                'plan_and_unit_details': {'unit_records': [['हिन्दी', '001', '1.00']]}}}


@pytest.mark.parametrize('details', [None, {}, {'basic_details': {'district': 'Lucknow'}}])
def test_loader_rejects_incomplete_input_before_connecting(monkeypatch, full_result, details):
    full_result['property_data'] = details
    monkeypatch.setattr(loader, 'get_connection', lambda: pytest.fail('Should reject before opening a DB connection'))
    with pytest.raises(ValueError, match='Full project detail JSON'):
        loader.insert_project_json(full_result)


def test_loader_rejects_mismatched_identity(monkeypatch, full_result):
    full_result['property_data']['identification']['project_id'] = 'UPRERAPRJ777'
    monkeypatch.setattr(loader, 'get_connection', lambda: pytest.fail('Should reject before connecting'))
    with pytest.raises(ValueError, match='does not match'):
        loader.insert_project_json(full_result)


@pytest.fixture
def postgres(monkeypatch):
    import psycopg2
    from psycopg2 import sql
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL database for integration checks')
    schema = 'handoff_' + uuid.uuid4().hex
    admin = psycopg2.connect(url)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    parts = urlsplit(url)
    scoped = urlunsplit(parts._replace(query=urlencode(parse_qsl(parts.query) + [('options', '-csearch_path=' + schema)])))
    monkeypatch.setattr(connection, 'DATABASE_URL', scoped)
    try:
        with connection.get_cursor() as cur:
            cur.execute((ROOT / 'db_schema/schema.sql').read_text())
        yield scoped
    finally:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


def test_real_loader_preserves_names_populates_fields_and_is_repeatable(postgres, full_result):
    first = loader.insert_project_json(full_result)
    assert loader.insert_project_json(full_result) == first
    with connection.get_cursor(commit=False) as cur:
        cur.execute('SELECT * FROM projects WHERE id=%s', [first]);project = cur.fetchone()
        assert project['project_name'] == full_result['property_data']['identification']['project_name']
        assert project['district'] == 'Lucknow' and project['project_type'] == 'Residential'
        cur.execute('SELECT COUNT(*) AS n FROM project_documents WHERE project_id=%s', [first])
        assert cur.fetchone()['n'] == 1
        cur.execute('SELECT section_name,data FROM project_extensions WHERE project_id=%s', [first])
        sections = {r['section_name']: r['data'] for r in cur.fetchall()}
        assert sections['khasra_plot_details'] == full_result['property_data']['land_details']['khasra_plot_details']
        assert sections['unit_records'] == [['हिन्दी', '001', '1.00']]
    incomplete = dict(full_result, property_data={})
    with pytest.raises(ValueError): loader.insert_project_json(incomplete)
    with connection.get_cursor(commit=False) as cur:
        cur.execute('SELECT project_name FROM projects WHERE id=%s', [first])
        assert cur.fetchone()['project_name'] == project['project_name']


def test_backfill_cli_fails_on_bad_missing_or_empty_input(postgres, full_result, tmp_path):
    env = dict(os.environ, DATABASE_URL=postgres)
    def run(path):
        return subprocess.run([sys.executable, '-m', 'scripts.backfill_db', str(path)],
                              cwd=ROOT / 'db_schema', env=env, capture_output=True, text=True)
    assert run(tmp_path / 'missing').returncode == 1
    assert run(tmp_path).returncode == 1
    (tmp_path / 'good.json').write_text(json.dumps(full_result))
    (tmp_path / 'bad.json').write_text('{broken')
    result = run(tmp_path)
    assert result.returncode == 1 and 'Loaded: 1   Skipped: 0   Failed: 1' in result.stdout
    (tmp_path / 'bad.json').unlink()
    assert run(tmp_path).returncode == 0
    with connection.get_cursor(commit=False) as cur:
        cur.execute('SELECT COUNT(*) AS n FROM projects');assert cur.fetchone()['n'] == 1


def test_name_migration_preserves_existing_rows(postgres, full_result):
    full_result['property_data']['identification']['project_name'] = 'Existing project'
    project_id = loader.insert_project_json(full_result)
    with connection.get_cursor() as cur:
        cur.execute("SELECT pg_get_viewdef('project_documents_view'::regclass, true) AS definition")
        definition = cur.fetchone()['definition']
        cur.execute('DROP VIEW project_documents_view')
        cur.execute('ALTER TABLE projects ALTER COLUMN project_name TYPE VARCHAR(255)')
        cur.execute('CREATE VIEW project_documents_view AS ' + definition)
        cur.execute('GRANT SELECT ON project_documents_view TO PUBLIC')
        migration = (ROOT / 'db_schema/db/migrations/006_project_name_text.sql').read_text()
        cur.execute(migration);cur.execute(migration)
        cur.execute("SELECT has_table_privilege('public', 'project_documents_view', 'SELECT') AS allowed")
        assert cur.fetchone()['allowed']
        cur.execute('SELECT project_name FROM project_documents_view WHERE project_id=%s', [project_id])
        assert cur.fetchone()['project_name'] == 'Existing project'
    full_result['property_data']['identification']['project_name'] = 'Long name ' + 'a' * 300
    assert loader.insert_project_json(full_result) == project_id


def test_collaborator_api_and_direct_agents(postgres, full_result, monkeypatch):
    pytest.importorskip('rapidfuzz', reason='Install agents/requirements-agents.txt for agent smoke checks')
    monkeypatch.syspath_prepend(str(ROOT / 'db_schema'))
    from fastapi.testclient import TestClient
    from api.main import app as data_app
    monkeypatch.setenv('AGENT_FORCE_DIRECT', '1')
    monkeypatch.setenv('AGENT_LLM_BACKEND', 'ollama')
    from agents.api import app as agent_app
    loader.insert_project_json(full_result)
    with connection.get_cursor() as cur:
        for name in ['004_add_agent_runs.sql', '005_add_document_extractions.sql']:
            cur.execute((ROOT / 'db_schema/db/migrations' / name).read_text())
    reg = full_result['registration_number']
    with TestClient(data_app) as client:
        assert client.get('/projects/' + reg).status_code == 200
        assert client.get('/projects/' + reg).json()['district'] == 'Lucknow'
    with TestClient(agent_app) as client:
        for name in ['property-identification', 'ownership-title', 'land-records-land-use',
                     'registration-encumbrance', 'project-regulatory-compliance']:
            result = client.post('/agents/' + name, json={'registration_number': reg})
            assert result.status_code == 200, (name, result.text)
    with connection.get_cursor(commit=False) as cur:
        cur.execute('SELECT COUNT(*) AS n FROM agent_runs');assert cur.fetchone()['n'] == 5
