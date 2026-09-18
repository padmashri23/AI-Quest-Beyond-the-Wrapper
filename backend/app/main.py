"""FastAPI service: ingestion runs, ledger queries, reports, and the deterministic tool
endpoints that Lyzr agents call."""
from __future__ import annotations

import json
import os
import hmac
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from .calc.engine import calculate  # noqa: E402
from .calc.units import known_units  # noqa: E402
from .factors.matcher import ACTIVITY_TYPES, library  # noqa: E402
from .guardrails.greenwashing import run_checks  # noqa: E402
from .ledger import db  # noqa: E402
from .pipeline import Pipeline  # noqa: E402
from .reports.render import JURISDICTIONS, figures_payload, render_markdown, template_narrative  # noqa: E402
from .auth import router as auth_router, authenticate, require
from .workspace import router as workspace_router
from .security import secret, production
from .runtime import router as runtime_router, observe

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"

@asynccontextmanager
async def lifespan(app):
    secret('DATA_ENCRYPTION_KEY'); secret('AUDIT_SIGNING_KEY')
    if production() and secret('DATA_ENCRYPTION_KEY') == secret('AUDIT_SIGNING_KEY'):
        raise RuntimeError('Production data encryption and audit signing keys must be independent')
    await run_in_threadpool(db.migrate_legacy)
    library()
    yield

app = FastAPI(title="Carbon Copilot API", version="2.0.0", lifespan=lifespan,
              docs_url=None if production() else '/docs')
origins = [s.strip() for s in os.getenv('ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000').split(',') if s.strip()]
if '*' in origins or (production() and not os.getenv('ALLOWED_ORIGINS')):
    raise RuntimeError('Configure explicit ALLOWED_ORIGINS for production')
if production():
    from urllib.parse import urlsplit
    if any(urlsplit(origin).scheme!='https' or not urlsplit(origin).netloc or urlsplit(origin).path for origin in origins):
        raise RuntimeError('Production origins must be HTTPS origins without paths')
    hosts=[host.strip() for host in os.getenv('ALLOWED_HOSTS','').split(',') if host.strip()]
    if not hosts or '*' in hosts:
        raise RuntimeError('Configure explicit ALLOWED_HOSTS for production')
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts+['127.0.0.1','localhost'])
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=['GET','POST','PUT','DELETE'], allow_headers=['Content-Type','X-CSRF-Token'])

@app.middleware('http')
async def secure_request(request: Request, call_next):
    try:
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin')
            if origin and origin not in origins:
                raise HTTPException(403,'Origin is not permitted')
        public={'/api/auth/status','/api/auth/setup','/api/auth/login','/api/health','/api/ready'}
        if request.url.path.startswith('/api/') and request.url.path not in public and request.method!='OPTIONS':
            tool_token=os.getenv('LYZR_TOOL_TOKEN','')
            tool_paths={'/api/tools/match_factor','/api/tools/calculate','/api/tools/units'}
            is_tool=(request.url.path in tool_paths and len(tool_token)>=32 and hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+tool_token))
            if not is_tool: await run_in_threadpool(authenticate, request)
        response=await call_next(request)
    except HTTPException as exc:
        response=JSONResponse({'detail':exc.detail},status_code=exc.status_code)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if production(): response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(runtime_router)
app.middleware('http')(observe)

def pipeline() -> Pipeline:
    return Pipeline()  # agent logs and state belong to one request


def _dump(model):
    return model.model_dump(mode="json")


# ----------------------------------------------------------------------
# Health / metadata
# ----------------------------------------------------------------------
@app.get("/api/health")
def health():
    p = pipeline()
    return {
        "ok": True,
        "agent_mode": p.orch.mode,
        "lyzr_configured": p.orch.client.available,
        "classifier_agent": bool(p.orch.classifier_agent_id),
        "writer_agent": bool(p.orch.writer_agent_id),
        "factor_tables": [t["table_id"] for t in p.lib.tables],
        "factor_rows": len(p.lib.rows),
    }


@app.get("/api/factors")
def factors():
    lib = library()
    return {"tables": lib.tables, "rows": [_dump(r) for r in lib.rows], "activity_types": ACTIVITY_TYPES}


@app.get("/api/tools/units")
def units():
    return known_units()


# ----------------------------------------------------------------------
# Deterministic tools (called by Lyzr agents via OpenAPI tool)
# ----------------------------------------------------------------------
class MatchReq(BaseModel):
    activity_type: str
    region: Optional[str] = None
    year: Optional[int] = None


@app.post("/api/tools/match_factor")
def tool_match_factor(req: MatchReq):
    return _dump(library().match(req.activity_type, req.region, req.year))


class CalcReq(BaseModel):
    quantity: str
    unit: str
    activity_type: str
    region: Optional[str] = None
    year: Optional[int] = None


@app.post("/api/tools/calculate")
def tool_calculate(req: CalcReq):
    try:
        qty = Decimal(req.quantity)
    except InvalidOperation:
        raise HTTPException(400, f"quantity '{req.quantity}' is not a decimal")
    m = library().match(req.activity_type, req.region, req.year)
    if not m.matched or not m.factor:
        raise HTTPException(422, m.reason)
    try:
        calc = calculate(qty, req.unit, m.factor)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"kg_co2e": str(calc.kg_co2e), "t_co2e": str(calc.t_co2e), "formula": calc.formula, "factor": _dump(m.factor), "match_quality": m.match_quality, "conversion": _dump(calc.conversion) if calc.conversion else None, "gas_breakdown": {k: str(v) for k, v in (calc.gas_breakdown or {}).items()} or None}


@app.get("/api/tools/lineage/{run_id}/{line_id}")
def tool_lineage(run_id: str, line_id: str):
    e = db.get_entry(run_id, line_id)
    if not e:
        raise HTTPException(404, "line not found")
    return _dump(e)


# ----------------------------------------------------------------------
# Runs
# ----------------------------------------------------------------------
@app.post("/api/runs")
async def create_run(
    request: Request,
    files: list[UploadFile] = File(...),
    org_name: str = Form("Demo Manufacturing Ltd"),
    jurisdiction: str = Form("CSRD"),
    default_region: Optional[str] = Form(None),
    prior_totals: Optional[str] = Form(None),
):
    user=require(request,'admin','analyst')
    if not 1 <= len(files) <= 20: raise HTTPException(413,'Upload between 1 and 20 files')
    if not org_name.strip() or len(org_name)>200: raise HTTPException(422,'Organization name must be 1–200 characters')
    if jurisdiction not in JURISDICTIONS:
        raise HTTPException(400, f"jurisdiction must be one of {list(JURISDICTIONS)}")
    payload = []
    for f in files:
        name=(f.filename or 'upload').replace('\\','/').split('/')[-1]
        if Path(name).suffix.lower() not in {'.csv','.xlsx','.xls','.pdf'}: raise HTTPException(422,'Use CSV, Excel or PDF activity files')
        data=await f.read(20*1024*1024+1)
        if not data or len(data)>20*1024*1024: raise HTTPException(413,'Each file must be 1 byte to 20 MB')
        payload.append((name,data))
    if sum(len(data) for _,data in payload)>50*1024*1024: raise HTTPException(413,'Total upload limit is 50 MB')
    try:
        prior = json.loads(prior_totals) if prior_totals else None
        if prior is not None and (not isinstance(prior,dict) or any(not Decimal(str(v)).is_finite() or Decimal(str(v))<0 for v in prior.values())):
            raise ValueError('Prior totals must be a mapping of nonnegative finite numbers')
        summary, entries, _ = await run_in_threadpool(pipeline().run,payload,org_name,jurisdiction,prior_totals=prior,default_region=default_region,actor=user['username'])
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(400, str(exc))
    return {"summary": _dump(summary), "entries": [_dump(e) for e in entries]}


@app.post("/api/demo")
def demo_run(request: Request, jurisdiction: str = "CSRD"):
    user=require(request,'admin','analyst')
    if jurisdiction not in JURISDICTIONS: raise HTTPException(422,'Unsupported jurisdiction')
    if not SAMPLES.exists():
        raise HTTPException(500, "sample data missing")
    files = [(p.name, p.read_bytes()) for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in (".csv", ".xlsx", ".pdf")]
    prior_path = SAMPLES / "prior_period_fy2024.json"
    prior = json.loads(prior_path.read_text()) if prior_path.exists() else None
    summary, entries, _ = pipeline().run(files, "Northbridge Precision Components Ltd", jurisdiction, prior_totals=prior,actor=user['username'])
    return {"summary": _dump(summary), "entries": [_dump(e) for e in entries]}


@app.get("/api/runs")
def list_runs():
    return [_dump(r) for r in db.list_runs()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return {"summary": _dump(r), "entries": [_dump(e) for e in db.get_entries(run_id)]}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    raise HTTPException(405,'Inventories are append-only. Create a correcting revision.')


@app.get("/api/runs/{run_id}/lineage/{line_id}")
def lineage(run_id: str, line_id: str):
    return tool_lineage(run_id, line_id)


@app.get("/api/runs/{run_id}/agent-log")
def agent_log(run_id: str):
    return [_dump(l) for l in db.get_log(run_id)]


@app.get("/api/runs/{run_id}/report")
def report(run_id: str, jurisdiction: Optional[str] = None, format: str = "md", regenerate: bool = False):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    jur = (jurisdiction or run.jurisdiction).upper()
    if jur not in JURISDICTIONS:
        raise HTTPException(400, f"jurisdiction must be one of {list(JURISDICTIONS)}")
    entries = db.get_entries(run_id)
    if regenerate:
        raise HTTPException(405, 'Use the authenticated POST draft-narrative action')
    cached = db.get_narrative(run_id, jur)
    source, narrative = cached or ('template', template_narrative(figures_payload(run, entries, jur)))

    log = db.get_log(run_id)
    if format == "json":
        return {"summary": _dump(run), "jurisdiction": jur, "narrative": narrative, "narrative_source": source, "figures": figures_payload(run, entries, jur), "lineage": [_dump(e) for e in entries], "agent_log": [_dump(l) for l in log]}
    md = '# DRAFT — NOT APPROVED FOR FILING\n\nFinal export requires independent approval through the compliance workspace.\n\n'+render_markdown(run, entries, log, narrative, source, jur)
    return PlainTextResponse(md, media_type="text/markdown")


class DraftRequest(BaseModel):
    jurisdiction: str
    expected_revision: int


@app.post('/api/runs/{run_id}/draft-narrative')
def draft_narrative(run_id: str, body: DraftRequest, request: Request):
    user = require(request, 'admin', 'analyst')
    run = db.get_run(run_id)
    if not run: raise HTTPException(404, 'Inventory not found')
    if body.jurisdiction not in JURISDICTIONS: raise HTTPException(422, 'Unsupported jurisdiction')
    if run.revision != body.expected_revision: raise HTTPException(409, 'Inventory changed; reload before drafting')
    entries = db.get_entries(run_id)
    payload = figures_payload(run, entries, body.jurisdiction)
    p = pipeline()
    narrative, source = p.orch.draft_narrative(payload, template_narrative)
    claims = [f for f in run_checks(entries, run.totals, narrative=narrative) if f.check_id == 'GW03']
    if claims:
        narrative, source = template_narrative(payload), 'template'
        p.orch._log('guardrails', 'claim_guard', 'narrative', 'Unbacked claim rejected; deterministic template used', mode='fallback')
    with db.transaction() as conn:
        current = conn.execute('SELECT MAX(revision) FROM revisions WHERE run_id=?',(run_id,)).fetchone()[0]
        if current != body.expected_revision: raise HTTPException(409,'Inventory changed while drafting; retry')
        db._artifact(conn,run_id,'narrative',f'{run.revision}:{body.jurisdiction}',{'source':source,'text':narrative},user['username'])
        for entry in p.orch.log:
            import uuid
            db._artifact(conn,run_id,'agent_log',uuid.uuid4().hex,entry.as_dict(),user['username'])
    return {'narrative_source':source,'revision':run.revision}


# ----------------------------------------------------------------------
# Static frontend (production build) if present
# ----------------------------------------------------------------------
_dist = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
