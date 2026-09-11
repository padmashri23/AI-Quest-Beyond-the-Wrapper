# agents/

Lyzr agent layer for the Carbon Copilot. Two agents, three deterministic tools, one orchestrator.

| Path | What it is |
|---|---|
| `classifier/` | **Scope Classifier** agent config + system prompt. Labels redacted lines with a closed-list `activity_type`. Temperature 0, JSON-only output. |
| `disclosure_writer/` | **Disclosure Writer** agent config + system prompt. Turns computed figures into ESRS E1 / SEC narrative. Number-locked. |
| `tools/openapi.yaml` | OpenAPI schema for the deterministic tools the backend exposes (`match_factor`, `calculate_emissions`, `get_lineage`, `list_units`). Register in Lyzr Studio as an OpenAPI tool. |
| `lyzr_client.py` | Minimal client for `POST /v3/inference/chat/`. |
| `orchestrator.py` | Hand-off logic, batching, label validation, number-lock, governance log. |
| `deploy_agents.py` | Creates both agents via the Agent API from the JSON configs. |

## Handoff contract

```
ingest -> redact -> rules classify -> [residue] -> Scope Classifier (Lyzr)
                                                    | validated labels only
                                   match_factor (tool) -> calculate (tool) -> ledger
                                                    |
                 greenwashing checks (tool) -> [figures] -> Disclosure Writer (Lyzr)
                                                    | number-lock + claim guard
                                                  report
```

The model never sees a price, an account number, or a raw vendor name. The model never
produces a number that reaches the report: labels are validated against a closed list and
narrative numerals are validated against the figures payload.

## Fallback mode

No `LYZR_API_KEY`? The orchestrator logs `mode=fallback`, leaves unmatched residue lines
as "needs review", and renders the narrative from a deterministic template. Every tCO2e
figure is identical in both modes because figures never come from an agent.
