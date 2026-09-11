"""FastAPI service: ingestion runs, ledger queries, reports, and the deterministic tool
endpoints that Lyzr agents call."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
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
from .schemas import AgentLogEntry  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"

app = FastAPI(title="Carbon Copilot API", version="1.0.0", description="Deterministic carbon accounting with Lyzr agents for classification and disclosure drafting.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pipeline: Optional[Pipeline] = None


def pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


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
    files: list[UploadFile] = File(...),
    org_name: str = Form("Demo Manufacturing Ltd"),
    jurisdiction: str = Form("CSRD"),
    default_region: Optional[str] = Form(None),
    prior_totals: Optional[str] = Form(None),
):
    if jurisdiction not in JURISDICTIONS:
        raise HTTPException(400, f"jurisdiction must be one of {list(JURISDICTIONS)}")
    payload = []
    for f in files:
        payload.append((f.filename or "upload", await f.read()))
    prior = json.loads(prior_totals) if prior_totals else None
    try:
        summary, entries, _ = pipeline().run(payload, org_name, jurisdiction, prior_totals=prior, default_region=default_region)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"summary": _dump(summary), "entries": [_dump(e) for e in entries]}


@app.post("/api/demo")
def demo_run(jurisdiction: str = "CSRD"):
    if not SAMPLES.exists():
        raise HTTPException(500, "sample data missing")
    files = [(p.name, p.read_bytes()) for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in (".csv", ".xlsx", ".pdf")]
    prior_path = SAMPLES / "prior_period_fy2024.json"
    prior = json.loads(prior_path.read_text()) if prior_path.exists() else None
    summary, entries, _ = pipeline().run(files, "Northbridge Precision Components Ltd", jurisdiction, prior_totals=prior)
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
    db.delete_run(run_id)
    return {"ok": True}


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
    p = pipeline()

    cached = None if regenerate else db.get_narrative(run_id, jur)
    if cached:
        source, narrative = cached
    else:
        payload = figures_payload(run, entries, jur)
        p.orch.log.clear()
        narrative, source = p.orch.draft_narrative(payload, template_narrative)
        # Claim guard on the narrative that will actually be published
        new_findings = run_checks(entries, run.totals, narrative=narrative)
        claim = [f for f in new_findings if f.check_id == "GW03"]
        if claim:
            p.orch._log("guardrails", "claim_guard", "narrative", f"GW03 raised; narrative replaced by template", mode="fallback")
            narrative, source = template_narrative(payload), "template"
            run.findings = [f for f in run.findings if f.check_id != "GW03"] + claim
            run.report_allowed = False
            db.update_findings(run)
        db.save_narrative(run_id, jur, source, narrative, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        db.append_log(run_id, [AgentLogEntry(**l.as_dict()) for l in p.orch.log])

    log = db.get_log(run_id)
    if format == "json":
        return {"summary": _dump(run), "jurisdiction": jur, "narrative": narrative, "narrative_source": source, "figures": figures_payload(run, entries, jur), "lineage": [_dump(e) for e in entries], "agent_log": [_dump(l) for l in log]}
    md = render_markdown(run, entries, log, narrative, source, jur)
    return PlainTextResponse(md, media_type="text/markdown")


# ----------------------------------------------------------------------
# Static frontend (production build) if present
# ----------------------------------------------------------------------
_dist = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
