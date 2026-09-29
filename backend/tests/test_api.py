"""Integration tests for the HTTP surface that the workspace tests do not already cover:
public metadata, the deterministic tool endpoints, authentication edge cases, upload
validation, report formats and the origin/CSRF gate."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import PASSWORD, inventory

CSV = b'description,quantity,unit,region,period\nNatural gas,100,therm,US,FY2025\n'


def upload(client, files=None, **form):
    data = {'org_name': 'Acme', 'jurisdiction': 'CSRD', **form}
    return client.post('/api/runs', data=data, files=files or [('files', ('a.csv', CSV, 'text/csv'))])


# ---------------------------------------------------------------- metadata
def test_health_factors_and_units_describe_the_deterministic_toolset(client):
    health = client.get('/api/health').json()
    assert health['ok'] and health['agent_mode'] == 'fallback' and health['lyzr_configured'] is False
    assert health['factor_rows'] > 0 and health['factor_tables']
    catalogue = client.get('/api/factors').json()
    assert {'tables', 'rows', 'activity_types'} <= set(catalogue)
    assert 'electricity_grid' in catalogue['activity_types'] and len(catalogue['rows']) == health['factor_rows']
    assert client.get('/api/tools/units').json()['kWh']['dimension'] == 'energy'


def test_public_routes_carry_security_headers_and_everything_else_needs_a_session():
    with TestClient(app) as anonymous:
        response = anonymous.get('/api/health')
        assert response.status_code == 200
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in response.headers['content-security-policy']
        assert 'strict-transport-security' not in response.headers  # development mode
        assert anonymous.get('/api/factors').status_code == 401
        assert anonymous.get('/api/tools/units').status_code == 401
        assert anonymous.post('/api/tools/calculate', json={'quantity': '1', 'unit': 'kWh', 'activity_type': 'electricity_grid'}).status_code == 401


# ---------------------------------------------------------------- tool endpoints
def test_tool_endpoints_calculate_deterministically_and_refuse_bad_input(client):
    match = client.post('/api/tools/match_factor', json={'activity_type': 'electricity_grid', 'region': 'GB', 'year': 2025}).json()
    assert match['matched'] and match['factor']['factor_id'] and match['factor']['unit'] == 'kWh'
    body = {'quantity': '1000', 'unit': 'kWh', 'activity_type': 'electricity_grid', 'region': 'GB', 'year': 2025}
    calc = client.post('/api/tools/calculate', json=body)
    assert calc.status_code == 200, calc.text
    result = calc.json()
    assert Decimal(result['kg_co2e']) == Decimal('1000') * Decimal(match['factor']['value'])
    assert Decimal(result['t_co2e']) == Decimal(result['kg_co2e']) / 1000
    assert '=' in result['formula'] and result['conversion'] is None and result['factor']['factor_id'] == match['factor']['factor_id']
    converted = client.post('/api/tools/calculate', json={**body, 'quantity': '1', 'unit': 'MWh'}).json()
    assert converted['conversion']['factor'] == '1000' and converted['kg_co2e'] == result['kg_co2e']
    assert client.post('/api/tools/calculate', json={**body, 'quantity': 'abc'}).status_code == 400
    assert client.post('/api/tools/calculate', json={**body, 'quantity': 'NaN'}).status_code == 422
    assert client.post('/api/tools/calculate', json={**body, 'unit': 'litre'}).status_code == 422
    assert client.post('/api/tools/calculate', json={**body, 'activity_type': 'unicorn_fuel'}).status_code == 422
    assert client.post('/api/tools/calculate', json={'quantity': '1'}).status_code == 422  # schema validation


# ---------------------------------------------------------------- authentication
def test_setup_runs_once_and_status_reports_the_local_workspace(client):
    assert client.get('/api/auth/status').json() == {'initialized': True, 'local_setup_allowed': True, 'deployment': 'local'}
    assert client.post('/api/auth/setup', json={'username': 'second', 'password': PASSWORD}).status_code == 409


def test_login_validation_rate_limit_and_session_lifecycle(client):
    me = client.get('/api/auth/me').json()
    assert me['username'] == 'preparer' and me['role'] == 'admin' and me['csrf']
    with TestClient(app) as anonymous:
        assert anonymous.post('/api/auth/login', json={'username': 'ab', 'password': PASSWORD}).status_code == 422
        assert anonymous.post('/api/auth/login', json={'username': 'preparer', 'password': 'short'}).status_code == 422
        # Eight failures from one address lock it out; an unknown username counts as a failure too.
        assert anonymous.post('/api/auth/login', json={'username': 'nobody', 'password': PASSWORD}).status_code == 401
        for _ in range(7):
            assert anonymous.post('/api/auth/login', json={'username': 'preparer', 'password': 'wrong-password-value'}).status_code == 401
        assert anonymous.post('/api/auth/login', json={'username': 'preparer', 'password': PASSWORD}).status_code == 429
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    assert client.get('/api/runs').status_code == 401


def test_user_management_is_admin_only_and_validates_roles(client):
    assert client.get('/api/auth/users').json() == [{'username': 'preparer', 'display_name': 'preparer', 'role': 'admin'}]
    assert client.post('/api/auth/users', json={'username': 'x_user', 'password': PASSWORD, 'role': 'superuser'}).status_code == 422
    assert client.post('/api/auth/users', json={'username': 'preparer', 'password': PASSWORD, 'role': 'analyst'}).status_code == 409
    assert client.post('/api/auth/users', json={'username': 'analyst1', 'password': PASSWORD, 'role': 'analyst', 'display_name': 'Ana'}).status_code == 200
    login = client.post('/api/auth/login', json={'username': 'ANALYST1', 'password': PASSWORD})
    assert login.status_code == 200 and login.json()['display_name'] == 'Ana' and login.json()['role'] == 'analyst'
    client.headers['x-csrf-token'] = login.json()['csrf']
    assert client.get('/api/auth/users').status_code == 403
    assert client.post('/api/auth/users', json={'username': 'another', 'password': PASSWORD, 'role': 'auditor'}).status_code == 403
    assert client.get('/api/runs').status_code == 200  # analysts still read the workspace


def test_state_changing_requests_need_a_permitted_origin_and_csrf_token(client):
    assert client.post('/api/demo', headers={'origin': 'https://evil.invalid'}).status_code == 403
    assert client.post('/api/demo', headers={'origin': 'http://localhost:5173', 'x-csrf-token': 'wrong'}).status_code == 403
    assert client.get('/api/runs', headers={'origin': 'https://evil.invalid'}).status_code == 200  # reads are not origin-gated


# ---------------------------------------------------------------- uploads
def test_upload_validation_rejects_bad_requests_before_any_processing(client):
    assert upload(client, jurisdiction='MARS').status_code == 400
    assert upload(client, org_name='   ').status_code == 422
    assert upload(client, org_name='x' * 201).status_code == 422
    assert upload(client, files=[('files', ('notes.txt', b'hello', 'text/plain'))]).status_code == 422
    assert upload(client, files=[('files', ('empty.csv', b'', 'text/csv'))]).status_code == 413
    assert upload(client, files=[('files', (f'f{i}.csv', CSV, 'text/csv')) for i in range(21)]).status_code == 413
    assert upload(client, prior_totals='{"scope1": "-5"}').status_code == 400
    assert upload(client, prior_totals='not json').status_code == 400
    assert upload(client, prior_totals='[1, 2]').status_code == 400


def test_default_region_fills_rows_that_have_none(client):
    csv = b'description,quantity,unit,period\nElectricity supply,1000,kWh,FY2025\n'
    response = upload(client, files=[('files', ('e.csv', csv, 'text/csv'))], default_region='GB')
    assert response.status_code == 200, response.text
    line = response.json()['entries'][0]
    assert line['item']['region'] == 'GB' and line['status'] == 'calculated'
    assert line['factor_match']['factor']['region'] == 'GB'


# ---------------------------------------------------------------- runs and reports
def test_run_retrieval_lineage_and_report_formats(client):
    run = inventory(client)
    run_id = run['summary']['run_id']
    line_id = run['entries'][0]['item']['line_id']
    assert [r['run_id'] for r in client.get('/api/runs').json()] == [run_id]
    assert client.get(f'/api/runs/{run_id}').json()['summary']['org_name'] == 'Test Manufacturing'
    assert client.get('/api/runs/missing').status_code == 404
    assert client.get(f'/api/runs/{run_id}/lineage/{line_id}').json()['item']['line_id'] == line_id
    assert client.get(f'/api/runs/{run_id}/lineage/nope').status_code == 404
    assert client.get(f'/api/tools/lineage/{run_id}/{line_id}').status_code == 200
    log = client.get(f'/api/runs/{run_id}/agent-log')
    assert log.status_code == 200 and isinstance(log.json(), list)

    markdown = client.get(f'/api/runs/{run_id}/report')
    assert markdown.headers['content-type'].startswith('text/markdown')
    assert markdown.text.startswith('# DRAFT') and 'NOT APPROVED FOR FILING' in markdown.text.splitlines()[0]
    as_json = client.get(f'/api/runs/{run_id}/report?format=json&jurisdiction=csrd').json()
    assert as_json['jurisdiction'] == 'CSRD' and as_json['narrative_source'] == 'template'
    assert as_json['figures'] and len(as_json['lineage']) == len(run['entries'])
    assert client.get(f'/api/runs/{run_id}/report?jurisdiction=MARS').status_code == 400
    assert client.get('/api/runs/missing/report').status_code == 404

    draft = f'/api/runs/{run_id}/draft-narrative'
    assert client.post('/api/runs/missing/draft-narrative', json={'jurisdiction': 'SEC', 'expected_revision': 1}).status_code == 404
    assert client.post(draft, json={'jurisdiction': 'SEC', 'expected_revision': 99}).status_code == 409
    assert client.post(draft, json={'jurisdiction': 'MARS', 'expected_revision': 1}).status_code == 422


@pytest.mark.slow
def test_demo_inventory_runs_over_the_bundled_samples(client):
    response = client.post('/api/demo?jurisdiction=SEC')
    assert response.status_code == 200, response.text
    summary = response.json()['summary']
    assert summary['org_name'].startswith('Northbridge') and summary['jurisdiction'] == 'SEC'
    assert Decimal(summary['totals']['total_location_based']) > 0 and summary['agent_mode'] == 'fallback'
    assert summary['prior_totals']  # the bundled FY2024 comparison is attached
    assert client.post('/api/demo?jurisdiction=MARS').status_code == 422
