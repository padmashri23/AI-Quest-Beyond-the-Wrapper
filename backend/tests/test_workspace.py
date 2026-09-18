import io
import json
import sqlite3
import zipfile
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ledger import db
from app.factors.matcher import library
from app.calc.engine import calculate

PASSWORD='test-only-long-password-42'

@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post('/api/auth/setup',json={'username':'preparer','password':PASSWORD}).status_code==200
        login=c.post('/api/auth/login',json={'username':'preparer','password':PASSWORD})
        c.headers['x-csrf-token']=login.json()['csrf']
        yield c

def inventory(c,description='Natural gas',quantity='100',unit='therm',region='US',jurisdiction='SEC'):
    csv=f'description,quantity,unit,region,period\n{description},{quantity},{unit},{region},FY2025\n'.encode()
    response=c.post('/api/runs',data={'org_name':'Test Manufacturing','jurisdiction':jurisdiction},files=[('files',('activity.csv',csv,'text/csv'))])
    assert response.status_code==200,response.text
    return response.json()

def test_auth_roles_csrf_and_no_deletion(client):
    with TestClient(app) as anon:
        assert anon.get('/api/runs').status_code==401
        assert anon.post('/api/auth/login',json={'username':'preparer','password':PASSWORD},headers={'origin':'https://attacker.invalid'}).status_code==403
    assert client.post('/api/demo',headers={'x-csrf-token':''}).status_code==403
    r=inventory(client)
    assert client.delete('/api/runs/'+r['summary']['run_id']).status_code==405
    assert client.post('/api/auth/users',json={'username':'auditor','password':PASSWORD,'role':'auditor'}).status_code==200
    login=client.post('/api/auth/login',json={'username':'auditor','password':PASSWORD}).json()
    client.headers['x-csrf-token']=login['csrf']
    assert client.post('/api/demo').status_code==403
    assert client.get('/api/runs').status_code==200

def test_complete_review_approval_export_and_invalidation(client):
    r=inventory(client);base='/api/runs/'+r['summary']['run_id']
    assert client.get(base+'/export').status_code==409
    w=client.get(base+'/workspace');assert w.status_code==200,w.text
    doc=w.json()['documents'][0]['document_id']
    for section in client.get('/api/regulations').json()['sections']:
        state=client.get(base+'/workspace').json()['readiness']
        result=client.put(base+'/sections/'+section['id'],json={'text':'Reviewed test disclosure with documented assumptions, boundary and evidence. No assurance claim is made.','evidence_ids':[doc],'expected_content_sha256':state['content_sha256']})
        assert result.status_code==200,result.text
    state=client.get(base+'/workspace').json()['readiness']
    assert state['ready_for_approval'],state['blockers']
    approval={'content_sha256':state['content_sha256'],'statement':'I reviewed the attached test evidence and calculation methodology.'}
    assert client.post(base+'/approve',json=approval).status_code==403
    assert client.post('/api/auth/users',json={'username':'reviewer','password':PASSWORD,'role':'reviewer'}).status_code==200
    login=client.post('/api/auth/login',json={'username':'reviewer','password':PASSWORD}).json();client.headers['x-csrf-token']=login['csrf']
    response=client.post(base+'/approve',json=approval);assert response.status_code==200,response.text
    export=client.get(base+'/export');assert export.status_code==200,export.text[:100] if export.status_code!=200 else ''
    z=zipfile.ZipFile(io.BytesIO(export.content));assert 'manifest.json' in z.namelist()
    manifest=json.loads(z.read('manifest.json'))
    import hashlib
    for name,sha in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
    # New retained evidence is a substantive dossier change and invalidates approval.
    assert client.post(base+'/evidence',files={'file':('new.txt',b'additional supporting evidence')}).status_code==200
    assert client.get(base+'/export').status_code==409
    assert db.verify()['valid']

def test_correction_optimistic_lock_and_scenarios(client):
    r=inventory(client);base='/api/runs/'+r['summary']['run_id'];e=r['entries'][0]
    w=client.get(base+'/workspace').json();doc=w['documents'][0]['document_id']
    correction={'expected_revision':1,'activity_type':'natural_gas_stationary','quantity':'200','unit':'therm','region':'US','period':'FY2025','rationale':'Corrected the quantity against the original source evidence.','evidence_ids':[doc]}
    url=base+'/entries/'+e['item']['line_id']+'/review'
    changed=client.post(url,json=correction);assert changed.status_code==200,changed.text
    assert changed.json()['summary']['revision']==2
    assert Decimal(changed.json()['summary']['totals']['scope1'])==Decimal('1.062290')
    assert client.post(url,json=correction).status_code==409
    scenario={'name':'Efficiency','currency':'USD','years':5,'discount_percent':'0','assumptions':'Assume a constant annual energy demand and unchanged prices.','levers':[{'name':'Efficiency','activity_type':'natural_gas_stationary','reduction_percent':'20','investment':'1000','annual_savings':'300'}]}
    result=client.post(base+'/scenarios',json=scenario);assert result.status_code==200,result.text
    assert result.json()['levers'][0]['npv']=='500.00'
    assert result.json()['levers'][0]['roi_percent']=='50.00'
    assert client.get(base).json()['summary']['totals']==changed.json()['summary']['totals']
    supplier=client.post(base+'/suppliers',json={'supplier':'Example Supplier','contact_email':'supplier@example.com','due_date':'2026-12-01','line_ids':[e['item']['line_id']]});assert supplier.status_code==200,supplier.text
    supplier_id=client.get(base+'/workspace').json()['suppliers'][0]['id']
    assert client.get(base+'/suppliers/'+supplier_id+'/draft').status_code==409

def test_market_scope2_coverage_and_overallocation(client):
    r=inventory(client,'Electricity supply','1000','kWh','GB','CSRD');base='/api/runs/'+r['summary']['run_id'];w=client.get(base+'/workspace').json()
    assert not w['readiness']['market']['complete']
    body={'line_id':r['entries'][0]['item']['line_id'],'quantity_kwh':'1000','factor_kg_per_kwh':'0.2','instrument_type':'residual_mix','serial_number':'mix-2025-GB','region':'GB','period':'FY2025','evidence_ids':[w['documents'][0]['document_id']],'quality_statement':'Residual mix source and regional coverage checked against the attached supporting document.','retired':False}
    response=client.post(base+'/instruments',json=body);assert response.status_code==200,response.text
    market=client.get(base+'/workspace').json()['readiness']['market'];assert market['complete'] and market['scope2_market_t']=='0.200000'
    assert client.post(base+'/instruments',json={**body,'serial_number':'another'}).status_code==422

def test_ledger_encryption_append_only_and_missing_record_detection(client):
    r=inventory(client)
    with db._conn() as conn:
        row=conn.execute('SELECT body FROM revisions').fetchone()[0]
        assert row.startswith('enc:v1:') and 'Test Manufacturing' not in row
        with pytest.raises(sqlite3.IntegrityError):conn.execute('DELETE FROM revisions')
    assert db.verify()['valid']
    # Simulate a database administrator bypassing the trigger, not an application path.
    with db._conn() as conn:
        conn.execute('DROP TRIGGER prevent_revisions_DELETE');conn.execute('DELETE FROM revisions');conn.commit()
    assert not db.verify()['valid']

def test_official_factors_and_math_refusals():
    lib=library()
    gb=lib.match('electricity_grid','GB',2025).factor
    assert gb.verified and gb.value==Decimal('0.177') and gb.source_sha256 and gb.source_row
    us=lib.match('electricity_grid','US',2025)
    assert us.factor.verified and us.factor.year==2023 and us.match_quality=='year_fallback'
    assert len([f for f in lib.rows if f.factor_id.startswith('EPA_EGRID2023')])>=25
    assert not lib.match('electricity_grid','GB',2020).matched
    for quantity in ('NaN','Infinity','-1','1e100'):
        with pytest.raises(ValueError):calculate(Decimal(quantity),'kWh',gb)

def test_tool_token_is_scoped_and_report_get_has_no_side_effects(client,monkeypatch):
    monkeypatch.setenv('LYZR_TOOL_TOKEN','t'*40)
    with TestClient(app) as service:
        service.headers['Authorization']='Bearer '+'t'*40
        response=service.post('/api/tools/calculate',json={'quantity':'100','unit':'therm','activity_type':'natural_gas_stationary','region':'US','year':2025})
        assert response.status_code==200,response.text
        assert service.get('/api/runs').status_code==401
    r=inventory(client);base='/api/runs/'+r['summary']['run_id']
    events=len(db.audit())
    assert client.get(base+'/report').status_code==200
    assert len(db.audit())==events
    assert client.get(base+'/report?regenerate=true').status_code==405
    response=client.post(base+'/draft-narrative',json={'jurisdiction':'SEC','expected_revision':1})
    assert response.status_code==200,response.text
