"""The discovery pre-filter must keep appropriations committee reports and drop
Rules Committee resolutions that merely reference an appropriations/authorization bill.

Regression for the audit finding: 7 "PROVIDING FOR FURTHER CONSIDERATION OF THE BILL
..." resolutions were slipping into the catalog because the old check only matched the
exact phrase "providing for consideration" (no "further").
"""

from __future__ import annotations

import pytest

from approps.discovery.report_catalog import _is_appropriations_report_title
from approps.discovery.subcommittee_map import (
    classify_subcommittee,
    extract_fiscal_year,
)

KEEP = [
    "ENERGY AND WATER DEVELOPMENT APPROPRIATIONS BILL, 2018",
    "DEPARTMENTS OF LABOR, HEALTH AND HUMAN SERVICES, AND EDUCATION, AND RELATED AGENCIES APPROPRIATIONS BILL, 2025",
    "MILITARY CONSTRUCTION, VETERANS AFFAIRS, AND RELATED AGENCIES APPROPRIATIONS BILL, 2024",
    # Line-break hyphenation in the GovInfo title (CRPT-119hrpt686, House THUD FY2027):
    # "AP- PROPRIATIONS" must still be recognized as an appropriations report.
    "DEPARTMENTS OF TRANSPORTATION, AND HOUSING AND URBAN DEVELOPMENT, AND RELATED AGENCIES AP- PROPRIATIONS BILL, 2027",
]

DROP = [
    # NDAA authorization rules (the 5 that slipped in)
    "PROVIDING FOR FURTHER CONSIDERATION OF THE BILL (H.R. 5515) TO AUTHORIZE APPROPRIATIONS FOR FISCAL YEAR 2019 FOR MILITARY ACTIVITIES",
    "PROVIDING FOR FURTHER CONSIDERATION OF THE BILL (H.R. 2670) TO AUTHORIZE APPROPRIATIONS FOR FISCAL YEAR 2024",
    # appropriations-bill rules (still resolutions, not reports)
    "PROVIDING FOR FURTHER CONSIDERATION OF THE BILL (H.R. 3354) MAKING APPROPRIATIONS FOR THE DEPARTMENT OF THE INTERIOR",
    "PROVIDING FOR CONSIDERATION OF THE BILL (H.R. 2740) MAKING APPROPRIATIONS",
    # "RELATING TO CONSIDERATION" variant (CRPT-114hrpt595, THUD FY2016): a rule about a
    # Senate amendment to an appropriations bill — the old "providing for" check missed it.
    "RELATING TO CONSIDERATION OF THE SENATE AMENDMENT TO THE BILL (H.R. 2577) MAKING APPROPRIATIONS FOR THE DEPARTMENTS OF TRANSPORTATION, AND HOUSING AND URBAN DEVELOPMENT, AND RELATED AGENCIES FOR THE FISCAL YEAR ENDING SEPTEMBER 30, 2016, AND FOR OTHER PURPOSES",
    # unrelated
    "A BILL TO NAME A POST OFFICE",
]


@pytest.mark.parametrize("title", KEEP)
def test_keeps_committee_reports(title):
    assert _is_appropriations_report_title(title) is True


@pytest.mark.parametrize("title", DROP)
def test_drops_rules_and_unrelated(title):
    assert _is_appropriations_report_title(title) is False


# Regression for the 119th-Congress catalog extension (FY2026 + FY2027):
# the House renamed the State-Foreign-Ops subcommittee, and one Senate print
# used a plural "BILLS, 2026" title that the fiscal-year parser missed.
def test_house_119_national_security_state_maps_to_sfops():
    assert (
        classify_subcommittee(
            "NATIONAL SECURITY, DEPARTMENT OF STATE, AND RELATED PROGRAMS APPROPRIATIONS BILL, 2026"
        )
        == "State-Foreign-Ops"
    )


def test_fiscal_year_parses_plural_bills():
    assert (
        extract_fiscal_year(
            "DEPARTMENT OF LABOR, HEALTH AND HUMAN SERVICES, AND EDUCATION, "
            "AND RELATED AGENCIES APPROPRIATIONS BILLS, 2026"
        )
        == 2026
    )
