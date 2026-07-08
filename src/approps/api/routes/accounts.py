"""API routes for cross-year account authority — follow one account through time.

Groups crosswalk-keyed line items by their authoritative `account_key` and returns,
per account, the money series across fiscal years, the label timeline, and the
classified title changes (see normalization.account_authority).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from approps.api.data import METRICS, load_line_items
from approps.normalization.account_authority import trace_account, trace_accounts

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

_KINDS = ("case", "prefix", "reword")


@router.get("")
def list_accounts(
    metric: str = Query("committee_recommendation", description=f"one of {METRICS}"),
    min_years: int = Query(2, ge=1, description="Only accounts seen in >= this many fiscal years"),
    changed_only: bool = Query(False, description="Only accounts with a title change"),
    kind: str | None = Query(None, description=f"Keep only accounts with a change of this kind {_KINDS}"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """List cross-year account authorities (keyed accounts followed through time).

    Sorted by account_key. Use `changed_only`/`kind=reword` to surface the accounts
    whose label changed substantively across years — the rename (and crosswalk
    over-merge) candidates.
    """
    if metric not in METRICS:
        raise HTTPException(400, f"metric must be one of {METRICS}")
    if kind is not None and kind not in _KINDS:
        raise HTTPException(400, f"kind must be one of {_KINDS}")

    auths = trace_accounts(load_line_items(), metric=metric, min_years=min_years)
    if changed_only or kind is not None:
        auths = [
            a
            for a in auths
            if any(kind is None or c.kind == kind for c in a.title_changes)
        ]

    total = len(auths)
    page = auths[offset : offset + limit]
    return {
        "accounts": [a.to_dict() for a in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{account_key}/history")
def account_history(
    account_key: str,
    metric: str = Query("committee_recommendation", description=f"one of {METRICS}"),
) -> dict:
    """One account's full cross-year history: money series, label timeline, changes."""
    if metric not in METRICS:
        raise HTTPException(400, f"metric must be one of {METRICS}")
    auth = trace_account(load_line_items(), account_key, metric=metric)
    if auth is None:
        raise HTTPException(404, f"No crosswalk-keyed line items for account_key {account_key!r}")
    return auth.to_dict()
