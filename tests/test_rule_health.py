"""Rules that change or disappear, and rules that can never work."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from custom_components.remindo.const import DOMAIN

from .common import add_rule, add_task, setup_integration, tick


async def _trigger_form(hass: HomeAssistant, entry, data: dict):
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": "user"})
    return await hass.config_entries.subentries.async_configure(flow["flow_id"], data)


async def test_deleted_rule_closes_its_task(hass: HomeAssistant) -> None:
    """A rule deleted while its task is open must not leave the task behind forever."""
    entry, _ = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    rule = await add_rule(hass, entry, {"summary": "Close the gate", "entity_id": "binary_sensor.gate", "value": "on"})
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    assert [t.summary for t in entry.runtime_data.open_tasks()] == ["Close the gate"]
    other = await add_task(hass, summary="Someone else's task")

    hass.config_entries.async_remove_subentry(entry, rule)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert [t.uid for t in manager.open_tasks()] == [other]


async def test_new_entity_starts_a_new_countdown(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Pointing a rule at another entity mid-countdown must not reuse the old countdown."""
    freezer.move_to("2026-11-09 15:00:00+01:00")
    entry, _ = await setup_integration(hass)
    hass.states.async_set("binary_sensor.gate", "off")
    hass.states.async_set("binary_sensor.door", "on")
    rule = await add_rule(
        hass, entry, {"summary": "Close it", "entity_id": "binary_sensor.gate", "value": "on", "for_minutes": 10}
    )
    hass.states.async_set("binary_sensor.gate", "on")
    await hass.async_block_till_done()
    await tick(hass, freezer, minutes=8)

    flow = await entry.start_subentry_reconfigure_flow(hass, rule)
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"summary": "Close it", "entity_id": "binary_sensor.door", "mode": "state"}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"value": "on", "for_minutes": 10})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"remind": True, "interval": 30})
    assert flow["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()

    await tick(hass, freezer, minutes=3)  # 11 min after the gate opened, 3 min for the door
    assert entry.runtime_data.open_tasks() == []


async def test_skip_then_done_both_count(hass: HomeAssistant) -> None:
    """✕ and then ✓ on a repeating task right after it are two different answers."""
    entry, _ = await setup_integration(hass)
    uid = await add_task(hass, summary="Water the plants", start="2026-11-09 08:00:00", repeat="daily")
    manager = entry.runtime_data
    due = manager.find(uid).start
    await hass.services.async_call(DOMAIN, "dismiss", {"uid": uid}, blocking=True)
    after_skip = manager.find(uid).start
    assert after_skip > due
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert manager.find(uid).start > after_skip
    # the same answer twice in a row (two phones) still counts once
    after_done = manager.find(uid).start
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)
    assert manager.find(uid).start == after_done


async def test_rule_form_rejects_rules_that_cannot_work(hass: HomeAssistant) -> None:
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.washer", "running")
    hass.states.async_set("sensor.toner", "40")

    result = await _trigger_form(hass, entry, {"summary": "X", "entity_id": "sensor.nope", "mode": "state"})
    assert result["errors"] == {"entity_id": "rule_entity_missing"}
    result = await _trigger_form(hass, entry, {"summary": "X", "entity_id": "sensor.washer", "mode": "calendar"})
    assert result["errors"] == {"mode": "rule_not_calendar"}
    result = await _trigger_form(hass, entry, {"summary": "X", "entity_id": "sensor.washer", "mode": "below"})
    assert result["errors"] == {"mode": "rule_not_numeric"}
    result = await _trigger_form(hass, entry, {"summary": "X", "entity_id": "sensor.toner", "mode": "below"})
    assert result["step_id"] == "condition_number"


async def test_repairs_warn_about_broken_rules(hass: HomeAssistant) -> None:
    """An entity renamed or removed after the rule was made shows up in Settings → Repairs."""
    entry, _ = await setup_integration(hass)
    hass.states.async_set("sensor.toner", "40")
    rule = await add_rule(hass, entry, {"summary": "Toner", "entity_id": "sensor.toner", "mode": "below", "value": 25})
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"rule_{rule}") is None

    hass.states.async_remove("sensor.toner")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, f"rule_{rule}")
    assert issue.translation_key == "rule_entity_missing"
    assert issue.translation_placeholders == {"rule": "Toner", "entity": "sensor.toner"}

    hass.states.async_set("sensor.toner", "low")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f"rule_{rule}").translation_key == "rule_not_numeric"

    hass.config_entries.async_remove_subentry(entry, rule)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f"rule_{rule}") is None
