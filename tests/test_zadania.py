from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
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
