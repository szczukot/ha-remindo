"""calendar.remindo: the tasks' due times, recurring tasks on every date."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.remindo.const import DOMAIN

from .common import add_rule, add_task, setup_integration, tick


async def _events(hass: HomeAssistant, days: int = 10) -> list[tuple[str, str, str]]:
    start = dt_util.now()
    result = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.remindo", "start_date_time": start, "end_date_time": start + timedelta(days=days)},
        blocking=True, return_response=True,
    )
    return [(e["summary"], e["start"], e["end"]) for e in result["calendar.remindo"]["events"]]


async def test_calendar_shows_tasks(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 08:00:00+01:00")
    entry, _ = await setup_integration(hass)
    await add_task(hass, summary="Note")  # starts now, shown for an hour
    await add_task(hass, summary="Just a note", start=None)  # no date: not in the calendar
    await add_task(hass, summary="Dentist", start="2026-11-12 10:00:00", remind_until="2026-11-12 11:30:00")
    await add_task(hass, summary="Water the plants", start="2026-11-10 18:00:00", repeat="weekly")
    await add_task(hass, summary="Medicine", start="2026-11-09 09:00:00", repeat="hourly", repeat_every=8)
    events = await _events(hass, days=15)
    assert events == [
        ("Note", "2026-11-09T08:00:00+01:00", "2026-11-09T09:00:00+01:00"),
        ("Medicine", "2026-11-09T09:00:00+01:00", "2026-11-09T10:00:00+01:00"),  # every N hours: only the next one
        ("Water the plants", "2026-11-10T18:00:00+01:00", "2026-11-10T19:00:00+01:00"),
        ("Dentist", "2026-11-12T10:00:00+01:00", "2026-11-12T11:30:00+01:00"),
        ("Water the plants", "2026-11-17T18:00:00+01:00", "2026-11-17T19:00:00+01:00"),
    ]
    state = hass.states.get("calendar.remindo")
    assert state.state == "on" and state.attributes["message"] == "Note"
    # done: gone from the calendar
    note = next(t for t in entry.runtime_data.open_tasks() if t.summary == "Note")
    await hass.services.async_call(DOMAIN, "done", {"uid": note.uid}, blocking=True)
    await tick(hass, freezer, seconds=1)
    assert "Note" not in [e[0] for e in await _events(hass)]
    assert hass.states.get("calendar.remindo").attributes["message"] == "Medicine"


async def test_rule_cannot_watch_own_calendar(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Loop", "entity_id": "calendar.remindo", "mode": "calendar"}
    )
    assert result["errors"] == {"entity_id": "rule_own_entity"}
    # another calendar is fine
    hass.states.async_set("calendar.bins", "off")
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.bins", "days_before": 1, "at_time": "18:00"})
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN]
