# Deployment and release gates

## Intended deployment

One organization/workspace per service and database. Roles do not create tenant isolation. Use separate deployments for separate customers. SQLite with encrypted application payloads is a single-node implementation, not a clustered database or full-disk encryption.

## Production configuration

1. Back up the existing ledger, WAL where applicable, and both cryptographic keys. Test restoration on a separate instance before migration or rollout.
2. Set `APP_ENV=production`, an explicit HTTPS `ALLOWED_ORIGINS` list, and independent `DATA_ENCRYPTION_KEY` / `AUDIT_SIGNING_KEY` values from your secret manager. Each key is 32 random bytes in URL-safe base64. Never commit keys. Startup refuses missing keys in production.
3. Terminate HTTPS at a managed reverse proxy. Restrict accepted hosts, trusted proxy addresses, request bodies (50 MB total), rate/concurrency limits, request timeouts and network access. Secure cookies require HTTPS. Do not expose development setup publicly.
4. Provision the first administrator with `python -m app.admin create-admin --username NAME` from `backend`, using the same key and ledger environment as the service. The password is read without echo. Bootstrap refuses an already initialized workspace.
5. Create a separate reviewer in Workspace members. An inventory preparer or substantive contributor cannot independently approve their own dossier. Configure operational account provisioning/recovery policy; SSO, MFA and self-service password recovery are not implemented here.
6. Run `python -m app.admin verify`. Store its audit head and exported signed manifests in independent retention-controlled storage. Schedule verification externally; alert on failure.
7. Use an encrypted persistent disk and least-privilege filesystem permissions. Payload encryption does not hide all metadata: usernames, roles, record identifiers, timing and integrity hashes remain in database columns.
8. For OCR, install Tesseract and optional required language packs; use `TESSERACT_CMD` on Windows. Docker includes English Tesseract. OCR-derived quantities require review. Parser work is bounded by file/page limits but is not isolated in a hardened worker sandbox.

## Migration and cryptographic limits

Startup baselines existing inventories into encrypted revisions in a transaction. Old JSON payload columns are encrypted in place. No historical source document, author approval or authenticity is invented. Reimport legacy source evidence to meet the final-export checks.

Migration does not guarantee eradication of previous plaintext from old backups, SQLite free pages, storage snapshots or historical WAL files. Apply the organization's secure retention/compaction procedure after making a recoverable, encrypted backup. Protect development keys under `backend/data/.keys` (or `KEY_DIR`); losing them makes encrypted records unreadable.

Append-only triggers reject application UPDATE/DELETE of audit records. HMAC chains detect modification and missing referenced records, but a database administrator holding the signing key can rewrite history. A truncated tail or restored older database requires an externally retained checkpoint to detect. This is tamper-evident storage, not WORM storage or a third-party digital-signature service. Key rotation and external checkpoint scheduling need an operational implementation.

## API workflow

All private endpoints require a workspace session. Mutating browser requests also require the session's `X-CSRF-Token`. Do not put session tokens in localStorage. Sessions expire after eight hours; logout revokes the session.

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` | Import CSV/Excel/PDF activity sources |
| `GET /api/runs/{id}/workspace` | Evidence, readiness and latest working artifacts |
| `POST /api/runs/{id}/entries/{line}/review` | Version-checked correction, confirmation or exclusion |
| `POST /api/runs/{id}/evidence` | Retain a supporting document |
| `PUT /api/runs/{id}/sections/{section}` | Save evidence-backed disclosure text using content-hash locking |
| `POST /api/runs/{id}/instruments` | Allocate market-based electricity evidence |
| `POST /api/runs/{id}/instruments/{instrument}/revoke` | Append an audited revocation |
| `POST /api/runs/{id}/scenarios` | Store reduction projections; does not change actual totals |
| `POST /api/runs/{id}/suppliers` | Prepare an unsent supplier request |
| `POST /api/runs/{id}/suppliers/{request}/response` | Record evidence received and assessment |
| `POST /api/runs/{id}/draft-narrative` | Explicit Lyzr/template draft action with role and revision checks |
| `POST /api/runs/{id}/approve` | Independent approval of the current content digest |
| `GET /api/runs/{id}/export` | Final package, HTTP 409 unless current approval and readiness checks pass |
| `GET /api/runs/{id}/audit` | Event history and ledger verification |

`GET /report` is always a draft, not the final export. Inventory deletion is disabled. Supporting documents are retained, not overwritten. Original sources can include PII and confidential amounts; users with workspace access can download them, with access logged. Application-side redaction is not a guarantee that arbitrary free text contains no sensitive data: assess external Lyzr processing, retention and contractual data protection before using real supplier records.

## Release gates that remain external or unverified

- Entity-specific legal applicability, jurisdiction/year mapping, complete required ESRS/SEC datapoints and presentation, taxonomy/iXBRL validation, assurance-provider acceptance and regulator submission. Twelve completed narrative sections are not proof of legal completeness.
- Specialist review of category coverage, factor selection, vintage, energy boundaries, emission estimation and market-based Scope 2 quality criteria. EPA Hub import coverage is deliberately limited; historic spend factors are not export-verified.
- Broader real-world OCR/Excel/PDF regression corpus, language/locale coverage, hostile-document security review and isolated parsing workers.
- Independent security assessment, dependency auditing, SSO/MFA, account lifecycle/recovery, organization retention policy, encrypted backups and restore drills, external WORM/checkpoint storage, observability and incident response.
- Load/soak testing, deployment tests, concurrent-workspace performance, disaster recovery and production support ownership. Browser QA is Edge/Chromium desktop and mobile emulation, not a full cross-browser/device certification.
- Provider-side Lyzr Data Analysis Agent and Safe AI configuration verification and evaluation evidence. The application has deterministic math/redaction guards, but those are not proof of provider-side capabilities being enabled.
- Autonomous email delivery/replies, mail-provider integration and domain/recipient approval. Current supplier outreach is intentionally a human-reviewed unsent draft workflow.

Do not label the deployment “fully compliant,” “audit assured,” or “production certified” solely because software tests pass.
