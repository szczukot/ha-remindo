"""Rules: a task is added automatically when an entity meets a condition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .manager import TaskManager

_LOGGER = logging.getLogger(__name__)

MODE_STATE = "state"  # state equals a value
MODE_ABOVE = "above"  # number above a limit
MODE_BELOW = "below"  # number below a limit
MODE_CALENDAR = "calendar"  # calendar event in N days
MODES = [MODE_STATE, MODE_ABOVE, MODE_BELOW, MODE_CALENDAR]
_IGNORED = (STATE_UNAVAILABLE, STATE_UNKNOWN, None)

# After a restart entities need a moment before their state can be trusted.
STARTUP_DELAY = 60  # s
RECHECK_DELAY = 60  # s, entity still unavailable when a countdown ends
RECHECK_MAX = 5
CALENDAR_RETRY_DELAY = 120  # s, calendar could not be read
CALENDAR_RETRY_MAX = 3


def _tokens(text: str | None, entity_id: str) -> str | None:
    """Simple placeholders for people who do not write templates.

    {state} = current value with unit, {name} = the entity's name. They are turned
    into an HA template, so the value is refreshed at every reminder.
    """
    if not text or ("{state}" not in text and "{name}" not in text):
        return text
    e = entity_id.replace("'", "")
    state = (
        f"{{{{ states('{e}') }}}}"
        f"{{{{ ' ' ~ state_attr('{e}', 'unit_of_measurement') if state_attr('{e}', 'unit_of_measurement') else '' }}}}"
    )
    name = f"{{{{ state_attr('{e}', 'friendly_name') or '{e}' }}}}"
    return text.replace("{state}", state).replace("{name}", name)


@dataclass
class Rule:
    """When entity_id meets the condition for for_minutes, add a task."""

    id: str
    summary: str
    entity_id: str
    mode: str = MODE_STATE
    value: str = "on"
    for_minutes: int = 0
    auto_close: bool = True
    description: str | None = None
    interval: int | None = None
    phones: list[str] | None = None
    speakers: list[str] | None = None
    tts_message: str | None = None
    max_reminders: int | None = None
    keep_done: bool | None = None
    done_message: str | None = None
    notify_data: dict[str, Any] | None = None
    # calendar only
    days_before: int = 1
    at_time: str = "18:00"
    contains: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def key(self) -> str:
        return f"rule_{self.id}"

    def matches(self, state: State | None) -> bool | None:
        """True/False, or None when the state cannot be judged (unavailable)."""
        if self.mode == MODE_CALENDAR:
            return None
        if state is None or state.state in _IGNORED:
            return None
        if self.mode == MODE_STATE:
            return state.state == str(self.value)
        try:
            current, limit = float(state.state), float(self.value)
        except (TypeError, ValueError):
            return None
        return current > limit if self.mode == MODE_ABOVE else current < limit


class RuleEngine:
    """Listens to state changes and creates / closes tasks according to the rules."""

    def __init__(self, manager: TaskManager) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.rules: dict[str, Rule] = {}
        self._unsubs: dict[str, CALLBACK_TYPE] = {}
        self._timers: dict[str, CALLBACK_TYPE] = {}
        # last result that could be judged; survives a detour through "unavailable"
        self._last: dict[str, bool] = {}
        # persisted, so a restart or a settings change does not lose them:
        self._deadlines: dict[str, str] = {}  # rule id → end of the "for N minutes" countdown
        self._calendar_checked: dict[str, str] = {}  # rule id → date of the last calendar check

    # ------------------------------------------------------------- persistence
    def restore(self, state: dict[str, Any]) -> None:
        self._deadlines = dict(state.get("pending") or {})
        self._calendar_checked = dict(state.get("calendar_checked") or {})

    def state(self) -> dict[str, Any]:
        return {"pending": dict(self._deadlines), "calendar_checked": dict(self._calendar_checked)}

    def load(self, data: list[dict[str, Any]]) -> None:
        for raw in data:
            try:
                rule = Rule.from_dict(raw)
            except TypeError:
                _LOGGER.warning("Skipping invalid rule: %s", raw)
                continue
            if rule.mode in MODES:
                self.rules[rule.id] = rule
        # forget the state of rules that were removed
        self._deadlines = {k: v for k, v in self._deadlines.items() if k in self.rules}
        self._calendar_checked = {k: v for k, v in self._calendar_checked.items() if k in self.rules}
        for rule in self.rules.values():
            self._watch(rule)

    @callback
    def stop(self) -> None:
        """Stop listening. Countdowns stay in the store and resume on the next load."""
        for cancel in (*self._unsubs.values(), *self._timers.values()):
            cancel()
        self._unsubs.clear()
        self._timers.clear()

    # ---------------------------------------------------------------- tracking
    @callback
    def _watch(self, rule: Rule) -> None:
        if rule.mode == MODE_CALENDAR:
            self._watch_calendar(rule)
            return

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            self._evaluate(rule, event.data["new_state"], event.data["old_state"])

        self._unsubs[rule.id] = async_track_state_change_event(self.hass, [rule.entity_id], _changed)
        current = rule.matches(self.hass.states.get(rule.entity_id))
        if current is not None:
            self._last[rule.id] = current
        if deadline := self._deadlines.get(rule.id):
            # a countdown was running when Home Assistant stopped or the settings changed
            if current is False:
                self._drop_deadline(rule.id)
            else:
                earliest = dt_util.utcnow() + timedelta(seconds=STARTUP_DELAY)
                self._arm(rule, max(dt_util.parse_datetime(deadline) or earliest, earliest))

    @callback
    def _evaluate(self, rule: Rule, new: State | None, old: State | None) -> None:
        now_match = rule.matches(new)
        if now_match is None:
            # unavailable / unknown (restart, Wi-Fi drop): neither start nor end
            return
        was_match = self._last.get(rule.id, rule.matches(old))
        self._last[rule.id] = now_match
        if now_match:
            if was_match is False:
                self._start(rule)
            return
        self._cancel_countdown(rule.id)
        if was_match is not False and rule.auto_close:
            self.hass.async_create_task(self._close(rule))

    @callback
    def _start(self, rule: Rule) -> None:
        if rule.id in self._timers:
            return
        if rule.for_minutes <= 0:
            self.hass.async_create_task(self._fire(rule))
            return
        deadline = dt_util.utcnow() + timedelta(minutes=rule.for_minutes)
        self._deadlines[rule.id] = deadline.isoformat()
        self.manager.async_schedule_save()
        self._arm(rule, deadline)

    @callback
    def _arm(self, rule: Rule, when: datetime, attempt: int = 0) -> None:
        """At `when`, add the task if the condition still holds."""

        @callback
        def _due(_now: datetime) -> None:
            self._timers.pop(rule.id, None)
            match = rule.matches(self.hass.states.get(rule.entity_id))
            if match is None and attempt < RECHECK_MAX:
                # cannot tell yet (entity still starting up): look again shortly
                self._arm(rule, dt_util.utcnow() + timedelta(seconds=RECHECK_DELAY), attempt + 1)
                return
            self._drop_deadline(rule.id)
            if match:
                self.hass.async_create_task(self._fire(rule))

        self._timers[rule.id] = async_track_point_in_time(self.hass, _due, when)

    @callback
    def _drop_deadline(self, rule_id: str) -> None:
        if self._deadlines.pop(rule_id, None) is not None:
            self.manager.async_schedule_save()

    @callback
    def _cancel_countdown(self, rule_id: str) -> None:
        if cancel := self._timers.pop(rule_id, None):
            cancel()
        self._drop_deadline(rule_id)

    async def _fire(self, rule: Rule) -> None:
        await self.manager.async_add(
            _tokens(rule.summary, rule.entity_id),
            description=rule.description,
            start="now",
            interval=rule.interval,
            key=rule.key,
            phones=rule.phones,
            speakers=rule.speakers,
            tts_message=_tokens(rule.tts_message, rule.entity_id),
            max_reminders=rule.max_reminders,
            keep_done=rule.keep_done,
            done_message=_tokens(rule.done_message, rule.entity_id),
            notify_data=rule.notify_data,
            templates=True,  # rule texts are written by an administrator
            restart=True,
            source="rule",
        )

    async def _close(self, rule: Rule) -> None:
        if task := self.manager.find(key=rule.key):
            await self.manager.async_done(task, "auto")

    # ---------------------------------------------------------------- calendar
    @callback
    def _watch_calendar(self, rule: Rule) -> None:
        at = dt_util.parse_time(rule.at_time) or dt_util.parse_time("18:00")

        @callback
        def _check(_now: datetime) -> None:
            self.hass.async_create_task(self._check_calendar(rule))

        self._unsubs[rule.id] = async_track_time_change(
            self.hass, _check, hour=at.hour, minute=at.minute, second=0
        )
        now = dt_util.now()
        if now.time() >= at and self._calendar_checked.get(rule.id) != now.date().isoformat():
            # today's check was missed (Home Assistant was down, or the rule is new)
            self._timers[rule.id] = async_call_later(self.hass, STARTUP_DELAY, _check)

    async def _check_calendar(self, rule: Rule, attempt: int = 0) -> None:
        """Is there an event in days_before days? If so, add a task naming the events."""
        if cancel := self._timers.pop(rule.id, None):
            cancel()  # a pending catch-up or retry is replaced by this check
        today = dt_util.start_of_local_day()
        day = today + timedelta(days=int(rule.days_before))
        try:
            resp = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"entity_id": rule.entity_id, "start_date_time": day.isoformat(),
                 "end_date_time": (day + timedelta(days=1) - timedelta(seconds=1)).isoformat()},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            if attempt < CALENDAR_RETRY_MAX:

                @callback
                def _retry(_now: datetime) -> None:
                    self.hass.async_create_task(self._check_calendar(rule, attempt + 1))

                self._timers[rule.id] = async_call_later(self.hass, CALENDAR_RETRY_DELAY, _retry)
            else:
                _LOGGER.warning("Remindo could not read calendar %s: %s", rule.entity_id, err)
            return
        self._calendar_checked[rule.id] = today.date().isoformat()
        self.manager.async_schedule_save()
        events = (resp or {}).get(rule.entity_id, {}).get("events", [])
        names = [e.get("summary", "") for e in events]
        if rule.contains:
            names = [n for n in names if rule.contains.lower() in n.lower()]
        if not names:
            return
        what = ", ".join(dict.fromkeys(names))
        summary = rule.summary.replace("{event}", what) if "{event}" in rule.summary else f"{rule.summary}: {what}"
        await self.manager.async_add(
            summary,
            description=rule.description,
            start="now",
            interval=rule.interval,
            # one task per event day: with "2 days before" two pickups in a row stay separate
            key=f"{rule.key}_{day.date().isoformat()}",
            phones=rule.phones,
            speakers=rule.speakers,
            tts_message=(rule.tts_message or summary).replace("{event}", what),
            max_reminders=rule.max_reminders,
            keep_done=rule.keep_done,
            notify_data=rule.notify_data,
            # nobody ticked it off: drop the task once the event day is over
            expires=day + timedelta(days=1) if rule.auto_close else None,
            templates=False,  # event names come from outside: never run them as templates
            restart=True,
            source="rule",
        )
