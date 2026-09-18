"""Review, disclosure preparation, scenarios and supplier response workflows."""
from __future__ import annotations
import hashlib
import io
import json
import re
import uuid
import zipfile
from decimal import Decimal
from email.message import EmailMessage
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .auth import require
from .calc.engine import calculate
from .calc.units import convert
from .classify.rules import apply_agent_label
from .factors.matcher import library, ACTIVITY_TYPES
from .guardrails.greenwashing import run_checks
from .guardrails.pii import redact_text
from .ledger import db
from .pipeline import Pipeline
from .regulations import PROFILES, SECTIONS
from .reports.render import figures_payload, template_narrative, render_markdown
from .schemas import FactorMatch, FactorRow
from .security import canonical, digest, sign

router = APIRouter(prefix="/api", tags=["Compliance workspace"])
EDITORS = ("admin", "analyst")
REVIEWERS = ("admin", "reviewer")


def inventory(run_id):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Inventory not found")
    return run


def editable(run_id):
    inventory(run_id)
    # Changes remain possible, but every substantive edit changes the approval digest.


def payload(run_id):
    return {"summary": inventory(run_id).model_dump(mode="json"), "entries": [e.model_dump(mode="json") for e in db.get_entries(run_id)]}


def evidence_exists(run_id, ids):
    available = {d["document_id"] for d in db.documents(run_id)}
    if not ids or not set(ids) <= available:
        raise HTTPException(422, "Attach at least one retained evidence document from this inventory")


def content(run_id):
    run = inventory(run_id)
    return {**payload(run_id), "profile": PROFILES[run.jurisdiction],
            "documents": db.documents(run_id), "sections": db.artifacts(run_id, "section"),
            "reviews": db.artifacts(run_id, "review"), "instruments": db.artifacts(run_id, "instrument")}


def readiness(run_id):
    run = inventory(run_id)
    entries = db.get_entries(run_id)
    sections = {x['id']:x for x in db.artifacts(run_id,'section')}
    reviews = {x['id']:x for x in db.artifacts(run_id,'review')}
    docs = {x['document_id'] for x in db.documents(run_id)}
    blockers=[]
    flagged_lines={lid for finding in run.findings if finding.severity=='warn' for lid in finding.line_ids}
    if not entries: blockers.append('No activity data has been ingested')
    for e in entries:
        lid=e.item.line_id
        if e.status not in ('calculated','excluded','duplicate'):
            blockers.append(f'{lid}: {e.status.replace("_"," ")}')
        if not e.item.document_id or e.item.document_id not in docs or not e.item.source_sha256:
            blockers.append(f'{lid}: original source evidence is not retained; reimport this legacy inventory')
        f=e.factor_match.factor
        if e.status=='calculated' and (not f or not f.verified or not f.url or not f.source_sha256):
            blockers.append(f'{lid}: factor requires verified official source evidence')
        if e.status=='calculated' and e.classification.scope==3 and not e.classification.scope3_category:
            blockers.append(f'{lid}: assign an evidenced Scope 3 category')
        needs_review=(lid in flagged_lines or e.status in ('excluded','duplicate') or e.classification.confidence < Decimal('0.7') or e.factor_match.match_quality not in ('exact','none') or '(OCR' in e.item.source_ref)
        if needs_review and (lid not in reviews or reviews[lid].get('entry_sha256')!=digest(e.model_dump(mode='json'))):
            blockers.append(f'{lid}: confirm classification, exclusion, OCR or factor fallback')
    for finding in run.findings:
        if finding.severity=='block': blockers.append(f'{finding.check_id}: {finding.title}')
    years={e.item.period for e in entries if e.item.period}
    if len(years)>1: blockers.append('Mixed reporting periods: create a separate inventory per period')
    if any(not e.item.period for e in entries): blockers.append('Reporting period is missing from one or more activities')
    for spec in SECTIONS:
        s=sections.get(spec['id'])
        if not s or len(s.get('text','').strip())<40 or not s.get('evidence_ids') or not set(s.get('evidence_ids',[]))<=docs:
            blockers.append(f"Disclosure section incomplete: {spec['title']}")
    for finding in run_checks(entries,run.totals,narrative='\n'.join(s.get('text','') for s in sections.values())):
        if finding.check_id=='GW03': blockers.append(f'Disclosure claim requires remediation: {finding.title}')
    market=market_totals(run_id)
    if run.jurisdiction=='CSRD' and run.totals.scope2_location>0 and not market['complete']:
        blockers.append('Market-based Scope 2 evidence is incomplete: allocate contracts or a documented residual mix to every electricity line')
    integrity=db.verify()
    if not integrity['valid']: blockers.append('Audit integrity verification failed')
    hashed=digest(content(run_id))
    approvals=db.artifacts(run_id,'approval')
    approval=next((a for a in reversed(approvals) if a.get('content_sha256')==hashed),None)
    return {'content_sha256':hashed,'blockers':blockers,'ready_for_approval':not blockers,
            'approved': bool(approval) and not blockers,'approval':approval,'revision':run.revision,
            'sections_complete':sum(1 for s in sections.values() if len(s.get('text','').strip())>=40 and s.get('evidence_ids')),
            'sections_total':len(SECTIONS),'market':market,'integrity':integrity}


@router.get('/regulations')
def regulations(): return {'profiles':PROFILES,'sections':SECTIONS}


@router.get('/runs/{run_id}/workspace')
def workspace(run_id: str):
    return {'readiness':readiness(run_id),'sections':db.artifacts(run_id,'section'),'documents':db.documents(run_id),
            'scenarios':db.artifacts(run_id,'scenario'),'suppliers':supplier_states(run_id),
            'instruments':db.artifacts(run_id,'instrument'),'reviews':db.artifacts(run_id,'review'), 'profile':PROFILES[inventory(run_id).jurisdiction]}


class Review(BaseModel):
    expected_revision: int
    activity_type: str
    quantity: Decimal | None = Field(default=None, ge=0, le=Decimal('1e18'))
    unit: str | None = Field(default=None,max_length=40)
    region: str | None = Field(default=None,max_length=80)
    period: str = Field(pattern=r'^FY20\d{2}$')
    factor_id: str | None = None
    scope3_category: int | None = Field(default=None,ge=1,le=15)
    decision: str = Field(default='calculate',pattern='^(calculate|exclude|confirm)$')
    rationale: str = Field(min_length=20,max_length=3000)
    evidence_ids: list[str] = Field(min_length=1,max_length=20)


@router.post('/runs/{run_id}/entries/{line_id}/review')
def review(run_id:str,line_id:str,body:Review,request:Request):
    user=require(request,*EDITORS,*REVIEWERS)
    run=inventory(run_id); entries=db.get_entries(run_id)
    e=next((x for x in entries if x.item.line_id==line_id),None)
    if not e: raise HTTPException(404,'Line not found')
    evidence_exists(run_id,body.evidence_ids)
    if body.activity_type not in ACTIVITY_TYPES: raise HTTPException(422,'Select a catalogued activity')
    before=e.model_dump(mode='json')
    e.item.quantity=body.quantity; e.item.unit=body.unit; e.item.region=body.region; e.item.period=body.period
    if body.decision!='confirm':
        e.classification=apply_agent_label(body.activity_type,Decimal('1'),redact_text(body.rationale)[0])
        e.classification.method='reviewer'
        if e.classification.scope==3:
            e.classification.scope3_category=body.scope3_category or e.classification.scope3_category
        e.calculation=None; e.duplicate_of=None
        if body.decision=='exclude':
            e.status='excluded'; e.factor_match=FactorMatch(matched=False,reason=body.rationale)
        else:
            if body.factor_id:
                f=next((f for f in library().rows if f.factor_id==body.factor_id),None)
                if not f or f.activity_type!=body.activity_type: raise HTTPException(422,'Factor and activity do not match')
                if f.year>int(body.period[2:]): raise HTTPException(422,'Factor postdates the reporting year')
                if body.quantity is None or not body.unit: raise HTTPException(422,'Quantity and unit are required')
                try: e.calculation=calculate(body.quantity,body.unit,f)
                except ValueError as exc: raise HTTPException(422,str(exc))
                e.factor_match=FactorMatch(matched=True,factor=f,match_quality='exact',reason=f'Reviewed selection: {f.factor_id}')
                e.status='calculated'; e.data_quality='measured'
            else: Pipeline()._resolve(e)
    elif (body.quantity!=Decimal(before['item']['quantity']) if before['item']['quantity'] is not None else body.quantity is not None) or body.unit!=before['item']['unit'] or body.region!=before['item']['region'] or body.period!=before['item']['period'] or body.activity_type!=before['classification']['activity_type']:
        raise HTTPException(422,'Use calculate to change activity inputs; confirm cannot alter calculations')
    run.totals=Pipeline._totals(entries)
    run.findings=run_checks(entries,run.totals,prior_totals=run.prior_totals)
    run.report_allowed=not any(f.severity=='block' for f in run.findings)
    after=e.model_dump(mode='json')
    try:
        with db.transaction() as conn:
            db._snapshot(conn,run,entries,user['username'],body.expected_revision)
            db._artifact(conn,run_id,'review',line_id,{'actor':user['username'],'rationale':body.rationale,'evidence_ids':body.evidence_ids,'before':before,'after':after,'entry_sha256':digest(after)},user['username'])
    except ValueError as exc: raise HTTPException(409,str(exc))
    return payload(run_id)


class Section(BaseModel):
    text: str = Field(min_length=40,max_length=20000)
    evidence_ids:list[str] = Field(min_length=1,max_length=30)
    expected_content_sha256:str


@router.put('/runs/{run_id}/sections/{section_id}')
def save_section(run_id:str,section_id:str,body:Section,request:Request):
    user=require(request,*EDITORS)
    if section_id not in {s['id'] for s in SECTIONS}:raise HTTPException(404,'Unknown disclosure section')
    evidence_exists(run_id,body.evidence_ids)
    with db.transaction() as conn:
        if digest(content(run_id))!=body.expected_content_sha256: raise HTTPException(409,'Workspace changed. Reload before saving.')
        db._artifact(conn,run_id,'section',section_id,{'text':body.text,'evidence_ids':body.evidence_ids,'author':user['username']},user['username'])
    return {'ok':True}


@router.post('/runs/{run_id}/evidence')
async def add_evidence(run_id:str,request:Request,file:UploadFile=File(...)):
    user=require(request,*EDITORS,*REVIEWERS); inventory(run_id)
    data=await file.read(20*1024*1024+1)
    if not data or len(data)>20*1024*1024: raise HTTPException(413,'Evidence must be between 1 byte and 20 MB')
    name=(file.filename or 'evidence').replace('\\','/').split('/')[-1]
    doc_id=db.add_document(run_id,name,data,user['username'])
    return {'document_id':doc_id,'sha256':hashlib.sha256(data).hexdigest()}


@router.get('/runs/{run_id}/evidence/{document_id}')
def download_evidence(run_id:str,document_id:str,request:Request):
    inventory(run_id); doc=db.get_document(run_id,document_id)
    if not doc: raise HTTPException(404,'Evidence not found')
    db.event(run_id,request.state.user['username'],'evidence.downloaded',{'id':document_id})
    from urllib.parse import quote
    return Response(doc[1],media_type='application/octet-stream',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{quote(doc[0])}"})


class Approval(BaseModel):
    content_sha256:str
    statement:str=Field(min_length=30,max_length=3000)


@router.post('/runs/{run_id}/approve')
def approve(run_id:str,body:Approval,request:Request):
    user=require(request,*REVIEWERS)
    with db.transaction() as conn:
        state=readiness(run_id)
        if state['content_sha256']!=body.content_sha256: raise HTTPException(409,'The dossier changed. Review the latest version.')
        if state['blockers']: raise HTTPException(409,{'message':'Final approval blocked','blockers':state['blockers']})
        c=content(run_id)
        authors={c['summary']['created_by']} | {s.get('author') for s in c['sections']} | {r.get('actor') for r in c['reviews']} | {r.get('author') for r in c['instruments']}
        if user['username'] in authors: raise HTTPException(403,'A separate reviewer must approve; preparers cannot approve their own dossier')
        record={'content_sha256':body.content_sha256,'reviewer':user['username'],'statement':body.statement,'approved_at':db.now(),'signature':sign(body.content_sha256)}
        db._artifact(conn,run_id,'approval',uuid.uuid4().hex,record,user['username'])
    return record


@router.get('/runs/{run_id}/export')
def export(run_id:str,request:Request):
    with db.transaction() as conn:
        state=readiness(run_id)
        if not state['approved']: raise HTTPException(409,{'message':'A current independent approval is required','blockers':state['blockers']})
        c=content(run_id); run=inventory(run_id); entries=db.get_entries(run_id)
        md=render_markdown(run,entries,db.get_log(run_id),template_narrative(figures_payload(run,entries,run.jurisdiction)),'deterministic approved snapshot',run.jurisdiction)
        md=f"# Reviewed sustainability dossier\n\n{c['profile']['notice']}\n\n"+md
        for section in c['sections']:
            title=next(s['title'] for s in SECTIONS if s['id']==section['id'])
            md+=f"\n\n## {title}\n\n{section['text']}\n\nEvidence: {', '.join(section['evidence_ids'])}"
        chain=[{k:event[k] for k in ('id','previous_hash','event_hash','signature')} for event in db.audit()]
        files={'disclosure.md':md.encode(),'inventory.json':canonical(c).encode(),'approval.json':canonical(state['approval']).encode(),'market-scope2.json':canonical(state['market']).encode(),'audit.json':canonical(db.audit(run_id)).encode(),'audit-chain.json':canonical(chain).encode()}
        for doc in c['documents']:
            name,data=db.get_document(run_id,doc['document_id']); files[f"evidence/{doc['document_id']}/{name.replace('/', '_').replace(chr(92),'_')}"]=data
        manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
        checkpoint={'files':manifest,'content_sha256':state['content_sha256'],'audit_head':state['integrity']['head'],'signature':sign(canonical(manifest)),'generated_at':db.now(),'purpose':'Reviewed disclosure preparation package; not a regulator submission or assurance opinion'}
        files['manifest.json']=canonical(checkpoint).encode()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():z.writestr(name,data)
        db._event(conn,run_id,request.state.user['username'],'dossier.exported',{'content_sha256':state['content_sha256'],'zip_sha256':hashlib.sha256(out.getvalue()).hexdigest()})
    return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="carbon-dossier-{run_id}.zip"'})


class Instrument(BaseModel):
    line_id:str
    quantity_kwh:Decimal=Field(gt=0,le=Decimal('1e18'))
    factor_kg_per_kwh:Decimal=Field(ge=0,le=100)
    instrument_type:str=Field(pattern='^(contract|residual_mix)$')
    serial_number:str=Field(min_length=3,max_length=200)
    region:str=Field(min_length=2,max_length=80)
    period:str=Field(pattern=r'^FY20\d{2}$')
    evidence_ids:list[str]=Field(min_length=1)
    quality_statement:str=Field(min_length=40,max_length=4000)
    retired:bool


@router.post('/runs/{run_id}/instruments')
def instrument(run_id:str,body:Instrument,request:Request):
    user=require(request,*EDITORS); inventory(run_id); evidence_exists(run_id,body.evidence_ids)
    e=db.get_entry(run_id,body.line_id)
    if not e or e.status!='calculated' or e.classification.activity_type!='electricity_grid':raise HTTPException(422,'Select a calculated electricity line')
    if body.period!=e.item.period or body.region.upper()!=(e.item.region or '').upper():raise HTTPException(422,'Instrument geography and period must match the activity')
    if body.instrument_type=='contract' and not body.retired:raise HTTPException(422,'Contractual instruments require retirement/cancellation evidence')
    qty,_=convert(e.calculation.quantity_input,e.calculation.unit_input,'kWh')
    with db.transaction() as conn:
        current=[i for i in db.artifacts(run_id,'instrument') if i.get('status')!='revoked']
        if any(i['serial_number']==body.serial_number for i in current):raise HTTPException(409,'Instrument serial already allocated')
        used=sum((Decimal(i['quantity_kwh']) for i in current if i['line_id']==body.line_id and i.get('entry_sha256')==digest(e.model_dump(mode='json'))),Decimal(0))
        if used+body.quantity_kwh>qty:raise HTTPException(422,'Instrument allocations exceed electricity consumption')
        record={**body.model_dump(mode='json'),'author':user['username'],'entry_sha256':digest(e.model_dump(mode='json'))}
        db._artifact(conn,run_id,'instrument',uuid.uuid4().hex,record,user['username'])
    return record


def market_totals(run_id):
    entries=[e for e in db.get_entries(run_id) if e.status=='calculated' and e.classification.activity_type=='electricity_grid']
    instruments=[i for i in db.artifacts(run_id,'instrument') if i.get('status')!='revoked']; total=Decimal(0); missing=[]
    for e in entries:
        qty,_=convert(e.calculation.quantity_input,e.calculation.unit_input,'kWh')
        valid=[i for i in instruments if i['line_id']==e.item.line_id and i.get('entry_sha256')==digest(e.model_dump(mode='json'))]
        allocated=sum((Decimal(i['quantity_kwh']) for i in valid),Decimal(0))
        if allocated!=qty:missing.append({'line_id':e.item.line_id,'unallocated_kwh':str(qty-allocated)})
        total+=sum((Decimal(i['quantity_kwh'])*Decimal(i['factor_kg_per_kwh'])/1000 for i in valid),Decimal(0))
    return {'complete':not missing,'scope2_market_t':str(total.quantize(Decimal('.000001'))) if not missing else None,'covered_t':str(total),'gaps':missing,'basis':'Contracts and residual mix, separately reported from location-based Scope 2'}


class Revocation(BaseModel):
    rationale:str=Field(min_length=20,max_length=3000)


@router.post('/runs/{run_id}/instruments/{instrument_id}/revoke')
def revoke_instrument(run_id:str,instrument_id:str,body:Revocation,request:Request):
    user=require(request,*EDITORS)
    with db.transaction() as conn:
        record=db.get_artifact(run_id,'instrument',instrument_id)
        if not record: raise HTTPException(404,'Instrument not found')
        db._artifact(conn,run_id,'instrument',instrument_id,{**record,'status':'revoked','revocation_reason':body.rationale,'author':user['username']},user['username'])
    return {'ok':True}


class Lever(BaseModel):
    name:str=Field(min_length=3,max_length=120)
    activity_type:str
    reduction_percent:Decimal=Field(gt=0,le=100)
    investment:Decimal=Field(ge=0,le=Decimal('1e15'))
    annual_savings:Decimal=Field(ge=0,le=Decimal('1e15'))


class Scenario(BaseModel):
    name:str=Field(min_length=3,max_length=120)
    currency:str=Field(pattern='^[A-Z]{3}$')
    years:int=Field(ge=1,le=50)
    discount_percent:Decimal=Field(ge=0,le=100)
    assumptions:str=Field(min_length=20,max_length=4000)
    levers:list[Lever]=Field(min_length=1,max_length=30)


@router.post('/runs/{run_id}/scenarios')
def scenario(run_id:str,body:Scenario,request:Request):
    user=require(request,*EDITORS); run=inventory(run_id); out=[]; allocated={}
    for lever in body.levers:
        baseline=run.totals.by_activity.get(lever.activity_type)
        if baseline is None:raise HTTPException(422,'Activity is absent from the inventory')
        allocated[lever.activity_type]=allocated.get(lever.activity_type,Decimal(0))+lever.reduction_percent
        if allocated[lever.activity_type]>100:raise HTTPException(422,'Combined reductions for an activity cannot exceed 100%')
        saving=baseline*lever.reduction_percent/100
        npv=sum((lever.annual_savings/((1+body.discount_percent/100)**y) for y in range(1,body.years+1)),Decimal(0))-lever.investment
        out.append({**lever.model_dump(mode='json'),'avoided_t_per_year':str(saving.quantize(Decimal('.000001'))),'npv':str(npv.quantize(Decimal('.01'))),
                    'roi_percent':str(((lever.annual_savings*body.years-lever.investment)/lever.investment*100).quantize(Decimal('.01'))) if lever.investment else None,
                    'payback_years':str((lever.investment/lever.annual_savings).quantize(Decimal('.01'))) if lever.annual_savings else None,
                    'formula':f'{baseline} t × {lever.reduction_percent}% / 100; NPV = discounted annual savings minus investment'})
    out.sort(key=lambda x:(x['roi_percent'] is not None, Decimal(x['roi_percent'] or 0),Decimal(x['npv'])),reverse=True)
    record={**body.model_dump(mode='json'),'levers':out,'baseline_revision':run.revision,'author':user['username'],'avoided_t':str(sum(Decimal(x['avoided_t_per_year']) for x in out)),'kind':'User-assumption projection; never included in actual emissions'}
    return db.put_artifact(run_id,'scenario',uuid.uuid4().hex,record,user['username'])


class SupplierRequest(BaseModel):
    supplier:str=Field(min_length=2,max_length=150)
    contact_email:str=Field(max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    line_ids:list[str]=Field(min_length=1,max_length=100)
    due_date:str=Field(pattern=r'^20\d{2}-\d{2}-\d{2}$')


@router.post('/runs/{run_id}/suppliers')
def supplier(run_id:str,body:SupplierRequest,request:Request):
    user=require(request,*EDITORS); run=inventory(run_id)
    entries={e.item.line_id:e for e in db.get_entries(run_id)}
    if not set(body.line_ids)<=set(entries):raise HTTPException(422,'Unknown line in supplier request')
    text=f"Dear {body.supplier},\n\nWe are preparing {run.org_name}'s {run.reporting_period} greenhouse gas inventory. Please provide activity quantities and units, the reporting boundary, methodology, emission factors and source citations, and any independent verification by {body.due_date}.\n\nReferences:\n"+'\n'.join(f'- {lid}: {entries[lid].item.description}' for lid in body.line_ids)+'\n\nPlease omit personal data and confidential pricing. Include source evidence and explain unavailable data.\n\nThank you.'
    record={**body.model_dump(),'body':text,'status':'draft','author':user['username'],'subject':f'Emissions evidence request — {run.reporting_period}'}
    return db.put_artifact(run_id,'supplier',uuid.uuid4().hex,record,user['username'])


def supplier_digest(record):
    return digest({key: record[key] for key in ('supplier', 'contact_email', 'subject', 'body', 'due_date', 'line_ids')})


def supplier_states(run_id):
    approvals = {a['id']: a for a in db.artifacts(run_id, 'supplier_approval')}
    result = []
    for record in db.artifacts(run_id, 'supplier'):
        sha = supplier_digest(record)
        approval = approvals.get(record['id'], {})
        approved = approval.get('content_sha256') == sha
        result.append({**record, 'content_sha256': sha, 'approved': approved,
                       'approved_by': approval.get('approved_by') if approved else None,
                       'delivery_status': 'Not sent; email delivery disabled'})
    return result


class SupplierApproval(BaseModel):
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    statement: str = Field(min_length=20, max_length=1000)


@router.post('/runs/{run_id}/suppliers/{supplier_id}/approve')
def approve_supplier(run_id: str, supplier_id: str, body: SupplierApproval, request: Request):
    user = require(request, *REVIEWERS)
    record = db.get_artifact(run_id, 'supplier', supplier_id)
    if not record:
        raise HTTPException(404, 'Request not found')
    if body.content_sha256 != supplier_digest(record):
        raise HTTPException(409, 'Request changed; review the current recipient and message before approving')
    return db.put_artifact(run_id, 'supplier_approval', supplier_id,
                           {**body.model_dump(), 'approved_by': user['username'], 'approved_at': db.now()},
                           user['username'])


@router.get('/runs/{run_id}/suppliers/{supplier_id}/draft')
def supplier_draft(run_id:str,supplier_id:str,request:Request):
    record=db.get_artifact(run_id,'supplier',supplier_id)
    if not record:raise HTTPException(404,'Request not found')
    approval = db.get_artifact(run_id, 'supplier_approval', supplier_id)
    if not approval or approval.get('content_sha256') != supplier_digest(record):
        raise HTTPException(409, 'An administrator or reviewer must approve this exact recipient and message first')
    db.event(run_id, request.state.user['username'], 'supplier.draft_downloaded',
             {'supplier_id': supplier_id, 'content_sha256': supplier_digest(record), 'sent': False})
    msg=EmailMessage();msg['To']=record['contact_email'];msg['Subject']=record['subject'];msg['X-Unsent']='1';msg.set_content(record['body'])
    return Response(msg.as_bytes(),media_type='message/rfc822',headers={'Content-Disposition':'attachment; filename="supplier-request.eml"'})


class SupplierResponse(BaseModel):
    evidence_ids:list[str]=Field(min_length=1)
    notes:str=Field(min_length=20,max_length=4000)


@router.post('/runs/{run_id}/suppliers/{supplier_id}/response')
def supplier_response(run_id:str,supplier_id:str,body:SupplierResponse,request:Request):
    user=require(request,*EDITORS); evidence_exists(run_id,body.evidence_ids)
    record=db.get_artifact(run_id,'supplier',supplier_id)
    if not record:raise HTTPException(404,'Request not found')
    return db.put_artifact(run_id,'supplier',supplier_id,{**record,**body.model_dump(),'status':'received; pending accounting review'},user['username'])


@router.get('/runs/{run_id}/audit')
def audit(run_id:str):
    inventory(run_id)
    return {'events':db.audit(run_id),'verification':db.verify()}
