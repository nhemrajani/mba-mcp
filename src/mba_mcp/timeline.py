"""Cycle-aware recruiting timelines.

Templates are curated data, not a live feed: each milestone is an ``MM-DD``
window inside a recruiting year that begins in ``cycle_start_month``. At read
time we project the template onto the current cycle so every date is relative
to today. A file in ``{data_dir}/timelines/{track}.json`` overrides the bundled
template, so a user can correct their own school's calendar without a fork.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

BUNDLED_DIR = Path(__file__).parent / "timelines"

# What students call a track versus what the template file is named.
TRACK_ALIASES = {
    "finance": "investment_banking",
    "banking": "investment_banking",
    "ib": "investment_banking",
    "investment banking": "investment_banking",
    "ibd": "investment_banking",
    "strategy": "consulting",
    "management consulting": "consulting",
    "mbb": "consulting",
}


def resolve_track(track: str) -> str:
    """Map a spoken track name onto a template slug."""
    slug = (track or "").strip().lower()
    slug = TRACK_ALIASES.get(slug, slug)
    return slug.replace(" ", "_").replace("-", "_")


class UnknownTrack(ValueError):
    """No template exists for the requested recruiting track."""


def available_tracks(overrides_dir: Path | None = None) -> list[str]:
    tracks = {path.stem for path in BUNDLED_DIR.glob("*.json")}
    if overrides_dir and overrides_dir.is_dir():
        tracks |= {path.stem for path in overrides_dir.glob("*.json")}
    return sorted(tracks)


def load_template(track: str, overrides_dir: Path | None = None) -> dict:
    slug = resolve_track(track)
    if overrides_dir:
        override = overrides_dir / f"{slug}.json"
        if override.is_file():
            template = json.loads(override.read_text(encoding="utf-8"))
            template["_source"] = str(override)
            return template

    bundled = BUNDLED_DIR / f"{slug}.json"
    if not bundled.is_file():
        raise UnknownTrack(
            f"No timeline template for '{track}'. Available: "
            f"{', '.join(available_tracks(overrides_dir)) or 'none'}. "
            "Add one as JSON in your data dir under timelines/."
        )
    template = json.loads(bundled.read_text(encoding="utf-8"))
    template["_source"] = "bundled"
    return template


def render(template: dict, today: date | None = None) -> dict:
    """Project a template onto the cycle containing ``today``."""
    today = today or date.today()
    cycle_start_month = int(template.get("cycle_start_month", 8))
    start_year = today.year if today.month >= cycle_start_month else today.year - 1

    milestones = []
    for raw in template.get("milestones", []):
        starts = _anchor(raw["starts"], start_year, cycle_start_month)
        ends = _anchor(raw["ends"], start_year, cycle_start_month)
        if ends < starts:
            ends = _anchor(raw["ends"], start_year + 1, cycle_start_month)
        if ends < today:
            status = "past"
        elif starts <= today:
            status = "active"
        else:
            status = "upcoming"
        milestones.append(
            {
                "id": raw["id"],
                "name": raw["name"],
                "description": raw.get("description", ""),
                "starts_on": starts.isoformat(),
                "ends_on": ends.isoformat(),
                "status": status,
                "days_until": (starts - today).days,
                "actions": list(raw.get("actions", [])),
            }
        )

    milestones.sort(key=lambda m: (m["starts_on"], m["ends_on"]))
    return {
        "track": template.get("track", ""),
        "label": template.get("label", ""),
        "audience": template.get("audience", ""),
        "cycle": f"{start_year}-{str(start_year + 1)[-2:]}",
        "today": today.isoformat(),
        "source": template.get("_source", "bundled"),
        "disclaimer": template.get("disclaimer", ""),
        "milestones": milestones,
    }


def get_timeline(track: str, overrides_dir: Path | None = None, today: date | None = None) -> dict:
    return render(load_template(track, overrides_dir), today=today)


def _anchor(month_day: str, start_year: int, cycle_start_month: int) -> date:
    month, day = (int(part) for part in month_day.split("-"))
    year = start_year if month >= cycle_start_month else start_year + 1
    return date(year, month, day)
