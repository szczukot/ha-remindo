"""Sensor z liczbą aktywnych zadań."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .manager import TaskManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ActiveTasksSensor(entry.runtime_data, entry)])


class ActiveTasksSensor(SensorEntity):
    """Ile zadań już przypomina (do zrobienia teraz)."""

    _attr_has_entity_name = True
    _attr_name = "Zadania aktywne"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zadań"

    def __init__(self, manager: TaskManager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_active"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.async_add_listener(self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return sum(1 for t in self._manager.open_tasks() if t.active)

    @property
    def extra_state_attributes(self) -> dict:
        active = [t for t in self._manager.open_tasks() if t.active]
        return {
            "zadania": [t.summary for t in active],
            "zaplanowane": sum(1 for t in self._manager.open_tasks() if not t.active and t.start),
        }
