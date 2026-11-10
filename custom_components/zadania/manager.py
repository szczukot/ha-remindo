"""Logika zadań: magazyn, harmonogram przypomnień, powiadomienia."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from typing import Any
import uuid

from homeassistant.const import STATE_HOME, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .rules import RuleEngine

from .const import (
    ACTION_DISMISS,
    ACTION_DONE,
    ACTION_PREFIX,
    ACTION_SNOOZE,
    CONF_CLICK_URL,
    CONF_DEFAULT_INTERVAL,
    CONF_DEFAULT_TIME,
    CONF_KEEP_HISTORY,
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
    EVENT_CREATED,
    EVENT_DISMISSED,
    EVENT_DONE,
    EVENT_REMINDED,
    EVENT_SNOOZED,
    REPEAT_NONE,
    SIGNAL_UPDATED,
    STATUS_DISMISSED,
    STATUS_DONE,
    STATUS_OPEN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_REPEAT_LABEL = {"hourly": "godz.", "daily": "dni", "weekly": "tyg.", "monthly": "mies.", "yearly": "lat"}
_REPEAT_ONE = {"hourly": "godzinę", "daily": "dzień", "weekly": "tydzień", "monthly": "miesiąc", "yearly": "rok"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    return dt_util.as_local(parsed) if parsed else None


def _parse_time(value: str | time | None, fallback: str) -> time:
    if isinstance(value, time):
        return value
    parsed = dt_util.parse_time(value or fallback)
    return parsed or dt_util.parse_time(fallback)  # type: ignore[return-value]


def add_months(value: datetime, months: int) -> datetime:
    """Dodaje miesiące, przycinając dzień do końca miesiąca (31.01 + 1 → 28/29.02)."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def next_occurrence(base: datetime, repeat: str, every: int, after: datetime) -> datetime:
    """Pierwsze wystąpienie po after, liczone od terminu base co every jednostek."""
    every = max(1, int(every or 1))
    base = dt_util.as_local(base)
    step = 0
    candidate = base
    while candidate <= after:
        step += every
        if repeat == "hourly":
            # Co N godzin: bez przestawiania godziny
            candidate = base + timedelta(hours=step)
            continue
        if repeat == "daily":
            candidate = base + timedelta(days=step)
        elif repeat == "weekly":
            candidate = base + timedelta(weeks=step)
        elif repeat == "monthly":
            candidate = add_months(base, step)
        elif repeat == "yearly":
            candidate = add_months(base, 12 * step)
        else:
            return base
        # Przeliczenie godziny w strefie lokalnej (zmiana czasu letni/zimowy)
        candidate = dt_util.as_local(candidate).replace(
            hour=base.hour, minute=base.minute, second=base.second
        )
    return candidate


@dataclass
class Task:
    """Jedno zadanie."""

    uid: str
    summary: str
    description: str | None = None
    start: str | None = None  # od kiedy przypominać (ISO); None = notatka
    next_reminder: str | None = None  # najbliższe przypomnienie (ISO)
    interval: int = 30  # co ile minut ponawiać (0 = raz)
    key: str | None = None
    repeat: str = REPEAT_NONE
    repeat_every: int = 1
    tts: bool = True
    push: bool = True
    tts_message: str | None = None
    phones: list[str] | None = None  # None = wszystkie z ustawień
    speakers: list[str] | None = None  # None = wszystkie z ustawień
    max_reminders: int | None = None  # maks. liczba przypomnień (None = bez limitu)
    remind_until: str | None = None  # nie przypominaj po tym terminie (ISO)
    status: str = STATUS_OPEN
    active: bool = False  # czy już przypomniało (zadanie „na teraz”)
    reminders: int = 0
    snoozes: int = 0
    created: str = field(default_factory=lambda: dt_util.now().isoformat())
    last_reminded: str | None = None
    closed: str | None = None
    close_reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def repeat_label(self) -> str | None:
        if self.repeat == REPEAT_NONE:
            return None
        if self.repeat_every > 1:
            return f"co {self.repeat_every} {_REPEAT_LABEL.get(self.repeat, self.repeat)}"
        return f"co {_REPEAT_ONE.get(self.repeat, self.repeat)}"


class TaskManager:
    """Trzyma zadania, planuje przypomnienia i obsługuje akcje."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        self.hass = hass
        self.options = {**DEFAULTS, **options}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.tasks: dict[str, Task] = {}
        self.history: list[dict[str, Any]] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._listeners: list[Callable[[], None]] = []
        self.rules = RuleEngine(self)
        self._legacy_rules: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ magazyn
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.tasks = {t["uid"]: Task.from_dict(t) for t in data.get("tasks", [])}
        self.history = data.get("history", [])
        self._legacy_rules: list[dict[str, Any]] = data.get("rules", [])
        now = dt_util.now()
        for task in self.tasks.values():
            if task.status == STATUS_OPEN and task.next_reminder:
                # Przypomnienia „przegapione” w czasie restartu: od razu
                if _dt(task.next_reminder) < now:  # type: ignore[operator]
                    task.next_reminder = _iso(now + timedelta(seconds=30))
            self._schedule(task)

    @callback
    def _save(self) -> None:
        keep = int(self.options.get(CONF_KEEP_HISTORY, 50))
        done = [t for t in self.tasks.values() if t.status == STATUS_DONE]
        done.sort(key=lambda t: t.closed or "", reverse=True)
        for old in done[keep:]:
            self.tasks.pop(old.uid, None)
        self.history = self.history[-keep * 4 :]
        self._store.async_delay_save(
            lambda: {
                "tasks": [t.as_dict() for t in self.tasks.values()],
                "history": self.history,
            },
            1,
        )
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_unload(self) -> None:
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        self.rules.stop()
        await self._store.async_save(
            {"tasks": [t.as_dict() for t in self.tasks.values()], "history": self.history}
        )

    # -------------------------------------------------------------------- reguły
    def take_legacy_rules(self) -> list[dict[str, Any]]:
        """Reguły zapisane przez starsze wersje — do przeniesienia do ustawień integracji."""
        rules, self._legacy_rules = self._legacy_rules, []
        if rules:
            self._save()
        return rules

    # ---------------------------------------------------------------- wyszukiwanie
    def open_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == STATUS_OPEN]

    def find(self, uid: str | None = None, key: str | None = None) -> Task | None:
        if uid and uid in self.tasks:
            return self.tasks[uid]
        if key:
            for task in self.open_tasks():
                if task.key == key:
                    return task
        return None

    # ------------------------------------------------------------------ akcje
    def _resolve_start(self, start: Any) -> datetime | None:
        """Datetime / date / 'now' / None → datetime lokalny (data bez godziny → domyślna godzina)."""
        if start in (None, ""):
            return None
        if isinstance(start, str):
            if start.lower() in ("now", "teraz"):
                return dt_util.now()
            parsed_dt = dt_util.parse_datetime(start)
            if parsed_dt is not None:
                start = parsed_dt
            else:
                parsed_d = dt_util.parse_date(start)
                if parsed_d is None:
                    raise ValueError(f"Nieznany format startu: {start}")
                start = parsed_d
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.get_default_time_zone())
            return dt_util.as_local(start)
        if isinstance(start, date):
            at = _parse_time(self.options.get(CONF_DEFAULT_TIME), "09:00:00")
            return datetime.combine(start, at, dt_util.get_default_time_zone())
        raise ValueError(f"Nieznany format startu: {start}")

    async def async_add(
        self,
        summary: str,
        *,
        description: str | None = None,
        start: Any = "now",
        interval: int | None = None,
        key: str | None = None,
        repeat: str = REPEAT_NONE,
        repeat_every: int = 1,
        tts: bool | None = None,
        push: bool = True,
        tts_message: str | None = None,
        phones: list[str] | None = None,
        speakers: list[str] | None = None,
        max_reminders: int | None = None,
        remind_until: Any = None,
        source: str = "service",
        context: Context | None = None,
    ) -> Task:
        start_dt = self._resolve_start(start)
        if key and (existing := self.find(key=key)):
            # Ten sam klucz już otwarty → nie dublujemy, tylko aktualizujemy treść
            existing.summary = summary
            if description is not None:
                existing.description = description
            self._save()
            return existing
        task = Task(
            uid=uuid.uuid4().hex[:12],
            summary=summary,
            description=description,
            start=_iso(start_dt),
            next_reminder=_iso(start_dt),
            interval=int(self.options[CONF_DEFAULT_INTERVAL] if interval is None else interval),
            key=key or None,
            repeat=repeat or REPEAT_NONE,
            repeat_every=max(1, int(repeat_every or 1)),
            tts=self.options[CONF_TTS_DEFAULT] if tts is None else tts,
            push=push,
            tts_message=tts_message,
            phones=self._norm(phones, "notify."),
            speakers=self._norm(speakers, "media_player."),
            max_reminders=int(max_reminders) if max_reminders else None,
            remind_until=_iso(self._resolve_start(remind_until)) if remind_until else None,
        )
        if task.repeat != REPEAT_NONE and start_dt is None:
            raise ValueError("Zadanie cykliczne musi mieć start")
        self.tasks[task.uid] = task
        self._schedule(task)
        self._fire(EVENT_CREATED, task, source, context)
        self._save()
        return task

    async def async_update(self, uid: str, **changes: Any) -> Task:
        task = self.tasks[uid]
        if "start" in changes:
            start_dt = self._resolve_start(changes.pop("start"))
            task.start = _iso(start_dt)
            task.next_reminder = _iso(start_dt)
            task.active = bool(start_dt and start_dt <= dt_util.now() and task.active)
        for name, value in changes.items():
            if hasattr(task, name) and value is not None:
                setattr(task, name, value)
        self._schedule(task)
        self._save()
        return task

    async def async_done(
        self, task: Task, source: str = "service", context: Context | None = None
    ) -> None:
        await self._close(task, STATUS_DONE, EVENT_DONE, source, context)

    async def async_dismiss(
        self, task: Task, source: str = "service", context: Context | None = None
    ) -> None:
        await self._close(task, STATUS_DISMISSED, EVENT_DISMISSED, source, context)

    async def _close(
        self, task: Task, status: str, event: str, source: str, context: Context | None
    ) -> None:
        if task.status != STATUS_OPEN:
            return
        now = dt_util.now()
        await self._clear_notifications(task)
        self._fire(event, task, source, context)
        self.history.append(
            {"uid": task.uid, "summary": task.summary, "key": task.key,
             "result": status, "at": now.isoformat(), "source": source,
             "reminders": task.reminders, "snoozes": task.snoozes}
        )
        if task.repeat != REPEAT_NONE and task.start:
            # Cykliczne: zostaje na liście, przeskakuje na następny termin
            nxt = next_occurrence(_dt(task.start), task.repeat, task.repeat_every, now)  # type: ignore[arg-type]
            task.start = task.next_reminder = _iso(nxt)
            task.active = False
            task.reminders = task.snoozes = 0
            self._schedule(task)
        elif status == STATUS_DONE:
            task.status = STATUS_DONE
            task.closed = now.isoformat()
            task.close_reason = source
            task.next_reminder = None
            self._schedule(task)
        else:
            self._cancel(task.uid)
            self.tasks.pop(task.uid, None)
        self._save()

    async def async_reopen(self, task: Task) -> None:
        if task.status == STATUS_DONE:
            task.status = STATUS_OPEN
            task.closed = task.close_reason = None
            self._save()

    async def async_snooze(
        self,
        task: Task,
        *,
        minutes: int | None = None,
        until: Any = None,
        source: str = "service",
        context: Context | None = None,
    ) -> None:
        if until:
            when = self._resolve_start(until)
        else:
            when = dt_util.now() + timedelta(minutes=int(minutes or 10))
        await self._clear_notifications(task)
        task.next_reminder = _iso(when)
        task.snoozes += 1
        task.active = False  # odłożone schodzi z „Teraz” do „Zaplanowane”
        self._schedule(task)
        self._fire(EVENT_SNOOZED, task, source, context, until=_iso(when))
        self._save()

    async def async_delete(self, task: Task) -> None:
        self._cancel(task.uid)
        await self._clear_notifications(task)
        self.tasks.pop(task.uid, None)
        self._save()

    # -------------------------------------------------------------- harmonogram
    @callback
    def _cancel(self, uid: str) -> None:
        if cancel := self._timers.pop(uid, None):
            cancel()

    @callback
    def _schedule(self, task: Task) -> None:
        self._cancel(task.uid)
        if task.status != STATUS_OPEN or not task.next_reminder:
            return
        when = _dt(task.next_reminder)

        @callback
        def _fire_reminder(_now: datetime) -> None:
            self._timers.pop(task.uid, None)
            self.hass.async_create_task(self._async_remind(task.uid))

        self._timers[task.uid] = async_track_point_in_time(self.hass, _fire_reminder, when)  # type: ignore[arg-type]

    async def _async_remind(self, uid: str) -> None:
        task = self.tasks.get(uid)
        if task is None or task.status != STATUS_OPEN:
            return
        now = dt_util.now()
        task.active = True
        task.reminders += 1
        task.last_reminded = now.isoformat()
        nxt = now + timedelta(minutes=task.interval) if task.interval > 0 else None
        if nxt and task.max_reminders and task.reminders >= task.max_reminders:
            nxt = None  # wykorzystano limit przypomnień
        if nxt and task.remind_until and nxt > _dt(task.remind_until):  # type: ignore[operator]
            nxt = None  # minął termin przypominania
        task.next_reminder = _iso(nxt)
        self._schedule(task)
        self._fire(EVENT_REMINDED, task, "schedule", None, count=task.reminders)
        self._save()
        try:
            await self._send_notifications(task)
        except Exception:  # noqa: BLE001 - powiadomienie nie może zatrzymać harmonogramu
            _LOGGER.exception("Nie udało się wysłać przypomnienia o zadaniu %s", task.summary)

    # ------------------------------------------------------------- powiadomienia
    def is_quiet(self, now: datetime | None = None) -> bool:
        now = now or dt_util.now()
        start = _parse_time(self.options.get(CONF_QUIET_START), "22:00:00")
        end = _parse_time(self.options.get(CONF_QUIET_END), "07:00:00")
        current = now.time()
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def someone_home(self) -> bool:
        entity = self.options.get(CONF_PRESENCE)
        if not entity:
            return True
        state = self.hass.states.get(entity)
        return state is not None and state.state in (STATE_HOME, STATE_ON)

    @staticmethod
    def _norm(values: list[str] | str | None, prefix: str) -> list[str] | None:
        if values is None:
            return None
        if isinstance(values, str):
            values = [v.strip() for v in values.split(",") if v.strip()]
        return [v if v.startswith(prefix) else prefix + v for v in values]

    def all_phones(self) -> list[str]:
        return [t if t.startswith("notify.") else f"notify.{t}" for t in self.options.get(CONF_NOTIFY) or []]

    def all_speakers(self) -> list[str]:
        value = self.options.get(CONF_MEDIA_PLAYER) or []
        return [value] if isinstance(value, str) else list(value)

    def phones_for(self, task: Task) -> list[str]:
        if not task.push:
            return []
        return self.all_phones() if task.phones is None else task.phones

    def speakers_for(self, task: Task) -> list[str]:
        if not task.tts:
            return []
        return self.all_speakers() if task.speakers is None else task.speakers

    def phone_label(self, target: str) -> str:
        """Nazwa telefonu z integracji mobile_app (notify.mobile_app_x → nazwa urządzenia)."""
        from homeassistant.util import slugify  # noqa: PLC0415

        service = target.removeprefix("notify.")
        for entry in self.hass.config_entries.async_entries("mobile_app"):
            name = entry.data.get("device_name") or entry.title
            if service == f"mobile_app_{slugify(name)}":
                return name
        return service.removeprefix("mobile_app_").replace("_", " ")

    def speaker_label(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    def _tag(self, task: Task) -> str:
        return f"zadania_{task.uid}"

    async def _send_notifications(self, task: Task) -> None:
        body = task.summary if not task.description else f"{task.summary}\n{task.description}"
        snooze = int(self.options[CONF_PHONE_SNOOZE])
        click = self.options.get(CONF_CLICK_URL) or "/todo?entity_id=todo.zadania"
        for target in self.phones_for(task):
            if True:
                service = target.removeprefix("notify.")
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {
                        "title": "📋 Zadanie",
                        "message": body,
                        "data": {
                            "tag": self._tag(task),
                            "group": "zadania",
                            "sticky": "true",
                            "clickAction": click,
                            "url": click,
                            "actions": [
                                {"action": f"{ACTION_PREFIX}_{ACTION_DONE}_{task.uid}", "title": "✅ Zrobione"},
                                {"action": f"{ACTION_PREFIX}_{ACTION_SNOOZE}_{task.uid}", "title": f"⏰ +{snooze} min"},
                                {"action": f"{ACTION_PREFIX}_{ACTION_DISMISS}_{task.uid}", "title": "❌ Nie robię"},
                            ],
                        },
                    },
                    blocking=False,
                )
        if self.options.get(CONF_PERSISTENT):
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {"title": "📋 Zadanie", "message": body, "notification_id": self._tag(task)},
                blocking=False,
            )
        speakers = self.speakers_for(task)
        if speakers and not self.is_quiet() and self.someone_home():
            await self._speak(task, speakers)

    async def _speak(self, task: Task, speakers: list[str]) -> None:
        tts_entity = self.options.get(CONF_TTS_ENTITY)
        if not tts_entity or not speakers:
            return
        if screen := self.options.get(CONF_SCREEN_SWITCH):
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": screen}, blocking=True
            )
        await self.hass.services.async_call(
            "tts",
            "speak",
            {
                "entity_id": tts_entity,
                "media_player_entity_id": speakers,
                "message": task.tts_message or task.summary,
                "cache": True,
            },
            blocking=False,
        )

    async def _clear_notifications(self, task: Task) -> None:
        if task.reminders == 0:
            return
        for target in sorted(set(self.all_phones()) | set(task.phones or [])):
            await self.hass.services.async_call(
                "notify",
                target.removeprefix("notify."),
                {"message": "clear_notification", "data": {"tag": self._tag(task)}},
                blocking=False,
            )
        if self.options.get(CONF_PERSISTENT):
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": self._tag(task)},
                blocking=False,
            )

    async def async_handle_phone_action(self, event: Event) -> None:
        action: str = event.data.get("action", "")
        if not action.startswith(f"{ACTION_PREFIX}_"):
            return
        try:
            _, kind, uid = action.split("_", 2)
        except ValueError:
            return
        task = self.tasks.get(uid)
        if task is None:
            return
        if kind == ACTION_DONE:
            await self.async_done(task, "phone", event.context)
        elif kind == ACTION_SNOOZE:
            await self.async_snooze(
                task, minutes=int(self.options[CONF_PHONE_SNOOZE]), source="phone", context=event.context
            )
        elif kind == ACTION_DISMISS:
            await self.async_dismiss(task, "phone", event.context)

    # ------------------------------------------------------------------ zdarzenia
    @callback
    def _fire(
        self, event: str, task: Task, source: str, context: Context | None, **extra: Any
    ) -> None:
        self.hass.bus.async_fire(
            event,
            {"uid": task.uid, "summary": task.summary, "key": task.key, "source": source, **extra},
            context=context,
        )

    def serialize(self, task: Task) -> dict[str, Any]:
        data = task.as_dict()
        data["repeat_label"] = task.repeat_label
        data["phone_labels"] = [self.phone_label(p) for p in self.phones_for(task)]
        data["speaker_labels"] = [self.speaker_label(s) for s in self.speakers_for(task)]
        return data
