"""FastAPI application for the approps public API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from approps.api.routes import accounts, flow, line_items, parse, reports

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Appropriations Data API",
    description=(
        "Structured line-item data extracted from Congressional appropriations "
        "committee reports. Covers all 12 subcommittees across both chambers."
    ),
    version="0.1.0",
)

# CORS for browser-based consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(line_items.router)
app.include_router(accounts.router)
app.include_router(flow.router)
app.include_router(parse.router)


@app.get("/api")
def api_root():
    return {
        "name": "Appropriations Data API",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "reports": "/api/reports",
            "line_items": "/api/line_items",
            "compare": "/api/line_items/compare",
            "accounts": "/api/accounts",
            "account_history": "/api/accounts/{account_key}/history",
            "flow": "/api/flow",
            "facets": "/api/facets",
            "parse_report": "/api/parse_report",
        },
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the "follow the money" static frontend at the root. Mounted last so it
# does not shadow the /api routes above.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
