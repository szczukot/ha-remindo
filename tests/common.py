"""Shared helpers for the tests."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.remindo.const import DOMAIN

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


async def setup_integration(hass: HomeAssistant, **options):
    """Set up Remindo with mocked notify / tts / switch services. Returns (entry, calls)."""
    await hass.config.async_set_time_zone("Europe/Warsaw")
    calls = {
        "notify": async_mock_service(hass, "notify", "mobile_app_test"),
        "tts": async_mock_service(hass, "tts", "speak"),
        "switch": async_mock_service(hass, "switch", "turn_on"),
        "pn_create": async_mock_service(hass, "persistent_notification", "create"),
        "pn_dismiss": async_mock_service(hass, "persistent_notification", "dismiss"),
    }
    hass.states.async_set("group.people_in_home", "home")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={**OPTS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta) -> None:
    """Let time pass and run everything that became due."""
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_task(hass: HomeAssistant, **data) -> str:
    """Add a task with the remindo.add action; returns its uid."""
    result = await hass.services.async_call(DOMAIN, "add", data, blocking=True, return_response=True)
    return result["uid"]


async def add_rule(hass: HomeAssistant, entry, data: dict) -> str:
    """Add a rule through the real form (subentry flow), like a user in the UI. Returns its id."""
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
