"""Account keys that are demonstrably wrong are withheld; keys with evidence are kept."""

from approps.normalization.account_gate import gate_account_keys, withhold_reason


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
    assert withhold_reason(_row(line_item_text="Operation of the National Park System"), set()) is None


def test_key_outside_the_subcommittee_is_withheld():
    row = _row(subcommittee="Homeland-Security", line_item_text="State Homeland Security Grant Program",
               account_key="069-8191", account_key_title="Discretionary Grants, Federal Transit Administration")
    assert withhold_reason(row, set()) == "withheld_jurisdiction"


def test_senate_attestation_admits_a_cross_coded_account():
    rows = [
        _row(report_id=rid, chamber="senate", subcommittee="Commerce-Justice-Science",
             account="Payment to the Legal Services Corporation",
             line_item_text="Payment to the Legal Services Corporation",
             account_key="020-0501", account_key_title="Payment to the Legal Services Corporation")
        for rid in ("S1", "S2")
    ]
    house = _row(subcommittee="Commerce-Justice-Science", line_item_text="Payment to the Legal Services Corporation",
                 account_key="020-0501", account_key_title="Payment to the Legal Services Corporation")
    counts = gate_account_keys(rows + [house])
    assert counts == {}
    assert house["account_key"] == "020-0501"


def test_a_single_senate_report_does_not_attest():
    senate = _row(report_id="S1", chamber="senate", subcommittee="Commerce-Justice-Science",
                  account="Payment to the Legal Services Corporation",
                  line_item_text="Payment to the Legal Services Corporation", account_key="020-0501")
    house = _row(subcommittee="Commerce-Justice-Science", line_item_text="Payment to the Legal Services Corporation",
                 account_key="020-0501")
    gate_account_keys([senate, house])
    assert house["account_key"] is None
    assert house["account_match"] == "withheld_jurisdiction"


def test_generic_label_without_agency_evidence_is_withheld():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries and expenses",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row, set()) == "withheld_generic"


def test_generic_label_named_by_its_department_is_kept():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries and expenses",
               department="FINANCIAL CRIMES ENFORCEMENT NETWORK",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row, set()) is None


def test_designation_only_label_is_generic():
    row = _row(line_item_text="(emergency)", account_key="014-1039",
               account_key_title="Construction, National Park Service, Interior")
    assert withhold_reason(row, set()) == "withheld_generic"


def test_heading_is_withheld():
    row = _row(subcommittee="Energy-Water", line_item_text="DEPARTMENT OF THE ARMY",
               account_key="096-8862", account_key_title="Department of the Army General Gift Fund")
    assert withhold_reason(row, set()) == "withheld_heading"


def test_tie_break_won_only_by_the_subcommittee_name_is_withheld():
    row = _row(subcommittee="Financial-Services", line_item_text="Salaries of judges and bankruptcy judges",
               account_key="020-0173", account_key_title="Salaries and Expenses, Financial Crimes Enforcement Network",
               account_match="agency_scoped")
    assert withhold_reason(row, set()) == "withheld_ambiguous"


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
    assert withhold_reason(row, set()) is None
