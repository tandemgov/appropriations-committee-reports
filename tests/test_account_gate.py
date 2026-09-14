"""Account keys that are demonstrably wrong are withheld; keys with evidence are kept."""

from approps.normalization.account_gate import JURISDICTION, gate_account_keys, withhold_reason


def _row(**kw):
    base = {
        "report_id": "R1", "chamber": "house", "subcommittee": "Interior-Environment",
        "account": None, "account_inferred": None, "line_item_text": "National Park Service",
        "department": None, "agency": None, "title_name": None, "program": None,
        "account_key": "014-1036", "account_key_title": "Operation of the National Park System, National Park Service, Interior",
        "account_key_agency": None, "account_key_bureau": None, "account_match": "exact",
    }
    base.update(kw)
    return base


def test_specific_in_jurisdiction_key_is_kept():
    assert withhold_reason(_row(line_item_text="Operation of the National Park System")) is None


def test_key_outside_the_subcommittee_is_withheld():
    row = _row(subcommittee="Homeland-Security", line_item_text="State Homeland Security Grant Program",
               account_key="069-8191", account_key_title="Discretionary Grants, Federal Transit Administration")
    assert withhold_reason(row) == "withheld_jurisdiction"


def test_repeated_senate_matches_do_not_admit_a_cross_jurisdiction_key():
    # "Mission Support" on Homeland rows matched NASA exactly in many Senate reports; repetition is not evidence.
    rows = [
        _row(report_id=rid, chamber="senate", subcommittee="Homeland-Security", account="Mission Support",
             line_item_text="Mission Support", account_key="080-0112",
             account_key_title="Mission Support, National Aeronautics and Space Administration")
        for rid in ("S1", "S2", "S3")
    ]
    assert gate_account_keys(rows) == {"withheld_jurisdiction": 3}


def test_reviewed_cross_coded_account_is_kept():
    row = _row(subcommittee="Commerce-Justice-Science", line_item_text="Payment to the Legal Services Corporation",
               account_key="020-0501", account_key_title="Payment to the Legal Services Corporation, Legal Services Corporation")
    assert withhold_reason(row) is None


def test_agency_without_a_jurisdiction_entry_is_withheld():
    assert "999" not in JURISDICTION
    row = _row(line_item_text="Some Commission", account_key="999-0001", account_key_title="Some Commission")
    assert withhold_reason(row) == "withheld_unmapped_agency"


def test_generic_label_without_agency_evidence_is_withheld():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries and expenses",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row) == "withheld_generic"


def test_generic_label_that_is_unique_in_jurisdiction_is_still_withheld():
    # "Inspector General" in a State-Foreign-Ops report is not evidence for the Export-Import Bank's IG.
    row = _row(subcommittee="State-Foreign-Ops", line_item_text="Inspector General",
               account_key="083-0400", account_key_title="Inspector General, Export-Import Bank of the United States")
    assert withhold_reason(row) == "withheld_generic"


def test_generic_label_named_by_its_department_is_kept():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries and expenses",
               department="FINANCIAL CRIMES ENFORCEMENT NETWORK",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row) is None


def test_single_word_that_only_begins_a_title_is_withheld():
    row = _row(subcommittee="State-Foreign-Ops", line_item_text="Vietnam",
               account_key="519-8000", account_key_title="Vietnam Education Foundation")
    assert withhold_reason(row) == "withheld_partial_label"


def test_single_word_that_is_the_whole_account_name_is_kept():
    row = _row(subcommittee="Commerce-Justice-Science", line_item_text="Aeronautics",
               account_key="080-0126", account_key_title="Aeronautics, National Aeronautics and Space Administration")
    assert withhold_reason(row) is None


def test_designation_only_label_is_generic():
    row = _row(line_item_text="(emergency)", account_key="014-1039",
               account_key_title="Construction, National Park Service, Interior")
    assert withhold_reason(row) == "withheld_generic"


def test_heading_is_withheld():
    row = _row(subcommittee="Energy-Water", line_item_text="DEPARTMENT OF THE ARMY",
               account_key="096-8862", account_key_title="Department of the Army General Gift Fund")
    assert withhold_reason(row) == "withheld_heading"


def test_tie_break_won_only_by_the_subcommittee_name_is_withheld():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries of judges and bankruptcy judges",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row) == "withheld_ambiguous"


def test_withheld_key_is_preserved_for_review():
    row = _row(line_item_text="Offsetting collections", account_key="020-6722",
               account_key_title="Offsetting Collections and Applied Refunds, Treasury", account_match="tango",
               account_key_agency="Department of the Treasury")
    counts = gate_account_keys([row])
    assert counts == {"withheld_jurisdiction": 1}
    assert row["account_key"] is None and row["account_key_agency"] is None
    assert row["account_key_withheld"] == "020-6722"


def test_enacted_row_without_a_subcommittee_skips_jurisdiction():
    row = _row(subcommittee=None, line_item_text="Economic Support Fund", account_key="072-1037",
               account_key_title="Economic Support Fund")
    assert withhold_reason(row) is None


def test_secondary_bill_needs_the_bureau_that_justifies_it():
    # USDA accounts are in Interior only for the Forest Service; Interior's hazardous-materials line is not USDA's account.
    usda = _row(line_item_text="Hazardous materials management", account_key="012-0500",
                account_key_title="Hazardous Materials Management, Agriculture")
    forest = _row(line_item_text="Wildland Fire Management", account_key="012-1115",
                  account_key_title="Wildland Fire Management, Forest Service, Agriculture")
    assert withhold_reason(usda) == "withheld_jurisdiction"
    assert withhold_reason(forest) is None


def test_primary_bill_needs_no_bureau():
    row = _row(subcommittee="Agriculture", line_item_text="Hazardous materials management", account_key="012-0500",
               account_key_title="Hazardous Materials Management, Agriculture")
    assert withhold_reason(row) is None


def test_partial_single_word_is_not_rescued_by_a_department_heading():
    row = _row(subcommittee="Financial-Services", line_item_text="Council", title_name="EXECUTIVE OFFICE OF THE PRESIDENT",
               account_key="011-1453", account_key_title="Council on Environmental Quality and Office of Environmental Quality, Executive")
    assert withhold_reason(row) == "withheld_partial_label"
