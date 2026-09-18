# Deployment and release gates

## Intended deployment

One organization/workspace per service and database. Roles do not create tenant isolation. Use separate deployments for separate customers. SQLite with encrypted application payloads is a single-node implementation, not a clustered database or full-disk encryption.

## Production configuration

1. Back up the existing ledger, WAL where applicable, and both cryptographic keys. Test restoration on a separate instance before migration or rollout.
2. Set `APP_ENV=production`, explicit HTTPS `ALLOWED_ORIGINS` and `ALLOWED_HOSTS` lists, and independent `DATA_ENCRYPTION_KEY` / `AUDIT_SIGNING_KEY` values from your secret manager. Use a third `BACKUP_ENCRYPTION_KEY` for backup commands. Each key is 32 random bytes in URL-safe base64. Alternatively set the corresponding `*_FILE` paths to mounted secret files, never both forms for the same key. Never commit keys. Startup refuses missing keys in production and refuses identical data/audit keys.
3. Terminate HTTPS at a managed reverse proxy. Restrict accepted hosts, trusted proxy addresses, request bodies (55 MB HTTP envelope; 50 MB uploaded-file budget), rate/concurrency limits, request timeouts and network access. Secure cookies require HTTPS. Do not expose development setup publicly. The application Content-Length check is not a substitute for a proxy's actual streaming body limit.
4. Provision the first administrator with `python -m app.admin create-admin --username NAME` from `backend`, using the same key and ledger environment as the service. The password is read without echo. Bootstrap refuses an already initialized workspace.
5. Create a separate reviewer in Workspace members. An inventory preparer or substantive contributor cannot independently approve their own dossier. Configure operational account provisioning/recovery policy; SSO, MFA and self-service password recovery are not implemented here.
6. Run `python -m app.admin verify`. Store its audit head and exported signed manifests in independent retention-controlled storage. Schedule verification externally; alert on failure.
7. Use an encrypted persistent disk and least-privilege filesystem permissions. Payload encryption does not hide all metadata: usernames, roles, record identifiers, timing and integrity hashes remain in database columns.
8. For OCR, install Tesseract and optional required language packs; use `TESSERACT_CMD` on Windows. Docker includes English Tesseract. OCR-derived quantities require review. Parser work is bounded by file/page limits but is not isolated in a hardened worker sandbox.

## Migration and cryptographic limits

Startup baselines existing inventories into encrypted revisions in a transaction. Old JSON payload columns are encrypted in place. No historical source document, author approval or authenticity is invented. Reimport legacy source evidence to meet the final-export checks.

Migration does not guarantee eradication of previous plaintext from old backups, SQLite free pages, storage snapshots or historical WAL files. Apply the organization's secure retention/compaction procedure after making a recoverable, encrypted backup. Protect development keys under `backend/data/.keys` (or `KEY_DIR`); losing them makes encrypted records unreadable.

Append-only triggers reject application UPDATE/DELETE of audit records. HMAC chains detect modification and missing referenced records, but a database administrator holding the signing key can rewrite history. A truncated tail or restored older database requires an externally retained checkpoint to detect. This is tamper-evident storage, not WORM storage or a third-party digital-signature service. Key rotation and external checkpoint scheduling need an operational implementation.

## Local deployment preparation

`compose.production.yml` is a **standalone** preparation manifest; do not merge it with the development `docker-compose.yml`, which publishes port 8000. It places the app behind Caddy HTTPS, mounts three secret files, drops app capabilities, uses a read-only root filesystem, sets a concurrency limit and probes `/api/ready`. Caddy handles certificates after a real domain, DNS and public connectivity are configured; see its [automatic HTTPS documentation](https://caddyserver.com/docs/automatic-https).

Set `COPILOT_DOMAIN`, `ACME_EMAIL`, `DATA_KEY_FILE`, `AUDIT_KEY_FILE` and `BACKUP_KEY_FILE` in your private deployment environment. Secret files must be readable by container UID 10001 while inaccessible to unrelated host users. Validate permissions and volume ownership on the chosen host. Use `docker compose -f compose.production.yml config --quiet` to validate configuration, then review before starting services. No hosting, DNS, certificate issuance or cloud provisioning has been performed here. The local Docker engine was unavailable, so image/proxy execution remains unverified.

The prepared production manifest defaults to offline Lyzr operation and does not mount Lyzr credentials. Add those explicitly through the chosen host's secret mechanism only after provider validation. Trusted forwarded IP handling is disabled; behind this proxy the current login limiter is shared by proxy IP, not individual clients. Configure a trusted-proxy boundary and edge abuse controls for the real deployment. Pin and review container image digests before release.

## Encrypted backup and recovery

Run from `backend`, with the same ledger, data key and signing key as the service and a separate backup key. Paths below are examples: choose a private directory outside the repository, and use new filenames on every run.

```powershell
.\.venv\Scripts\python.exe -m app.admin backup --output D:/private-backups/inventory-001.enc --checkpoint D:/private-checkpoints/inventory-001.json
.\.venv\Scripts\python.exe -m app.admin restore-drill --backup D:/private-backups/inventory-001.enc --checkpoint D:/private-checkpoints/inventory-001.json
.\.venv\Scripts\python.exe -m app.admin verify-checkpoint --checkpoint D:/private-checkpoints/inventory-001.json
# An actual restore creates a NEW database; it never replaces the running ledger.
.\.venv\Scripts\python.exe -m app.admin restore --backup D:/private-backups/inventory-001.enc --checkpoint D:/private-checkpoints/inventory-001.json --output D:/private-recovery/restored-001.sqlite
```

The [SQLite online-backup API](https://www.sqlite.org/backup.html) captures a consistent snapshot including committed WAL data. The archive is encrypted and authenticated with the independent backup key. Signed metadata binds its database hash and audit checkpoint. Restore verifies those checks plus the separately retained checkpoint, revokes all restored sessions and records a recovery event. The drill uses a temporary restored database and leaves live data untouched. All destination files must be new; accidental overwrite is refused. If checkpoint-file creation fails after writing a backup, that backup may remain, but the command fails: inspect it and rerun with fresh paths rather than assuming a complete backup pair.

Keep the matching checkpoint separately in independently controlled retention storage, not only beside the archive. A later checkpoint can detect an older backup but cannot make it contain missing later events; consciously reconcile that recovery gap. Retain all three keys separately in your secret-management recovery process. Losing required keys prevents restoration. A valid backup does not prove the truth of the original accounting evidence.

This implementation handles database snapshots up to 256 MB, uses in-memory encrypted archives (up to 400 MB input), and has a snapshot deadline. It is suitable for the current single-node demo; design streaming/object-storage backups for larger datasets. Temporary decrypted recovery files require a trusted encrypted local disk. File deletion is not guaranteed secure erasure. Scheduling, off-host retention, external alerting and host-level disaster drills remain operational work. An actual switchover requires stopping writers, validating recovered state and explicitly changing `LEDGER_PATH`; it is never automated by the restore command.

## Health, telemetry and CI

- `GET /api/ready` is a minimal public readiness probe: database connectivity plus decryption of the latest inventory, when present. It is not a full audit-chain, factor or Lyzr health check.
- `GET /api/operations` is administrator-only. It exposes current-process request counts, errors, average/max durations and honest integration status. Metrics reset on restart and are not aggregated across workers.
- Structured request logs contain generated request IDs, normalized route templates, bounded method names, status and duration; no bodies, queries, cookies or user-supplied filenames. Configure infrastructure log retention/access separately. Review other server/proxy log sources before promising end-to-end PII-free logging.
- `.github/workflows/verify.yml` prepares offline backend tests, frontend build/lint, Python requirements auditing and production npm dependency auditing on push/PR. It has not been run by GitHub here. Deployment approval, alert routing and independent application security testing are not supplied by that workflow.

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
| `POST /api/runs/{id}/suppliers/{request}/approve` | Administrator/reviewer approval bound to exact recipient/message hash |
| `GET /api/runs/{id}/suppliers/{request}/draft` | Unsent email download; HTTP 409 without current approval |
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
- Independent security assessment, continuous dependency auditing, SSO/MFA, account lifecycle/recovery, organization retention policy, scheduled off-host backups and host-level recovery drills, external WORM/checkpoint storage, monitored alerting and incident response. Local backup/restore checks and basic process telemetry are implemented, not a managed operations service.
- Load/soak testing, deployment tests, concurrent-workspace performance, disaster recovery and production support ownership. Browser QA is Edge/Chromium desktop and mobile emulation, not a full cross-browser/device certification.
- Provider-side Lyzr Data Analysis Agent and Safe AI configuration verification and evaluation evidence. The application has deterministic math/redaction guards, but those are not proof of provider-side capabilities being enabled.
- Autonomous email delivery/replies, mail-provider integration and domain/recipient approval. Current supplier outreach is intentionally a human-reviewed unsent draft workflow.

Do not label the deployment “fully compliant,” “audit assured,” or “production certified” solely because software tests pass.
