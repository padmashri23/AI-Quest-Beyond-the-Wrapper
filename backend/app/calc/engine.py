"""Deterministic emission calculation engine.

    kg CO2e = quantity_in_factor_unit x factor_value
    t CO2e  = kg CO2e / 1000
Uses python.decimal with a 28-digit context. No floats anywhere. The returned
Calculation carries every operand so the audit trail can reproduce the figure by hand.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, getcontext, localcontext

from ..schemas import Calculation, FactorRow
from .units import convert, normalise_unit

getcontext().prec = 28

_KG_Q = Decimal("0.000001")
_T_Q = Decimal("0.000001")

# IPCC AR5 100-year GWPs, as used by the EPA GHG Emission Factors Hub (2024 edition).
GWP = {
    "AR5-100": {"CO2": Decimal("1"), "CH4": Decimal("28"), "N2O": Decimal("265")},
    "AR4-100": {"CO2": Decimal("1"), "CH4": Decimal("25"), "N2O": Decimal("298")},
}


def calculate(quantity: Decimal, unit: str, factor: FactorRow) -> Calculation:
    # Context must be local: FastAPI calculation workers have independent contexts.
    with localcontext() as context:
        context.prec = 60
        if not factor.value.is_finite() or factor.value < 0:
            raise ValueError('Factor must be finite and non-negative')
        if factor.components and any(not v.is_finite() or v < 0 for v in factor.components.values()):
            raise ValueError('Gas components must be finite and non-negative')
        return _calculate(quantity, unit, factor)


def _calculate(quantity: Decimal, unit: str, factor: FactorRow) -> Calculation:
    if quantity is None:
        raise ValueError("quantity is required")
    if not quantity.is_finite() or quantity < 0 or quantity > Decimal('1e18'):
        raise ValueError("Quantity must be finite, non-negative and no greater than 1e18; corrections require a reviewed revision")
    unit_norm = normalise_unit(unit)
    if unit_norm is None:
        raise ValueError(f"Unknown unit '{unit}'")

    qty_conv, step = convert(quantity, unit_norm, factor.unit)

    gas_breakdown = None
    if factor.components:
        gwp = GWP[factor.gwp_set or "AR5-100"]
        gas_breakdown = {}
        kg_total = Decimal("0")
        for gas, per_unit in factor.components.items():
            kg_gas = (qty_conv * per_unit * gwp[gas]).quantize(_KG_Q, rounding=ROUND_HALF_EVEN)
            gas_breakdown[gas] = kg_gas
            kg_total += kg_gas
        kg = kg_total
        comp_str = " + ".join(f"{gas}:{per_unit}x{gwp[gas]}" for gas, per_unit in factor.components.items())
        formula = f"{qty_conv} {factor.unit} x ({comp_str}) kg/{factor.unit} = {kg} kg CO2e"
    else:
        kg = (qty_conv * factor.value).quantize(_KG_Q, rounding=ROUND_HALF_EVEN)
        formula = f"{qty_conv} {factor.unit} x {factor.value} kg CO2e/{factor.unit} = {kg} kg CO2e"

    if step:
        formula = f"{quantity} {unit_norm} x {step.factor} = {qty_conv} {factor.unit}; " + formula

    t = (kg / Decimal("1000")).quantize(_T_Q, rounding=ROUND_HALF_EVEN)

    return Calculation(
        quantity_input=quantity,
        unit_input=unit_norm,
        conversion=step,
        quantity_converted=qty_conv,
        unit_converted=factor.unit,
        factor_value=factor.value,
        factor_unit=f"kg CO2e/{factor.unit}",
        kg_co2e=kg,
        t_co2e=t,
        gas_breakdown=gas_breakdown,
        formula=formula + f"; / 1000 = {t} tCO2e",
    )
