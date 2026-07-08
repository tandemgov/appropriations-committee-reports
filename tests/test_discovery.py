"""Tests for the discovery layer."""

from approps.discovery.subcommittee_map import (
    classify_stage,
    classify_subcommittee,
    extract_fiscal_year,
)


def test_classify_defense():
    title = "DEPARTMENT OF DEFENSE APPROPRIATIONS BILL, 2024"
    assert classify_subcommittee(title) == "Defense"


def test_classify_interior():
    title = "DEPARTMENT OF THE INTERIOR, ENVIRONMENT, AND RELATED AGENCIES APPROPRIATIONS BILL, 2024"
    assert classify_subcommittee(title) == "Interior-Environment"


def test_classify_dhs():
    title = "DEPARTMENT OF HOMELAND SECURITY APPROPRIATIONS BILL, 2025"
    assert classify_subcommittee(title) == "Homeland-Security"


def test_classify_labor_hhs():
    title = "DEPARTMENTS OF LABOR, HEALTH AND HUMAN SERVICES, AND EDUCATION, AND RELATED AGENCIES APPROPRIATION BILL, 2024"
    assert classify_subcommittee(title) == "Labor-HHS-Education"


def test_classify_thud():
    title = "TRANSPORTATION, HOUSING AND URBAN DEVELOPMENT, AND RELATED AGENCIES APPROPRIATIONS BILL, 2024"
    assert classify_subcommittee(title) == "THUD"


def test_classify_legislative_branch():
    title = "LEGISLATIVE BRANCH APPROPRIATIONS BILL, 2025"
    assert classify_subcommittee(title) == "Legislative-Branch"


def test_classify_unknown():
    title = "SOME RANDOM BILL ABOUT FISH"
    assert classify_subcommittee(title) is None


def test_extract_fy_from_bill_title():
    assert extract_fiscal_year("DEPARTMENT OF DEFENSE APPROPRIATIONS BILL, 2024") == 2024


def test_extract_fy_from_act_title():
    assert extract_fiscal_year("Consolidated Appropriations Act, 2023") == 2023


def test_extract_fy_from_long_title():
    title = "MAKING APPROPRIATIONS FOR THE DEPARTMENT OF HOMELAND SECURITY FOR THE FISCAL YEAR ENDING SEPTEMBER 30, 2026"
    assert extract_fiscal_year(title) == 2026


def test_extract_fy_none():
    assert extract_fiscal_year("SOME BILL WITHOUT A YEAR") is None


def test_classify_stage_committee():
    assert classify_stage("DEFENSE APPROPRIATIONS BILL, 2024", "CRPT-118hrpt121") == "committee"


def test_classify_stage_conference():
    title = "JOINT EXPLANATORY STATEMENT OF THE COMMITTEE OF CONFERENCE"
    assert classify_stage(title, "CRPT-118hrpt1234") == "conference"
