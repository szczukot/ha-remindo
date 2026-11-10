"""Config flow, translations, language, errors, To-do entity, restart."""

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.remindo import texts
from custom_components.remindo.const import DOMAIN

from .common import OPTS, add_rule, setup_integration

COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN


# --------------------------------------------------------------- config flow


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "mobile_app_phone")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"notify_targets": ["notify.mobile_app_phone"], "default_interval": 15.0, "phone_snooze": 20.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Remindo"
    options = result["result"].options
    assert options["notify_targets"] == ["notify.mobile_app_phone"]
    assert options["default_interval"] == 15 and isinstance(options["default_interval"], int)
    await hass.async_block_till_done()
    assert hass.states.get("todo.remindo") is not None


async def test_options_flow_updates_and_reloads(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTS, "media_player": ["media_player.kitchen"], "default_interval": 45}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["media_player"] == ["media_player.kitchen"]
    assert entry.runtime_data.options["default_interval"] == 45


async def test_rule_reconfigure(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.washer", "run")
    sub_id = await add_rule(hass, entry, {"summary": "Hang laundry", "entity_id": "sensor.washer", "value": "finished"})
    flow = await entry.start_subentry_reconfigure_flow(hass, sub_id)
    assert flow["step_id"] == "trigger"
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Hang the laundry", "entity_id": "sensor.washer", "mode": "state"}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "end", "for_minutes": 5})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"remind": False, "auto_close": False}
    )
    assert flow["type"] is FlowResultType.ABORT and flow["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    sub = entry.subentries[sub_id]
    assert sub.title == "Hang the laundry"
    assert sub.data["value"] == "end" and sub.data["for_minutes"] == 5
    assert sub.data["interval"] == 0 and sub.data["auto_close"] is False


# -------------------------------------------------------------- translations


def _keys(node, prefix=""):
    if isinstance(node, dict):
        out = set()
        for key, value in node.items():
            out |= _keys(value, f"{prefix}.{key}" if prefix else key)
        return out
    return {prefix}


def _leaves(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, node


def test_strings_equal_english() -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == en


def test_polish_matches_english() -> None:
    en = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    pl = json.loads((COMPONENT / "translations" / "pl.json").read_text(encoding="utf-8"))
    assert _keys(en) == _keys(pl)
    pl_values = dict(_leaves(pl))
    for key, value in _leaves(en):
        placeholders = set(re.findall(r"\{(\w+)\}", value))
        assert placeholders == set(re.findall(r"\{(\w+)\}", pl_values[key])), key


def test_services_yaml_translated() -> None:
    en = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    yaml_services = re.findall(r"^(\w+):\s*$", (COMPONENT / "services.yaml").read_text(encoding="utf-8"), re.M)
    assert set(yaml_services) == set(en["services"])


def test_backend_texts_complete() -> None:
    assert set(texts._TEXTS["en"]) == set(texts._TEXTS["pl"])
    assert set(texts._UNITS["en"]) == set(texts._UNITS["pl"])


@pytest.mark.parametrize(
    ("lang", "repeat", "every", "expected"),
    [
        ("en", "daily", 1, "every day"),
        ("en", "monthly", 3, "every 3 months"),
        ("pl", "daily", 1, "co dzień"),
        ("pl", "monthly", 3, "co 3 miesiące"),
        ("pl", "weekly", 5, "co 5 tygodni"),
        ("pl", "yearly", 22, "co 22 lata"),
        ("pl", "hourly", 12, "co 12 godzin"),
        ("de", "weekly", 2, "every 2 weeks"),
    ],
)
def test_repeat_label(hass: HomeAssistant, lang, repeat, every, expected) -> None:
    hass.config.language = lang
    assert texts.repeat_label(hass, repeat, every) == expected


# --------------------------------------------------------- language at runtime


@pytest.mark.parametrize(
    ("lang", "title", "done", "dismiss"),
    [("en", "📋 Task", "✅ Done", "❌ Skip"), ("pl", "📋 Zadanie", "✅ Zrobione", "❌ Nie robię")],
)
async def test_push_follows_language(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, lang, title, done, dismiss
) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    hass.config.language = lang
    _, calls = await setup_integration(hass)
    await hass.services.async_call(DOMAIN, "add", {"summary": "X", "speakers": []}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = calls["notify"][0].data
    assert data["title"] == title
    assert [a["title"] for a in data["data"]["actions"]] == [done, "⏰ +10 min", dismiss]
    assert calls["pn_create"][0].data["title"] == title


async def test_logbook_description(hass: HomeAssistant) -> None:
    from custom_components.remindo.logbook import async_describe_events

    hass.config.language = "en"
    described = {}
    async_describe_events(hass, lambda domain, event_type, fn: described.setdefault(event_type, fn))
    assert set(described) == {f"remindo_{e}" for e in ("created", "reminded", "done", "snoozed", "dismissed")}
    describe = described["remindo_reminded"]
    event = type("E", (), {"event_type": "remindo_reminded", "data": {"summary": "Bin", "source": "rule", "count": 3}})()
    assert describe(event) == {"name": "Task: Bin", "message": "reminded (by rule), time #3"}
    hass.config.language = "pl"
    assert describe(event) == {"name": "Zadanie: Bin", "message": "przypomniano (z reguły), 3. raz"}


# ------------------------------------------------------------- service errors


async def test_service_errors_are_translated(hass: HomeAssistant) -> None:
    await setup_integration(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "done", {"uid": "nope"}, blocking=True)
    assert err.value.translation_key == "task_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "add", {"summary": "X", "start": "someday"}, blocking=True, return_response=True)
    assert err.value.translation_key == "invalid_start"
    assert err.value.translation_placeholders == {"start": "someday"}
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add", {"summary": "X", "start": None, "repeat": "daily"}, blocking=True, return_response=True
        )
    assert err.value.translation_key == "repeat_needs_start"


async def test_service_unavailable_after_unload(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "done", {"uid": "x"}, blocking=True)
    assert err.value.translation_key == "not_loaded"


# ------------------------------------------------------------ phone and To-do


async def test_phone_done_and_dismiss(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    done = async_capture_events(hass, "remindo_done")
    dismissed = async_capture_events(hass, "remindo_dismissed")
    a = (await hass.services.async_call(DOMAIN, "add", {"summary": "A"}, blocking=True, return_response=True))["uid"]
    b = (await hass.services.async_call(DOMAIN, "add", {"summary": "B"}, blocking=True, return_response=True))["uid"]
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DONE_{a}"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"REMINDO_DISMISS_{b}"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": "SOMETHING_ELSE"})
    await hass.async_block_till_done()
    tasks = entry.runtime_data.tasks
    assert tasks[a].status == "done"
    assert b not in tasks  # dismissed tasks leave the list and go to history
    assert entry.runtime_data.history[-1]["result"] == "dismissed"
    assert done[0].data["source"] == "phone" and dismissed[0].data["source"] == "phone"
    cleared = [c for c in calls["notify"] if c.data["message"] == "clear_notification"]
    assert {c.data["data"]["tag"] for c in cleared} == {f"remindo_{a}", f"remindo_{b}"}


async def test_click_url_in_push(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    _, calls = await setup_integration(hass)
    await hass.services.async_call(DOMAIN, "add", {"summary": "X", "speakers": []}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = calls["notify"][0].data["data"]
    assert data["clickAction"] == data["url"] == "/todo?entity_id=todo.remindo"
    assert data["tag"].startswith("remindo_")


async def test_todo_entity_roundtrip(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    await hass.services.async_call(
        "todo", "add_item", {"item": "Water plants", "due_datetime": "2026-11-10 08:00:00"},
        target={"entity_id": "todo.remindo"}, blocking=True,
    )
    task = next(iter(manager.tasks.values()))
    assert task.summary == "Water plants" and task.start.startswith("2026-11-10T08:00")
    assert hass.states.get("todo.remindo").state == "1"

    await hass.services.async_call(
        "todo", "update_item", {"item": task.uid, "rename": "Water all plants"},
        target={"entity_id": "todo.remindo"}, blocking=True,
    )
    assert task.summary == "Water all plants"

    await hass.services.async_call(
        "todo", "update_item", {"item": task.uid, "status": "completed"},
        target={"entity_id": "todo.remindo"}, blocking=True,
    )
    assert task.status == "done"
    assert hass.states.get("todo.remindo").state == "0"

    await hass.services.async_call(
        "todo", "remove_item", {"item": task.uid}, target={"entity_id": "todo.remindo"}, blocking=True
    )
    assert task.uid not in manager.tasks


async def test_todo_shows_repeat_in_description(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    hass.config.language = "en"
    await setup_integration(hass)
    await hass.services.async_call(
        DOMAIN, "add", {"summary": "Filter", "start": "2026-12-01", "repeat": "monthly", "repeat_every": 3, "description": "HRV"},
        blocking=True, return_response=True,
    )
    items = await hass.services.async_call(
        "todo", "get_items", {}, target={"entity_id": "todo.remindo"}, blocking=True, return_response=True
    )
    item = items["todo.remindo"]["items"][0]
    assert item["description"] == "🔁 every 3 months\nHRV"


# ------------------------------------------------------------------- restart


async def test_tasks_survive_restart_and_missed_reminder_fires(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Later", "start": "2026-11-09T16:00:00", "speakers": []},
        blocking=True, return_response=True,
    )
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 0

    # HA was down while the reminder was due
    freezer.move_to("2026-11-09 17:00:00+01:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not entry.runtime_data.tasks[res["uid"]].active
    freezer.tick(timedelta(seconds=31))  # missed reminders fire 30 s after start
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    task = entry.runtime_data.tasks[res["uid"]]
    assert task.summary == "Later"
    assert task.active
    assert len([c for c in calls["notify"] if c.data["message"] == "Later"]) == 1


async def test_snooze_until_picked_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = (await hass.services.async_call(DOMAIN, "add", {"summary": "X", "speakers": []}, blocking=True, return_response=True))["uid"]
    # card "tomorrow 09:00" and the date picker both send a local date-time
    await hass.services.async_call(DOMAIN, "snooze", {"uid": uid, "until": "2026-11-10T09:00:00"}, blocking=True)
    task = entry.runtime_data.tasks[uid]
    assert task.next_reminder.startswith("2026-11-10T09:00:00") and not task.active
    await hass.services.async_call(DOMAIN, "snooze", {"uid": uid, "until": "2026-11-12T18:45:00"}, blocking=True)
    assert task.next_reminder.startswith("2026-11-12T18:45:00")


async def test_card_gets_default_time(hass: HomeAssistant, hass_ws_client) -> None:
    await setup_integration(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "remindo/subscribe"})
    await client.receive_json()
    msg = await client.receive_json()
    assert msg["event"]["options"]["default_time"] == "09:00:00"


async def test_snooze_then_interval_resumes(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """+1 h on a task reminding every 5 min: one reminder in an hour, then every 5 min again."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    uid = (await hass.services.async_call(DOMAIN, "add", {"summary": "X", "interval": 5, "speakers": []}, blocking=True, return_response=True))["uid"]
    task = entry.runtime_data.tasks[uid]

    async def tick(**kw):
        freezer.tick(timedelta(**kw))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    await tick(seconds=2)
    assert task.reminders == 1
    await hass.services.async_call(DOMAIN, "snooze", {"uid": uid, "minutes": 60}, blocking=True)
    await tick(minutes=59)
    assert task.reminders == 1 and not task.active  # quiet during the snooze
    await tick(minutes=1, seconds=1)
    assert task.reminders == 2 and task.active
    await tick(minutes=5, seconds=1)
    assert task.reminders == 3  # back to every 5 min


async def test_speech_waits_for_busy_speaker(hass: HomeAssistant, monkeypatch) -> None:
    """Another automation is talking on the tablet: Remindo waits until it is quiet."""
    import asyncio

    from custom_components.remindo import manager as mgr

    monkeypatch.setattr(mgr, "SPEAK_WAIT_MAX", 5)
    entry, calls = await setup_integration(hass)
    hass.states.async_set("media_player.tablet", "playing")
    await hass.services.async_call(DOMAIN, "add", {"summary": "Washer"}, blocking=True, return_response=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    await asyncio.sleep(1)
    assert len(calls["notify"]) == 1  # push is not delayed
    assert calls["tts"] == []  # speaker busy: waiting
    hass.states.async_set("media_player.tablet", "idle")
    await asyncio.sleep(1)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls["tts"]) == 1


async def test_speech_skipped_if_done_while_waiting(hass: HomeAssistant, monkeypatch) -> None:
    import asyncio

    from custom_components.remindo import manager as mgr

    monkeypatch.setattr(mgr, "SPEAK_WAIT_MAX", 5)
    entry, calls = await setup_integration(hass)
    hass.states.async_set("media_player.tablet", "playing")
    uid = (await hass.services.async_call(DOMAIN, "add", {"summary": "Washer"}, blocking=True, return_response=True))["uid"]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    hass.states.async_set("media_player.tablet", "idle")
    await asyncio.sleep(1)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls["tts"] == []


# ------------------------------------------------------------ 0.9.0 features


async def _remind(hass, freezer, seconds=2):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_keep_done_off_removes_task(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    a = (await hass.services.async_call(DOMAIN, "add", {"summary": "Gone", "keep_done": False}, blocking=True, return_response=True))["uid"]
    b = (await hass.services.async_call(DOMAIN, "add", {"summary": "Stays"}, blocking=True, return_response=True))["uid"]
    c = (await hass.services.async_call(
        DOMAIN, "add", {"summary": "Yearly", "start": "2026-11-11", "repeat": "yearly", "keep_done": False},
        blocking=True, return_response=True))["uid"]
    for uid in (a, b, c):
        await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert a not in manager.tasks
    assert manager.tasks[b].status == "done"
    assert manager.tasks[c].status == "open" and manager.tasks[c].start.startswith("2027-11-11")  # recurring stays
    assert [h["summary"] for h in manager.history if h["result"] == "done"] == ["Gone", "Stays", "Yearly"]


async def test_keep_done_option_default(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    hass.config_entries.async_update_entry(entry, options={**OPTS, "keep_done": False})
    await hass.async_block_till_done()
    manager = entry.runtime_data
    uid = (await hass.services.async_call(DOMAIN, "add", {"summary": "X"}, blocking=True, return_response=True))["uid"]
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert uid not in manager.tasks


async def test_done_message_on_auto_close(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    _, calls = await setup_integration(hass)
    await hass.services.async_call(
        DOMAIN, "add", {"summary": "Gate open", "key": "gate", "done_message": "Gate closed ✅", "speakers": []},
        blocking=True, return_response=True)
    await _remind(hass, freezer)
    await hass.services.async_call(DOMAIN, "close_by_key", {"key": "gate"}, blocking=True)
    await hass.async_block_till_done()
    assert calls["notify"][-1].data == {"title": "📋 Task", "message": "Gate closed ✅"}

    # not sent when ticked off by hand, nor when it never reminded
    await hass.services.async_call(
        DOMAIN, "add", {"summary": "B", "key": "b", "done_message": "nope", "speakers": []}, blocking=True, return_response=True)
    await _remind(hass, freezer)
    await hass.services.async_call(DOMAIN, "done", {"key": "b"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "add", {"summary": "C", "key": "c", "start": "2026-12-01", "done_message": "nope"}, blocking=True, return_response=True)
    await hass.services.async_call(DOMAIN, "close_by_key", {"key": "c"}, blocking=True)
    await hass.async_block_till_done()
    assert not [c for c in calls["notify"] if c.data.get("message") == "nope"]


async def test_template_summary(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    hass.states.async_set("sensor.outside", "5")
    uid = (await hass.services.async_call(
        DOMAIN, "add", {"summary": "Window open, {{ states('sensor.outside') }}°C", "interval": 5, "speakers": []},
        blocking=True, return_response=True))["uid"]
    task = entry.runtime_data.tasks[uid]
    assert task.summary == "Window open, 5°C"
    await _remind(hass, freezer)
    hass.states.async_set("sensor.outside", "-2")
    await _remind(hass, freezer, 5 * 60 + 1)
    assert task.summary == "Window open, -2°C"
    assert calls["notify"][-1].data["message"] == "Window open, -2°C"
    # broken template: plain text, no crash
    res = await hass.services.async_call(DOMAIN, "add", {"summary": "Bad {{ nope( }}"}, blocking=True, return_response=True)
    assert entry.runtime_data.tasks[res["uid"]].summary == "Bad {{ nope( }}"


async def test_other_notifiers(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    telegram = async_mock_service(hass, "notify", "telegram_home")
    send_message = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set("notify.email_me", "unknown", {"friendly_name": "E-mail me"})
    await hass.services.async_call(
        DOMAIN, "add",
        {"summary": "Bins", "phones": ["notify.mobile_app_test", "notify.telegram_home", "notify.email_me"], "speakers": []},
        blocking=True, return_response=True)
    await _remind(hass, freezer)
    assert "actions" in calls["notify"][0].data["data"]  # app: with buttons
    assert telegram[0].data == {"title": "📋 Task", "message": "Bins"}  # text only
    assert send_message[0].data == {"entity_id": "notify.email_me", "title": "📋 Task", "message": "Bins"}
    assert entry.runtime_data.phone_label("notify.email_me") == "E-mail me"
    # clearing goes only to the app
    await hass.services.async_call(DOMAIN, "done", {"uid": next(iter(entry.runtime_data.tasks))}, blocking=True)
    await hass.async_block_till_done()
    assert len(telegram) == 1 and len(send_message) == 1


async def test_rule_done_message_and_keep(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Close the gate", "entity_id": "binary_sensor.gate", "mode": "state"})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "on", "for_minutes": 0})
    assert "done_message" in {str(k) for k in flow["data_schema"].schema}
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"remind": True, "interval": 10, "auto_close": True, "done_message": "Gate closed ✅", "keep_done": False, "speakers": []})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    manager = entry.runtime_data
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    await _remind(hass, freezer)
    assert [t.summary for t in manager.open_tasks()] == ["Close the gate"]
    hass.states.async_set("binary_sensor.gate", "off")
    await hass.async_block_till_done()
    assert manager.open_tasks() == [] and manager.tasks == {}  # closed and not kept
    assert calls["notify"][-1].data["message"] == "Gate closed ✅"


async def test_date_only_uses_default_time_and_early_done(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """"Flag on 11 Nov every year": date only → 09:00; ticking off early moves to next year."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    uid = (await hass.services.async_call(
        DOMAIN, "add", {"summary": "Hang the flag", "start": "2026-11-11", "repeat": "yearly"},
        blocking=True, return_response=True))["uid"]
    task = entry.runtime_data.tasks[uid]
    assert task.start == "2026-11-11T09:00:00+01:00"
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert task.start == "2027-11-11T09:00:00+01:00"


async def test_rule_simple_tokens(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """{state} and {name} work without knowing templates and update at each reminder."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    attrs = {"unit_of_measurement": "%", "friendly_name": "Bathroom humidity"}
    hass.states.async_set("sensor.hum", "60", attrs)
    await add_rule(hass, entry, {"summary": "Air the bathroom: {name} {state}", "entity_id": "sensor.hum", "mode": "above", "value": 70})
    hass.states.async_set("sensor.hum", "75", attrs)
    await hass.async_block_till_done()
    await _remind(hass, freezer)
    task = entry.runtime_data.open_tasks()[0]
    assert task.summary == "Air the bathroom: Bathroom humidity 75 %"
    hass.states.async_set("sensor.hum", "82", attrs)
    await _remind(hass, freezer, 30 * 60 + 1)
    assert task.summary == "Air the bathroom: Bathroom humidity 82 %"


async def test_rule_spoken_text_and_notify_data(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A rule can say something else than the task text, and add Companion app options."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass, notify_data={"car_ui": True, "channel": "Remindo"})
    hass.states.async_set("sensor.dishwasher", "run", {"friendly_name": "Dishwasher"})
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Unload the dishwasher", "entity_id": "sensor.dishwasher", "mode": "state"})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "finished", "for_minutes": 0})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"remind": True, "interval": 3, "auto_close": True, "keep_done": False,
         "phones": ["notify.mobile_app_test"], "speakers": ["media_player.tablet"],
         "tts_message": "It's me, your {name}. Open me, please.",
         "notify_data": {"priority": "high", "ttl": 0, "channel": "Appliances", "tag": "mine", "actions": []}},
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    hass.states.async_set("sensor.dishwasher", "finished", {"friendly_name": "Dishwasher"})
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert calls["tts"][0].data["message"] == "It's me, your Dishwasher. Open me, please."
    push = calls["notify"][0].data
    assert push["message"] == "Unload the dishwasher"
    data = push["data"]
    assert data["car_ui"] is True  # from the integration options
    assert data["priority"] == "high" and data["ttl"] == 0 and data["channel"] == "Appliances"  # the rule wins
    # the tag and the buttons cannot be replaced: clearing and Done/Snooze depend on them
    assert data["tag"].startswith("remindo_") and len(data["actions"]) == 3


async def test_notify_data_from_the_action(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await setup_integration(hass)
    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "X", "speakers": [], "notify_data": {"notification_icon": "mdi:washing-machine"}},
        blocking=True, return_response=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls["notify"][0].data["data"]["notification_icon"] == "mdi:washing-machine"
    await hass.services.async_call(DOMAIN, "update", {"uid": res["uid"], "notify_data": None}, blocking=True)
    assert entry.runtime_data.tasks[res["uid"]].notify_data is None
