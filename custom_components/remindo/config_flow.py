"""Config flow: integration options and rules (subentries)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_CLICK_URL,
    CONF_DEFAULT_INTERVAL,
    CONF_DEFAULT_TIME,
    CONF_KEEP_DONE,
    CONF_MEDIA_PLAYER,
    CONF_NOTIFY,
    CONF_NOTIFY_DATA,
    CONF_PERSISTENT,
    CONF_PHONE_SNOOZE,
    CONF_PRESENCE,
    CONF_QUIET_END,
    CONF_QUIET_PUSH,
    CONF_QUIET_START,
    CONF_SCREEN_SWITCH,
    CONF_TTS_DEFAULT,
    CONF_TTS_ENTITY,
    DEFAULTS,
    DOMAIN,
)
from .rules import MODES, rule_problem

# shown literally in the form help texts
_TOKENS = {"state": "{state}", "name": "{name}", "event": "{event}"}

_NOT_TARGETS = {"send_message", "persistent_notification", "notify"}


def _notify_services(hass: HomeAssistant) -> list[str]:
    """The HA app (with buttons) first, then other channels: Telegram, e-mail, SMS, notify.* entities."""
    services = hass.services.async_services().get("notify", {})
    mobile = sorted(f"notify.{name}" for name in services if name.startswith("mobile_app_"))
    other = sorted(
        {f"notify.{name}" for name in services if not name.startswith("mobile_app_") and name not in _NOT_TARGETS}
        | set(hass.states.async_entity_ids("notify"))
    )
    return mobile + other


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
            vol.Optional(CONF_QUIET_PUSH, default=values[CONF_QUIET_PUSH]): selector.BooleanSelector(),
            vol.Optional(CONF_CLICK_URL, default=values[CONF_CLICK_URL]): selector.TextSelector(),
            vol.Optional(CONF_KEEP_DONE, default=values[CONF_KEEP_DONE]): selector.BooleanSelector(),
            opt(CONF_NOTIFY_DATA): selector.ObjectSelector(),
        }
    )


def _bad_mapping(data: dict[str, Any], key: str) -> dict[str, str]:
    """Extra notification data must be key: value pairs."""
    value = data.get(key)
    return {key: "not_mapping"} if value and not isinstance(value, dict) else {}


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    if isinstance(data.get(CONF_MEDIA_PLAYER), str):
        data[CONF_MEDIA_PLAYER] = [data[CONF_MEDIA_PLAYER]]
    for key in (CONF_DEFAULT_INTERVAL, CONF_PHONE_SNOOZE):
        if key in data:
            data[key] = int(data[key])
    return data


class RemindoConfigFlow(ConfigFlow, domain=DOMAIN):
    """First set-up."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (errors := _bad_mapping(user_input, CONF_NOTIFY_DATA)):
                return self.async_create_entry(title="Remindo", data={}, options=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(self.hass, user_input or {}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RemindoOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Rules are added on the integration page: "＋ Add rule"."""
        return {RULE: RuleSubentryFlow}


class RemindoOptionsFlow(OptionsFlow):
    """Change the settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (errors := _bad_mapping(user_input, CONF_NOTIFY_DATA)):
                return self.async_create_entry(data=_clean(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.hass, user_input or dict(self.config_entry.options)),
            errors=errors,
        )


# ----------------------------------------------------------------------- rules

RULE = "rule"


def _num(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    number = float(value)
    return int(number) if number.is_integer() else number


class RuleSubentryFlow(ConfigSubentryFlow):
    """A rule: when an entity meets a condition, add a task. Three steps."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # --- adding
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_trigger(user_input)

    # --- editing
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_trigger(user_input)

    def _suggest(self, schema: dict) -> vol.Schema:
        # a stored None means "not set": let the field's default show instead
        known = {k: v for k, v in self._data.items() if v is not None}
        return self.add_suggested_values_to_schema(vol.Schema(schema), known)

    async def async_step_trigger(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input["entity_id"]
            if entity_id.startswith("calendar."):
                user_input["mode"] = "calendar"
            elif user_input["mode"] == "calendar" and str(self._data.get("entity_id", "")).startswith("calendar."):
                # the rule was for a calendar and now watches something else
                user_input["mode"] = "state"
            exists = self.hass.states.get(entity_id) is not None or er.async_get(self.hass).async_get(entity_id) is not None
            if problem := rule_problem(user_input["mode"], entity_id, self.hass.states.get(entity_id), exists):
                errors["entity_id" if problem == "rule_entity_missing" else "mode"] = problem
            self._data.update(user_input)
            if not errors:
                return await self.async_step_condition()
        schema = {
            vol.Required("summary"): selector.TextSelector(),
            vol.Required("entity_id"): selector.EntitySelector(),
            vol.Required("mode", default=self._data.get("mode", "state")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=MODES, translation_key="rule_mode",
                                              mode=selector.SelectSelectorMode.LIST)
            ),
        }
        editing = self.source == "reconfigure"
        return self.async_show_form(
            step_id="trigger_edit" if editing else "trigger",
            data_schema=self._suggest(schema),
            errors=errors,
            description_placeholders={**_TOKENS, "rule": self._get_reconfigure_subentry().title if editing else ""},
        )

    async def async_step_trigger_edit(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_trigger(user_input)

    async def async_step_condition(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        mode = self._data["mode"]
        if user_input is not None:
            if mode in ("above", "below"):
                user_input["value"] = str(_num(user_input["value"]))
            for key in ("for_minutes", "days_before"):
                if key in user_input:
                    user_input[key] = int(user_input[key])
            if mode == "calendar":
                user_input.setdefault("contains", None)
                user_input["value"] = ""
                user_input["at_time"] = str(user_input["at_time"])[:5]
            self._data.update(user_input)
            return await self.async_step_notify()
        entity = self._data["entity_id"]
        minutes = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=10080, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
        )
        if mode == "state":
            schema = {
                vol.Required("value"): selector.StateSelector(selector.StateSelectorConfig(entity_id=entity)),
                vol.Required("for_minutes", default=self._data.get("for_minutes", 0)): minutes,
            }
        elif mode in ("above", "below"):
            schema = {
                vol.Required("value"): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, step="any")
                ),
                vol.Required("for_minutes", default=self._data.get("for_minutes", 0)): minutes,
            }
        else:
            schema = {
                vol.Required("days_before", default=self._data.get("days_before", 1)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=30, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required("at_time", default=self._data.get("at_time", "18:00")): selector.TimeSelector(),
                vol.Optional("contains"): selector.TextSelector(),
            }
        state = self.hass.states.get(entity)
        return self.async_show_form(
            step_id=f"condition_{'state' if mode == 'state' else 'number' if mode != 'calendar' else 'calendar'}",
            data_schema=self._suggest(schema),
            description_placeholders={
                "entity": state.name if state else entity,
                "current": state.state if state else "?",
            },
        )

    async def async_step_condition_state(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_condition(user_input)

    async def async_step_condition_number(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_condition(user_input)

    async def async_step_condition_calendar(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_condition(user_input)

    async def async_step_notify(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        options = {**DEFAULTS, **self._get_entry().options}
        phones = [p if p.startswith("notify.") else f"notify.{p}" for p in options.get(CONF_NOTIFY) or []]
        speakers = options.get(CONF_MEDIA_PLAYER) or []
        speakers = [speakers] if isinstance(speakers, str) else list(speakers)
        errors: dict[str, str] = {}
        if user_input is not None and (errors := _bad_mapping(user_input, "notify_data")):
            self._data.update(user_input)
            user_input = None
        if user_input is not None:
            data = {**self._data, **user_input}
            data["interval"] = int(data.get("interval") or 0) if data.get("remind", True) else 0
            data["max_reminders"] = int(data["max_reminders"]) if data.get("max_reminders") else None
            data.pop("remind", None)
            # a field left empty is not sent at all: clear it instead of keeping the old value
            # the spelling of an existing list is reused ("aquarium" → "Aquarium")
            manager = getattr(self._get_entry(), "runtime_data", None)
            data["list"] = manager.norm_list(data.get("list")) if manager else str(data.get("list") or "").strip() or None
            for key in ("max_reminders", "done_message", "tts_message", "notify_data", "list"):
                if key not in user_input:
                    data[key] = None
            # no channel configured yet → None = "all configured" once there are some
            data["phones"] = user_input.get("phones", []) if phones else None
            data["speakers"] = user_input.get("speakers", []) if speakers else None
            title = data["summary"]
            if self.source == "reconfigure":
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), data=data, title=title
                )
            return self.async_create_entry(title=title, data=data)

        def labels(values: list[str], domain: str) -> list[selector.SelectOptionDict]:
            out = []
            for value in values:
                state = self.hass.states.get(value)
                name = state.name if state else value.split(".", 1)[-1].removeprefix("mobile_app_").replace("_", " ")
                out.append(selector.SelectOptionDict(value=value, label=name))
            return out

        interval = self._data.get("interval", options[CONF_DEFAULT_INTERVAL])
        schema: dict = {
            vol.Required("remind", default=interval != 0): selector.BooleanSelector(),
            vol.Optional("interval", default=interval or options[CONF_DEFAULT_INTERVAL]): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=10080, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional("max_reminders"): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=1000, mode=selector.NumberSelectorMode.BOX)
            ),
        }
        # None = "all configured" (the rule was made before any channel existed)
        chosen_phones = self._data.get("phones")
        chosen_speakers = self._data.get("speakers")
        if phones:
            schema[vol.Optional("phones", default=phones if chosen_phones is None else chosen_phones)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=labels(phones, "notify"), multiple=True)
            )
        if speakers:
            schema[vol.Optional("speakers", default=speakers if chosen_speakers is None else chosen_speakers)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=labels(speakers, "media_player"), multiple=True)
            )
            schema[vol.Optional("tts_message")] = selector.TextSelector()
        schema[vol.Required("auto_close", default=self._data.get("auto_close", True))] = selector.BooleanSelector()
        if self._data.get("mode") != "calendar":
            schema[vol.Optional("done_message")] = selector.TextSelector()
        schema[vol.Required("keep_done", default=self._data.get("keep_done", options[CONF_KEEP_DONE]))] = selector.BooleanSelector()
        manager = getattr(self._get_entry(), "runtime_data", None)
        schema[vol.Optional("list")] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=manager.lists() if manager else [], custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        if phones:
            schema[vol.Optional("notify_data")] = selector.ObjectSelector()
        return self.async_show_form(
            step_id="notify", data_schema=self._suggest(schema), errors=errors, description_placeholders=_TOKENS
        )

