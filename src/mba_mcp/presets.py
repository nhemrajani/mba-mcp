"""Curated starter packs of firms for a track.

Not a registry of every company's ATS — that is exactly what
:func:`ats.discover_ats` exists to avoid. These are opinionated first drafts of
a target list, so a student can go from install to "show me open roles" in one
sentence instead of hunting for eighteen careers URLs.
"""

from __future__ import annotations

import json
from pathlib import Path

BUNDLED_DIR = Path(__file__).parent / "presets"


class UnknownPack(ValueError):
    """No starter pack exists under that name."""


def available_packs(overrides_dir: Path | None = None) -> list[str]:
    packs = {path.stem for path in BUNDLED_DIR.glob("*.json")}
    if overrides_dir and overrides_dir.is_dir():
        packs |= {path.stem for path in overrides_dir.glob("*.json")}
    return sorted(packs)


def load_pack(name: str, overrides_dir: Path | None = None) -> dict:
    from .timeline import resolve_track

    slug = resolve_track(name)
    if overrides_dir:
        override = overrides_dir / f"{slug}.json"
        if override.is_file():
            return json.loads(override.read_text(encoding="utf-8"))
    bundled = BUNDLED_DIR / f"{slug}.json"
    if not bundled.is_file():
        raise UnknownPack(
            f"No starter pack called '{name}'. Available: "
            f"{', '.join(available_packs(overrides_dir)) or 'none'}."
        )
    return json.loads(bundled.read_text(encoding="utf-8"))


def describe_packs(overrides_dir: Path | None = None) -> list[dict]:
    described = []
    for name in available_packs(overrides_dir):
        try:
            pack = load_pack(name, overrides_dir)
        except (UnknownPack, ValueError):
            continue
        described.append(
            {
                "pack": name,
                "label": pack.get("label", name),
                "companies": len(pack.get("companies", [])),
                "note": pack.get("note", ""),
            }
        )
    return described
