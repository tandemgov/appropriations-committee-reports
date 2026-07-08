"""Infer account groupings for House vision rows from reconciling subtotal blocks.

House comparative statements are extracted from scanned images, and the row's account
heading is usually lost — every label lands in ``line_item_text`` and ``account`` is
null (Senate/enacted keep their account from the text/PDF layer). The table's own
structure recovers it: a run of line items is closed by a ``Subtotal, <name>`` or
``Total, <name>`` row that names their grouping. We assign that name to the block —
**but only when the block's amounts sum exactly to the subtotal's amount**, so the
assignment is arithmetic-verified rather than guessed.

The reconciler is a stack: a reconciled inner subtotal collapses into a single addend
for its enclosing block, so nested accounts (``... Subtotal, PPA ... Total, ACCOUNT``)
reconcile at every level. A block reconciles if its amounts match the rollup on *any*
shared value column (committee recommendation, budget estimate, or prior-year enacted),
which tolerates a single OCR-mangled column. Parenthetical-only memo lines
("(transfer out)") carry non-add amounts and are excluded from the sum but still labeled.

The result goes in the additive ``account_inferred`` field; ``account`` is never
overwritten. Applied per report over its ordered ``comparative_lines``.
"""

from __future__ import annotations

import re

# Rollup rows: "Subtotal, Federal Assistance", "Total, Operations and Support",
# "Total. Joint Items" (a period — the vision model sometimes emits these and fails to
# flag them is_subtotal, so they'd otherwise be summed as data and double-count),
# "Subtotal" (bare, no name). The name may be empty.
_ROLLUP_TEXT_RE = re.compile(r"^\s*(?:sub)?total\b[.,:]", re.IGNORECASE)
_ROLLUP_NAME_RE = re.compile(r"^\s*(?:sub)?total\b[.,:]?\s*(.*?)\s*$", re.IGNORECASE)
# A parenthetical-only label is a non-add memo line (e.g. "(transfer out)",
# "(Appropriations)") — it carries an amount that is NOT part of the block sum.
_MEMO_ONLY_RE = re.compile(r"^\s*\(.*\)\s*$")

_COLS = ("committee_recommendation", "budget_estimate", "prior_year_enacted")


def _is_rollup(line: dict) -> bool:
    """A subtotal/total row — the ``is_subtotal`` flag, or total-with-punctuation text
    the flag missed. Such a row bounds a block and is itself excluded from the sum."""
    text = (line.get("line_item_text") or "").strip()
    return bool(line.get("is_subtotal")) or bool(_ROLLUP_TEXT_RE.match(text))


def _rollup_name(text: str) -> str | None:
    """The grouping name after "Subtotal,/Total.", or None if not a total / no name."""
    m = _ROLLUP_NAME_RE.match(text or "")
    if not m:
        return None
    return m.group(1).strip(" .:,") or None


def _col_values(line: dict) -> dict[str, int]:
    """The line's present dollar columns, {column: value}."""
    out = {}
    for c in _COLS:
        amt = line.get(c)
        v = amt.get("value") if isinstance(amt, dict) else None
        if v is not None:
            out[c] = v
    return out


def _is_paren_amount(line: dict) -> bool:
    """Whether the row's committee-recommendation amount is written in parentheses,
    e.g. ``(62,596)``. In House comparative statements parentheses mark a **non-add
    memo** component (a limitation, a transfer, a gross figure already counted in a
    net), not a negative — so such a row may need excluding from a block sum."""
    amt = line.get("committee_recommendation")
    raw = amt.get("raw_text", "") if isinstance(amt, dict) else ""
    return raw.strip().startswith("(")


def infer_block_accounts(lines: list[dict]) -> int:
    """Set ``account_inferred`` on rows whose subtotal block reconciles. Mutates in
    place; returns the number of rows newly labeled.

    Segments on the working stack are either a leaf (one line item) or a *group* (a
    collapsed, already-reconciled inner subtotal). On a rollup row we check whether the
    stacked segments sum to it on a shared column; if so we label the direct leaves and
    replace the whole run with a single group carrying the rollup's amounts.
    """
    labeled = 0
    # Each segment: {"values": {col: int}, "leaves": [dict] | None (None == group)}
    pending: list[dict] = []

    def reconciles(target: dict[str, int]) -> bool:
        # Try each shared column in priority order (committee recommendation first).
        # For a column, sum the segments that carry it — a segment blank in that column
        # contributes nothing — and compare to the rollup. Matching on any one column is
        # enough, which tolerates a single OCR-mangled column. For each column we also try
        # the sum with parenthesized (non-add memo) amounts excluded, so a block whose
        # total is net-of-memo reconciles; the with-memo sum is still tried first so no
        # currently-reconciling block regresses.
        for col in _COLS:
            if col not in target:
                continue
            addends = [s["values"][col] for s in pending if col in s["values"]]
            if not addends:
                continue
            if sum(addends) == target[col]:
                return True
            non_memo = [
                s["values"][col]
                for s in pending
                if col in s["values"] and not s.get("paren")
            ]
            if non_memo and len(non_memo) != len(addends) and sum(non_memo) == target[col]:
                return True
        return False

    for line in lines:
        text = (line.get("line_item_text") or "").strip()
        if _is_rollup(line):
            name = _rollup_name(text)
            target = _col_values(line)
            if name and target and reconciles(target):
                for seg in pending:
                    if seg["leaves"] is None:
                        continue  # a group keeps the inner label it already got
                    for leaf in seg["leaves"]:
                        if not (leaf.get("account") or "").strip() and not leaf.get(
                            "account_inferred"
                        ):
                            leaf["account_inferred"] = name
                            labeled += 1
                # Collapse a reconciled *named* sub-total into one group carrying its
                # amounts, so it is a single addend for any enclosing block. A bare
                # "Subtotal" (no name) is ambiguous — treat it as a plain barrier rather
                # than roll its value up, which empirically caused spurious parent matches.
                pending = [{"values": target, "leaves": None}]
            else:
                pending = []  # non-reconciling or unnamed rollup is a barrier
        elif not text:
            continue
        else:
            is_memo = bool(_MEMO_ONLY_RE.match(text))
            pending.append(
                {
                    "values": {} if is_memo else _col_values(line),
                    "leaves": [line],
                    "paren": _is_paren_amount(line),
                }
            )
    return labeled
