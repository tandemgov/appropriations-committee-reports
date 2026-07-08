# Demo

Two self-contained pages (double-click to open — no server, no network, every figure drawn from the real artifacts).

## Project brief — goals & status

- **`overview.html`** — the whole project at a glance: what it aims to do (the seven SOW deliverables), the two-track extraction architecture, what's extracted and verified to date, an honest scope-vs-target read, the scaling constraint, and the roadmap. Start here for the big picture.

## Reading the Unreadable — the House extraction story

A guided walkthrough of how we extracted and *verified* the House appropriations comparative statement from H. Rept. 118-553 (Homeland Security, FY2025), whose funding tables are published as scanned images rather than data. It tells the real story from this work session: reading 63 image pages into 926 structured line items, catching the gross-vs-net trap in our own cross-check, fixing a sign bug in our parser, and proving the result two independent ways (external account totals against the source text, and the table's own delta-column arithmetic on every row), landing at 436/436 verified comparative rows with the one genuine OCR error caught and auto-repaired.

- **`walkthrough.html`** — open it in any browser (double-click, no server or network needed; all screenshots are embedded). A scrolling, narrated walkthrough with the actual source-table screenshots as evidence.
- **`demo.gif`** — a short looping animation of the same story, for embedding in a deck or message.
- **`assets/`** — the processed screenshots used in the GIF (the HTML is fully self-contained and does not need them).

Every figure and number is drawn from the actual report and the actual verification run; nothing is illustrative.
