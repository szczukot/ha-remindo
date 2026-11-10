import asyncio
from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.util import dt as dt_util

from custom_components.zadania.const import DOMAIN
from custom_components.zadania.manager import add_months, next_occurrence

OPTS = {
    "notify_targets": ["notify.mobile_app_test"],
    "persistent_notification": True,
    "tts_entity": "tts.test",
    "media_player": "media_player.tablet",
    "screen_switch": "switch.screen",
    "presence_entity": "group.people_in_home",
    "tts_default": True,
    "quiet_start": "22:00:00",
    "quiet_end": "07:00:00",
    "default_interval": 30,
    "default_time": "09:00:00",
    "phone_snooze": 10,
}


async def _setup(hass: HomeAssistant):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    calls = {
        "notify": async_mock_service(hass, "notify", "mobile_app_test"),
        "tts": async_mock_service(hass, "tts", "speak"),
        "switch": async_mock_service(hass, "switch", "turn_on"),
        "pn_create": async_mock_service(hass, "persistent_notification", "create"),
        "pn_dismiss": async_mock_service(hass, "persistent_notification", "dismiss"),
    }
    hass.states.async_set("group.people_in_home", "home")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=OPTS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def test_reminder_flow(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await _setup(hass)
    done_events = async_capture_events(hass, "zadania_done")

    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Zamknij bramę", "key": "brama", "interval": 5},
        blocking=True, return_response=True,
    )
    uid = res["uid"]
    # duplikat po kluczu
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Zamknij bramę!", "key": "brama"},
        blocking=True, return_response=True,
    )
    assert res2["uid"] == uid

    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 1
    actions = calls["notify"][0].data["data"]["actions"]
    assert actions[0]["action"] == f"ZADANIA_DONE_{uid}"
    assert len(calls["tts"]) == 1 and len(calls["switch"]) == 1
    assert hass.states.get("sensor.zadania_aktywne").state == "1"

    # po 5 min ponowne przypomnienie
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 2

    # przycisk z telefonu: odłóż
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"ZADANIA_SNOOZE_{uid}"})
    await hass.async_block_till_done()
    task = entry.runtime_data.tasks[uid]
    assert task.snoozes == 1
    assert calls["notify"][-1].data["message"] == "clear_notification"

    # brama się zamknęła
    await hass.services.async_call(DOMAIN, "close_by_key", {"key": "brama"}, blocking=True)
    await hass.async_block_till_done()
    assert task.status == "done"
    assert len(done_events) == 1 and done_events[0].data["source"] == "auto"
    assert hass.states.get("sensor.zadania_aktywne").state == "0"


async def test_no_tts_when_away_or_quiet(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 23:00:00+01:00")
    entry, calls = await _setup(hass)
    await hass.services.async_call(DOMAIN, "add", {"summary": "Noc"}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["notify"]) == 1 and len(calls["tts"]) == 0

    freezer.move_to("2026-11-10 12:00:00+01:00")
    hass.states.async_set("group.people_in_home", "not_home")
    await hass.services.async_call(DOMAIN, "add", {"summary": "Pusto"}, blocking=True)
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls["tts"]) == 0


async def test_recurring_and_todo(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 10:00:00+01:00")
    entry, calls = await _setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "add",
        {"summary": "Filtr rekuperatora", "start": "2026-11-09T09:00:00", "repeat": "monthly", "repeat_every": 3},
        blocking=True, return_response=True,
    )
    uid = res["uid"]
    await hass.async_block_till_done()
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    task = entry.runtime_data.tasks[uid]
    assert task.status == "open"
    assert task.start.startswith("2027-02-09T09:00")

    # standardowa usługa todo: dodaj z samą datą, odhacz
    await hass.services.async_call(
        "todo", "add_item", {"item": "Kup mleko", "due_date": "2026-11-12"},
        target={"entity_id": "todo.zadania"}, blocking=True,
    )
    items = await hass.services.async_call(
        "todo", "get_items", {}, target={"entity_id": "todo.zadania"}, blocking=True, return_response=True
    )
    mleko = [i for i in items["todo.zadania"]["items"] if i["summary"] == "Kup mleko"][0]
    assert mleko["due"].startswith("2026-11-12T09:00")
    await hass.services.async_call(
        "todo", "update_item", {"item": mleko["uid"], "status": "completed"},
        target={"entity_id": "todo.zadania"}, blocking=True,
    )
    assert entry.runtime_data.tasks[mleko["uid"]].status == "done"

    # restart (reload) zachowuje dane
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert uid in entry.runtime_data.tasks


def test_add_months() -> None:
    d = datetime(2026, 1, 31, 9, 0, tzinfo=dt_util.UTC)
    assert add_months(d, 1).day == 28
    assert next_occurrence(d, "weekly", 2, d + timedelta(days=1)) == d + timedelta(weeks=2)


async def test_targets_and_snooze(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await _setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Tylko telefon", "phones": [], "speakers": []},
        blocking=True, return_response=True,
    )
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Tylko głos", "phones": [], "speakers": ["media_player.tablet"]},
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


async def _add_rule(hass: HomeAssistant, entry, data: dict) -> str:
    """Dodaje regułę przez prawdziwy formularz (podwpis) — tak jak użytkownik w UI."""
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": data["summary"], "entity_id": data["entity_id"], "mode": data.get("mode", "state")}
    )
    cond = {k: data[k] for k in ("value", "for_minutes", "days_before", "at_time", "contains") if k in data}
    if not data["entity_id"].startswith("calendar."):
        cond.setdefault("for_minutes", 0)
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], cond)
    assert flow["step_id"] == "notify", flow
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"remind": True, "interval": 30, "auto_close": data.get("auto_close", True)}
    )
    assert flow["type"] == "create_entry", flow
    await hass.async_block_till_done()
    return next(s.subentry_id for s in entry.subentries.values() if s.title == data["summary"])


async def test_rules(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await _setup(hass)
    hass.states.async_set("binary_sensor.brama", "off")
    hass.states.async_set("sensor.zmywarka", "run")
    gate = await _add_rule(hass, entry, {"summary": "Zamknij bramę", "entity_id": "binary_sensor.brama", "value": "on", "for_minutes": 10})
    await _add_rule(hass, entry, {"summary": "Wypakuj zmywarkę", "entity_id": "sensor.zmywarka", "value": "finished"})
    manager = entry.runtime_data
    assert len(manager.rules.rules) == 2

    hass.states.async_set("sensor.zmywarka", "finished")
    await hass.async_block_till_done()
    assert [t.summary for t in manager.open_tasks()] == ["Wypakuj zmywarkę"]
    hass.states.async_set("sensor.zmywarka", "unavailable")
    hass.states.async_set("sensor.zmywarka", "finished")
    await hass.async_block_till_done()
    assert len(manager.open_tasks()) == 1
    hass.states.async_set("sensor.zmywarka", "ready")
    await hass.async_block_till_done()
    assert manager.open_tasks() == []

    hass.states.async_set("binary_sensor.brama", "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert manager.open_tasks() == []
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [t.key for t in manager.open_tasks()] == [f"rule_{gate}"]
    hass.states.async_set("binary_sensor.brama", "off")
    await hass.async_block_till_done()
    assert manager.open_tasks() == []

    # edycja (reconfigure) zmienia treść
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"), context={"source": "reconfigure", "subentry_id": gate}
    )
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Brama!", "entity_id": "binary_sensor.brama", "mode": "state"}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "on", "for_minutes": 1})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"remind": False, "auto_close": True})
    assert flow["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    rule = entry.runtime_data.rules.rules[gate]
    assert rule.summary == "Brama!" and rule.interval == 0 and rule.for_minutes == 1

    # usunięcie
    hass.config_entries.async_remove_subentry(entry, gate)
    await hass.async_block_till_done()
    assert list(entry.runtime_data.rules.rules) != [gate] and len(entry.runtime_data.rules.rules) == 1


async def test_calendar_rule(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-12 17:59:50+01:00")
    entry, calls = await _setup(hass)

    async def get_events(call):
        assert call.data["start_date_time"].startswith("2026-11-13T00:00")
        return {"calendar.smieci": {"events": [{"summary": "Odpady biodegradowalne"}, {"summary": "Papier i tektura"}]}}

    hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
    hass.states.async_set("calendar.smieci", "off")
    await _add_rule(hass, entry, {"summary": "Wystaw śmietnik", "entity_id": "calendar.smieci", "days_before": 1, "at_time": "18:00:00"})
    manager = entry.runtime_data
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [t.summary for t in manager.open_tasks()] == ["Wystaw śmietnik: Odpady biodegradowalne, Papier i tektura"]
    freezer.move_to("2026-11-14 00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert manager.open_tasks() == []


async def test_legacy_rules_migrated(hass: HomeAssistant, hass_storage) -> None:
    hass_storage["zadania"] = {"version": 1, "key": "zadania", "data": {"tasks": [], "history": [], "rules": [
        {"id": "abc", "summary": "Stara reguła", "entity_id": "binary_sensor.x", "mode": "state", "value": "on"}]}}
    entry, calls = await _setup(hass)
    subs = list(entry.subentries.values())
    assert [s.title for s in subs] == ["Stara reguła"]
    assert len(entry.runtime_data.rules.rules) == 1


async def test_ws_survives_reload(hass: HomeAssistant, hass_ws_client) -> None:
    entry, calls = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "zadania/subscribe"})
    assert (await asyncio.wait_for(client.receive_json(), 2))["success"]
    assert (await asyncio.wait_for(client.receive_json(), 2))["event"]["tasks"] == []
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.wait_for(client.receive_json(), 2)  # odświeżenie po przeładowaniu
    res = await hass.services.async_call(DOMAIN, "add", {"summary": "Po reloadzie", "start": None}, blocking=True, return_response=True)
    msg = await asyncio.wait_for(client.receive_json(), 2)
    assert [t["summary"] for t in msg["event"]["tasks"]] == ["Po reloadzie"]
    await hass.services.async_call(DOMAIN, "dismiss", {"uid": res["uid"]}, blocking=True)
    msg = await asyncio.wait_for(client.receive_json(), 2)
    assert msg["event"]["tasks"] == []


async def test_reminder_limits(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, calls = await _setup(hass)
    res = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Max 2", "interval": 5, "max_reminders": 2, "speakers": []},
        blocking=True, return_response=True,
    )
    res2 = await hass.services.async_call(
        DOMAIN, "add", {"summary": "Do 15:12", "interval": 5, "remind_until": "2026-11-09T15:12:00", "speakers": []},
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
