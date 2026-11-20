"""A heads-up before the due time ("Tomorrow at 14:30: Dentist"), then the usual reminders."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.remindo.const import DOMAIN

from .common import add_task, setup_integration, tick


def _pushes(calls) -> list[str]:
    return [c.data["message"] for c in calls["notify"] if c.data.get("message") not in ("clear_notification", "TTS")]


async def test_heads_up_minutes_before(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Dentist", start="2026-11-20T14:30:00+01:00", advance=60)
    await tick(hass, freezer, minutes=89)
    assert _pushes(calls) == []
    await tick(hass, freezer, minutes=2)
    assert _pushes(calls) == ["Today at 14:30: Dentist"]
    push = calls["notify"][-1].data["data"]
    assert [a["action"] for a in push["actions"]] == [f"REMINDO_ACK_{uid}", f"REMINDO_DONE_{uid}", f"REMINDO_DISMISS_{uid}"]
    assert push["tag"] == f"remindo_{uid}"
    # no speaker for the heads-up, and the task is not "reminding" yet
    assert calls["tts"] == []
    assert not entry.runtime_data.find(uid).active
    # at the due time: the usual reminders
    await tick(hass, freezer, minutes=60)
    assert _pushes(calls) == ["Today at 14:30: Dentist", "Dentist"]


async def test_heads_up_at_a_time_the_day_before(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    _, calls = await setup_integration(hass)
    await add_task(hass, summary="Bins", start="2026-11-21T07:00:00+01:00", advance_at="20:00", advance_days=1)
    await tick(hass, freezer, hours=7, minutes=59)
    assert _pushes(calls) == []
    await tick(hass, freezer, minutes=2)
    assert _pushes(calls) == ["Tomorrow at 07:00: Bins"]


async def test_done_after_the_heads_up(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Ticked off from the heads-up: no reminders at the due time, the notification is cleared."""
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Dentist", start="2026-11-20T14:30:00+01:00", advance=60)
    await tick(hass, freezer, minutes=91)
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DONE_{uid}"})
    await hass.async_block_till_done()
    assert entry.runtime_data.find(uid).status == "done"
    assert any(c.data.get("message") == "clear_notification" for c in calls["notify"])
    await tick(hass, freezer, hours=2)
    assert _pushes(calls) == ["Today at 14:30: Dentist"]


async def test_heads_up_late_and_once(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Added after the heads-up time: sent right away; never twice for the same due time."""
    freezer.move_to("2026-11-20 14:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Dentist", start="2026-11-20T14:30:00+01:00", advance=60)
    await tick(hass, freezer, seconds=31)
    assert _pushes(calls) == ["Today at 14:30: Dentist"]
    # a reload (like a restart) does not send it again
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=5)
    assert _pushes(calls) == ["Today at 14:30: Dentist"]
    # moved to tomorrow: a new heads-up for the new time
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "start": "2026-11-21T10:00:00+01:00"}, blocking=True)
    await tick(hass, freezer, hours=19)
    assert _pushes(calls)[-1] == "Today at 10:00: Dentist"


async def test_recurring_heads_up_every_date(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Gym", start="2026-11-20T18:00:00+01:00", repeat="daily", advance=30, interval=0)
    await tick(hass, freezer, hours=5, minutes=31)
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    await tick(hass, freezer, hours=24)
    assert _pushes(calls) == ["Today at 18:00: Gym", "Today at 18:00: Gym"]


async def test_quiet_hours_delay_the_heads_up(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-20 12:00:00+01:00")
    _, calls = await setup_integration(hass, quiet_push=True)
    await add_task(hass, summary="Train", start="2026-11-21T09:00:00+01:00", advance=180)  # 06:00, quiet until 07:00
    await tick(hass, freezer, hours=18, minutes=1)
    assert _pushes(calls) == []
    await tick(hass, freezer, hours=1)
    assert _pushes(calls) == ["Today at 09:00: Train"]


async def test_ill_remember_keeps_the_reminders(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """"I'll remember" only takes the heads-up away: the reminders come at the due time as set."""
    freezer.move_to("2026-11-20 12:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Dentist", start="2026-11-20T14:30:00+01:00", advance=60)
    await tick(hass, freezer, minutes=91)
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_ACK_{uid}"})
    await hass.async_block_till_done()
    task = entry.runtime_data.find(uid)
    assert task.status == "open" and not task.active
    assert calls["notify"][-1].data["message"] == "clear_notification"
    await tick(hass, freezer, minutes=60)  # 14:31
    assert _pushes(calls) == ["Today at 14:30: Dentist", "Dentist"]
    await tick(hass, freezer, minutes=30)  # and again, as set
    assert _pushes(calls) == ["Today at 14:30: Dentist", "Dentist", "Dentist"]
