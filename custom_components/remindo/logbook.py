"""Logbook descriptions of task events."""

from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from . import texts
from .const import (
    DOMAIN,
    EVENT_CREATED,
    EVENT_DISMISSED,
    EVENT_DONE,
    EVENT_REMINDED,
    EVENT_SNOOZED,
)

_KEYS = {
    EVENT_CREATED: "ev_created",
    EVENT_REMINDED: "ev_reminded",
    EVENT_DONE: "ev_done",
    EVENT_SNOOZED: "ev_snoozed",
    EVENT_DISMISSED: "ev_dismissed",
}
_SOURCES = ("phone", "card", "todo", "auto", "rule", "expired", "rule_removed")


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:
    @callback
    def describe(event: Event) -> dict[str, str]:
        data = event.data
        message = texts.text(hass, _KEYS[event.event_type])
        if (src := data.get("source")) in _SOURCES:
            message += f" ({texts.text(hass, f'src_{src}')})"
        if event.event_type == EVENT_REMINDED and data.get("count", 1) > 1:
            message += texts.text(hass, "nth", count=data["count"])
        return {
            LOGBOOK_ENTRY_NAME: texts.text(hass, "task", summary=data.get("summary")),
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    for event_type in _KEYS:
        async_describe_event(DOMAIN, event_type, describe)
