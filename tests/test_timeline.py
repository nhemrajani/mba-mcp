import json
from datetime import date

import pytest

from mba_mcp import timeline


def test_consulting_template_is_available():
    assert "consulting" in timeline.available_tracks()


def test_unknown_track_names_what_is_available():
    with pytest.raises(timeline.UnknownTrack, match="consulting"):
        timeline.get_timeline("underwater basket weaving")


def test_milestones_project_onto_the_current_cycle():
    rendered = timeline.get_timeline("consulting", today=date(2026, 9, 15))
    assert rendered["cycle"] == "2026-27"
    assert rendered["today"] == "2026-09-15"
    assert rendered["disclaimer"]

    by_id = {m["id"]: m for m in rendered["milestones"]}
    assert by_id["kickoff"]["starts_on"] == "2026-08-15"
    assert by_id["kickoff"]["status"] == "past"
    assert by_id["presentations"]["status"] == "active"

    # Dates after the cycle start month roll into the following calendar year.
    assert by_id["first_rounds"]["starts_on"] == "2027-01-20"
    assert by_id["first_rounds"]["status"] == "upcoming"
    assert by_id["first_rounds"]["days_until"] == (date(2027, 1, 20) - date(2026, 9, 15)).days


def test_cycle_before_the_start_month_belongs_to_the_previous_year():
    rendered = timeline.get_timeline("consulting", today=date(2027, 1, 10))
    assert rendered["cycle"] == "2026-27"
    by_id = {m["id"]: m for m in rendered["milestones"]}
    assert by_id["applications"]["starts_on"] == "2026-11-15"
    assert by_id["applications"]["status"] == "active"


def test_milestones_are_sorted_and_well_formed():
    rendered = timeline.get_timeline("consulting", today=date(2026, 9, 1))
    starts = [m["starts_on"] for m in rendered["milestones"]]
    assert starts == sorted(starts)
    for milestone in rendered["milestones"]:
        assert milestone["ends_on"] >= milestone["starts_on"]
        assert milestone["actions"]
        assert milestone["status"] in {"past", "active", "upcoming"}


def test_data_dir_template_overrides_the_bundled_one(tmp_path):
    overrides = tmp_path / "timelines"
    overrides.mkdir()
    (overrides / "consulting.json").write_text(
        json.dumps(
            {
                "track": "consulting",
                "label": "My school's calendar",
                "cycle_start_month": 8,
                "milestones": [
                    {
                        "id": "only",
                        "name": "Deadline",
                        "starts": "01-05",
                        "ends": "01-06",
                        "description": "",
                        "actions": ["apply"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rendered = timeline.get_timeline("consulting", overrides_dir=overrides, today=date(2026, 9, 1))
    assert rendered["label"] == "My school's calendar"
    assert [m["id"] for m in rendered["milestones"]] == ["only"]
    assert rendered["milestones"][0]["starts_on"] == "2027-01-05"


# --------------------------------------------------------------------------
# Investment banking track
# --------------------------------------------------------------------------


def test_finance_aliases_resolve_to_the_banking_template():
    for name in ("finance", "IB", "Investment Banking", "banking"):
        assert timeline.resolve_track(name) == "investment_banking"
    assert timeline.resolve_track("MBB") == "consulting"


def test_banking_cycle_starts_in_spring_so_pre_mba_programs_land_first():
    rendered = timeline.get_timeline("finance", today=date(2026, 9, 15))
    assert rendered["track"] == "investment_banking"
    assert rendered["cycle"] == "2026-27"
    by_id = {m["id"]: m for m in rendered["milestones"]}

    # The pre-MBA programs run the spring BEFORE term, not the following spring.
    assert by_id["pre_mba_programs"]["starts_on"] == "2026-04-01"
    assert by_id["pre_mba_programs"]["status"] == "past"
    assert by_id["applications"]["status"] == "active"
    assert by_id["superdays"]["starts_on"] == "2026-11-15"
    assert by_id["second_wave"]["ends_on"] == "2027-05-31"


def test_banking_milestones_are_ordered_and_actionable():
    rendered = timeline.get_timeline("investment_banking", today=date(2026, 12, 1))
    starts = [m["starts_on"] for m in rendered["milestones"]]
    assert starts == sorted(starts)
    assert all(m["actions"] for m in rendered["milestones"])
    assert "not live firm deadlines" in rendered["disclaimer"]
