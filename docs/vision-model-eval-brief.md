# Research brief: cheaper vision extraction for House appropriations tables

## The ask

We extract dense financial tables from scanned images in House appropriations reports. Our current pipeline uses a free local model (Nemotron-Parse) for the bulk and pays Gemini to clean up the hardest ~⅓ of pages. We want the research team to find a **cheaper way to do the paid cleanup leg** — either a cheaper/at-parity model, or a way to **reduce how many pages need the paid model at all**. This is a low-risk thing to optimize because we already have a fully automated, objective accuracy gate (below), so any candidate can be benchmarked without human labeling.

## What the model actually does in our pipeline

The House "Comparative Statement" tables are **scanned bitonal (1-bit) TIFF images embedded in the PDFs** — not digital text. Native scan resolution is ~1321×2221 px per page. Each table is a 6-column ledger: a hierarchically-indented line item plus five dollar columns (prior-year enacted, budget request, committee recommendation, and two signed deltas), values in thousands.

Pipeline:
1. **Bulk pass — Nemotron-Parse v1.2**, self-hosted on a DGX Spark (free, no per-call cost). Renders each table image and emits the table as LaTeX. Achieves ~92–98% row accuracy and ~100% account-level recall across the corpus.
2. **Verify** — a self-checking gate (below) flags "suspect" pages: rows whose arithmetic doesn't close, pages the model emitted nothing for, or accounts the recall check says are missing. This is ~**⅓ of pages**.
3. **Cleanup — Gemini** re-extracts only the suspect pages and we splice those in, reaching ~**99.5%**.

So the paid model's job is narrow: **read the ~⅓ hardest scanned table pages accurately.** A replacement only has to win on those pages.

## Why this is a good optimization target: we can benchmark objectively

We do **not** need human-labeled ground truth to evaluate a candidate. Two automatic checks give a per-page accuracy signal:

- **Delta-arithmetic gate.** Each row carries redundant columns: `recommendation − prior_year = delta_vs_enacted` and `recommendation − budget = delta_vs_estimate`. These identities must hold exactly, so a single misread digit breaks them. This validates every value-bearing row with zero labeling.
- **Inline-totals recall cross-check.** The reports also contain account totals in the narrative HTML (deterministically extracted, 100% verified). Every account total must appear in the table output (matched on the dollar value, which is effectively unique). This catches dropped rows/accounts — something the arithmetic gate can't see.

We also have validated Gemini outputs for several reports to use as a reference for exact-agreement scoring. **Net: a candidate model can be scored automatically on (a) % rows passing arithmetic, (b) account recall, (c) agreement vs our validated outputs — and we already log per-page $ cost.** That makes a clean cost-vs-accuracy bake-off straightforward.

## Current baseline and costs (measured)

- **Suspect-page fraction:** ~32% of pages go to the paid model (~2,270 calls for the full corpus).
- **Per-call tokens (measured, one dense page):** ~608 input + ~1,795 visible output + **~8,794 "thinking" tokens** (billed as output). Thinking is ~80% of the cost.
- **Current Gemini prices (paid tier, ≤200k prompt):** 2.5 Pro $1.25/$10 per 1M in/out; 3.1 Pro Preview $2/$12.
- **Cost:** ~$0.107/call on 2.5 Pro → **~$242 to clean the whole corpus**; 3.1 Pro ~$291. (A naive all-pages-to-Gemini approach with no local first pass would be ~3× this.)
- **The real constraint today is the per-model per-day quota (wall-clock), not dollars.**

## What makes the data hard (requirements any candidate must meet)

- **Scanned bitonal images, not text** — pure OCR fidelity matters; digit confusion (notably 6↔8) is the dominant error, and it gets worse if the scan is downsampled below native resolution.
- **Dense numeric precision** — every digit of multi-million-dollar figures must be exact; "close" fails the gate.
- **Column structure on sparse rows** — memo/subtotal rows where only some of the five columns are filled are where models misplace values.
- **Non-comparative table types interleaved** — e.g. 302(b) allocation tables and 7-column Bureau-of-Reclamation/MilCon project tables. These must NOT be coerced into the 5-column schema (a model that "helpfully" extracts everything actually hurts us here).
- **Large pages** — some Defense/THUD tables run 300–900 image pages; throughput and stability matter.

## Levers to explore (three buckets)

**A. Cheaper model for the cleanup leg (drop-in on suspect pages).**
Benchmark cheaper VLMs against our gate on the suspect pages. Candidates to price and test (team should pull *current* pricing for each):
- Gemini 2.5 **Flash** / Flash-Lite (our early test had Flash ~95% on full pages; on the cleanup-only role, possibly enough — far cheaper than Pro).
- Anthropic Claude vision (Haiku / Sonnet tiers).
- OpenAI GPT-4.1-mini / 4o / o-series vision.
- Qwen2.5-VL-72B (hosted via Together/Fireframes/Fireworks, or self-host).

**B. Purpose-built table/document services (priced per page, deterministic).**
These are designed for tabular extraction and bill per page (~$0.01–0.065/page), often cheaper and more stable than LLM-per-page, and may handle column structure better:
- AWS Textract (table API), Google Document AI, Azure Document Intelligence.
- Mistral OCR (cheap document OCR API).
- Open OCR/doc models to self-host: PaddleOCR-VL, dots.ocr, GOT-OCR2.0, MinerU, Surya. (Note: we already tried Marker — unreliable column alignment on these tables.)

**C. Reduce the number of paid calls (improve the free first pass / routing).**
This may beat swapping models, since fewer suspect pages = less paid spend regardless of model:
- **Image preprocessing on the bitonal scans** before the model: render at native resolution (we already saw native-crop cut digit errors materially), plus deskew / denoise / contrast — cheap and could shrink the suspect fraction.
- **Stronger local model**: fine-tune Nemotron on these tables, or self-host a larger VLM (Qwen2.5-VL-32B/72B) for the first pass.
- **Two-tier escalation**: run a *cheap* model on suspect pages first; only the still-failing pages escalate to the expensive model.

**D. Cost knobs on whatever model we keep.**
- **Disable/cap "thinking" tokens** (`thinking_budget=0` on Gemini, or equivalent). Thinking is ~80% of our per-call cost; turning it off drops corpus cleanup to **~$42–52**. Needs an accuracy A/B on suspect pages — these are dense, so it may or may not hold.
- **Batch API** (Gemini and others offer ~50% off for async batch). Cleanup is not latency-sensitive, so batch mode is a near-free ~half-off.
- **Crop to the table region** to cut input image tokens (minor here, since our input tokens are already small).

## Proposed evaluation protocol

1. Take a fixed **suspect-page test set** — the pages our gate flags across a representative spread of subcommittees and years (include Defense/THUD for the dense/large case, and Energy-Water/MilCon for the non-standard project tables).
2. Run each candidate on those pages, map output into our 5-column schema, and score with the **delta-arithmetic gate + recall cross-check + agreement vs validated Gemini outputs**.
3. Record **$ per page** (and per corpus) and throughput / rate-limit behavior.
4. Compare on a single chart: **accuracy (gate PASS %) vs cost per page**, with Gemini 2.5/3.1 Pro as the reference points.

## What we'd want back

- A ranked shortlist: model/service, measured gate-PASS % on the suspect set, $ per corpus, and throughput.
- A recommendation on the cheapest option that holds ~99.5% after cleanup (or that meaningfully shrinks the suspect fraction).
- A quick verdict on the two near-free knobs: **thinking-off** and **batch API** (do they preserve accuracy?).

The harness, sample data, and current per-page cost logs are all in this repo; we can hand over the flagged suspect-page set and the scoring scripts so the bake-off is plug-and-play.
