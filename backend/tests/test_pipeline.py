"""End-to-end run over the bundled sample dataset in fallback (no Lyzr key) mode, plus
the orchestrator's number-lock and label validation contracts."""
from decimal import Decimal
from pathlib import Path

from app.pipeline import Pipeline
from app.reports.render import figures_payload, render_markdown, template_narrative
from agents.orchestrator import Orchestrator, number_lock
from agents.lyzr_client import LyzrClient

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def _files():
    return [(p.name, p.read_bytes()) for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in (".csv", ".pdf")]


def test_sample_run_is_deterministic_and_traceable():
    p = Pipeline(Orchestrator(client=LyzrClient(api_key=""), allowed_activity_types=set()))
    s1, e1, _ = p.run(_files(), "Test Co", "CSRD")
    s2, e2, _ = p.run(_files(), "Test Co", "CSRD")
    assert s1.totals.total_location_based == s2.totals.total_location_based > 0
    assert s1.agent_mode == "fallback"
    # every calculated line cites a factor and carries a formula
    for e in e1:
        if e.status == "calculated":
            assert e.factor_match.factor is not None and e.calculation is not None
            assert e.factor_match.factor.factor_id in e.factor_match.reason
            assert "=" in e.calculation.formula
    # totals equal the sum of lines (no hidden arithmetic)
    total = sum((e.calculation.t_co2e for e in e1 if e.status == "calculated"), Decimal("0"))
    assert total == s1.totals.total_location_based
    # PII never survives into the ledger text
    for e in e1:
        assert "@" not in (e.item.raw_text or "")


def test_report_renders_with_template_narrative():
    p = Pipeline(Orchestrator(client=LyzrClient(api_key=""), allowed_activity_types=set()))
    s, entries, log = p.run(_files(), "Test Co", "SEC")
    payload = figures_payload(s, entries, "SEC")
    narrative = template_narrative(payload)
    ok, problems = number_lock(narrative, payload)
    assert ok, problems
    md = render_markdown(s, entries, log, narrative, "template", "SEC")
    assert "Item 1504" in md and "Appendix A" in md
    # the template must never trip the claim guard it is supposed to pass
    from app.guardrails.greenwashing import run_checks
    assert not [f for f in run_checks(entries, s.totals, narrative=narrative) if f.check_id == "GW03"]


def test_number_lock_rejects_invented_or_rounded_numbers():
    payload = {"figures": {"scope1_t": "123.456789"}, "data_quality": {"lines_total": 88}}
    assert number_lock("Scope 1 was 123.456789 tCO2e across 88 lines.", payload)[0]
    ok, problems = number_lock("Scope 1 was 123.46 tCO2e.", payload)
    assert not ok and any("rounded" in p for p in problems)
    ok, problems = number_lock("Scope 1 was 999 tCO2e.", payload)
    assert not ok and "999" in problems


def test_label_validation_rejects_unknown_activity():
    o = Orchestrator(client=LyzrClient(api_key=""), allowed_activity_types={"electricity_grid"})
    batch = [{"line_id": "a"}, {"line_id": "b"}]
    text = '[{"line_id":"a","activity_type":"electricity_grid","confidence":0.9,"reason":"ok"},{"line_id":"b","activity_type":"made_up","confidence":0.9,"reason":"x"}]'
    accepted, rejected = o._validate_labels(batch, text)
    assert set(accepted) == {"a"} and rejected == 1
