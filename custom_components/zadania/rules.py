"""Reguły: zadanie dodawane automatycznie, gdy encja osiągnie zadany stan."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any
import uuid

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, State, callback
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

MODE_STATE = "state"  # stan równy wartości
MODE_ABOVE = "above"  # liczba powyżej
MODE_BELOW = "below"  # liczba poniżej
MODE_CALENDAR = "calendar"  # wydarzenie w kalendarzu za N dni
MODES = [MODE_STATE, MODE_ABOVE, MODE_BELOW, MODE_CALENDAR]
_IGNORED = (STATE_UNAVAILABLE, STATE_UNKNOWN, None)


@dataclass
class Rule:
    """Gdy entity_id spełnia warunek przez for_minutes, dodaj zadanie."""

    id: str
    summary: str
    entity_id: str
    mode: str = MODE_STATE
    value: str = "on"
    for_minutes: int = 0
    auto_close: bool = True
    enabled: bool = True
    description: str | None = None
    interval: int | None = None
    phones: list[str] | None = None
    speakers: list[str] | None = None
    tts_message: str | None = None
    # tylko dla kalendarza
    days_before: int = 1
    at_time: str = "18:00"
    contains: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.setdefault("id", uuid.uuid4().hex[:10])
        return cls(**known)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def key(self) -> str:
        return f"rule_{self.id}"

    def matches(self, state: State | None) -> bool | None:
        """True/False, albo None gdy stanu nie da się ocenić (niedostępny)."""
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
    """Słucha zmian stanów i tworzy / zamyka zadania według reguł."""

    def __init__(self, manager: TaskManager) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.rules: dict[str, Rule] = {}
        self._unsubs: dict[str, CALLBACK_TYPE] = {}
        self._pending: dict[str, CALLBACK_TYPE] = {}

    def load(self, data: list[dict[str, Any]]) -> None:
        for raw in data:
            try:
                rule = Rule.from_dict(raw)
            except TypeError:
                _LOGGER.warning("Pominięto uszkodzoną regułę: %s", raw)
                continue
            self.rules[rule.id] = rule
        for rule in self.rules.values():
            self._watch(rule)

    def dump(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.rules.values()]

    @callback
    def stop(self) -> None:
        for rule_id in list(self._unsubs):
            self._unwatch(rule_id)

    # ------------------------------------------------------------------ zmiany
    @callback
    def save(self, data: dict[str, Any]) -> Rule:
        rule_id = data.get("id") or uuid.uuid4().hex[:10]
        current = self.rules.get(rule_id)
        merged = {**(current.as_dict() if current else {}), **data, "id": rule_id}
        rule = Rule.from_dict(merged)
        if rule.mode not in MODES:
            raise ValueError(f"Nieznany warunek: {rule.mode}")
        self.rules[rule_id] = rule
        self._unwatch(rule_id)
        self._watch(rule)
        return rule

    @callback
    def delete(self, rule_id: str) -> None:
        self._unwatch(rule_id)
        self.rules.pop(rule_id, None)

    # ---------------------------------------------------------------- śledzenie
    @callback
    def _watch(self, rule: Rule) -> None:
        if not rule.enabled:
            return
        if rule.mode == MODE_CALENDAR:
            at = dt_util.parse_time(rule.at_time) or dt_util.parse_time("18:00")

            @callback
            def _daily(_now: datetime) -> None:
                self.hass.async_create_task(self._check_calendar(rule.id))

            self._unsubs[rule.id] = async_track_time_change(
                self.hass, _daily, hour=at.hour, minute=at.minute, second=0
            )
            return

        @callback
        def _changed(event: Event[EventStateChangedData]) -> None:
            self._evaluate(rule.id, event.data["old_state"], event.data["new_state"])

        self._unsubs[rule.id] = async_track_state_change_event(self.hass, [rule.entity_id], _changed)

    @callback
    def _unwatch(self, rule_id: str) -> None:
        if unsub := self._unsubs.pop(rule_id, None):
            unsub()
        if pending := self._pending.pop(rule_id, None):
            pending()

    @callback
    def _evaluate(self, rule_id: str, old: State | None, new: State | None) -> None:
        rule = self.rules.get(rule_id)
        if rule is None or not rule.enabled:
            return
        now_match = rule.matches(new)
        if now_match is None:
            # Niedostępne / nieznane: nic nie robimy (np. restart, zanik Wi-Fi)
            return
        was_match = rule.matches(old)
        if now_match and was_match is False:
            self._start(rule)
        elif not now_match:
            if pending := self._pending.pop(rule.id, None):
                pending()
            if was_match is not False and rule.auto_close:
                self.hass.async_create_task(self._close(rule))

    @callback
    def _start(self, rule: Rule) -> None:
        if rule.id in self._pending:
            return
        if rule.for_minutes <= 0:
            self.hass.async_create_task(self._fire(rule))
            return

        @callback
        def _later(_now: Any) -> None:
            self._pending.pop(rule.id, None)
            if rule.matches(self.hass.states.get(rule.entity_id)):
                self.hass.async_create_task(self._fire(rule))

        self._pending[rule.id] = async_call_later(self.hass, rule.for_minutes * 60, _later)

    async def _fire(self, rule: Rule) -> None:
        await self.manager.async_add(
            rule.summary,
            description=rule.description,
            start="now",
            interval=rule.interval,
            key=rule.key,
            phones=rule.phones,
            speakers=rule.speakers,
            tts_message=rule.tts_message,
            source="rule",
        )

    async def _check_calendar(self, rule_id: str) -> None:
        """Czy za days_before dni jest wydarzenie? Jeśli tak — zadanie z nazwami wydarzeń."""
        rule = self.rules.get(rule_id)
        if rule is None or not rule.enabled:
            return
        day = dt_util.start_of_local_day() + timedelta(days=int(rule.days_before))
        try:
            resp = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {"entity_id": rule.entity_id, "start_date_time": day.isoformat(),
                 "end_date_time": (day + timedelta(days=1) - timedelta(seconds=1)).isoformat()},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Nie udało się odczytać kalendarza %s", rule.entity_id)
            return
        events = (resp or {}).get(rule.entity_id, {}).get("events", [])
        names = [e.get("summary", "") for e in events]
        if rule.contains:
            names = [n for n in names if rule.contains.lower() in n.lower()]
        if not names:
            return
        what = ", ".join(dict.fromkeys(names))
        summary = rule.summary.replace("{wydarzenie}", what) if "{wydarzenie}" in rule.summary else f"{rule.summary}: {what}"
        message = (rule.tts_message or summary).replace("{wydarzenie}", what)
        await self.manager.async_add(
            summary, description=rule.description, start="now", interval=rule.interval,
            key=rule.key, phones=rule.phones, speakers=rule.speakers, tts_message=message, source="rule",
        )
        if rule.auto_close:
            # zamknij po dniu wydarzenia, jeśli nikt nie odhaczył
            @callback
            def _end(_now: datetime) -> None:
                self._pending.pop(rule.id, None)
                self.hass.async_create_task(self._close(rule))

            if old := self._pending.pop(rule.id, None):
                old()
            self._pending[rule.id] = async_track_point_in_time(self.hass, _end, day + timedelta(days=1))

    async def _close(self, rule: Rule) -> None:
        if task := self.manager.find(key=rule.key):
            await self.manager.async_done(task, "auto")
