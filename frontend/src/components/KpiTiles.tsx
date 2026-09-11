import { fmtT, type ScopeTotals } from '../api'

export default function KpiTiles({ t }: { t: ScopeTotals }) {
  const gaps = t.lines_unmatched + t.lines_unclassified + t.lines_no_quantity + t.lines_unit_error
  return (
    <div className="kpis">
      <div className="kpi s1">
        <div className="eyebrow">Scope 1</div>
        <div className="v num">{fmtT(t.scope1)}</div>
        <div className="u">tCO₂e · direct combustion</div>
      </div>
      <div className="kpi s2">
        <div className="eyebrow">Scope 2</div>
        <div className="v num">{fmtT(t.scope2_location)}</div>
        <div className="u">tCO₂e · location-based</div>
      </div>
      <div className="kpi s3">
        <div className="eyebrow">Scope 3</div>
        <div className="v num">{fmtT(t.scope3)}</div>
        <div className="u">tCO₂e · {Object.keys(t.scope3_by_category).length} categories</div>
      </div>
      <div className="kpi total">
        <div className="eyebrow">Total</div>
        <div className="v num">{fmtT(t.total_location_based)}</div>
        <div className="u">tCO₂e · location-based</div>
        <div className="d">
          {t.lines_calculated} of {t.lines_total} lines calculated · {gaps} gap{gaps === 1 ? '' : 's'} · {t.lines_duplicate} duplicate{t.lines_duplicate === 1 ? '' : 's'} removed
        </div>
      </div>
    </div>
  )
}
