"""Remindo: tasks that keep reminding you, for Home Assistant."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import homeassistant.helpers.config_validation as cv
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
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_DESCRIPTION,
    ATTR_DONE_MESSAGE,
    ATTR_INTERVAL,
    ATTR_KEEP_DONE,
    ATTR_KEY,
    ATTR_MAX_REMINDERS,
    ATTR_MINUTES,
    ATTR_NOTIFY_DATA,
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
    CONF_DEFAULT_INTERVAL,
    CONF_DEFAULT_TIME,
    CONF_KEEP_DONE,
    DOMAIN,
    REPEAT_NONE,
    REPEAT_OPTIONS,
    SIGNAL_UPDATED,
)
from .manager import RemindoError, Task, TaskManager

PLATFORMS = [Platform.TODO, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RemindoConfigEntry = ConfigEntry[TaskManager]


def _when(value: Any) -> Any:
    """A bare date stays a date (→ default time) instead of becoming midnight."""
    if isinstance(value, str) and len(value.strip()) == 10:
        try:
            return cv.date(value.strip())
        except vol.Invalid:
            pass
    return vol.Any(cv.datetime, cv.date, cv.string)(value)


_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=0, max=10080))
_MAX_REMINDERS = vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)))
_PHONES = vol.Any(None, cv.ensure_list_csv)
_SPEAKERS = vol.Any(None, cv.entity_ids)

ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_START, default="now"): vol.Any(None, _when),
        vol.Optional(ATTR_INTERVAL): _INTERVAL,
        vol.Optional(ATTR_KEY): cv.string,
        vol.Optional(ATTR_REPEAT, default=REPEAT_NONE): vol.In(REPEAT_OPTIONS),
        vol.Optional(ATTR_REPEAT_EVERY, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        vol.Optional(ATTR_TTS): cv.boolean,
        vol.Optional(ATTR_TTS_MESSAGE): cv.string,
        vol.Optional(ATTR_PUSH, default=True): cv.boolean,
        vol.Optional(ATTR_PHONES): _PHONES,
        vol.Optional(ATTR_SPEAKERS): _SPEAKERS,
        vol.Optional(ATTR_MAX_REMINDERS): _MAX_REMINDERS,
        vol.Optional(ATTR_REMIND_UNTIL): vol.Any(None, _when),
        vol.Optional(ATTR_KEEP_DONE): cv.boolean,
        vol.Optional(ATTR_DONE_MESSAGE): cv.string,
        vol.Optional(ATTR_NOTIFY_DATA): vol.Any(None, dict),
    }
)
TARGET = {vol.Optional(ATTR_UID): cv.string, vol.Optional(ATTR_KEY): cv.string}
_HAS_TARGET = cv.has_at_least_one_key(ATTR_UID, ATTR_KEY)
TARGET_SCHEMA = vol.All(vol.Schema(TARGET), _HAS_TARGET)
SNOOZE_SCHEMA = vol.All(
    vol.Schema(
        {
            **TARGET,
            vol.Optional(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=100000)),
            vol.Optional(ATTR_UNTIL): _when,
        }
    ),
    _HAS_TARGET,
)
# Fields a task can be changed in. A field that is sent is applied; null clears it.
UPDATE_FIELDS = {
    vol.Optional(ATTR_SUMMARY): cv.string,
    vol.Optional(ATTR_DESCRIPTION): vol.Any(None, cv.string),
    vol.Optional(ATTR_START): vol.Any(None, _when),
    vol.Optional(ATTR_INTERVAL): _INTERVAL,
    vol.Optional(ATTR_PHONES): _PHONES,
    vol.Optional(ATTR_SPEAKERS): _SPEAKERS,
    vol.Optional(ATTR_MAX_REMINDERS): _MAX_REMINDERS,
    vol.Optional(ATTR_REMIND_UNTIL): vol.Any(None, _when),
    vol.Optional(ATTR_KEEP_DONE): vol.Any(None, cv.boolean),
    vol.Optional(ATTR_NOTIFY_DATA): vol.Any(None, dict),
}
UPDATE_SCHEMA = vol.All(vol.Schema({**TARGET, **UPDATE_FIELDS}), _HAS_TARGET)
CLOSE_SCHEMA = vol.Schema({vol.Required(ATTR_KEY): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Lovelace card, the services and the card's data stream."""
    integration = await async_get_integration(hass, DOMAIN)
    path = Path(__file__).parent / "frontend" / "remindo-card.js"
    # The URL carries a hash of the file, so browsers never keep an old card
    digest = await hass.async_add_executor_job(lambda: hashlib.sha1(path.read_bytes()).hexdigest()[:8])
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}-{digest}")
    websocket_api.async_register_command(hass, ws_subscribe)
    _register_services(hass)
    return True


def _manager(hass: HomeAssistant) -> TaskManager:
    if (manager := hass.data.get(DOMAIN)) is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return manager


def _target(manager: TaskManager, data: dict[str, Any]) -> Task:
    task = manager.find(uid=data.get(ATTR_UID), key=data.get(ATTR_KEY))
    if task is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="task_not_found",
            translation_placeholders={"uid": str(data.get(ATTR_UID)), "key": str(data.get(ATTR_KEY))},
        )
    return task


async def async_setup_entry(hass: HomeAssistant, entry: RemindoConfigEntry) -> bool:
    manager = TaskManager(hass, dict(entry.options or entry.data))
    await manager.async_load()
    entry.runtime_data = manager
    hass.data[DOMAIN] = manager
    manager.rules.load(
        [{**sub.data, "id": sub.subentry_id} for sub in entry.subentries.values() if sub.subentry_type == "rule"]
    )
    entry.async_on_unload(
        hass.bus.async_listen("mobile_app_notification_action", manager.async_handle_phone_action)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # cards that were open before a reload get fresh data
    async_dispatcher_send(hass, SIGNAL_UPDATED)
    return True


async def _async_reload(hass: HomeAssistant, entry: RemindoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RemindoConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.pop(DOMAIN, None)
        await entry.runtime_data.async_unload()
    return ok


async def _may_use_templates(hass: HomeAssistant, call: ServiceCall) -> bool:
    """Templates run for automations and administrators, not for other users' text."""
    if call.context.user_id is None:
        return True
    user = await hass.auth.async_get_user(call.context.user_id)
    return user is not None and user.is_admin


def _translated[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn manager errors into translated service errors."""

    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except RemindoError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=err.key, translation_placeholders=err.placeholders
            ) from err
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    return wrapper


@callback
def _register_services(hass: HomeAssistant) -> None:
    @_translated
    async def add(call: ServiceCall) -> ServiceResponse:
        data = call.data
        task = await _manager(hass).async_add(
            data[ATTR_SUMMARY],
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
            keep_done=data.get(ATTR_KEEP_DONE),
            done_message=data.get(ATTR_DONE_MESSAGE),
            notify_data=data.get(ATTR_NOTIFY_DATA),
            templates=await _may_use_templates(hass, call),
            source="service",
            context=call.context,
        )
        return {"uid": task.uid}

    @_translated
    async def update(call: ServiceCall) -> None:
        manager = _manager(hass)
        changes = {k: v for k, v in call.data.items() if k not in (ATTR_UID, ATTR_KEY)}
        await manager.async_update(_target(manager, call.data), changes)

    async def done(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_done(_target(manager, call.data), "service", call.context)

    async def dismiss(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_dismiss(_target(manager, call.data), "service", call.context)

    @_translated
    async def snooze(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_snooze(
            _target(manager, call.data),
            minutes=call.data.get(ATTR_MINUTES),
            until=call.data.get(ATTR_UNTIL),
            source="service",
            context=call.context,
        )

    async def delete(call: ServiceCall) -> None:
        manager = _manager(hass)
        await manager.async_delete(_target(manager, call.data))

    async def close_by_key(call: ServiceCall) -> None:
        manager = _manager(hass)
        if task := manager.find(key=call.data[ATTR_KEY]):
            await manager.async_done(task, "auto", call.context)

    hass.services.async_register(DOMAIN, "add", add, ADD_SCHEMA, SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "update", update, UPDATE_SCHEMA)
    hass.services.async_register(DOMAIN, "done", done, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, "dismiss", dismiss, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, "snooze", snooze, SNOOZE_SCHEMA)
    hass.services.async_register(DOMAIN, "delete", delete, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, "close_by_key", close_by_key, CLOSE_SCHEMA)


@websocket_api.websocket_command({vol.Required("type"): "remindo/subscribe"})
@websocket_api.async_response
async def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream of tasks for the card (the full list after every change).

    It listens to a signal, not to one manager, so it survives a reload of the
    integration (e.g. after the settings change).
    """

    def payload() -> dict[str, Any]:
        manager = _manager(hass)
        return {
            "tasks": [manager.serialize(t) for t in manager.tasks.values()],
            "dismissed": [h for h in manager.history if h.get("result") == "dismissed"][-20:],
            "options": {
                "default_interval": manager.options.get(CONF_DEFAULT_INTERVAL),
                "default_time": manager.options.get(CONF_DEFAULT_TIME),
                "keep_done": manager.options.get(CONF_KEEP_DONE, True),
                "phones": [{"id": p, "name": manager.phone_label(p)} for p in manager.all_phones()],
                "speakers": [{"id": s, "name": manager.speaker_label(s)} for s in manager.all_speakers()],
            },
        }

    @callback
    def forward() -> None:
        try:
            data = payload()
        except ServiceValidationError:
            return  # the integration is being reloaded
        connection.send_message(websocket_api.event_message(msg["id"], data))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, forward)
    connection.send_result(msg["id"])
    forward()
