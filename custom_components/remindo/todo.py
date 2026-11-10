"""Encja To-do dla zadań."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STATUS_DONE, STATUS_OPEN
from .manager import Task, TaskManager


def _minute(value: date | datetime | None) -> str | None:
    """Porównanie terminów z dokładnością do minuty."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M")
    return value.isoformat()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: TaskManager = entry.runtime_data
    async_add_entities([RemindoTodoList(manager, entry)])


class RemindoTodoList(TodoListEntity):
    """Lista zadań z przypomnieniami."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: TaskManager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_todo"
        self._attr_name = "Remindo"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    @staticmethod
    def _to_item(task: Task) -> TodoItem:
        due_raw = task.next_reminder or task.start
        due = dt_util.as_local(dt_util.parse_datetime(due_raw)) if due_raw else None
        description = task.description
        if label := task.repeat_label:
            description = f"🔁 {label}" + (f"\n{description}" if description else "")
        return TodoItem(
            uid=task.uid,
            summary=task.summary,
            status=TodoItemStatus.COMPLETED if task.status == STATUS_DONE else TodoItemStatus.NEEDS_ACTION,
            due=due if task.status == STATUS_OPEN else None,
            description=description,
            completed=dt_util.parse_datetime(task.closed) if task.closed else None,
        )

    @property
    def todo_items(self) -> list[TodoItem]:
        tasks = sorted(
            self._manager.tasks.values(),
            key=lambda t: (t.status != STATUS_OPEN, t.next_reminder or t.start or "9999", t.created),
        )
        return [self._to_item(t) for t in tasks]

    @property
    def extra_state_attributes(self) -> dict:
        return {"active": sum(1 for t in self._manager.open_tasks() if t.active)}

    @staticmethod
    def _clean_description(text: str | None) -> str | None:
        if text and text.startswith("🔁"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        return text or None

    async def async_create_todo_item(self, item: TodoItem) -> None:
        start: date | datetime | None = item.due
        await self._manager.async_add(
            item.summary or "",
            description=self._clean_description(item.description),
            start=start,
            source="todo",
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        task = self._manager.tasks.get(item.uid or "")
        if task is None:
            return
        if item.status == TodoItemStatus.COMPLETED and task.status == STATUS_OPEN:
            await self._manager.async_done(task, "todo")
            return
        if item.status == TodoItemStatus.NEEDS_ACTION and task.status == STATUS_DONE:
            await self._manager.async_reopen(task)
        changes: dict = {
            "summary": item.summary,
            "description": self._clean_description(item.description),
        }
        current = self._to_item(task).due
        if task.status == STATUS_OPEN and _minute(item.due) != _minute(current):
            changes["start"] = item.due
        await self._manager.async_update(task.uid, **changes)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            if task := self._manager.tasks.get(uid):
                if task.status == STATUS_OPEN:
                    await self._manager.async_dismiss(task, "todo")
                else:
                    await self._manager.async_delete(task)
