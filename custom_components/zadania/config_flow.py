"""Konfiguracja z UI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLICK_URL,
    CONF_DEFAULT_INTERVAL,
    CONF_DEFAULT_TIME,
    CONF_MEDIA_PLAYER,
    CONF_NOTIFY,
    CONF_PERSISTENT,
    CONF_PHONE_SNOOZE,
    CONF_PRESENCE,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCREEN_SWITCH,
    CONF_TTS_DEFAULT,
    CONF_TTS_ENTITY,
    DEFAULTS,
    DOMAIN,
)


def _notify_services(hass: HomeAssistant) -> list[str]:
    services = hass.services.async_services().get("notify", {})
    return sorted(f"notify.{name}" for name in services if name.startswith("mobile_app_"))


def _schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    values = {**DEFAULTS, **current}
    if isinstance(values.get(CONF_MEDIA_PLAYER), str):
        values[CONF_MEDIA_PLAYER] = [values[CONF_MEDIA_PLAYER]]

    def opt(key: str) -> vol.Optional:
        if values.get(key) not in (None, ""):
            return vol.Optional(key, description={"suggested_value": values[key]})
        return vol.Optional(key)

    return vol.Schema(
        {
            vol.Optional(CONF_NOTIFY, default=values[CONF_NOTIFY]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_notify_services(hass), multiple=True, custom_value=True
                )
            ),
            vol.Optional(CONF_PERSISTENT, default=values[CONF_PERSISTENT]): selector.BooleanSelector(),
            opt(CONF_TTS_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="tts")),
            opt(CONF_MEDIA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            opt(CONF_SCREEN_SWITCH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            opt(CONF_PRESENCE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["group", "person", "zone", "binary_sensor", "input_boolean"])
            ),
            vol.Optional(CONF_TTS_DEFAULT, default=values[CONF_TTS_DEFAULT]): selector.BooleanSelector(),
            vol.Optional(CONF_QUIET_START, default=values[CONF_QUIET_START]): selector.TimeSelector(),
            vol.Optional(CONF_QUIET_END, default=values[CONF_QUIET_END]): selector.TimeSelector(),
            vol.Optional(CONF_DEFAULT_INTERVAL, default=values[CONF_DEFAULT_INTERVAL]): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1440, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_DEFAULT_TIME, default=values[CONF_DEFAULT_TIME]): selector.TimeSelector(),
            vol.Optional(CONF_PHONE_SNOOZE, default=values[CONF_PHONE_SNOOZE]): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=1440, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_CLICK_URL, default=values[CONF_CLICK_URL]): selector.TextSelector(),
        }
    )


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    if isinstance(data.get(CONF_MEDIA_PLAYER), str):
        data[CONF_MEDIA_PLAYER] = [data[CONF_MEDIA_PLAYER]]
    for key in (CONF_DEFAULT_INTERVAL, CONF_PHONE_SNOOZE):
        if key in data:
            data[key] = int(data[key])
    return data


class ZadaniaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pierwsza konfiguracja."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Zadania", data={}, options=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(self.hass, {}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ZadaniaOptionsFlow()


class ZadaniaOptionsFlow(OptionsFlow):
    """Zmiana ustawień."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean(user_input))
        return self.async_show_form(
            step_id="init", data_schema=_schema(self.hass, dict(self.config_entry.options))
        )
