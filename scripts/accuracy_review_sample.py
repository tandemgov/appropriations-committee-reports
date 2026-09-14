"""Draw the bounded accuracy-review sample: 24 source units across four extraction tracks.

A unit is a contiguous region of source a reviewer can transcribe completely:
  house_vision / house_typeset / enacted -> one PDF page
  senate                                  -> a 44-line window of the source HTML <pre> text
Reviewers are given only the source locator, never the extracted rows (blind transcription).
"""
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from approps.cli import _primary_json_files  # noqa: E402
from approps.config import EXTRACTED_DIR  # noqa: E402

OUT = ROOT / "docs" / "accuracy_review"
rng = random.Random(20260913)

reports = defaultdict(list)
for f in _primary_json_files(EXTRACTED_DIR):
    d = json.loads(f.read_text())
    lines = d.get("comparative_lines", [])
    if not lines:
        continue
    first = lines[0]
    stage, chamber = first.get("stage"), first.get("chamber")
    methods = {ln.get("verification_method") for ln in lines}
    if stage == "enacted":
        track = "enacted"
    elif chamber == "senate":
        track = "senate"
    elif "verbatim_page" in methods:
        track = "house_typeset"
    else:
        track = "house_vision"
    fy = next((ln["fiscal_year"] for ln in lines if ln.get("fiscal_year")), None)
    sub = next((ln["subcommittee"] for ln in lines if ln.get("subcommittee")), None)
    reports[track].append(dict(report_id=d["report_id"], path=str(f), fy=fy, sub=sub,
                               congress=first.get("congress"), n=len(lines)))

def raw_path(rid, congress, kind):
    base = ROOT / "data/raw" / str(congress)
    for sub in ("house", "senate", "cprt"):
        p = base / sub / f"{rid}.{kind}"
        if p.exists():
            return p
    return None

def pick_spread(cands, k):
    """k reports spread across fiscal years and subcommittees (no repeated subcommittee if avoidable)."""
    cands = sorted(cands, key=lambda r: (r["fy"] or 0, r["report_id"]))
    buckets = [cands[i * len(cands) // k:(i + 1) * len(cands) // k] for i in range(k)]
    chosen, used = [], set()
    for b in buckets:
        rng.shuffle(b)
        pick = next((r for r in b if r["sub"] not in used), b[0])
        used.add(pick["sub"])
        chosen.append(pick)
    return chosen

def amount_raws(ln):
    out = []
    for k in ("prior_year_enacted", "budget_estimate", "committee_recommendation",
              "delta_vs_enacted", "delta_vs_estimate"):
        a = ln.get(k)
        if isinstance(a, dict) and a.get("value") is not None and re.search(r"\d{1,3},\d{3}", a.get("raw_text") or ""):
            out.append(a["raw_text"].strip("()$ "))
    return out

def find_pdf_page(pdf, text_pages, ln):
    raws = amount_raws(ln)
    label = re.sub(r"[.\s]+$", "", (ln.get("line_item_text") or ""))[:25]
    hits = [i for i, t in enumerate(text_pages) if raws and all(r in t for r in raws) and label[:12] in t]
    return hits[0] + 1 if len(hits) == 1 else None

units = []

# House vision: 8 units; page = line_number // 100 (comparative_house sets page*100).
for r in pick_spread(reports["house_vision"], 8):
    d = json.loads(Path(r["path"]).read_text())
    pages = sorted({ln["line_number"] // 100 for ln in d["comparative_lines"]
                    if ln.get("line_number") and amount_raws(ln)})
    page = rng.choice(pages[len(pages) // 10: -max(1, len(pages) // 10)] or pages)
    units.append(dict(unit_id=f"hv-{r['report_id']}-p{page}", track="house_vision", **r,
                      source=str(raw_path(r["report_id"], r["congress"], "pdf")), pdf_page=page))

# Enacted: 6 units; locate the page by searching the text layer for a random value row.
for r in pick_spread(reports["enacted"], 6):
    d = json.loads(Path(r["path"]).read_text())
    src = raw_path(r["report_id"], r["congress"], "pdf")
    pdf = pdfium.PdfDocument(str(src))
    text_pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    rows = [ln for ln in d["comparative_lines"] if amount_raws(ln)]
    for _ in range(40):
        page = find_pdf_page(pdf, text_pages, rng.choice(rows))
        if page:
            break
    units.append(dict(unit_id=f"en-{r['report_id']}-p{page}", track="enacted", **r,
                      source=str(src), pdf_page=page))

# House typeset: 4 units from the one born-digital report, spread across its statement.
for r in reports["house_typeset"]:
    d = json.loads(Path(r["path"]).read_text())
    src = raw_path(r["report_id"], r["congress"], "pdf")
    pdf = pdfium.PdfDocument(str(src))
    text_pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    rows = [ln for ln in d["comparative_lines"] if amount_raws(ln)]
    for q in range(4):
        seg = rows[q * len(rows) // 4:(q + 1) * len(rows) // 4]
        for _ in range(40):
            page = find_pdf_page(pdf, text_pages, rng.choice(seg))
            if page:
                break
        units.append(dict(unit_id=f"ht-{r['report_id']}-p{page}", track="house_typeset", **r,
                          source=str(src), pdf_page=page))

# Senate: 6 units; a 44-line window of the HTML centred on a random value row's source line.
for r in pick_spread(reports["senate"], 6):
    d = json.loads(Path(r["path"]).read_text())
    src = raw_path(r["report_id"], r["congress"], "htm")
    html_lines = src.read_text(errors="replace").splitlines()
    rows = [ln for ln in d["comparative_lines"] if amount_raws(ln)]
    for _ in range(60):
        ln = rng.choice(rows)
        raws, label = amount_raws(ln), (ln.get("line_item_text") or "")[:20]
        hits = [i for i, t in enumerate(html_lines) if label and label in t and all(x in t for x in raws)]
        if len(hits) == 1:
            start = max(1, hits[0] + 1 - 22)
            break
    units.append(dict(unit_id=f"se-{r['report_id']}-L{start}", track="senate", **r,
                      source=str(src), html_line_start=start, html_line_end=start + 43))

for u in units:
    u.pop("path")
(OUT / "units.json").write_text(json.dumps(units, indent=2))
for u in units:
    print(u["unit_id"], u["fy"], u["sub"], u.get("pdf_page") or u.get("html_line_start"), u["source"] and Path(u["source"]).name)
print(len(units), "units;", len({u['sub'] for u in units}), "subcommittees;", sorted({u['fy'] for u in units}))
