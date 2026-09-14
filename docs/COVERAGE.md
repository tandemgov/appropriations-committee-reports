# Coverage

What the release contains, by stage, chamber, subcommittee, and fiscal year, and why the gaps are where they are.
Figures are from the release manifest (`data/release/manifest.json`); regenerate them with `approps output` and `scripts/build_release.py`.

## Stages

Appropriations line items pass through three stages before they are law.
The release covers two.

| Stage | In the release? | Source | Fiscal years |
|---|---|---|---|
| **Subcommittee mark** | **No.** | Subcommittee marks are circulated as bill text and summary tables, not as line-item statements; when a line-item table is public at all, it is the full committee's. The committee report is the first public line-item document, so there is nothing separate to extract. | — |
| **Committee** (each chamber) | Yes | The House or Senate committee report's comparative statement of new budget authority. | House FY2016–FY2027; Senate FY2016–FY2026, with gaps below |
| **Enacted** | Yes | The joint explanatory statement printed as a House Rules Committee Print (GovInfo `CPRT`) for each consolidated appropriations act. | FY2016–FY2024 |

Enacted rows carry `chamber = house` because the prints are House-numbered; they are the final agreed level, not a House position.

## Rows by fiscal year

Each cell is `reports / rows with a verification tier / rows`.
A verification tier means some check stands behind the amount (see [DATA_DICTIONARY.md](DATA_DICTIONARY.md)); it is not a measure of accuracy, which is in [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md).

| FY | House committee | Senate committee | Enacted |
|---|---|---|---|
| 2016 | 12 / 3,532 / 5,740 | 12 / 3,630 / 4,007 | 2 / 1,166 / 1,167 |
| 2017 | 12 / 3,582 / 5,824 | 12 / 3,750 / 3,872 | 1 / 1,232 / 1,232 |
| 2018 | 12 / 3,629 / 5,772 | 8 / 2,082 / 2,212 | 2 / 1,283 / 1,285 |
| 2019 | 13 / 5,382 / 8,676 | 12 / 3,839 / 4,021 | 1 / 818 / 818 |
| 2020 | 12 / 3,325 / 5,434 | 10 / 2,801 / 2,905 | 2 / 1,482 / 1,482 |
| 2021 | 12 / 3,791 / 6,016 | — | 2 / 1,435 / 1,435 |
| 2022 | 12 / 3,755 / 5,440 | 3 / 729 / 754 | 2 / 1,979 / 1,979 |
| 2023 | 12 / 3,913 / 6,297 | — | 2 / 1,628 / 1,636 |
| 2024 | 10 / 2,462 / 3,840 | 12 / 4,484 / 4,857 | 2 / 1,738 / 1,775 |
| 2025 | 12 / 4,066 / 9,152 | 11 / 3,793 / 4,101 | — |
| 2026 | 12 / 2,362 / 4,799 | 7 / 2,055 / 2,376 | — |
| 2027 | 12 / 5,322 / 7,489 | — | — |
| **Total** | **143 / 45,121 / 74,479** | **87 / 27,163 / 29,105** | **16 / 12,761 / 12,809** |

246 reports and 116,393 rows in all; 85,045 rows (73.1%) carry a verification tier.
Inline funding tables add 13,853 records (7,079 House, 6,774 Senate) from the narrative sections of the same committee reports.

## Committee reports by subcommittee

`1` means a report with a comparative statement is in the release; `0` means none.
The catalog (`data/reference/report_catalog.json`) is GovInfo's full list of appropriations committee reports for the 114th–119th Congresses, and every catalogued report is in the release except Senate Labor-HHS FY2026 (`CRPT-119srpt55`), which GovInfo published only as a PDF with no comparative statement; its 146 inline funding tables are included.

**House**

| | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Agriculture | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Commerce-Justice-Science | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 |
| Defense | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Energy-Water | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Financial-Services | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Homeland-Security | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Interior-Environment | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Labor-HHS-Education | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 |
| Legislative-Branch | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| MilCon-VA | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| State-Foreign-Ops | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| THUD | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

The House committee did not report CJS or Labor-HHS for FY2024. Homeland Security FY2019 has two reports: the committee report (`CRPT-115hrpt948`) and a report on a later continuing-appropriations bill (`CRPT-116hrpt9`).

**Senate**

| | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Agriculture | 1 | 1 | 1 | 1 | 1 | — | 1 | — | 1 | 1 | 1 | — |
| Commerce-Justice-Science | 1 | 1 | 1 | 1 | 1 | — | 0 | — | 1 | 1 | 1 | — |
| Defense | 1 | 1 | 0 | 1 | 1 | — | 0 | — | 1 | 1 | 1 | — |
| Energy-Water | 1 | 1 | 1 | 1 | 1 | — | 1 | — | 1 | 1 | 0 | — |
| Financial-Services | 1 | 1 | 0 | 1 | 1 | — | 0 | — | 1 | 1 | 0 | — |
| Homeland-Security | 1 | 1 | 0 | 1 | 1 | — | 0 | — | 1 | 0 | 0 | — |
| Interior-Environment | 1 | 1 | 0 | 1 | 1 | — | 0 | — | 1 | 1 | 1 | — |
| Labor-HHS-Education | 1 | 1 | 1 | 1 | 0 | — | 0 | — | 1 | 1 | 0¹ | — |
| Legislative-Branch | 1 | 1 | 1 | 1 | 1 | — | 0 | — | 1 | 1 | 1 | — |
| MilCon-VA | 1 | 1 | 1 | 1 | 0 | — | 1 | — | 1 | 1 | 1 | — |
| State-Foreign-Ops | 1 | 1 | 1 | 1 | 1 | — | 0 | — | 1 | 1 | 0 | — |
| THUD | 1 | 1 | 1 | 1 | 1 | — | 0 | — | 1 | 1 | 1 | — |

`—`: the Senate committee reported no appropriations bills that year. FY2021 and FY2023 were settled in omnibus acts without Senate committee reports; FY2027 had not been marked up when this release was built. Other zeros are bills the Senate committee did not report.
¹ Inline funding tables only; see above.

## Enacted statements by subcommittee

Rows are assigned to a subcommittee from the omnibus division they appear in.

| | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 |
|---|---|---|---|---|---|---|---|---|---|
| Agriculture | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Commerce-Justice-Science | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Defense | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| Energy-Water | 0 | 0 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| Financial-Services | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Homeland-Security | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| Interior-Environment | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Labor-HHS-Education | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| Legislative-Branch | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| MilCon-VA | 1 | 0 | 1 | 0 | 1 | 1 | 1 | 1 | 1 |
| State-Foreign-Ops | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| THUD | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

A `1` means at least one row, not full detail.
Energy-Water and Homeland Security statements carry most of their detail in prose rather than tables, so they are thinly represented (a few dozen rows a year) or absent.
FY2019's print covers only the seven bills enacted in the February 2019 act; the other five were enacted separately in September 2018 without a print in this corpus.
FY2025 was funded by a full-year continuing resolution, which has no explanatory statement, and FY2026–FY2027 were not enacted when this release was built.

## What coverage does not mean

- A report being present does not mean every line of its statement was extracted. The accuracy review measured completeness at 96–98% of source rows per track; see [ACCURACY_REVIEW.md](ACCURACY_REVIEW.md).
- A row being present does not mean its amounts are trustworthy. Filter on `column_layout = 'standard'` and a `verification_tier` other than `none`, and read [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
- An account appearing in several years does not mean it has a total in each. `account_year_totals` resolves 6,163 of 9,154 report-account pairs; the other 2,991 are `unresolved` rather than guessed.
- House–Senate comparisons are only possible in years both chambers reported the bill; see the tables above.
