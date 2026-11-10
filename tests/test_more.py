"""Config flow, translations, language, errors, To-do entity, restart."""

import json
from datetime import timedelta
from pathlib import Path
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from custom_components.remindo import texts
from custom_components.remindo.const import DOMAIN

from .test_remindo import OPTS, _add_rule, _setup

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
    entry, _ = await _setup(hass)
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
    entry, _ = await _setup(hass)
    hass.states.async_set("sensor.washer", "run")
    sub_id = await _add_rule(hass, entry, {"summary": "Hang laundry", "entity_id": "sensor.washer", "value": "finished"})
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
    _, calls = await _setup(hass)
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
    await _setup(hass)
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
    entry, _ = await _setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "done", {"uid": "x"}, blocking=True)
    assert err.value.translation_key == "not_loaded"


# ------------------------------------------------------------ phone and To-do


async def test_phone_done_and_dismiss(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await _setup(hass)
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
    _, calls = await _setup(hass)
    await hass.services.async_call(DOMAIN, "add", {"summary": "X", "speakers": []}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = calls["notify"][0].data["data"]
    assert data["clickAction"] == data["url"] == "/todo?entity_id=todo.remindo"
    assert data["tag"].startswith("remindo_")


async def test_todo_entity_roundtrip(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await _setup(hass)
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
    await _setup(hass)
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
    entry, calls = await _setup(hass)
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
