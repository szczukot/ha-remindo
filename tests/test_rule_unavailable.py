"""Rules on an entity that becomes unavailable (device offline, dead battery, no Wi-Fi)."""

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import InvalidData

from custom_components.remindo.rules import UNAVAILABLE_MIN_MINUTES, Rule

from .common import add_rule, setup_integration, tick


def _open(entry) -> list[str]:
    return [t.summary for t in entry.runtime_data.open_tasks()]


async def test_unavailable_adds_and_closes_the_task(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 12:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.solar", "45")
    await add_rule(hass, entry, {"summary": "Solar controller offline", "entity_id": "sensor.solar",
                                 "mode": "unavailable", "for_minutes": 30})
    # a short drop (Wi-Fi reconnect) is not a task
    hass.states.async_set("sensor.solar", "unavailable")
    await tick(hass, freezer, minutes=5)
    hass.states.async_set("sensor.solar", "46")
    await tick(hass, freezer, minutes=40)
    assert _open(entry) == []
    # offline for longer: a task, which closes itself when the device is back
    hass.states.async_set("sensor.solar", "unavailable")
    await tick(hass, freezer, minutes=29)
    assert _open(entry) == []
    await tick(hass, freezer, minutes=2)
    assert _open(entry) == ["Solar controller offline"]
    hass.states.async_set("sensor.solar", "47")
    await hass.async_block_till_done()
    assert _open(entry) == []


async def test_unknown_is_not_unavailable(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """unknown = the device is there but has no value yet."""
    freezer.move_to("2026-11-18 12:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.solar", "45")
    await add_rule(hass, entry, {"summary": "Offline", "entity_id": "sensor.solar", "mode": "unavailable", "for_minutes": 10})
    hass.states.async_set("sensor.solar", "unknown")
    await tick(hass, freezer, minutes=30)
    assert _open(entry) == []


async def test_already_unavailable_when_the_rule_starts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The device died while Home Assistant was down, or the rule is made for a dead device."""
    freezer.move_to("2026-11-18 12:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.solar", "unavailable")
    hass.states.async_set("sensor.gate", "unavailable")
    await add_rule(hass, entry, {"summary": "Solar offline", "entity_id": "sensor.solar", "mode": "unavailable", "for_minutes": 15})
    await add_rule(hass, entry, {"summary": "Gate offline", "entity_id": "sensor.gate", "mode": "unavailable", "for_minutes": 15})
    # the gate sensor was only starting up
    await tick(hass, freezer, minutes=3)
    hass.states.async_set("sensor.gate", "off")
    await tick(hass, freezer, minutes=15)
    assert _open(entry) == ["Solar offline"]


async def test_shutting_down_is_not_offline(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 12:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.solar", "45")
    await add_rule(hass, entry, {"summary": "Offline", "entity_id": "sensor.solar", "mode": "unavailable", "for_minutes": 10})
    hass.set_state(CoreState.stopping)
    hass.states.async_set("sensor.solar", "unavailable")
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    assert entry.runtime_data.rules._deadlines == {}


async def test_the_wait_has_a_minimum(hass: HomeAssistant) -> None:
    """Right after a restart entities are unavailable for a while: never "immediately"."""
    assert Rule(id="x", summary="s", entity_id="sensor.a", mode="unavailable", for_minutes=0).wait_minutes == UNAVAILABLE_MIN_MINUTES
    assert Rule(id="x", summary="s", entity_id="sensor.a", mode="state", for_minutes=0).wait_minutes == 0
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.solar", "45")
    with pytest.raises(InvalidData):
        await add_rule(hass, entry, {"summary": "Offline", "entity_id": "sensor.solar", "mode": "unavailable", "for_minutes": 1})
