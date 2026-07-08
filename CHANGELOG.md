<!-- markdownlint-disable MD024, MD013 -->
# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

### Changed

### Breaking

### Fixed

- **Senate comparative rows whose dot leader was squeezed out are no longer dropped.** A label long enough to consume the entire dot-leader field left the reader with no `...` to split label from numbers, so the row matched no parse branch and was silently dropped — 682 line items across 72 of 87 Senate reports, 363 of them `Total` rows, whose loss also deleted the block structure the reconciler recovers from document order. A second reader now adjudicates by column geometry (the declared right edges) when the dot-leader reader can't, and stitches a wrapped-label tail back onto its row. Extraction is strictly additive (+169 rows, 0 value-cells removed, every recovered amount string-matches the source); Senate reconcile checkable totals rise 4,833 → 5,198 and overall strict pass rate holds at 75.7%. (refs #2)

### Internal / Infra
