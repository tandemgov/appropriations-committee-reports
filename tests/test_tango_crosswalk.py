"""Tango federal-account matcher: conservative containment + agency scoping."""

from __future__ import annotations

import csv

import pytest

from approps.normalization.tango_crosswalk import TangoCrosswalk


@pytest.fixture
def crosswalk(tmp_path):
    ref = tmp_path / "tango_accounts.csv"
    with ref.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["federal_account_symbol", "account_title", "agency", "bureau"])
        w.writeheader()
        w.writerows([
            {"federal_account_symbol": "019-0113", "account_title": "Diplomatic Programs, State",
             "agency": "Department of State", "bureau": "Department of State"},
            # Two agencies share an "Office of Inspector General" account -> ambiguous.
            {"federal_account_symbol": "019-0209", "account_title": "Office of Inspector General, State",
             "agency": "Department of State", "bureau": "Department of State"},
            {"federal_account_symbol": "070-0116", "account_title": "Office of Inspector General, Homeland Security",
             "agency": "Department of Homeland Security", "bureau": "Departmental Management"},
            {"federal_account_symbol": "070-0530", "account_title": "Operations and Support, Coast Guard",
             "agency": "Department of Homeland Security", "bureau": "Coast Guard"},
        ])
    return TangoCrosswalk(path=ref)


def test_unambiguous_containment_match(crosswalk):
    m = crosswalk.match("Diplomatic Programs")
    assert m is not None and m.federal_account_symbol == "019-0113"
    assert m.agency == "Department of State"


def test_ambiguous_across_agencies_is_not_matched_without_scope(crosswalk):
    # "Office of Inspector General" exists for two agencies -> no single account.
    assert crosswalk.match("Inspector General") is None


def test_agency_scope_resolves_the_ambiguity(crosswalk):
    m = crosswalk.match("Inspector General", allowed_agencies={"Department of Homeland Security"})
    assert m is not None and m.federal_account_symbol == "070-0116"


def test_generic_or_absent_label_does_not_match(crosswalk):
    assert crosswalk.match("Salaries and Expenses") is None  # all stopwords
    assert crosswalk.match("Nonexistent Widget Account") is None


def test_missing_reference_is_safe():
    tc = TangoCrosswalk(path=__import__("pathlib").Path("/no/such/file.csv"))
    assert tc._accounts == []
    assert tc.match("anything") is None
