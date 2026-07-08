"""Tests for the account-name normalization layer (crosswalk hygiene + canonicalize)."""

from approps.normalization.account_names import (
    clean_account_label,
    extract_designation,
    is_fragment,
    normalize_account,
    strip_number_leakage,
)


def test_case_and_punctuation_collapse():
    assert normalize_account("International disaster assistance") == "international disaster assistance"
    assert normalize_account("International Disaster Assistance") == "international disaster assistance"


def test_number_leakage_stripped_but_years_preserved():
    # Leaked amount columns at the end are removed...
    assert strip_number_leakage("International narcotics control 300 000") == "International narcotics control"
    assert strip_number_leakage("Intl chancery center 1 320 743 743 577") == "Intl chancery center"
    # ...but a year embedded mid-name is preserved.
    assert strip_number_leakage("Research at 1890 Institutions") == "Research at 1890 Institutions"


def test_designation_not_triggered_by_account_name_body():
    # "Disaster" in the name must NOT be read as a designation.
    assert extract_designation("International Disaster Assistance") == "base"
    # But an explicit parenthetical/suffix qualifier is.
    assert extract_designation("International Disaster Assistance (emergency)") == "emergency"
    assert extract_designation("International Disaster Assistance [OCO]") == "OCO"
    assert extract_designation("Operations, Emergency") == "emergency"


def test_normalize_drops_designation_and_parentheticals():
    a = normalize_account("International Disaster Assistance (emergency)")
    b = normalize_account("International disaster assistance")
    assert a == b == "international disaster assistance"


def test_fragment_detection():
    assert is_fragment("operations)")
    assert is_fragment("relief, and mitigation)")
    assert is_fragment("appropriation)")
    assert not is_fragment("International Disaster Assistance")
    assert not is_fragment("Industrial Technology Services")


def test_clean_account_label_end_to_end():
    label = clean_account_label("International Disaster Assistance (emergency) 1,250,000")
    assert label.normalized == "international disaster assistance"
    assert label.designation == "emergency"
    assert label.is_fragment is False
