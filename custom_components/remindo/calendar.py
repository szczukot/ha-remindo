"""Read-only calendar with the tasks' due times (recurring tasks on every date)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .manager import Task, TaskManager, _dt, next_occurrence

# an event needs an end: a task without "stop reminding at" is shown this long
DEFAULT_LENGTH = timedelta(hours=1)
# a recurring task is expanded at most this many times per request (a year of daily dates)
MAX_OCCURRENCES = 400


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RemindoCalendar(entry.runtime_data, entry)])


def _length(task: Task, start: datetime) -> timedelta:
    until = _dt(task.remind_until)
    return until - start if until and until > start else DEFAULT_LENGTH


def _event(task: Task, start: datetime) -> CalendarEvent:
    return CalendarEvent(
        start=start,
        end=start + _length(task, start),
        summary=task.summary,
        description=task.description,
        uid=task.uid,
    )


def task_events(task: Task, start: datetime, end: datetime) -> list[CalendarEvent]:
    """The task's dates that overlap [start, end)."""
    due = _dt(task.start)
    if due is None:
        return []
    length = _length(task, due)
    if not task.recurring or task.repeat == "hourly":
        # every N hours would fill the calendar: only the current date is shown
        return [_event(task, due)] if due < end and due + length > start else []
    events: list[CalendarEvent] = []
    current = due
    while current < end and len(events) < MAX_OCCURRENCES:
        if current + length > start:
            events.append(_event(task, current))
        current = next_occurrence(due, task.repeat, task.repeat_every, current)
    return events


class RemindoCalendar(CalendarEntity):
    """The open tasks that have a due time."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-check-outline"

    def __init__(self, manager: TaskManager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_name = "Remindo"
        self.entity_id = "calendar.remindo"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def event(self) -> CalendarEvent | None:
        """The task going on now, or the next one."""
        now = dt_util.now()
        upcoming = [
            ev
            for task in self._manager.open_tasks()
            for ev in task_events(task, now, now + timedelta(days=400))[:1]
        ]
        return min(upcoming, key=lambda ev: ev.start_datetime_local, default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events = [
            ev for task in self._manager.open_tasks() for ev in task_events(task, start_date, end_date)
        ]
        return sorted(events, key=lambda ev: ev.start_datetime_local)
