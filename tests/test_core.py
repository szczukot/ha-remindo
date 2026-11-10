"""Core behaviour: reminders, recurring tasks, targets, rules, calendar, card stream."""

import asyncio
from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.remindo.const import DOMAIN
from custom_components.remindo.manager import add_months, next_occurrence

from .common import add_rule, setup_integration


async def test_reminder_flow(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    done_events = async_capture_events(hass, "remindo_done")

    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Close the gate", "key": "gate", "interval": 5},
        blocking=True, return_response=True,
    )
    uid = res["uid"]
    # same key again: no duplicate
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Close the gate!", "key": "gate"},
        blocking=True, return_response=True,
    )
    assert res2["uid"] == uid

    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 1
    actions = calls["notify"][0].data["data"]["actions"]
    assert actions[0]["action"] == f"REMINDO_DONE_{uid}"
    assert len(calls["tts"]) == 1 and len(calls["switch"]) == 1
    assert hass.states.get("sensor.remindo_active").state == "1"

    # reminded again after 5 min
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 2

    # phone button: snooze
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_SNOOZE_{uid}"})
    await hass.async_block_till_done()
    task = entry.runtime_data.tasks[uid]
    assert task.snoozes == 1
    assert calls["notify"][-1].data["message"] == "clear_notification"

    # the gate was closed
    await hass.services.async_call(DOMAIN, "close_by_key", {"key": "gate"}, blocking=True)
    await hass.async_block_till_done()
    assert task.status == "done"
    assert len(done_events) == 1 and done_events[0].data["source"] == "auto"
    assert hass.states.get("sensor.remindo_active").state == "0"


async def test_no_tts_when_away_or_quiet(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 23:00:00+01:00")
    entry, calls = await setup_integration(hass)
    await hass.services.async_call(DOMAIN, "add", {"summary": "Night"}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 1 and len(calls["tts"]) == 0

    freezer.move_to("2026-11-10 12:00:00+01:00")
    hass.states.async_set("group.people_in_home", "not_home")
    await hass.services.async_call(DOMAIN, "add", {"summary": "Nobody home"}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["tts"]) == 0


async def test_recurring_and_todo(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 10:00:00+01:00")
    entry, calls = await setup_integration(hass)
    res = await hass.services.async_call(
        DOMAIN, "add",
        {"summary": "HRV filter", "start": "2026-11-09T09:00:00", "repeat": "monthly", "repeat_every": 3},
        blocking=True, return_response=True,
    )
    uid = res["uid"]
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    task = entry.runtime_data.tasks[uid]
    assert task.status == "open"
    assert task.start.startswith("2027-02-09T09:00")

    # the standard todo actions: add with a date only, tick off
    await hass.services.async_call(
        "todo", "add_item", {"item": "Buy milk", "due_date": "2026-11-12"},
        target={"entity_id": "todo.remindo"}, blocking=True,
    )
    items = await hass.services.async_call(
        "todo", "get_items", {}, target={"entity_id": "todo.remindo"}, blocking=True, return_response=True
    )
    milk = [i for i in items["todo.remindo"]["items"] if i["summary"] == "Buy milk"][0]
    assert milk["due"].startswith("2026-11-12T09:00")
    await hass.services.async_call(
        "todo", "update_item", {"item": milk["uid"], "status": "completed"},
        target={"entity_id": "todo.remindo"}, blocking=True,
    )
    assert entry.runtime_data.tasks[milk["uid"]].status == "done"

    # a reload keeps the data
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert uid in entry.runtime_data.tasks


def test_add_months() -> None:
    d = datetime(2026, 1, 31, 9, 0, tzinfo=dt_util.UTC)
    assert add_months(d, 1).day == 28
    assert next_occurrence(d, "weekly", 2, d + timedelta(days=1)) == d + timedelta(weeks=2)


async def test_targets_and_snooze(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    await hass.services.async_call(
        DOMAIN, "add", {"summary": "List only", "phones": [], "speakers": []},
        blocking=True, return_response=True,
    )
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Voice only", "phones": [], "speakers": ["media_player.tablet"]},
        blocking=True, return_response=True,
    )
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 0
    assert len(calls["tts"]) == 1 and calls["tts"][0].data["media_player_entity_id"] == ["media_player.tablet"]
    task = entry.runtime_data.tasks[res2["uid"]]
    assert task.active
    await hass.services.async_call(DOMAIN, "snooze", {"uid": task.uid, "minutes": 60}, blocking=True)
    assert not task.active
    assert task.next_reminder.startswith("2026-11-09T16:00")


def test_hourly() -> None:
    d = datetime(2026, 11, 9, 9, 0, tzinfo=dt_util.UTC)
    assert next_occurrence(d, "hourly", 5, d + timedelta(hours=6)) == d + timedelta(hours=10)


async def test_rules(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    hass.states.async_set("sensor.dishwasher", "run")
    gate = await add_rule(hass, entry, {"summary": "Close the gate", "entity_id": "binary_sensor.gate", "value": "on", "for_minutes": 10})
    await add_rule(hass, entry, {"summary": "Unload the dishwasher", "entity_id": "sensor.dishwasher", "value": "finished"})
    manager = entry.runtime_data
    assert len(manager.rules.rules) == 2

    hass.states.async_set("sensor.dishwasher", "finished")
    await hass.async_block_till_done()
    assert [t.summary for t in manager.open_tasks()] == ["Unload the dishwasher"]
    hass.states.async_set("sensor.dishwasher", "unavailable")
    hass.states.async_set("sensor.dishwasher", "finished")
    await hass.async_block_till_done()
    assert len(manager.open_tasks()) == 1
    hass.states.async_set("sensor.dishwasher", "ready")
    await hass.async_block_till_done()
    assert manager.open_tasks() == []

    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert manager.open_tasks() == []
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [t.key for t in manager.open_tasks()] == [f"rule_{gate}"]
    hass.states.async_set("binary_sensor.gate", "off")
    await hass.async_block_till_done()
    assert manager.open_tasks() == []

    # editing (reconfigure) changes the text
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"), context={"source": "reconfigure", "subentry_id": gate}
    )
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Gate!", "entity_id": "binary_sensor.gate", "mode": "state"}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "on", "for_minutes": 1})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"remind": False, "auto_close": True})
    assert flow["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    rule = entry.runtime_data.rules.rules[gate]
    assert rule.summary == "Gate!" and rule.interval == 0 and rule.for_minutes == 1

    # removal
    hass.config_entries.async_remove_subentry(entry, gate)
    await hass.async_block_till_done()
    assert list(entry.runtime_data.rules.rules) != [gate] and len(entry.runtime_data.rules.rules) == 1


async def test_calendar_rule(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, calls = await setup_integration(hass)

    async def get_events(call):
        assert call.data["start_date_time"].startswith("2026-11-13T00:00")
        return {"calendar.waste": {"events": [{"summary": "Bio waste"}, {"summary": "Paper"}]}}

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    hass.states.async_set("calendar.waste", "off")
    await add_rule(hass, entry, {"summary": "Put the bins out", "entity_id": "calendar.waste", "days_before": 1, "at_time": "18:00:00"})
    manager = entry.runtime_data
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [t.summary for t in manager.open_tasks()] == ["Put the bins out: Bio waste, Paper"]
    freezer.move_to("2026-11-14 00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert manager.open_tasks() == []


async def test_ws_survives_reload(hass: HomeAssistant, hass_ws_client) -> None:
    entry, calls = await setup_integration(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "remindo/subscribe"})
    assert (await asyncio.wait_for(client.receive_json(), 2))["success"]
    assert (await asyncio.wait_for(client.receive_json(), 2))["event"]["tasks"] == []
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.wait_for(client.receive_json(), 2)  # refresh after the reload
    res = await hass.services.async_call(DOMAIN, "add", {"summary": "After reload", "start": None}, blocking=True, return_response=True)
    msg = await asyncio.wait_for(client.receive_json(), 2)
    assert [t["summary"] for t in msg["event"]["tasks"]] == ["After reload"]
    await hass.services.async_call(DOMAIN, "dismiss", {"uid": res["uid"]}, blocking=True)
    msg = await asyncio.wait_for(client.receive_json(), 2)
    assert msg["event"]["tasks"] == []


async def test_reminder_limits(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Max 2", "interval": 5, "max_reminders": 2, "speakers": []},
        blocking=True, return_response=True,
    )
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Until 15:12", "interval": 5, "remind_until": "2026-11-09T15:12:00", "speakers": []},
        blocking=True, return_response=True,
    )
    for _ in range(5):
        freezer.tick(timedelta(minutes=5, seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    t1 = entry.runtime_data.tasks[res["uid"]]
    t2 = entry.runtime_data.tasks[res2["uid"]]
    assert t1.reminders == 2 and t1.next_reminder is None and t1.active
    assert t2.reminders == 2 and t2.next_reminder is None
