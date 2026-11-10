"""Things that used to go wrong: broken targets, restarts, unavailable entities, untrusted text."""

import asyncio
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)

from custom_components.remindo.const import DOMAIN

from .common import add_rule, add_task, setup_integration, tick

TODO = {"entity_id": "todo.remindo"}


def _calendar(hass: HomeAssistant, events: list[str], fail_times: int = 0) -> list[int]:
    """Register a fake calendar.get_events; returns a one-item list counting the calls."""
    calls = [0]

    async def get_events(call):
        calls[0] += 1
        if calls[0] <= fail_times:
            raise RuntimeError("calendar not ready")
        return {"calendar.waste": {"events": [{"summary": name} for name in events]}}

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    hass.states.async_set("calendar.waste", "off")
    return calls


# ------------------------------------------------------------ notifications


async def test_missing_phone_does_not_block_the_rest(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A phone that no longer exists: other channels still work and the task can be closed."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="X", phones=["notify.mobile_app_old_phone", "notify.mobile_app_test"])
    await tick(hass, freezer, seconds=2)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls["notify"]) == 1
    assert len(calls["pn_create"]) == 1
    assert len(calls["tts"]) == 1
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert entry.runtime_data.tasks[uid].status == "done"


async def test_presence_from_a_zone(hass: HomeAssistant) -> None:
    """The state of a zone is the number of people in it."""
    entry, _ = await setup_integration(hass, presence_entity="zone.home")
    manager = entry.runtime_data
    hass.states.async_set("zone.home", "2")
    assert manager.someone_home()
    hass.states.async_set("zone.home", "0")
    assert not manager.someone_home()
    hass.states.async_set("zone.home", "unavailable")
    assert not manager.someone_home()


async def test_speaks_over_music_after_a_short_wait(hass: HomeAssistant, monkeypatch) -> None:
    """A speaker that keeps playing (music) delays the message only briefly."""
    from custom_components.remindo import manager as mgr

    monkeypatch.setattr(mgr, "SPEAK_WAIT_MAX", 1)
    entry, calls = await setup_integration(hass)
    hass.states.async_set("media_player.tablet", "playing")
    await add_task(hass, summary="Washer")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    assert calls["tts"] == []
    await asyncio.sleep(1.6)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls["tts"]) == 1


async def test_quiet_hours_for_push(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With the option on, a reminder at night waits until the quiet hours end."""
    freezer.move_to("2026-11-09 23:00:00+01:00")
    entry, calls = await setup_integration(hass, quiet_push=True)
    uid = await add_task(hass, summary="Washer", interval=30)
    task = entry.runtime_data.tasks[uid]
    await tick(hass, freezer, seconds=2)
    assert calls["notify"] == [] and task.reminders == 0 and not task.active
    assert task.next_reminder == "2026-11-10T07:00:00+01:00"
    await tick(hass, freezer, hours=4)  # 03:00, still quiet
    assert calls["notify"] == []
    freezer.move_to("2026-11-10 07:00:01+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 1 and task.active


async def test_sensor_has_no_unit(hass: HomeAssistant) -> None:
    await setup_integration(hass)
    assert "unit_of_measurement" not in hass.states.get("sensor.remindo_active").attributes


# ---------------------------------------------------------- recurring tasks


async def test_recurring_task_can_be_deleted(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    a = await add_task(hass, summary="Pills", start="2026-11-10T08:00:00", repeat="daily")
    b = await add_task(hass, summary="Plants", start="2026-11-10T08:00:00", repeat="weekly")
    # "won't do" only skips one date
    await hass.services.async_call(DOMAIN, "dismiss", {"uid": a}, blocking=True)
    assert manager.tasks[a].start == "2026-11-11T08:00:00+01:00"
    # the delete action and removing it in the To-do card remove it for good
    await hass.services.async_call(DOMAIN, "delete", {"uid": a}, blocking=True)
    await hass.services.async_call("todo", "remove_item", {"item": b}, target=TODO, blocking=True)
    assert manager.tasks == {}
    # no timers left behind
    await tick(hass, freezer, days=2)
    assert manager.tasks == {}


async def test_recurring_stop_time_moves_with_the_task(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """ "Stop reminding at 9:00" must work on the second day too."""
    freezer.move_to("2026-11-09 07:59:59+01:00")
    entry, _ = await setup_integration(hass)
    uid = await add_task(
        hass, summary="Pills", start="2026-11-09T08:00:00", repeat="daily", interval=10,
        remind_until="2026-11-09T09:00:00", speakers=[],
    )
    task = entry.runtime_data.tasks[uid]
    await tick(hass, freezer, minutes=10, seconds=2)
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert task.start == "2026-11-10T08:00:00+01:00"
    assert task.remind_until == "2026-11-10T09:00:00+01:00"
    freezer.move_to("2026-11-10 08:00:01+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for _ in range(3):
        await tick(hass, freezer, minutes=10, seconds=1)
    assert task.reminders == 4


# -------------------------------------------------------------------- rules


async def test_rule_fires_after_a_detour_through_unavailable(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.washer", "run")
    await add_rule(hass, entry, {"summary": "Unload", "entity_id": "sensor.washer", "value": "finished"})
    manager = entry.runtime_data  # adding a rule reloads the integration
    hass.states.async_set("sensor.washer", "unavailable")
    hass.states.async_set("sensor.washer", "finished")
    await hass.async_block_till_done()
    assert [t.summary for t in manager.open_tasks()] == ["Unload"]


async def test_rule_does_not_fire_when_the_state_just_appears(hass: HomeAssistant) -> None:
    """After a restart the entity shows up already in the target state: that is not a change."""
    entry, _ = await setup_integration(hass)
    await add_rule(hass, entry, {"summary": "Unload", "entity_id": "sensor.washer", "value": "off"})
    hass.states.async_set("sensor.washer", "unavailable")
    hass.states.async_set("sensor.washer", "off")
    await hass.async_block_till_done()
    assert entry.runtime_data.open_tasks() == []
    # a real cycle afterwards does fire
    hass.states.async_set("sensor.washer", "on")
    hass.states.async_set("sensor.washer", "off")
    await hass.async_block_till_done()
    assert len(entry.runtime_data.open_tasks()) == 1


async def test_countdown_survives_a_reload(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """ "Open for 10 min" keeps counting when the settings change or HA restarts."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    await add_rule(hass, entry, {"summary": "Close the gate", "entity_id": "binary_sensor.gate", "value": "on", "for_minutes": 10})
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=5)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=4)
    assert entry.runtime_data.open_tasks() == []
    await tick(hass, freezer, minutes=2)
    assert [t.summary for t in entry.runtime_data.open_tasks()] == ["Close the gate"]


async def test_countdown_dropped_if_condition_ended_meanwhile(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    await add_rule(hass, entry, {"summary": "Close the gate", "entity_id": "binary_sensor.gate", "value": "on", "for_minutes": 10})
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set("binary_sensor.gate", "off")  # closed while Remindo was not running
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=30)
    assert entry.runtime_data.open_tasks() == []


async def test_rule_edit_can_clear_optional_fields(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    step1 = {"summary": "Gate", "entity_id": "binary_sensor.gate", "mode": "state"}
    step2 = {"value": "on", "for_minutes": 0}
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], step1)
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], step2)
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"remind": True, "interval": 10, "max_reminders": 3, "done_message": "closed", "auto_close": True, "keep_done": True},
    )
    await hass.async_block_till_done()
    sub_id = next(iter(entry.subentries))
    assert entry.subentries[sub_id].data["max_reminders"] == 3

    flow = await entry.start_subentry_reconfigure_flow(hass, sub_id)
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], step1)
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], step2)
    # the user emptied both fields: the frontend does not send empty optional fields at all
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"remind": True, "interval": 10, "auto_close": True, "keep_done": True}
    )
    assert flow["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    data = entry.subentries[sub_id].data
    assert data["max_reminders"] is None and data["done_message"] is None


# ----------------------------------------------------------------- calendar


async def test_calendar_check_is_caught_up_once(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """HA was down at the check time: the check runs after start, but only once that day."""
    freezer.move_to("2026-11-12 19:00:00+01:00")
    entry, _ = await setup_integration(hass)
    lookups = _calendar(hass, ["Paper"])
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.waste", "days_before": 1, "at_time": "18:00:00"})
    manager = entry.runtime_data
    await tick(hass, freezer, seconds=61)
    assert [t.summary for t in manager.open_tasks()] == ["Bins: Paper"]
    await hass.services.async_call(DOMAIN, "done", {"uid": manager.open_tasks()[0].uid}, blocking=True)
    # another restart the same evening must not bring the task back
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=5)
    assert entry.runtime_data.open_tasks() == []
    assert lookups[0] == 1


async def test_calendar_is_retried_when_not_ready(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, _ = await setup_integration(hass)
    lookups = _calendar(hass, ["Paper"], fail_times=2)
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.waste", "days_before": 1, "at_time": "18:00:00"})
    await tick(hass, freezer, seconds=11)
    assert entry.runtime_data.open_tasks() == []
    await tick(hass, freezer, minutes=2, seconds=1)
    await tick(hass, freezer, minutes=2, seconds=1)
    assert lookups[0] == 3
    assert [t.summary for t in entry.runtime_data.open_tasks()] == ["Bins: Paper"]


async def test_unticked_calendar_task_expires_even_after_reload(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Nobody put the bins out: the task is dropped after the event day, not marked done."""
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, _ = await setup_integration(hass)
    _calendar(hass, ["Paper"])
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.waste", "days_before": 1, "at_time": "18:00:00"})
    await tick(hass, freezer, seconds=11)
    task = entry.runtime_data.open_tasks()[0]
    assert task.expires == "2026-11-14T00:00:00+01:00"
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to("2026-11-14 00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert manager.tasks[task.uid].status == "dismissed"
    expired = [h for h in manager.history if h["uid"] == task.uid]
    assert [(h["result"], h["source"]) for h in expired] == [("dismissed", "expired")]


# ------------------------------------------------------------ untrusted text


async def test_templates_only_from_trusted_sources(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Calendar event names, the To-do card and non-admin users never get templates rendered."""
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, calls = await setup_integration(hass)
    hass.states.async_set("alarm_control_panel.home", "armed_away")
    secret = "{{ states('alarm_control_panel.home') }}"

    _calendar(hass, [f"Paper {secret}"])
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.waste", "days_before": 1, "at_time": "18:00:00"})
    manager = entry.runtime_data
    await tick(hass, freezer, seconds=11)
    task = manager.open_tasks()[0]
    assert task.summary == f"Bins: Paper {secret}"
    # the spoken text is taken as it is, too
    assert await manager._speak(task, ["media_player.tablet"]) == f"Bins: Paper {secret}"

    await hass.services.async_call("todo", "add_item", {"item": f"Note {secret}"}, target=TODO, blocking=True)
    assert manager.open_tasks()[-1].summary == f"Note {secret}"

    # (the first user ever created is the owner, so the administrator comes first)
    admin = await hass.auth.async_create_user("parent", group_ids=["system-admin"])
    uid = await _add_as(hass, admin.id, f"From an admin {secret}")
    assert manager.tasks[uid].summary == "From an admin armed_away"

    user = await hass.auth.async_create_user("kid", group_ids=["system-users"])
    uid = await _add_as(hass, user.id, f"From a user {secret}")
    assert manager.tasks[uid].summary == f"From a user {secret}"


async def _add_as(hass: HomeAssistant, user_id: str, summary: str) -> str:
    result = await hass.services.async_call(
        DOMAIN, "add", {"summary": summary, "start": None},
        blocking=True, return_response=True, context=Context(user_id=user_id),
    )
    return result["uid"]


# ------------------------------------------------------------------ editing


async def test_update_action(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Old", description="note", interval=30)
    task = entry.runtime_data.tasks[uid]
    await tick(hass, freezer, seconds=2)
    assert task.active

    # only the fields that are sent change
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "summary": "New"}, blocking=True)
    assert (task.summary, task.description, task.interval) == ("New", "note", 30)

    await hass.services.async_call(
        DOMAIN, "update",
        {"uid": uid, "description": None, "interval": 5, "phones": [], "speakers": ["media_player.tablet"], "max_reminders": 4},
        blocking=True,
    )
    assert task.description is None and task.interval == 5 and task.max_reminders == 4
    assert task.phones == [] and task.speakers == ["media_player.tablet"]
    assert task.next_reminder.startswith("2026-11-09T15:05:0")  # the new rhythm starts now

    # a new due time moves the task back to "Scheduled"; a bare date uses the default time
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "start": "2026-12-01"}, blocking=True)
    assert task.start == task.next_reminder == "2026-12-01T09:00:00+01:00" and not task.active
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "start": None}, blocking=True)
    assert task.start is None and task.next_reminder is None

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "update", {"uid": "missing", "summary": "x"}, blocking=True)


async def test_update_keeps_a_recurring_task_recurring(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="Pills", start="2026-12-01T08:00:00", repeat="daily")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "update", {"uid": uid, "start": None}, blocking=True)
    assert err.value.translation_key == "repeat_needs_start"


async def test_todo_card_can_clear_the_description(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="X", description="note", start=None)
    await hass.services.async_call("todo", "update_item", {"item": uid, "description": ""}, target=TODO, blocking=True)
    assert entry.runtime_data.tasks[uid].description is None


async def test_snooze_ignores_a_finished_task(hass: HomeAssistant) -> None:
    """A stale notification button must not touch a task that is already done."""
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="X")
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    snoozed = []
    hass.bus.async_listen("remindo_snoozed", snoozed.append)
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_SNOOZE_{uid}"})
    await hass.async_block_till_done()
    task = entry.runtime_data.tasks[uid]
    assert task.snoozes == 0 and task.next_reminder is None and snoozed == []


async def test_times_from_the_card(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The card sends absolute (UTC) moments, and a bare date for "tomorrow"."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="X", start="2026-11-09T17:30:00.000Z")
    task = entry.runtime_data.tasks[uid]
    assert task.start == "2026-11-09T18:30:00+01:00"
    await hass.services.async_call(DOMAIN, "snooze", {"uid": uid, "until": "2026-11-10"}, blocking=True)
    assert task.next_reminder == "2026-11-10T09:00:00+01:00"


# ------------------------------------------------------------------ storage


async def test_broken_stored_task_is_skipped(hass: HomeAssistant, hass_storage) -> None:
    hass_storage["remindo"] = {
        "version": 1, "key": "remindo",
        "data": {"tasks": [{"summary": "no uid"}, {"uid": "ok1", "summary": "Fine", "next_reminder": "garbage"}], "history": []},
    }
    entry, _ = await setup_integration(hass)
    assert list(entry.runtime_data.tasks) == ["ok1"]
    assert entry.runtime_data.tasks["ok1"].next_reminder is None


# ------------------------------------------------- second review (0.10.2)


async def test_stale_phone_button_does_not_skip_a_recurring_task(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Two people tap "Done" (or yesterday's notification is tapped): only one date is closed."""
    freezer.move_to("2026-11-10 08:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = await add_task(hass, summary="Pills", start="2026-11-10T08:00:00", repeat="daily", speakers=[])
    task = entry.runtime_data.tasks[uid]
    await tick(hass, freezer, seconds=2)
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DONE_{uid}"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DONE_{uid}"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DISMISS_{uid}"})
    await hass.async_block_till_done()
    assert task.start == "2026-11-11T08:00:00+01:00"
    assert len(entry.runtime_data.history) == 1
    # the stale notification itself is removed from the phone
    assert calls["notify"][-1].data == {"message": "clear_notification", "data": {"tag": f"remindo_{uid}"}}


async def test_rule_firing_again_wakes_a_silent_task(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The washer finishes again while the old task is snoozed for days: remind now."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    hass.states.async_set("sensor.washer", "on")
    await add_rule(hass, entry, {"summary": "Unload", "entity_id": "sensor.washer", "value": "off", "auto_close": False})
    manager = entry.runtime_data
    hass.states.async_set("sensor.washer", "off")
    await hass.async_block_till_done()
    await tick(hass, freezer, seconds=2)
    task = manager.open_tasks()[0]
    await hass.services.async_call(DOMAIN, "snooze", {"uid": task.uid, "until": "2026-11-12T09:00:00"}, blocking=True)

    hass.states.async_set("sensor.washer", "on")
    hass.states.async_set("sensor.washer", "off")
    await hass.async_block_till_done()
    await tick(hass, freezer, seconds=2)
    assert len(manager.open_tasks()) == 1 and task.active and task.reminders == 1 and task.snoozes == 0

    # while it is reminding, another cycle changes nothing
    before = task.next_reminder
    hass.states.async_set("sensor.washer", "on")
    hass.states.async_set("sensor.washer", "off")
    await hass.async_block_till_done()
    assert task.next_reminder == before and task.reminders == 1


async def test_rule_edit_keeps_all_channels_selected(hass: HomeAssistant) -> None:
    """A rule made before any phone was configured means "all": editing it later must show them ticked."""
    entry, _ = await setup_integration(hass, notify_targets=[], media_player=[])
    hass.states.async_set("binary_sensor.gate", "off")
    sub = await add_rule(hass, entry, {"summary": "Gate", "entity_id": "binary_sensor.gate", "value": "on"})
    assert entry.subentries[sub].data["phones"] is None and entry.subentries[sub].data["speakers"] is None
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "notify_targets": ["notify.mobile_app_test"], "media_player": ["media_player.tablet"]}
    )
    await hass.async_block_till_done()
    flow = await entry.start_subentry_reconfigure_flow(hass, sub)
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Gate", "entity_id": "binary_sensor.gate", "mode": "state"})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "on", "for_minutes": 0})
    shown = {str(k): k for k in flow["data_schema"].schema}
    for field, expected in (("phones", ["notify.mobile_app_test"]), ("speakers", ["media_player.tablet"])):
        assert shown[field].default() == expected
        assert "suggested_value" not in (shown[field].description or {})


async def test_reopen_restarts_reminders(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Un-ticking in the To-do card, or "Restore" on the card: the task reminds again."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    manager = entry.runtime_data
    a = await add_task(hass, summary="Done by mistake", interval=5, speakers=[])
    b = await add_task(hass, summary="Skipped by mistake", interval=5, speakers=[])
    await tick(hass, freezer, seconds=2)
    await hass.services.async_call(DOMAIN, "done", {"uid": a}, blocking=True)
    await hass.services.async_call(DOMAIN, "dismiss", {"uid": b}, blocking=True)
    assert manager.tasks[b].status == "dismissed"
    # a dismissed task is not a to-do item, but it is still sent to the card
    items = await hass.services.async_call("todo", "get_items", {}, target=TODO, blocking=True, return_response=True)
    assert [i["summary"] for i in items["todo.remindo"]["items"]] == ["Done by mistake"]

    pushes = len([c for c in calls["notify"] if "actions" in c.data.get("data", {})])
    await hass.services.async_call("todo", "update_item", {"item": a, "status": "needs_action"}, target=TODO, blocking=True)
    await hass.services.async_call(DOMAIN, "reopen", {"uid": b}, blocking=True)
    await tick(hass, freezer, seconds=2)
    assert manager.tasks[a].active and manager.tasks[b].active
    assert len([c for c in calls["notify"] if "actions" in c.data.get("data", {})]) == pushes + 2


async def test_only_recent_dismissed_tasks_are_kept(hass: HomeAssistant) -> None:
    from custom_components.remindo.manager import KEEP_DISMISSED

    entry, _ = await setup_integration(hass)
    for n in range(KEEP_DISMISSED + 3):
        uid = await add_task(hass, summary=f"T{n}", start=None)
        await hass.services.async_call(DOMAIN, "dismiss", {"uid": uid}, blocking=True)
    assert len(entry.runtime_data.tasks) == KEEP_DISMISSED


async def test_restored_expired_task_stays(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, _ = await setup_integration(hass)
    _calendar(hass, ["Paper"])
    await add_rule(hass, entry, {"summary": "Bins", "entity_id": "calendar.waste", "days_before": 0, "at_time": "18:00:00"})
    await tick(hass, freezer, seconds=11)
    manager = entry.runtime_data
    task = manager.open_tasks()[0]
    await tick(hass, freezer, hours=6, seconds=1)  # past midnight: expired
    assert task.status == "dismissed"
    await hass.services.async_call(DOMAIN, "reopen", {"uid": task.uid}, blocking=True)
    await tick(hass, freezer, minutes=5)
    assert task.status == "open" and task.expires is None and task.active


async def test_moving_the_due_time_moves_the_stop_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 07:00:00+01:00")
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="Pills", start="2026-11-09T08:00:00", repeat="daily", remind_until="2026-11-09T09:00:00")
    task = entry.runtime_data.tasks[uid]
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "start": "2026-11-09T20:00:00"}, blocking=True)
    assert task.remind_until == "2026-11-09T21:00:00+01:00"
    # unless the stop time is set in the same call
    await hass.services.async_call(
        DOMAIN, "update", {"uid": uid, "start": "2026-11-09T10:00:00", "remind_until": "2026-11-09T12:00:00"}, blocking=True)
    assert task.remind_until == "2026-11-09T12:00:00+01:00"


async def test_card_is_told_about_the_ha_notification(hass: HomeAssistant, hass_ws_client) -> None:
    """ "No channel" still means a notification in HA when that option is on: the card says so."""
    await setup_integration(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "remindo/subscribe"})
    await client.receive_json()
    msg = await client.receive_json()
    assert msg["event"]["options"]["persistent"] is True
    assert "dismissed" not in msg["event"]
