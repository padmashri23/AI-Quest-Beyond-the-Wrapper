# Carbon Copilot — Autonomous ESG & Carbon Accounting Compliance Copilot

**AI Quest: Beyond the Wrapper · Problem 04 · ClimateTech / FinTech Compliance**

Ingests invoices, utility bills, freight and travel logs and ERP exports; classifies every
line into GHG Protocol Scope 1 / 2 / 3; binds it to an official EPA eGRID / EPA GHG Hub /
DEFRA emission factor; does the arithmetic in code (never in a model); runs greenwashing
checks; and emits a CSRD (ESRS E1) or SEC (Reg S-K Item 1504) disclosure where every tonne
traces back to the source row, the factor citation and the formula.

```
ingest -> redact PII -> rules classify -> [residue] -> Lyzr Scope Classifier
                                                         | validated labels only
                                     match_factor (tool) -> calculate (tool) -> SQLite ledger
                                                         |
                  greenwashing checks -> [figures] -> Lyzr Disclosure Writer -> number-lock -> report
```

## Quick start

### Docker (one command)

```bash
cp .env.example .env            # optional: add your Lyzr key + agent IDs
docker compose up --build
# open http://localhost:8000  -> click "Run bundled sample dataset"
```

### Local

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                        # 19 golden + contract tests
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                                      # http://localhost:5173, proxies /api to :8000
```

Without a `LYZR_API_KEY` the system runs in **rules-only fallback**: every figure is
identical, the residue of lines the rules cannot label is shown as "needs review", and the
narrative comes from a deterministic template. With a key and the two agent IDs the same
run sends the residue to the Scope Classifier and drafts the narrative with the Disclosure
Writer.

### Creating the Lyzr agents

1. In [Lyzr Agent Studio](https://studio.lyzr.ai) create two agents using the system prompts in
   `agents/classifier/system_prompt.md` and `agents/disclosure_writer/system_prompt.md`
   (settings in the sibling `agent.json`: classifier temperature 0, JSON output), or run
   `python agents/deploy_agents.py` with `LYZR_API_KEY` set.
2. Register `agents/tools/openapi.yaml` as an OpenAPI tool (point the server URL at your
   backend) and attach it to the Disclosure Writer so it can pull lineage on demand.
3. Put the agent IDs in `.env` as `LYZR_CLASSIFIER_AGENT_ID` / `LYZR_WRITER_AGENT_ID`.

## Repository layout

```
agents/                      Lyzr agent definitions, prompts, tool schemas, orchestrator
  classifier/                Scope Classifier agent (closed-list labels, JSON only)
  disclosure_writer/         Disclosure Writer agent (CSRD / SEC narrative, number-locked)
  tools/openapi.yaml         Deterministic tool contract exposed by the backend
  orchestrator.py            Handoff, batching, label validation, number-lock, governance log
  lyzr_client.py             POST /v3/inference/chat/ client
  deploy_agents.py           Creates the agents from the JSON configs
backend/                     FastAPI service
  app/ingestion/             CSV/Excel (pandas) and PDF (pdfplumber) parsers -> LineItem
  app/guardrails/pii.py      Redaction of prices, account numbers, emails, phones, names
  app/classify/rules.py      Ordered rule engine; only the residue goes to the agent
  app/factors/tables/*.json  EPA eGRID2022, EPA GHG Hub 2024, DEFRA 2023 (with citations)
  app/factors/matcher.py     Exact-key lookup with region/year fallback; never guesses
  app/calc/units.py          Unit conversion constants with sources (NIST, EIA, EPA)
  app/calc/engine.py         python.decimal arithmetic, per-gas GWP folding, formula string
  app/guardrails/greenwashing.py  GW01-GW12 checks (blocking + warning)
  app/ledger/db.py           SQLite audit ledger (runs, entries, agent log, narratives)
  app/reports/render.py      ESRS E1 / SEC markdown with citations, governance log, lineage
  app/main.py                API + tool endpoints + static frontend
  tests/                     Golden calculations and orchestrator contract tests
  data/samples/              Synthetic FY2025 dataset for a fictional UK/US manufacturer
frontend/                    React + Vite dashboard (overview, ledger, lineage drawer, findings, report, log)
Dockerfile, docker-compose.yml, .env.example
```

## How the design answers the rubric

| Pillar | Where to look |
|---|---|
| **Lyzr architecture & tool calling (30)** | `agents/orchestrator.py` is the only place agents and tools meet. The classifier returns labels from a closed list (anything else is rejected); the writer's draft is *number-locked* (every numeral must exist in the figures payload or the draft is discarded and logged). Tools are published as OpenAPI (`agents/tools/openapi.yaml`) and served at `/api/tools/*`. The Governance log tab shows every handoff with token and latency estimates. |
| **Emission calculation accuracy (30)** | `backend/app/calc/engine.py` uses `decimal` with a 28-digit context, folds per-gas factors with AR5 GWPs, and refuses cross-dimension conversions (litres to kWh raises). Factor tables carry source, table reference and year. `pytest` re-derives hand-computed goldens (e.g. 100 therms US gas = 531.145 kg CO2e). Utility PDFs that duplicate ERP postings are counted once (GW11). |
| **Auditability & traceability (20)** | Click any ledger row: source file and row/page, redacted raw text, redaction kinds, classification rule or agent decision with confidence, factor row and citation, conversion constant with source, and the full formula. The report's Appendix A prints the same for every line; Appendix B lists every gap with the reason no estimate was produced. |
| **Sustainability dashboard UX (20)** | CSO view: scope tiles, scope / category / activity charts, findings that need attention, report status. Auditor view: filterable ledger, lineage drawer, governance log, one-click CSRD or SEC markdown. |

### Quest checkpoints

- **Hallucination mitigation** — no number originates in a model; unknown activity keys and unbacked claims are rejected, not corrected.
- **Groundedness** — every figure cites a factor row; unmatched lines become data gaps, never estimates.
- **Retrieval quality** — factor "retrieval" is an exact dictionary lookup on a canonical key with an explicit fallback chain, so there is no semantic drift.
- **Cost & tokens** — rules label ~90% of lines; only the residue is batched (20 per call) to the classifier with redacted, minimal fields.
- **Prompt architecture** — closed-list output schema, data-not-instructions rule for descriptions, refusal path for arithmetic requests, jurisdiction vocabulary switch.
- **Latency** — the numeric pipeline is synchronous Python (a 65-line sample runs in well under a second); agent calls are the only network hops and are batched.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/runs` | multipart `files[]`, `org_name`, `jurisdiction` (CSRD/SEC), `default_region`, `prior_totals` JSON |
| POST | `/api/demo` | run the bundled sample |
| GET | `/api/runs`, `/api/runs/{id}` | list / fetch a run with ledger entries |
| GET | `/api/runs/{id}/lineage/{line_id}` | full lineage for a line |
| GET | `/api/runs/{id}/report?jurisdiction=CSRD&format=md` | disclosure (md or json) |
| GET | `/api/runs/{id}/agent-log` | governance log |
| POST | `/api/tools/match_factor`, `/api/tools/calculate` | deterministic tools for Lyzr agents |
| GET | `/api/tools/units`, `/api/factors`, `/api/health` | reference data |

## Greenwashing controls

| ID | Severity | Check |
|---|---|---|
| GW01 | block | A tCO2e figure without a factor citation |
| GW02 | block | Location- and market-based Scope 2 mixed in one total |
| GW03 | block | "carbon neutral / net zero / offset" in narrative without an offset ledger |
| GW04 | warn | Any scope fell >30% year-on-year vs prior period |
| GW05 | warn | Scope 3 categories with spend but zero emissions |
| GW06 | warn | Energy/fuel quantity outliers (kWh vs MWh, litre vs gallon) |
| GW07 / GW08 | warn | Lines with no official factor / lines nobody could classify |
| GW09 | info | More than half of the footprint is spend-based |
| GW10 | warn | Low-confidence agent labels |
| GW11 | warn | Same consumption in two source documents (counted once) |
| GW12 | info | Identical rows within one file |

## Data notes

Factor tables are transcribed subsets of the official publications with citations; re-verify
against the current release before a real filing. Spend-based (USEEIO) factors are per 2022 USD;
lines in other currencies are reported as gaps rather than converted. The sample dataset is
synthetic and contains deliberate traps (a gas bill in kWh, a PG&E electricity bill, duplicate
PDF/ERP postings, names and account numbers) so the guardrails have something to catch.

## Stretch goals (not built)

Decarbonisation scenario simulator, supplier outreach agent for missing Scope 3 data, market-based
Scope 2 with contractual instruments.
