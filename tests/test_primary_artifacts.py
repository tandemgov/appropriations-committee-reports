"""The combined-output glob must ignore intermediate House vision artifacts.

`output`/`crosswalk`/`verify` walk the extracted dir for ``*.json``. House vision
extraction leaves ``<id>_nemotron.json`` and ``<id>_hybrid.json`` next to the primary
``<id>.json``; if those are ingested too, the same report is double- or triple-counted
in the combined dataset. This pins the exclusion.
"""

from __future__ import annotations

from approps.cli import _primary_json_files


def test_primary_json_files_excludes_intermediate_passes(tmp_path):
    house = tmp_path / "118" / "house"
    house.mkdir(parents=True)
    primary = house / "CRPT-118hrpt553.json"
    for name in (
        "CRPT-118hrpt553.json",          # primary — keep
        "CRPT-118hrpt553_nemotron.json",  # intermediate — drop
        "CRPT-118hrpt553_hybrid.json",    # intermediate — drop
        "CRPT-118srpt44.json",            # another primary — keep
    ):
        (house / name).write_text("{}")

    found = _primary_json_files(tmp_path)
    names = sorted(p.name for p in found)

    assert names == ["CRPT-118hrpt553.json", "CRPT-118srpt44.json"]
    assert primary in found
    assert not any("_nemotron" in p.name or "_hybrid" in p.name for p in found)
