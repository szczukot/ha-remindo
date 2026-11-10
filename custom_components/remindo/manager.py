"""Task logic: storage, reminder schedule, notifications."""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.const import STATE_HOME, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import texts
from .const import (
    ACTION_DISMISS,
    ACTION_DONE,
    ACTION_PREFIX,
    ACTION_SNOOZE,
    CONF_CLICK_URL,
    CONF_DEFAULT_INTERVAL,
    CONF_DEFAULT_TIME,
    CONF_KEEP_DONE,
    CONF_KEEP_HISTORY,
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
from .rules import RuleEngine

_LOGGER = logging.getLogger(__name__)

# Announcement queue: wait a moment (other automations reacting to the same
# change may speak too), then until the speakers are quiet, one message at a time.
SPEAK_SETTLE = 3.0  # s
SPEAK_WAIT_MAX = 20.0  # s, max wait for a busy speaker (longer = music, not an announcement)
SPEAK_START_MAX = 5.0  # s, max wait for our own message to start playing
SPEAK_CHARS_PER_SECOND = 12  # to estimate the length of a message spoken over music
_BUSY = ("playing", "buffering")

# Dismissed tasks stay restorable; only the most recent ones are kept.
KEEP_DISMISSED = 20

# Reminders that were due while Home Assistant was down are sent this long after start.
MISSED_DELAY = timedelta(seconds=30)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RemindoError(ValueError):
    """Error with a translation key (exceptions.* in strings.json)."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


def _is_template(text: str | None) -> bool:
    return bool(text) and ("{{" in text or "{%" in text)


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
    """Add months, clamping the day to the end of the month (31 Jan + 1 → 28/29 Feb)."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def next_occurrence(base: datetime, repeat: str, every: int, after: datetime) -> datetime:
    """First occurrence after `after`, counted from `base` in steps of `every` units."""
    every = max(1, int(every or 1))
    base = dt_util.as_local(base)
    step = 0
    candidate = base
    while candidate <= after:
        step += every
        if repeat == "hourly":
            # Every N hours: real elapsed time, the wall-clock hour is not preserved
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
        # Keep the local wall-clock time across daylight-saving changes
        candidate = dt_util.as_local(candidate).replace(
            hour=base.hour, minute=base.minute, second=base.second
        )
    return candidate


@dataclass
class Task:
    """A single task."""

    uid: str
    summary: str
    description: str | None = None
    start: str | None = None  # remind from (ISO); None = a note without reminders
    next_reminder: str | None = None  # next reminder (ISO)
    interval: int = 30  # minutes between reminders (0 = remind once)
    key: str | None = None
    repeat: str = REPEAT_NONE
    repeat_every: int = 1
    tts: bool = True
    push: bool = True
    tts_message: str | None = None
    phones: list[str] | None = None  # None = all configured
    speakers: list[str] | None = None  # None = all configured
    max_reminders: int | None = None  # None = no limit
    remind_until: str | None = None  # no reminders after this time (ISO)
    expires: str | None = None  # drop the task at this time if still open (ISO)
    keep_done: bool | None = None  # None = integration option
    done_message: str | None = None  # sent when the task closes itself
    notify_data: dict[str, Any] | None = None  # extra data for the HA app notification
    templates: bool = False  # texts come from a trusted source and may be HA templates
    template: str | None = None  # summary template, rendered at every reminder
    status: str = STATUS_OPEN
    active: bool = False  # already reminded (shown under "Now")
    reminders: int = 0
    snoozes: int = 0
    created: str = field(default_factory=lambda: dt_util.now().isoformat())
    last_reminded: str | None = None
    closed: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def recurring(self) -> bool:
        return self.repeat != REPEAT_NONE and bool(self.start)


class TaskManager:
    """Holds the tasks, schedules reminders and handles actions."""

    def __init__(self, hass: HomeAssistant, options: dict[str, Any]) -> None:
        self.hass = hass
        self.options = {**DEFAULTS, **options}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.tasks: dict[str, Task] = {}
        self.history: list[dict[str, Any]] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._expiry_timers: dict[str, CALLBACK_TYPE] = {}
        self._listeners: list[Callable[[], None]] = []
        self.rules = RuleEngine(self)
        self._speak_lock = asyncio.Lock()
        self._speaking: set[asyncio.Task[None]] = set()
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ storage
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.tasks = {}
        for raw in data.get("tasks", []):
            try:
                task = Task.from_dict(raw)
            except TypeError:
                _LOGGER.warning("Skipping invalid stored task: %s", raw)
                continue
            self.tasks[task.uid] = task
        self.history = data.get("history", [])
        self.rules.restore(data.get("rule_state") or {})
        now = dt_util.now()
        for task in self.tasks.values():
            if task.status == STATUS_OPEN and task.next_reminder:
                when = _dt(task.next_reminder)
                if when is None:
                    task.next_reminder = None
                elif when < now:
                    task.next_reminder = _iso(now + MISSED_DELAY)
            self._schedule(task)
            self._schedule_expiry(task)

    def _data(self) -> dict[str, Any]:
        return {
            "tasks": [t.as_dict() for t in self.tasks.values()],
            "history": self.history,
            "rule_state": self.rules.state(),
        }

    @callback
    def async_schedule_save(self) -> None:
        """Write the store soon, without notifying listeners."""
        self._store.async_delay_save(self._data, 1)

    @callback
    def _save(self) -> None:
        """Trim old entries, write the store and tell entities and cards."""
        keep = int(self.options.get(CONF_KEEP_HISTORY, 50))
        for status, limit in ((STATUS_DONE, keep), (STATUS_DISMISSED, KEEP_DISMISSED)):
            closed = [t for t in self.tasks.values() if t.status == status]
            closed.sort(key=lambda t: t.closed or "", reverse=True)
            for old in closed[limit:]:
                self.tasks.pop(old.uid, None)
        self.history = self.history[-keep * 4 :]
        self.async_schedule_save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_unload(self) -> None:
        for cancel in (*self._timers.values(), *self._expiry_timers.values()):
            cancel()
        self._timers.clear()
        self._expiry_timers.clear()
        for speaking in list(self._speaking):
            speaking.cancel()
        self.rules.stop()
        await self._store.async_save(self._data())

    # ------------------------------------------------------------------- lookup
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

    # ------------------------------------------------------------------ actions
    def _resolve_start(self, start: Any) -> datetime | None:
        """Datetime / date / 'now' / None → local datetime (a bare date gets the default time)."""
        if start in (None, ""):
            return None
        if isinstance(start, str):
            if start.lower() == "now":
                return dt_util.now()
            # a bare date ("2026-12-01") → default time; parse_datetime would give midnight
            parsed_dt = None if _DATE_ONLY.match(start.strip()) else dt_util.parse_datetime(start)
            if parsed_dt is not None:
                start = parsed_dt
            else:
                parsed_d = dt_util.parse_date(start)
                if parsed_d is None:
                    raise RemindoError("invalid_start", start=str(start))
                start = parsed_d
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.get_default_time_zone())
            return dt_util.as_local(start)
        if isinstance(start, date):
            at = _parse_time(self.options.get(CONF_DEFAULT_TIME), "09:00:00")
            return datetime.combine(start, at, dt_util.get_default_time_zone())
        raise RemindoError("invalid_start", start=str(start))

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
        expires: datetime | None = None,
        keep_done: bool | None = None,
        done_message: str | None = None,
        notify_data: dict[str, Any] | None = None,
        templates: bool = False,
        restart: bool = False,
        source: str = "service",
        context: Context | None = None,
    ) -> Task:
        """Add a task.

        `templates` allows HA templates in the texts (trusted callers only).
        `restart`: if a task with this key is open but no longer reminding (snoozed, or its
        limit is used up), start reminding again; used when a rule's condition occurs anew.
        """
        start_dt = self._resolve_start(start)
        template = summary if templates and _is_template(summary) else None
        if template:
            summary = self._render(template)
        if key and (existing := self.find(key=key)):
            # The same key is already open → update the text instead of adding a duplicate
            existing.summary = summary
            existing.template = template
            if description is not None:
                existing.description = description
            if expires is not None:
                existing.expires = _iso(expires)
                self._schedule_expiry(existing)
            if restart and existing.start and (not existing.active or not existing.next_reminder):
                existing.next_reminder = _iso(dt_util.now())
                existing.reminders = existing.snoozes = 0
                self._schedule(existing)
            self._save()
            return existing
        if (repeat or REPEAT_NONE) != REPEAT_NONE and start_dt is None:
            raise RemindoError("repeat_needs_start")
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
            expires=_iso(expires),
            keep_done=keep_done,
            done_message=done_message or None,
            notify_data=dict(notify_data) if notify_data else None,
            templates=templates,
            template=template,
        )
        self.tasks[task.uid] = task
        self._schedule(task)
        self._schedule_expiry(task)
        self._fire(EVENT_CREATED, task, source, context)
        self._save()
        return task

    async def async_update(self, task: Task, changes: dict[str, Any]) -> Task:
        """Change fields of a task. A key present in `changes` is applied; None clears it."""
        now = dt_util.now()
        if summary := changes.get("summary"):
            if summary != task.summary:
                task.summary = summary
                task.template = None  # edited by hand: no longer follows the template
        if "description" in changes:
            task.description = changes["description"] or None
        if "start" in changes:
            start_dt = self._resolve_start(changes["start"])
            if task.repeat != REPEAT_NONE and start_dt is None:
                raise RemindoError("repeat_needs_start")
            old_start, until = _dt(task.start), _dt(task.remind_until)
            if start_dt and old_start and until and "remind_until" not in changes:
                # "stop reminding at" moves together with the due time
                task.remind_until = _iso(until + (start_dt - old_start))
            task.start = task.next_reminder = _iso(start_dt)
            task.active = bool(start_dt and start_dt <= now and task.active)
        if "interval" in changes and changes["interval"] is not None:
            task.interval = max(0, int(changes["interval"]))
            if task.active:
                # already reminding: the new rhythm starts now
                task.next_reminder = _iso(now + timedelta(minutes=task.interval)) if task.interval else None
        if "phones" in changes:
            task.phones = self._norm(changes["phones"], "notify.")
            task.push = True
        if "speakers" in changes:
            task.speakers = self._norm(changes["speakers"], "media_player.")
            task.tts = True
        if "max_reminders" in changes:
            task.max_reminders = int(changes["max_reminders"]) if changes["max_reminders"] else None
        if "remind_until" in changes:
            until = changes["remind_until"]
            task.remind_until = _iso(self._resolve_start(until)) if until else None
        if "keep_done" in changes:
            task.keep_done = changes["keep_done"]
        if "notify_data" in changes:
            task.notify_data = dict(changes["notify_data"]) if changes["notify_data"] else None
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
        if source == "auto" and task.done_message and task.reminders:
            message = self._render(task.done_message) if task.templates else task.done_message
            await self._send_plain(task, message)
        self._fire(event, task, source, context)
        self.history.append(
            {"uid": task.uid, "summary": task.summary, "key": task.key,
             "result": status, "at": now.isoformat(), "source": source,
             "reminders": task.reminders, "snoozes": task.snoozes}
        )
        if task.recurring:
            # Recurring: stays on the list and moves to the next due time
            due = _dt(task.start)
            nxt = next_occurrence(due, task.repeat, task.repeat_every, max(now, due))  # type: ignore[arg-type]
            if until := _dt(task.remind_until):
                # "stop reminding at" moves together with the due time
                task.remind_until = _iso(nxt + (until - due))  # type: ignore[operator]
            task.start = task.next_reminder = _iso(nxt)
            task.active = False
            task.reminders = task.snoozes = 0
            self._schedule(task)
        elif status == STATUS_DONE and not self.keep_done(task):
            self._cancel(task.uid)
            self.tasks.pop(task.uid, None)
        else:
            # done, or dismissed (kept so it can be restored)
            task.status = status
            task.closed = now.isoformat()
            task.next_reminder = None
            task.active = False
            self._cancel(task.uid)
        self._save()

    async def async_reopen(self, task: Task) -> None:
        """Open a done or dismissed task again; a task with a due time reminds again right away."""
        if task.status == STATUS_OPEN:
            return
        now = dt_util.now()
        task.status = STATUS_OPEN
        task.closed = None
        task.active = False
        task.reminders = task.snoozes = 0
        if task.start:
            task.next_reminder = _iso(now)
        if (expires := _dt(task.expires)) and expires <= now:
            task.expires = None  # restored after its date passed: keep it until handled
        self._schedule(task)
        self._schedule_expiry(task)
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
        if task.status != STATUS_OPEN:
            return
        if until:
            when = self._resolve_start(until)
        else:
            when = dt_util.now() + timedelta(minutes=int(minutes or 10))
        await self._clear_notifications(task)
        task.next_reminder = _iso(when)
        task.snoozes += 1
        task.active = False  # snoozed: moves from "Now" to "Scheduled"
        self._schedule(task)
        self._fire(EVENT_SNOOZED, task, source, context, until=_iso(when))
        self._save()

    async def async_delete(self, task: Task) -> None:
        """Remove a task for good (also a recurring one), without a history entry."""
        self._cancel(task.uid)
        await self._clear_notifications(task)
        self.tasks.pop(task.uid, None)
        self._save()

    # ----------------------------------------------------------------- schedule
    @callback
    def _cancel(self, uid: str) -> None:
        """Stop all timers of a task."""
        for timers in (self._timers, self._expiry_timers):
            if cancel := timers.pop(uid, None):
                cancel()

    @callback
    def _schedule(self, task: Task) -> None:
        """(Re)arm the reminder timer."""
        uid = task.uid
        if cancel := self._timers.pop(uid, None):
            cancel()
        if task.status != STATUS_OPEN or (when := _dt(task.next_reminder)) is None:
            return

        @callback
        def _fire_reminder(_now: datetime) -> None:
            self._timers.pop(uid, None)
            self.hass.async_create_task(self._async_remind(uid))

        self._timers[uid] = async_track_point_in_time(self.hass, _fire_reminder, when)

    @callback
    def _schedule_expiry(self, task: Task) -> None:
        """(Re)arm the timer that drops a task nobody ticked off."""
        uid = task.uid
        if cancel := self._expiry_timers.pop(uid, None):
            cancel()
        if task.status != STATUS_OPEN or (expires := _dt(task.expires)) is None:
            return

        @callback
        def _expire(_now: datetime) -> None:
            self._expiry_timers.pop(uid, None)
            if (current := self.tasks.get(uid)) is not None:
                self.hass.async_create_task(self.async_dismiss(current, "expired"))

        self._expiry_timers[uid] = async_track_point_in_time(self.hass, _expire, expires)

    async def _async_remind(self, uid: str) -> None:
        task = self.tasks.get(uid)
        if task is None or task.status != STATUS_OPEN:
            return
        now = dt_util.now()
        if (expires := _dt(task.expires)) and expires <= now:
            await self.async_dismiss(task, "expired")
            return
        if self.options.get(CONF_QUIET_PUSH) and self.is_quiet(now):
            # quiet hours also for push: the reminder waits until they end
            task.next_reminder = _iso(self._quiet_end(now))
            self._schedule(task)
            self._save()
            return
        if task.template:
            task.summary = self._render(task.template)
        task.active = True
        task.reminders += 1
        task.last_reminded = now.isoformat()
        nxt = now + timedelta(minutes=task.interval) if task.interval > 0 else None
        if nxt and task.max_reminders and task.reminders >= task.max_reminders:
            nxt = None  # reminder limit used up
        if nxt and (until := _dt(task.remind_until)) and nxt > until:
            nxt = None  # past the "stop reminding at" time
        task.next_reminder = _iso(nxt)
        self._schedule(task)
        self._fire(EVENT_REMINDED, task, "schedule", None, count=task.reminders)
        self._save()
        await self._send_notifications(task)

    # ------------------------------------------------------------ notifications
    def _quiet_times(self) -> tuple[time, time]:
        return (
            _parse_time(self.options.get(CONF_QUIET_START), "22:00:00"),
            _parse_time(self.options.get(CONF_QUIET_END), "07:00:00"),
        )

    def is_quiet(self, now: datetime | None = None) -> bool:
        start, end = self._quiet_times()
        current = (now or dt_util.now()).time()
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _quiet_end(self, now: datetime) -> datetime:
        """The next moment the quiet hours end."""
        end = self._quiet_times()[1]
        candidate = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    def someone_home(self) -> bool:
        entity = self.options.get(CONF_PRESENCE)
        if not entity:
            return True
        state = self.hass.states.get(entity)
        if state is None:
            return False
        if entity.startswith("zone."):
            # the state of a zone is the number of people in it
            try:
                return float(state.state) > 0
            except ValueError:
                return False
        return state.state in (STATE_HOME, STATE_ON)

    @staticmethod
    def _norm(values: list[str] | str | None, prefix: str) -> list[str] | None:
        if values is None:
            return None
        if isinstance(values, str):
            values = [v.strip() for v in values.split(",") if v.strip()]
        return [v if v.startswith(prefix) else prefix + v for v in values]

    def all_phones(self) -> list[str]:
        return self._norm(self.options.get(CONF_NOTIFY) or [], "notify.") or []

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

    def keep_done(self, task: Task) -> bool:
        return self.options.get(CONF_KEEP_DONE, True) if task.keep_done is None else task.keep_done

    def _render(self, text: str) -> str:
        """Render an HA template ({{ ... }}); on error return the plain text."""
        if not _is_template(text):
            return text
        try:
            return str(Template(text, self.hass).async_render(parse_result=False)).strip() or text
        except TemplateError as err:
            _LOGGER.warning("Template error in %r: %s", text, err)
            return text

    async def _call(self, domain: str, service: str, data: dict[str, Any], *, blocking: bool = False) -> bool:
        """Call a service; a broken target (e.g. a phone that no longer exists) must not stop the rest."""
        try:
            await self.hass.services.async_call(domain, service, data, blocking=blocking)
        except Exception as err:  # noqa: BLE001
            name = f"{domain}.{service}"
            if name not in self._warned:
                self._warned.add(name)
                _LOGGER.warning("Remindo could not call %s (check the integration settings): %s", name, err)
            return False
        return True

    @staticmethod
    def _is_mobile(target: str) -> bool:
        return target.removeprefix("notify.").startswith("mobile_app_")

    async def _notify_plain(self, target: str, title: str, message: str) -> None:
        """Telegram, e-mail, SMS…: a notify.<service> or a notify.* entity (no buttons)."""
        if self.hass.states.get(target) is not None:
            await self._call("notify", "send_message", {"entity_id": target, "title": title, "message": message})
        else:
            await self._call("notify", target.removeprefix("notify."), {"title": title, "message": message})

    async def _send_plain(self, task: Task, message: str) -> None:
        title = texts.text(self.hass, "title")
        for target in self.phones_for(task):
            await self._notify_plain(target, title, message)

    def phone_label(self, target: str) -> str:
        """Readable name of a channel (notify.mobile_app_x → the device name)."""
        if (state := self.hass.states.get(target)) is not None:
            return state.name
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
        return f"remindo_{task.uid}"

    async def _send_notifications(self, task: Task) -> None:
        title = texts.text(self.hass, "title")
        body = task.summary if not task.description else f"{task.summary}\n{task.description}"
        snooze = int(self.options[CONF_PHONE_SNOOZE])
        click = self.options.get(CONF_CLICK_URL) or DEFAULTS[CONF_CLICK_URL]
        # anything the Companion app understands (icon, Android Auto, priority…): from the
        # integration options, then from the task; the tag and the buttons stay ours
        extra = {**(self.options.get(CONF_NOTIFY_DATA) or {}), **(task.notify_data or {})}
        for target in self.phones_for(task):
            if not self._is_mobile(target):
                await self._notify_plain(target, title, body)
                continue
            await self._call(
                "notify",
                target.removeprefix("notify."),
                {
                    "title": title,
                    "message": body,
                    "data": {
                        "group": "remindo",
                        "sticky": "true",
                        "clickAction": click,
                        "url": click,
                        **extra,
                        "tag": self._tag(task),
                        "actions": [
                            {"action": f"{ACTION_PREFIX}_{ACTION_DONE}_{task.uid}", "title": texts.text(self.hass, "done")},
                            {"action": f"{ACTION_PREFIX}_{ACTION_SNOOZE}_{task.uid}", "title": texts.text(self.hass, "snooze", minutes=snooze)},
                            {"action": f"{ACTION_PREFIX}_{ACTION_DISMISS}_{task.uid}", "title": texts.text(self.hass, "dismiss")},
                        ],
                    },
                },
            )
        if self.options.get(CONF_PERSISTENT):
            await self._call(
                "persistent_notification",
                "create",
                {"title": title, "message": body, "notification_id": self._tag(task)},
            )
        speakers = self.speakers_for(task)
        if speakers and not self.is_quiet() and self.someone_home():
            speaking = self.hass.async_create_background_task(
                self._speak_queued(task.uid, speakers), "remindo speak"
            )
            self._speaking.add(speaking)
            speaking.add_done_callback(self._speaking.discard)

    def _busy(self, speakers: list[str]) -> bool:
        return any((st := self.hass.states.get(e)) is not None and st.state in _BUSY for e in speakers)

    async def _wait(self, condition: Callable[[], bool], timeout: float) -> bool:
        """Poll every 0.5 s until condition() is true; False on timeout."""
        for _ in range(int(timeout * 2)):
            if condition():
                return True
            await asyncio.sleep(0.5)
        return condition()

    async def _speak_queued(self, uid: str, speakers: list[str]) -> None:
        async with self._speak_lock:
            if SPEAK_SETTLE:
                await asyncio.sleep(SPEAK_SETTLE)
            quiet = await self._wait(lambda: not self._busy(speakers), SPEAK_WAIT_MAX)
            task = self.tasks.get(uid)
            # the task may have been ticked off while waiting
            if task is None or task.status != STATUS_OPEN or not task.active:
                return
            message = await self._speak(task, speakers)
            if not message:
                return
            if quiet:
                # hold the queue until our own message has played
                if await self._wait(lambda: self._busy(speakers), SPEAK_START_MAX):
                    await self._wait(lambda: not self._busy(speakers), SPEAK_WAIT_MAX)
            else:
                # the speaker plays something long (music): we spoke over it and cannot
                # see when our message ends, so estimate it
                await asyncio.sleep(min(SPEAK_WAIT_MAX, SPEAK_START_MAX + len(message) / SPEAK_CHARS_PER_SECOND))

    async def _speak(self, task: Task, speakers: list[str]) -> str | None:
        """Say the task on the speakers; returns the message, or None if nothing was said."""
        tts_entity = self.options.get(CONF_TTS_ENTITY)
        if not tts_entity or not speakers:
            return None
        if screen := self.options.get(CONF_SCREEN_SWITCH):
            await self._call("switch", "turn_on", {"entity_id": screen}, blocking=True)
        message = task.tts_message or task.summary
        if task.templates:
            message = self._render(message)
        spoken = await self._call(
            "tts",
            "speak",
            {"entity_id": tts_entity, "media_player_entity_id": speakers, "message": message, "cache": True},
        )
        return message if spoken else None

    async def _clear_notifications(self, task: Task, *, force: bool = False) -> None:
        if task.reminders == 0 and not force:
            return
        for target in sorted(set(self.all_phones()) | set(task.phones or [])):
            if self._is_mobile(target):
                await self._call(
                    "notify",
                    target.removeprefix("notify."),
                    {"message": "clear_notification", "data": {"tag": self._tag(task)}},
                )
        if self.options.get(CONF_PERSISTENT):
            await self._call("persistent_notification", "dismiss", {"notification_id": self._tag(task)})

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
        if task.status != STATUS_OPEN or not task.active:
            # a stale notification (already handled on another phone, or yesterday's
            # occurrence of a recurring task): remove it, do not touch the task
            await self._clear_notifications(task, force=True)
            return
        if kind == ACTION_DONE:
            await self.async_done(task, "phone", event.context)
        elif kind == ACTION_SNOOZE:
            await self.async_snooze(
                task, minutes=int(self.options[CONF_PHONE_SNOOZE]), source="phone", context=event.context
            )
        elif kind == ACTION_DISMISS:
            await self.async_dismiss(task, "phone", event.context)

    # ------------------------------------------------------------------- events
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
        """Task as sent to the card."""
        data = task.as_dict()
        data["phone_labels"] = [self.phone_label(p) for p in self.phones_for(task)]
        data["speaker_labels"] = [self.speaker_label(s) for s in self.speakers_for(task)]
        return data
