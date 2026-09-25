# Hackathon demo: Carbon Copilot

## What to say   

"Carbon Copilot turns invoices and activity logs into traceable carbon accounts. AI helps interpret data, deterministic tools calculate emissions, and people approve the evidence. It refuses to present unresolved or unsupported results as a final reviewed dossier."

This is an evidence and disclosure-preparation demonstration, not an official filing, legal opinion, assurance engagement or claim of complete regulatory coverage. CSRD/SEC are reference profiles. No jurisdictional eligibility decision is needed to demonstrate the software with fictional data.

## Before presenting

1. Follow the local startup steps in the README. For a repeatable offline presentation, set `$env:LYZR_DISABLED='true'` before launching the backend. Existing credentials remain untouched. Explain that this is rules-only mode, not a live Lyzr demonstration.
2. Use fictional records only. Create the first administrator, then a separate reviewer using **Manage workspace members**. Store your chosen passwords privately; the application has no default demo credentials.
3. Choose **Explore sample inventory** once. It intentionally includes accounting gaps. Do not promise that every sample line can pass final export: missing evidence and unverified historic factors are real blockers.
4. Keep the test command and source-factor catalogue ready. Never show `.env`, secrets or real supplier documents on screen.

## Five-minute walkthrough

| Time | Screen / action | Point to demonstrate |
|---|---|---|
| 0:00 | Overview | Scope totals, activity composition, source-backed figures and unresolved review status. |
| 0:45 | Activity ledger → View | Original source reference, retained evidence, selected publication/year, quantity/unit conversion and formula. |
| 1:30 | Review queue | A correction needs rationale and evidence. Missing inputs remain visible instead of becoming guessed numbers. |
| 2:15 | Disclosures | Final export is locked until readiness and independent approval pass. A draft is not a filing. |
| 3:00 | Reduction plans | Enter an assumption-based efficiency lever; show projected savings/ROI separately from actual emissions. |
| 3:40 | Suppliers | Prepare a request to `supplier@example.com`, inspect the message, enter an approval statement and approve it. Download remains locked before approval; the resulting email is unsent. No provider is connected. |
| 4:20 | Audit trail / Factor library | Show event lineage and source/version evidence; explain tamper detection and externally retained checkpoints. |

Do not enter made-up disclosure evidence just to make a real inventory appear ready. For a positive approval/export demonstration, the automated integration test constructs a clearly fictional, one-line inventory, attaches explicit test disclosures, signs in as a separate reviewer and verifies every exported file hash. Run `python -m pytest backend/tests/test_workspace.py::test_complete_review_approval_export_and_invalidation -q` from the repository root using the backend virtual environment.

## Evidence for the judging rubric

| Checkpoint | Implemented evidence | Limit to disclose |
|---|---|---|
| Hallucination mitigation | Closed activity labels; malformed/non-finite and duplicate labels refused; number/claim guards; deterministic Decimal math. | Validation reduces specific failure modes; it does not prove zero hallucinations. |
| Groundedness | Source bytes, SHA-256 hashes, publication/row references, formulas, evidence-backed corrections. | A cited factor still needs the right boundary and methodology. |
| Retrieval quality | Exact activity/region/year selection, bounded fallback rules and explicit unmatched results. | No semantic retrieval benchmark; EPA Hub coverage is partial. |
| Cost / tokens | Rules first, residual batches, explicit narrative generation and estimated token traces. | Estimates are not provider billing measurements. |
| Prompt architecture | Versioned classifier/writer prompts, constrained accepted labels, redaction and guarded outputs. | Repository prompts do not establish the current hosted configuration. |
| Latency | Request timing, agent-call latency and lazy-loaded UI panels. | Local timings are not load/soak or multi-user production benchmarks. |

For the weighted tracks, show the orchestrator/tool boundary (30%), verified factor + calculation details (30%), original-to-export lineage (20%), and working dashboard controls (20%). Do not invent a numeric judge score.

## Live Lyzr demonstration: separate preflight

Only claim a live Lyzr run after confirming the configured classifier/writer IDs, successful calls with synthetic inputs, the actual tool registrations and the provider's Data Analysis Agent / Safe AI settings. The current offline suite validates application-side safeguards, not those hosted capabilities. Capture a sanitized execution trace and provider usage evidence without API keys or personal data.

The [official Lyzr ADK overview](https://docs.lyzr.ai/lyzr-adk/overview) distinguishes agent configuration, tools and responsible-AI policies. A locally declared feature label is not proof that a deployed policy is enabled.

## Recovery and release boundaries

Use the commands in [DEPLOYMENT.md](DEPLOYMENT.md) to create an encrypted backup plus a matching signed checkpoint and run an isolated restore drill. Store keys separately; keep the checkpoint outside the database's trust domain.

Before real-company use: complete applicability and assurance review, verified factor/category coverage, hosted-agent validation, SSO/MFA/account lifecycle, independent security assessment, real OCR and load testing, production hosting/monitoring, retained checkpoints and scheduled recovery drills. Email sending and reply ingestion still require a provider integration with approval enforcement.
