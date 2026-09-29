"""Unit tests for the conversion table and the Decimal calculation engine.

The golden suite proves whole calculations against published factors; these tests pin
the smaller contracts underneath them: alias normalisation, dimension isolation,
rounding mode, GWP selection and every refusal path.
"""
from decimal import Decimal, getcontext

import pytest

from app.calc.engine import GWP, calculate
from app.calc.units import convert, dimension_of, known_units, normalise_unit
from app.schemas import FactorRow


def factor(**overrides) -> FactorRow:
    base = dict(factor_id="TEST_ROW", activity_type="electricity_grid", scope=2, region="GB", year=2025,
                value=Decimal("0.2"), unit="kWh", source="test", table_ref="synthetic")
    base.update(overrides)
    return FactorRow(**base)


# ---------------------------------------------------------------- unit normalisation
@pytest.mark.parametrize("raw,canonical", [
    ("kwh", "kWh"), ("KWH", "kWh"), (" MWh ", "MWh"), ("therms", "therm"), ("thm", "therm"),
    ("Liters", "litre"), ("ltr", "litre"), ("gal", "us_gallon"), ("mt", "tonne"), ("lbs", "lb"),
    ("kilometer", "km"), ("mi", "mile"), ("ton-mile", "ton_mile"), ("pax_km", "passenger_km"),
    ("nights", "room_night"), ("m³", "m3"), ("$", "usd"), ("ccf", "ccf"), ("GJ", "GJ"),
])
def test_aliases_normalise_to_canonical_units(raw, canonical):
    assert normalise_unit(raw) == canonical


def test_unknown_units_are_none_not_guessed():
    assert normalise_unit(None) is None
    assert normalise_unit("bananas") is None
    assert normalise_unit("") is None
    assert dimension_of("bananas") is None


@pytest.mark.parametrize("unit,dimension", [
    ("kWh", "energy"), ("therm", "energy"), ("ccf", "energy"), ("litre", "volume"), ("uk_gallon", "volume"),
    ("lb", "mass"), ("short_ton", "mass"), ("mile", "distance"), ("ton_mile", "freight"),
    ("passenger_mile", "travel"), ("m3", "water"), ("room_night", "accommodation"), ("kg_waste", "waste"),
    ("usd", "spend"),
])
def test_every_unit_belongs_to_one_dimension(unit, dimension):
    assert dimension_of(unit) == dimension


# ---------------------------------------------------------------- conversion
def test_identity_conversion_returns_no_step():
    quantity, step = convert(Decimal("5"), "kwh", "kWh")
    assert quantity == Decimal("5") and step is None


@pytest.mark.parametrize("quantity,source,target,expected", [
    ("1", "MWh", "kWh", "1000"),
    ("1", "GWh", "MWh", "1000"),
    ("10", "therm", "kWh", "293.001"),
    ("1", "mmBtu", "therm", "10"),
    ("1", "ccf", "scf_natural_gas", "100"),
    ("1", "uk_gallon", "litre", "4.54609"),
    ("2", "short_ton", "kg", "1814.36948"),
    ("100", "passenger_mile", "passenger_km", "160.9344"),
    ("1000", "kg_waste", "tonne_waste", "1"),
    ("1", "kL", "m3", "1"),
])
def test_same_dimension_conversions_use_documented_constants(quantity, source, target, expected):
    converted, step = convert(Decimal(quantity), source, target)
    assert converted == Decimal(expected)
    assert step is not None and step.from_unit == normalise_unit(source) and step.to_unit == normalise_unit(target)
    assert step.source  # every step cites where the constant came from


def test_cross_dimension_and_unknown_conversions_are_refused():
    with pytest.raises(ValueError, match="dimensions differ"):
        convert(Decimal("1"), "litre", "kWh")
    with pytest.raises(ValueError, match="Unknown unit 'furlong'"):
        convert(Decimal("1"), "furlong", "km")
    with pytest.raises(ValueError, match="Unknown unit 'furlong'"):
        convert(Decimal("1"), "km", "furlong")


def test_known_units_catalogue_is_self_describing():
    units = known_units()
    assert set(units["therm"]) == {"dimension", "to_base", "source"}
    assert units["therm"]["dimension"] == "energy"
    assert Decimal(units["MWh"]["to_base"]) == Decimal("1000")
    assert all(meta["source"] for meta in units.values())


# ---------------------------------------------------------------- engine
def test_simple_factor_formula_rounding_and_metadata():
    calc = calculate(Decimal("1234.5678"), "kWh", factor())
    # 1234.5678 x 0.2 = 246.91356 kg -> 0.24691356 t, both quantised to 6 dp
    assert calc.kg_co2e == Decimal("246.913560")
    assert calc.t_co2e == Decimal("0.246914")
    assert calc.conversion is None and calc.gas_breakdown is None
    assert calc.factor_unit == "kg CO2e/kWh" and calc.unit_input == "kWh" and calc.unit_converted == "kWh"
    assert "1234.5678 kWh x 0.2 kg CO2e/kWh = 246.913560 kg CO2e" in calc.formula
    assert calc.formula.endswith("/ 1000 = 0.246914 tCO2e")
    assert "ROUND_HALF_EVEN" in calc.rounding and "decimal" in calc.engine


def test_half_values_round_to_even_not_away_from_zero():
    unit_factor = factor(value=Decimal("1"))
    assert calculate(Decimal("0.0000025"), "kWh", unit_factor).kg_co2e == Decimal("0.000002")
    assert calculate(Decimal("0.0000035"), "kWh", unit_factor).kg_co2e == Decimal("0.000004")


def test_conversion_step_is_recorded_in_calculation_and_formula():
    calc = calculate(Decimal("3"), "MWh", factor())
    assert calc.conversion is not None
    assert (calc.conversion.from_unit, calc.conversion.to_unit, calc.conversion.factor) == ("MWh", "kWh", Decimal("1000"))
    assert calc.quantity_converted == Decimal("3000") and calc.unit_input == "MWh"
    assert calc.formula.startswith("3 MWh x 1000 = 3000 kWh; ")
    assert calc.kg_co2e == Decimal("600.000000")


COMPONENTS = {"CO2": Decimal("53.06"), "CH4": Decimal("0.001"), "N2O": Decimal("0.0001")}


def test_gas_components_are_weighted_with_the_requested_gwp_set():
    ar5 = calculate(Decimal("10"), "mmBtu", factor(unit="mmBtu", components=COMPONENTS, gwp_set="AR5-100", value=Decimal("53.1145")))
    ar4 = calculate(Decimal("10"), "mmBtu", factor(unit="mmBtu", components=COMPONENTS, gwp_set="AR4-100", value=Decimal("53.1145")))
    assert ar5.kg_co2e == Decimal("531.145000")
    # AR4: CH4 10 x 0.001 x 25 = 0.25; N2O 10 x 0.0001 x 298 = 0.298; CO2 530.6
    assert ar4.kg_co2e == Decimal("531.148000")
    assert ar4.gas_breakdown == {"CO2": Decimal("530.600000"), "CH4": Decimal("0.250000"), "N2O": Decimal("0.298000")}
    assert "CH4:0.001x25" in ar4.formula and "N2O:0.0001x298" in ar4.formula
    assert set(GWP) == {"AR5-100", "AR4-100"}


def test_components_default_to_ar5_when_no_gwp_set_given():
    explicit = calculate(Decimal("7"), "mmBtu", factor(unit="mmBtu", components=COMPONENTS, gwp_set="AR5-100"))
    implicit = calculate(Decimal("7"), "mmBtu", factor(unit="mmBtu", components=COMPONENTS, gwp_set=None))
    assert explicit.kg_co2e == implicit.kg_co2e and explicit.gas_breakdown == implicit.gas_breakdown


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "-0.5", "1e19"])
def test_non_finite_negative_or_oversized_quantities_are_refused(bad):
    with pytest.raises(ValueError):
        calculate(Decimal(bad), "kWh", factor())


def test_quantity_upper_bound_is_inclusive():
    calc = calculate(Decimal("1e18"), "kWh", factor())
    assert calc.kg_co2e == Decimal("2e17")


def test_negative_factor_or_component_is_refused():
    with pytest.raises(ValueError, match="Factor must be finite and non-negative"):
        calculate(Decimal("1"), "kWh", factor(value=Decimal("-0.1")))
    with pytest.raises(ValueError, match="Gas components must be finite and non-negative"):
        calculate(Decimal("1"), "kWh", factor(components={"CO2": Decimal("-1")}))


def test_unknown_unit_and_dimension_mismatch_are_refused():
    with pytest.raises(ValueError, match="Unknown unit 'bananas'"):
        calculate(Decimal("1"), "bananas", factor())
    with pytest.raises(ValueError, match="dimensions differ"):
        calculate(Decimal("1"), "litre", factor())


def test_engine_precision_is_local_and_leaves_global_context_untouched():
    before = getcontext().prec
    calculate(Decimal("1"), "kWh", factor())
    assert getcontext().prec == before
