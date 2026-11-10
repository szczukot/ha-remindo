"""Zadania z przypomnieniami dla Home Assistant."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_DESCRIPTION,
    ATTR_INTERVAL,
    ATTR_KEY,
    ATTR_MAX_REMINDERS,
    ATTR_MINUTES,
    ATTR_PHONES,
    ATTR_PUSH,
    ATTR_REMIND_UNTIL,
    ATTR_REPEAT,
    ATTR_REPEAT_EVERY,
    ATTR_SPEAKERS,
    ATTR_START,
    ATTR_SUMMARY,
    ATTR_TTS,
    ATTR_TTS_MESSAGE,
    ATTR_UID,
    ATTR_UNTIL,
    CARD_URL,
    DOMAIN,
    SIGNAL_UPDATED,
    REPEAT_NONE,
    REPEAT_OPTIONS,
)
from .manager import Task, TaskManager

PLATFORMS = [Platform.TODO, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ZadaniaConfigEntry = ConfigEntry[TaskManager]

_WHEN = vol.Any(cv.datetime, cv.date, cv.string)

ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_START, default="now"): vol.Any(None, _WHEN),
        vol.Optional(ATTR_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=0, max=10080)),
        vol.Optional(ATTR_KEY): cv.string,
        vol.Optional(ATTR_REPEAT, default=REPEAT_NONE): vol.In(REPEAT_OPTIONS),
        vol.Optional(ATTR_REPEAT_EVERY, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        vol.Optional(ATTR_TTS): cv.boolean,
        vol.Optional(ATTR_TTS_MESSAGE): cv.string,
        vol.Optional(ATTR_PUSH, default=True): cv.boolean,
        vol.Optional(ATTR_PHONES): vol.Any(None, cv.ensure_list_csv),
        vol.Optional(ATTR_SPEAKERS): vol.Any(None, cv.entity_ids),
        vol.Optional(ATTR_MAX_REMINDERS): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=1000))),
        vol.Optional(ATTR_REMIND_UNTIL): vol.Any(None, _WHEN),
    }
)
TARGET = {vol.Optional(ATTR_UID): cv.string, vol.Optional(ATTR_KEY): cv.string}
TARGET_SCHEMA = vol.All(vol.Schema(TARGET), cv.has_at_least_one_key(ATTR_UID, ATTR_KEY))
SNOOZE_SCHEMA = vol.All(
    vol.Schema(
        {
            **TARGET,
            vol.Optional(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=100000)),
            vol.Optional(ATTR_UNTIL): _WHEN,
        }
    ),
    cv.has_at_least_one_key(ATTR_UID, ATTR_KEY),
)
CLOSE_SCHEMA = vol.Schema({vol.Required(ATTR_KEY): cv.string})
RULE_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("mode", default="state"): vol.In(["state", "above", "below", "calendar"]),
        vol.Optional("value", default=""): vol.Coerce(str),
        vol.Optional("days_before", default=1): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
        vol.Optional("at_time", default="18:00"): cv.string,
        vol.Optional("contains"): vol.Any(None, cv.string),
        vol.Optional("for_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=10080)),
        vol.Optional("auto_close", default=True): cv.boolean,
        vol.Optional("enabled", default=True): cv.boolean,
        vol.Optional(ATTR_DESCRIPTION): vol.Any(None, cv.string),
        vol.Optional(ATTR_INTERVAL): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=10080))),
        vol.Optional(ATTR_PHONES): vol.Any(None, cv.ensure_list_csv),
        vol.Optional(ATTR_SPEAKERS): vol.Any(None, cv.entity_ids),
        vol.Optional(ATTR_TTS_MESSAGE): vol.Any(None, cv.string),
        vol.Optional(ATTR_MAX_REMINDERS): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=1000))),
    }
)
RULE_DELETE_SCHEMA = vol.Schema({vol.Required("id"): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Rejestruje kartę Lovelace (raz na uruchomienie HA)."""
    integration = await async_get_integration(hass, DOMAIN)
    path = Path(__file__).parent / "frontend" / "zadania-card.js"
    # Wersja w adresie = skrót zawartości pliku, żeby przeglądarki nie trzymały starej karty
    digest = await hass.async_add_executor_job(lambda: hashlib.sha1(path.read_bytes()).hexdigest()[:8])
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}-{digest}")
    websocket_api.async_register_command(hass, ws_subscribe)
    return True


def _manager(hass: HomeAssistant) -> TaskManager:
    if (manager := hass.data.get(DOMAIN)) is not None:
        return manager
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Integracja Zadania nie jest załadowana")
    return entries[0].runtime_data


def _target(manager: TaskManager, data: dict[str, Any]) -> Task:
    task = manager.find(uid=data.get(ATTR_UID), key=data.get(ATTR_KEY))
    if task is None:
        raise ServiceValidationError(
            f"Nie znaleziono otwartego zadania (uid={data.get(ATTR_UID)}, klucz={data.get(ATTR_KEY)})"
        )
    return task


async def async_setup_entry(hass: HomeAssistant, entry: ZadaniaConfigEntry) -> bool:
    manager = TaskManager(hass, dict(entry.options or entry.data))
    await manager.async_load()
    entry.runtime_data = manager
    hass.data[DOMAIN] = manager

    entry.async_on_unload(
        hass.bus.async_listen("mobile_app_notification_action", manager.async_handle_phone_action)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # karty otwarte przed przeładowaniem dostaną świeże dane
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    return True


async def _async_reload(hass: HomeAssistant, entry: ZadaniaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZadaniaConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.pop(DOMAIN, None)
        await entry.runtime_data.async_unload()
    return ok


@callback
def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "add"):
        return

    async def add(call: ServiceCall) -> ServiceResponse:
        data = dict(call.data)
        try:
            task = await _manager(hass).async_add(
                data.pop(ATTR_SUMMARY),
                description=data.get(ATTR_DESCRIPTION),
                start=data.get(ATTR_START),
                interval=data.get(ATTR_INTERVAL),
                key=data.get(ATTR_KEY),
                repeat=data.get(ATTR_REPEAT, REPEAT_NONE),
                repeat_every=data.get(ATTR_REPEAT_EVERY, 1),
                tts=data.get(ATTR_TTS),
                push=data.get(ATTR_PUSH, True),
                tts_message=data.get(ATTR_TTS_MESSAGE),
                phones=data.get(ATTR_PHONES),
                speakers=data.get(ATTR_SPEAKERS),
                max_reminders=data.get(ATTR_MAX_REMINDERS),
                remind_until=data.get(ATTR_REMIND_UNTIL),
                source="service",
                context=call.context,
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"uid": task.uid}

    async def done(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_done(_target(manager, call.data), "service", call.context)

    async def dismiss(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_dismiss(_target(manager, call.data), "service", call.context)

    async def snooze(call: ServiceCall) -> None:
        manager = _manager(hass)
        try:
            await manager.async_snooze(
                _target(manager, call.data),
                minutes=call.data.get(ATTR_MINUTES),
                until=call.data.get(ATTR_UNTIL),
                source="service",
                context=call.context,
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def close_by_key(call: ServiceCall) -> None:
        manager = _manager(hass)
        if task := manager.find(key=call.data[ATTR_KEY]):
            await manager.async_done(task, "auto", call.context)

    hass.services.async_register(DOMAIN, "add", add, ADD_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "done", done, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, "dismiss", dismiss, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, "snooze", snooze, SNOOZE_SCHEMA)
    hass.services.async_register(DOMAIN, "close_by_key", close_by_key, CLOSE_SCHEMA)

    async def rule_save(call: ServiceCall) -> ServiceResponse:
        try:
            return await _manager(hass).async_rule_save(dict(call.data))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def rule_delete(call: ServiceCall) -> None:
        await _manager(hass).async_rule_delete(call.data["id"])

    hass.services.async_register(DOMAIN, "rule_save", rule_save, RULE_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "rule_delete", rule_delete, RULE_DELETE_SCHEMA)


@websocket_api.websocket_command({vol.Required("type"): "zadania/subscribe"})
@websocket_api.async_response
async def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Strumień zadań dla karty (pełna lista po każdej zmianie).

    Słucha sygnału, a nie konkretnego menedżera, więc przeżywa przeładowanie
    integracji (np. po zmianie ustawień).
    """

    def payload() -> dict[str, Any]:
        manager = _manager(hass)
        return {
            "tasks": [manager.serialize(t) for t in manager.tasks.values()],
            "rules": manager.rules.dump(),
            "dismissed": [h for h in manager.history if h.get("result") == "dismissed"][-20:],
            "options": {
                "phone_snooze": manager.options.get("phone_snooze"),
                "default_interval": manager.options.get("default_interval"),
                "phones": [{"id": p, "name": manager.phone_label(p)} for p in manager.all_phones()],
                "speakers": [{"id": s, "name": manager.speaker_label(s)} for s in manager.all_speakers()],
            },
        }

    @callback
    def forward() -> None:
        try:
            data = payload()
        except ServiceValidationError:
            return  # integracja w trakcie przeładowania
        connection.send_message(websocket_api.event_message(msg["id"], data))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, forward)
    connection.send_result(msg["id"])
    forward()
