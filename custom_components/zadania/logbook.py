"""Opisy zdarzeń zadań w dzienniku."""

from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_CREATED,
    EVENT_DISMISSED,
    EVENT_DONE,
    EVENT_REMINDED,
    EVENT_SNOOZED,
)

_TEXT = {
    EVENT_CREATED: "dodano",
    EVENT_REMINDED: "przypomniano",
    EVENT_DONE: "zrobione",
    EVENT_SNOOZED: "odłożono",
    EVENT_DISMISSED: "nie robię",
}
_SOURCE = {"phone": "z telefonu", "card": "z karty", "todo": "z listy To-do", "auto": "automatycznie", "rule": "z reguły"}


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:
    @callback
    def describe(event: Event) -> dict[str, str]:
        data = event.data
        text = _TEXT.get(event.event_type, event.event_type)
        if src := _SOURCE.get(data.get("source", "")):
            text += f" ({src})"
        if event.event_type == EVENT_REMINDED and data.get("count", 1) > 1:
            text += f", {data['count']}. raz"
        return {LOGBOOK_ENTRY_NAME: f"Zadanie: {data.get('summary')}", LOGBOOK_ENTRY_MESSAGE: text}

    for event_type in _TEXT:
        async_describe_event(DOMAIN, event_type, describe)
