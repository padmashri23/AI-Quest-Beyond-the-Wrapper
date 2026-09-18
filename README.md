# Carbon Copilot — evidence-led carbon accounting

A single-workspace ESG accounting and disclosure-preparation application. Import activity evidence, classify Scope 1/2/3, calculate with Decimal tools, resolve review findings and export an independently approved evidence package.

**This is not a certified filing system.** It does not submit to EDGAR, provide assurance, establish legal applicability, or cover every CSRD/ESRS or CSDDD requirement. See [deployment and release gates](docs/DEPLOYMENT.md).

For the hackathon, start with the [five-minute demo and judging checklist](docs/DEMO.md). Hosting and a legal reviewer are not prerequisites for a synthetic-data demonstration.

## Start locally

From the repository root, install backend dependencies and build the dashboard:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If the virtual environment does not exist, create it first with `python -m venv backend/.venv`. On macOS/Linux use `backend/.venv/bin/python`.

Open http://127.0.0.1:8000. Create the first administrator on the local setup screen, then import activities or choose **Explore sample inventory**. No default production password is provided.

For frontend development, use `npm --prefix frontend run dev`; Vite proxies the API to port 8000.

### Docker

```sh
docker compose up --build -d
docker compose exec copilot python -m app.admin create-admin --username administrator
```

The container runs as a non-root user and includes Tesseract OCR. Configure production secrets, HTTPS and origins before exposing it. The Docker image has not been deployment-tested in this environment.

## Implemented workflows

| Area | Behaviour |
|---|---|
| Ingestion | CSV, every Excel sheet, text PDF, optional Tesseract OCR. Unreadable pages become explicit review items. Original bytes are retained encrypted and SHA-256 linked to activities. |
| Accounting | Scope categorization, exact activity/region/year matching, Decimal unit conversion and per-gas GWP calculations. No future-year factors; fallback selections need review. |
| Official factors | Direct imports of supported non-null aggregate CO₂e rows from DESNZ 2025/2026 workbooks, eGRID 2023 revision 2 subregions/US, and EPA Hub 2025 stationary natural gas. More than 5,000 imported rows, each with publication hash and source row. |
| Human review | Correct quantities, units, periods, activities, category and factor selections; confirm or exclude with rationale and retained evidence. Optimistic locking prevents stale inventory edits. |
| Greenwashing controls | Missing provenance, unsupported climate claims, accounting gaps and unresolved review requirements block final approval/export on the server. Potential duplicate invoices need human adjudication. |
| Scope 2 | Separate location-based accounting and evidence-backed market-based instrument/residual-mix allocations, coverage checks, over-allocation prevention and audited revocation. |
| Disclosures | Versioned CSRD/SEC reference profiles; 12 evidence-backed preparation sections; independent reviewer sign-off bound to a content digest. Changes invalidate approval. |
| Audit | Encrypted payloads/evidence; append-only revision/artifact tables; HMAC-signed hash-chain events; source downloads recorded; independently retainable checkpoints. |
| Export | Approval-gated ZIP containing reviewed Markdown, inventory, evidence, approval, market-based accounting, audit events/chain and signed file-hash manifest. Not regulator-ready XBRL/iXBRL. |
| Scenarios | Assumption-based reduction levers, Decimal avoided emissions, NPV, ROI and payback. Multi-lever API sorts by ROI; dashboard creates individual-lever scenarios. Projections never alter actual totals. |
| Suppliers | Preview requests, approve the exact recipient/message as administrator or reviewer, then download an unsent email draft. Changed content invalidates approval. Attach responses and record assessment; email delivery is disabled. |
| Operations | Encrypted consistent backups, signed external checkpoints, verified non-overwriting restore/drill commands, revoked restored sessions, readiness checks and bounded request telemetry. A separate HTTPS deployment manifest and CI workflow are prepared. |
| Access/UI | Administrator, analyst, reviewer and read-only auditor roles; expiring HttpOnly cookie sessions, CSRF checks, explicit origins, sanitized Markdown; responsive overview, ledger, review queue, disclosures, scenarios, suppliers, factors and audit/governance screens. |

## Lyzr handoff

```text
Source evidence -> redaction -> rules -> unresolved rows -> Lyzr classifier
                                     -> validated labels
                                     -> exact factor lookup -> Decimal calculator
                                     -> immutable inventory revision
Validated figures -> explicit draft action -> Lyzr writer -> number/claim checks
Reviewed corrections + evidence + sections -> independent approval -> export
```

The orchestrator rejects unknown labels and invented narrative numbers. Unresolved lines remain gaps. Lyzr availability can change which residual lines are classified; totals are not guaranteed identical to rules-only mode.

Configure `LYZR_API_KEY`, `LYZR_CLASSIFIER_AGENT_ID` and `LYZR_WRITER_AGENT_ID` in the existing `.env`. Set `LYZR_DISABLED=true` to force offline operation even when credentials exist. Viewing a draft is read-only; requesting AI regeneration is an authenticated, CSRF-protected POST action.

Agent templates are in `agents/classifier` and `agents/disclosure_writer`. The numeric and PII safeguards here run in application code; the repository does not demonstrate certification of Lyzr Safe AI, or a separate deployed Lyzr Data Analysis Agent. Validate those provider-side configurations for the judging rubric.

For hosted tool calling, configure a separate 32+ character `LYZR_TOOL_TOKEN`, use HTTPS, and register `agents/tools/openapi.yaml` with Bearer authentication. That token authorizes only factor matching, calculation and units—not private inventory lineage. The local orchestrator also calls the same deterministic Python calculation functions directly.

## Publication provenance and legal profiles

Run `backend/.venv/Scripts/python.exe backend/scripts/sync_factors.py` to reproduce the catalogue from pinned publications. Downloaded files are checked against pinned SHA-256 hashes; changed publications require explicit source review before accepting a new fingerprint.

- [UK 2026 conversion factors](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026): revised flat workbook; 2025 retained for historic reporting.
- [EPA eGRID detailed data](https://www.epa.gov/egrid/detailed-data): the imported workbook is **2023 revision 2**, not an invented 2024 dataset.
- [EPA Hub 2025](https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf): the verified automated mapping currently covers stationary natural gas, not the entire PDF.
- [EU implementing/delegated acts](https://finance.ec.europa.eu/regulation-and-supervision/financial-services-legislation/implementing-and-delegated-acts/corporate-sustainability-reporting-directive_en): the versioned profile requires reporting-year and applicability review.
- [SEC proposed rescission, May 2026](https://www.sec.gov/newsroom/press-releases/2026-49-sec-proposes-rescission-climate-related-disclosure-rules): the 2024 rule is treated as stayed; a proposal is not represented as a final rescission.

The original 2023/2024 transcribed subsets remain available for historic reproduction but are marked unverified and block final export if used. Source verification means the imported number matches the pinned publication—not that its geography, GWP basis, fuel boundary or Scope 3 category is right for every invoice. Unsupported spend/country/methodology combinations require further authoritative data rather than guessed factors.

## Verification

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend audit --omit=dev --audit-level=high
```

For the backend advisory check, install `pip-audit==2.10.1` in a development environment and run `python -m pip_audit -r backend/requirements.txt --progress-spinner off` with the backend virtual environment. The CI workflow repeats this check. A clean advisory scan is not a security certification or penetration test.

Backend tests cover historical golden values, current official factors, finite-number refusals, full Excel sheet lineage, OCR success/failure handling, authentication/roles/CSRF, encrypted append-only records, missing-record tamper detection, migration, review conflicts, Scope 2 allocation, scenarios, supplier drafts and approval/export invalidation.

Additional tests exercise malformed/non-finite agent labels, duplicate-label refusal, supplier approval and stale-content rejection, secret-file configuration, private telemetry, tampered/older backup rejection and recovery without touching live data. Hosted Lyzr configuration and billed token costs are not established by offline tests.

OCR tests mock the OCR engine output; they do not establish recognition accuracy across real supplier scans. Test databases/keys are isolated from the existing workspace. Browser QA has exercised desktop/mobile navigation and the major data-entry workflows using the real local API.

## Main code

- `backend/app/workspace.py`: readiness, review, evidence, approval, export, market Scope 2, scenarios and supplier requests.
- `backend/app/auth.py`, `security.py`, `ledger/db.py`: access controls, encryption and signed audit revisions.
- `backend/app/regulations.py`: versioned legal reference profiles and disclosure section guidance.
- `backend/scripts/sync_factors.py`: pinned-source factor import.
- `frontend/src/App.tsx`, `components/Overview.tsx`, `CompliancePanels.tsx`, `ReviewEditor.tsx`: responsive application and workflows.
