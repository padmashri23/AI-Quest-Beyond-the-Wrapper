"""Unit tests for the rules-first classifier and the deterministic factor matcher.

The matcher tests build a tiny synthetic factor table so the resolution chain
(exact -> year fallback -> region fallback -> GLOBAL -> none) is asserted on its own,
independent of whichever official publication is currently imported.
"""
import json
from decimal import Decimal

import pytest

from app.classify.rules import apply_agent_label, classify_by_rules
from app.factors.matcher import ACTIVITY_TYPES, EGRID_SUBREGIONS, FactorLibrary, library
from app.schemas import LineItem


def item(description: str, **overrides) -> LineItem:
    return LineItem(line_id="line", source_file="f.csv", source_ref="row 1", description=description, **overrides)


# ---------------------------------------------------------------- rule families
@pytest.mark.parametrize("description,unit,activity,rule_id", [
    ("R-410A top-up", "kg", "refrigerant_r410a", "R00_R410A"),
    ("Natural gas statement", "kWh", "natural_gas_stationary", "R02_NATGAS"),
    ("Electricity supply - Octopus", "MWh", "electricity_grid", "R01_ELEC"),
    ("Standby diesel for generator", "litre", "diesel_stationary", "R03_DIESEL_GEN"),
    ("Fleet fuel card", "litre", "diesel_mobile", "R04_DIESEL_FLEET"),
    ("Unleaded fuel", "litre", "petrol_mobile", "R05_PETROL"),
    ("Forklift gas cylinders", "litre", "propane_stationary", "R06_LPG"),
    ("Ocean freight Maersk", "tonne_km", "sea_freight", "R14_SEA_FREIGHT"),
    ("Air cargo", "tonne_km", "air_freight", "R15_AIR_FREIGHT"),
    ("Rail freight container", "tonne_km", "rail_freight", "R16_RAIL_FREIGHT"),
    ("Pallet delivery", "tonne_km", "road_freight", "R17_ROAD_FREIGHT"),
    ("Long-haul flight to Singapore", "passenger_km", "air_travel_long_haul", "R07_AIR_LONG"),
    ("Short-haul flight", "passenger_km", "air_travel_short_haul", "R08_AIR_SHORT"),
    ("Domestic flight", "passenger_km", "air_travel_domestic", "R09_AIR_DOM"),
    ("Airfare", "passenger_km", "air_travel_medium_haul", "R10_AIR_GENERIC"),
    ("Eurostar ticket", "passenger_km", "rail_travel", "R11_RAIL"),
    ("Premier Inn", "room_night", "hotel_stay", "R12_HOTEL"),
    ("Employee mileage claim", "mile", "car_travel", "R13_CAR"),
    ("Thames Water", "m3", "water_supply", "R18_WATER_SUPPLY"),
    ("Trade effluent charge", "m3", "water_treatment", "R19_WATER_TREAT"),
    ("Recycling collection", "tonne", "waste_recycled_mixed", "R20_WASTE_RECYCLED"),
    ("General waste skip hire", "tonne", "waste_landfill_mixed", "R21_WASTE_LANDFILL"),
    ("T&D losses", "kWh", "electricity_transmission_losses", "R22_TD_LOSSES"),
])
def test_each_rule_family_labels_scope_and_activity(description, unit, activity, rule_id):
    classification = classify_by_rules(item(description, quantity=Decimal("1"), unit=unit))
    assert (classification.activity_type, classification.rule_id, classification.method) == (activity, rule_id, "rule")
    assert classification.scope == ACTIVITY_TYPES[activity]["scope"]
    assert classification.scope3_category == ACTIVITY_TYPES[activity].get("cat")


def test_freight_keywords_win_over_passenger_travel_keywords():
    # "rail freight" must never resolve to passenger rail even though "rail" is a travel keyword
    assert classify_by_rules(item("Rail freight to depot", quantity=Decimal("1"), unit="tonne_km")).activity_type == "rail_freight"
    assert classify_by_rules(item("Air freight consignment", quantity=Decimal("1"), unit="tonne_km")).activity_type == "air_freight"


def test_confidence_tiers_follow_rule_ordering():
    assert classify_by_rules(item("Electricity supply", quantity=Decimal("1"), unit="kWh")).confidence == Decimal("0.95")
    assert classify_by_rules(item("Recycling collection", quantity=Decimal("1"), unit="tonne")).confidence == Decimal("0.80")


def test_gl_code_hint_is_the_strongest_signal():
    hinted = classify_by_rules(item("Misc utilities", gl_code="6110-01", quantity=Decimal("1"), unit="kWh"))
    assert (hinted.activity_type, hinted.rule_id, hinted.confidence) == ("natural_gas_stationary", "GL_6110", Decimal("0.90"))
    assert classify_by_rules(item("Anything at all", gl_code="7000")).activity_type == "not_an_emission_source"
    fallthrough = classify_by_rules(item("Electricity supply", gl_code="9999", quantity=Decimal("1"), unit="kWh"))
    assert fallthrough.rule_id == "R01_ELEC"


def test_spend_rules_need_a_monetary_signal():
    by_spend = classify_by_rules(item("Dell laptops", spend=Decimal("5000")))
    assert (by_spend.activity_type, by_spend.rule_id) == ("spend_it_equipment", "R31_SPEND_IT")
    by_currency_unit = classify_by_rules(item("KPMG audit fee", quantity=Decimal("1200"), unit="USD"))
    assert by_currency_unit.activity_type == "spend_professional_services"
    counted_not_priced = classify_by_rules(item("Dell laptops", quantity=Decimal("3"), unit="unit"))
    assert counted_not_priced.method == "unclassified" and counted_not_priced.rule_id == "R31_SPEND_IT"
    assert classify_by_rules(item("Steel rebar", spend=Decimal("900"))).activity_type == "spend_steel_products"


def test_keyword_with_contradicting_unit_is_held_for_review():
    held = classify_by_rules(item("Diesel", quantity=Decimal("10"), unit="kWh"))
    assert held.method == "unclassified" and held.activity_type is None
    assert held.rule_id == "R04_DIESEL_FLEET" and held.confidence == Decimal("0.3") and "needs review" in held.reason


def test_no_keyword_match_is_left_for_the_agent():
    unmatched = classify_by_rules(item("Miscellaneous sundries"))
    assert unmatched.method == "unclassified" and unmatched.confidence == 0 and unmatched.rule_id is None
    assert "classifier agent" in unmatched.reason


def test_vendor_and_raw_text_are_part_of_the_matched_text():
    assert classify_by_rules(item("Invoice 4471", vendor="EDF Energy", quantity=Decimal("1"), unit="kWh")).activity_type == "electricity_grid"
    assert classify_by_rules(item("Invoice 4472", raw_text="... natural gas supply ...", quantity=Decimal("1"), unit="kWh")).activity_type == "natural_gas_stationary"


@pytest.mark.parametrize("description", ["Software licence renewal", "Payroll March", "Office insurance premium"])
def test_non_emission_lines_are_labelled_explicitly(description):
    classification = classify_by_rules(item(description, spend=Decimal("100")))
    assert classification.activity_type == "not_an_emission_source" and classification.scope is None


def test_apply_agent_label_accepts_only_catalogue_keys():
    accepted = apply_agent_label("hotel_stay", Decimal("0.8"), "agent reasoning")
    assert (accepted.method, accepted.scope, accepted.scope3_category, accepted.confidence) == ("agent", 3, 6, Decimal("0.8"))
    for bad in (None, "", "unicorn_fuel"):
        rejected = apply_agent_label(bad, Decimal("0.9"), "x")
        assert rejected.method == "unclassified" and rejected.confidence == 0 and "rejected" in rejected.reason


# ---------------------------------------------------------------- factor matcher
def row(factor_id, activity, scope, region, year, value, unit="kWh", **extra):
    return {"factor_id": factor_id, "activity_type": activity, "scope": scope, "region": region, "year": year,
            "value": value, "unit": unit, "source": "synthetic", "table_ref": "synthetic table", **extra}


@pytest.fixture
def lib(tmp_path) -> FactorLibrary:
    table = {
        "table_id": "synthetic", "url": "https://example.test/table",
        "rows": [
            row("EL_GB_2023", "electricity_grid", 2, "GB", 2023, "0.2"),
            row("EL_GB_2025", "electricity_grid", 2, "GB", 2025, "0.18"),
            row("EL_US_2022", "electricity_grid", 2, "US", 2022, "0.37"),
            row("HOTEL_GLOBAL", "hotel_stay", 3, "GLOBAL", 2024, "10", unit="room_night", scope3_category=6),
            row("RAIL_FUTURE", "rail_travel", 3, "GB", 2030, "0.03", unit="passenger_km", scope3_category=6),
        ],
    }
    (tmp_path / "synthetic.json").write_text(json.dumps(table), encoding="utf-8")
    return FactorLibrary(tmp_path)


def test_exact_region_and_year_is_preferred(lib):
    match = lib.match("electricity_grid", "GB", 2025)
    assert match.matched and match.factor.factor_id == "EL_GB_2025" and match.match_quality == "exact"
    assert match.reason == "EL_GB_2025 from synthetic (synthetic table)"


def test_older_year_is_used_when_requested_year_is_missing(lib):
    match = lib.match("electricity_grid", "GB", 2024)
    assert match.factor.factor_id == "EL_GB_2023" and match.match_quality == "year_fallback"
    assert match.reason.startswith("year_fallback: requested region=GB year=2024; used GB 2023.")


def test_no_year_means_newest_row(lib):
    match = lib.match("electricity_grid", "GB", None)
    assert match.factor.factor_id == "EL_GB_2025" and match.match_quality == "exact"


def test_uk_and_lowercase_regions_normalise_to_gb(lib):
    assert lib.match("electricity_grid", "uk", 2025).factor.factor_id == "EL_GB_2025"
    assert lib.match("electricity_grid", " gb ", 2025).match_quality == "exact"


def test_defra_family_countries_fall_back_to_gb(lib):
    match = lib.match("electricity_grid", "IE", 2025)
    assert match.factor.factor_id == "EL_GB_2025" and match.match_quality == "region_fallback"
    assert "requested region=IE" in match.reason


def test_egrid_subregions_fall_back_to_the_us_average(lib):
    assert "CAMX" in EGRID_SUBREGIONS
    match = lib.match("electricity_grid", "CAMX", 2025)
    assert match.factor.factor_id == "EL_US_2022" and match.match_quality == "region_fallback"


def test_global_rows_are_the_last_resort(lib):
    assert lib.match("hotel_stay", "JP", 2025).match_quality == "global_fallback"
    assert lib.match("hotel_stay", None, 2024).match_quality == "exact"
    assert lib.match("hotel_stay", None, 2025).match_quality == "year_fallback"


def test_rows_newer_than_the_reporting_year_are_never_used(lib):
    match = lib.match("rail_travel", "GB", 2025)
    assert not match.matched and match.factor is None and match.match_quality == "none"
    assert "no estimate produced" in match.reason


def test_unknown_activity_and_non_sources_do_not_match(lib):
    unknown = lib.match("unicorn_fuel", "GB", 2025)
    assert not unknown.matched and unknown.reason.startswith("Unknown or missing activity_type")
    assert not lib.match(None, "GB", 2025).matched
    assert lib.match("not_an_emission_source", "GB", 2025).reason == "Line is not an emission source"


def test_rows_inherit_the_table_url_and_metadata_excludes_rows(lib):
    assert lib.match("electricity_grid", "GB", 2025).factor.url == "https://example.test/table"
    assert lib.tables == [{"table_id": "synthetic", "url": "https://example.test/table"}]
    assert len(lib.list_rows()) == 5 and lib.list_rows() is not lib.rows


def test_shared_library_is_a_singleton_with_verified_official_rows():
    shared = library()
    assert shared is library()
    assert any(r.verified and r.source_sha256 for r in shared.rows)
