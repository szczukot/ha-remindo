"""Calendar rules "N minutes before the start": a task per event, with a heads-up."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, SupportsResponse

from custom_components.remindo.rules import advance_from_text, event_text

from .common import add_rule, setup_integration, tick


def _calendar(hass: HomeAssistant, events: list[dict]) -> None:
    async def get_events(call):
        return {"calendar.google": {"events": events}}

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    hass.states.async_set("calendar.google", "off")


def _pushes(calls) -> list[str]:
    return [c.data["message"] for c in calls["notify"] if c.data.get("message") not in ("clear_notification", "TTS")]


DENTIST = {"summary": "Dentist", "start": "2026-11-20T14:30:00+01:00", "end": "2026-11-20T15:30:00+01:00",
           "location": "Main St 1", "description": ""}


async def _rule(hass, entry, **extra):
    await add_rule(hass, entry, {"summary": "{event} at {time}, {location}", "entity_id": "calendar.google",
                                 "timing": "start", "before_minutes": 60, **extra})


async def test_heads_up_then_reminders_then_closed(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    _calendar(hass, [DENTIST, {"summary": "Holiday", "start": "2026-11-20", "end": "2026-11-21"}])
    await _rule(hass, entry)
    manager = entry.runtime_data
    await tick(hass, freezer, minutes=2)
    assert manager.open_tasks() == []  # its heads-up is still far: added later
    await tick(hass, freezer, hours=1, minutes=29)  # 13:31
    assert [t.summary for t in manager.open_tasks()] == ["Dentist at 14:30, Main St 1"]  # not the all-day event
    await tick(hass, freezer, minutes=1)
    assert _pushes(calls) == ["Today at 14:30: Dentist at 14:30, Main St 1"]
    await tick(hass, freezer, minutes=59)  # 14:31
    assert _pushes(calls)[-1] == "Dentist at 14:30, Main St 1"
    await tick(hass, freezer, hours=1)  # 15:31: the event is over, nobody ticked it off
    assert manager.open_tasks() == []


async def test_own_time_in_the_description(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    _calendar(hass, [{**DENTIST, "description": "Bring the card. remindo: 2h"}])
    await _rule(hass, entry)
    await tick(hass, freezer, minutes=31)  # 12:31
    await tick(hass, freezer, minutes=1)
    assert _pushes(calls) == ["Today at 14:30: Dentist at 14:30, Main St 1"]


async def test_ticked_off_is_not_added_again(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 13:40:00+01:00")
    entry, _ = await setup_integration(hass)
    _calendar(hass, [DENTIST])
    await _rule(hass, entry, contains="dent")
    await tick(hass, freezer, minutes=2)
    manager = entry.runtime_data
    (task,) = manager.open_tasks()
    await manager.async_done(task)
    await tick(hass, freezer, minutes=30)
    assert manager.open_tasks() == []


async def test_moved_and_deleted_events(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 13:40:00+01:00")
    entry, calls = await setup_integration(hass)
    events = [dict(DENTIST)]
    _calendar(hass, events)
    await _rule(hass, entry)
    manager = entry.runtime_data
    await tick(hass, freezer, minutes=2)
    assert [t.start for t in manager.open_tasks()] == ["2026-11-20T14:30:00+01:00"]
    # moved by 15 min in Google
    events[0].update(start="2026-11-20T14:45:00+01:00", end="2026-11-20T15:45:00+01:00")
    await tick(hass, freezer, minutes=10)
    assert [t.start for t in manager.open_tasks()] == ["2026-11-20T14:45:00+01:00"]
    # deleted
    events.clear()
    await tick(hass, freezer, minutes=10)
    assert manager.open_tasks() == []


async def test_only_events_matching_the_filter(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 13:40:00+01:00")
    entry, _ = await setup_integration(hass)
    _calendar(hass, [DENTIST, {**DENTIST, "summary": "Lunch"}])
    await _rule(hass, entry, contains="lunch")
    await tick(hass, freezer, minutes=2)
    assert [t.summary for t in entry.runtime_data.open_tasks()] == ["Lunch at 14:30, Main St 1"]


async def test_day_timing_gets_time_and_place(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The "N days before" rules also know {time} and {location}."""
    freezer.move_to("2026-11-19 17:59:50+01:00")
    entry, _ = await setup_integration(hass)
    _calendar(hass, [DENTIST])
    await add_rule(hass, entry, {"summary": "Tomorrow {event} at {time}", "entity_id": "calendar.google",
                                 "days_before": 1, "at_time": "18:00:00"})
    await tick(hass, freezer, seconds=11)
    assert [t.summary for t in entry.runtime_data.open_tasks()] == ["Tomorrow Dentist at 14:30"]


def test_texts() -> None:
    assert advance_from_text("remindo: 30") == 30
    assert advance_from_text("x\nRemindo: 2h") == 120
    assert advance_from_text("remindo=1d") == 1440
    assert advance_from_text("remindo: 30 days") is None
    assert advance_from_text(None) is None
    assert event_text("Bins", [{"summary": "Paper", "start": "2026-11-20"}], append=True) == "Bins: Paper"
    assert event_text("{event} {time}", [{"summary": "Paper", "start": "2026-11-20"}], append=True) == "Paper "
