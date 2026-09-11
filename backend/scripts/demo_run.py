"""Run the bundled sample dataset through the pipeline and print a status summary.
Usage (from backend/): python scripts/demo_run.py"""
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent))

from app.pipeline import Pipeline  # noqa: E402

SAMPLES = BACKEND / "data" / "samples"
files = [(p.name, p.read_bytes()) for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in (".csv", ".pdf")]
prior = json.loads((SAMPLES / "prior_period_fy2024.json").read_text())
summary, entries, log = Pipeline().run(files, "Northbridge Precision Components Ltd", "CSRD", prior_totals=prior)

print("run", summary.run_id, "mode", summary.agent_mode, "period", summary.reporting_period)
t = summary.totals
print(f"S1={t.scope1} S2={t.scope2_location} S3={t.scope3} total={t.total_location_based}")
print("status:", Counter(e.status for e in entries))
print("methods:", Counter(e.classification.method for e in entries))
print()
for e in entries:
    print(f"{e.item.line_id:38} {e.status:16} {str(e.classification.activity_type):32} {str(e.item.quantity):>12} {str(e.item.unit):14} {e.item.region!s:5} {e.calculation.t_co2e if e.calculation else '':>12}  {e.factor_match.factor.factor_id if e.factor_match.factor else e.factor_match.reason[:60] or e.classification.reason[:60]}")
print()
for f in summary.findings:
    print(f"[{f.severity}] {f.check_id} {f.title} ({len(f.line_ids)} lines)")
print()
for l in log:
    print(l.ts, l.agent, l.mode, l.step, "|", l.input_summary, "->", l.output_summary)
