"""Weekdays, monthly patterns and "count from ticking off"."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.remindo.const import DOMAIN

from .common import add_task, setup_integration, tick


def _when(task) -> str:
    return task.start[:16]


async def _done(hass: HomeAssistant, uid: str) -> None:
    await hass.services.async_call(DOMAIN, "done", {"uid": uid}, blocking=True)


async def test_weekdays(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-17 08:00:00+01:00")  # Tuesday
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    # set on a Tuesday for Mon + Thu: the first date is Thursday
    uid = await add_task(hass, summary="Bins", start="2026-11-17 19:00:00", repeat="weekly", repeat_days="mon, thu")
    task = manager.find(uid)
    assert task.repeat_days == [0, 3]
    assert _when(task) == "2026-11-19T19:00"
    await tick(hass, freezer, days=2, hours=11, minutes=1)  # Thu 19:01
    await _done(hass, uid)
    assert _when(task) == "2026-11-23T19:00"  # Monday
    await _done(hass, uid)  # ticked off early, a second time from elsewhere: ignored (30 s)
    assert _when(task) == "2026-11-23T19:00"
    # every 2nd week, numbers work too
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "repeat_every": 2, "repeat_days": [4]}, blocking=True)
    assert _when(task) == "2026-11-27T19:00"  # Friday of the same (first) week
    await hass.services.async_call(DOMAIN, "update", {"uid": uid, "repeat_days": None}, blocking=True)
    assert task.repeat_days is None


async def test_monthly_patterns(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-01 08:00:00+01:00")
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    third_tue = await add_task(hass, summary="Meeting", start="2026-11-17 18:00:00", repeat="monthly", repeat_on="weekday")
    last_fri = await add_task(hass, summary="Report", start="2026-11-06 10:00:00", repeat="monthly", repeat_on="last_weekday")
    last_day = await add_task(hass, summary="Invoice", start="2026-11-03 09:00:00", repeat="monthly", repeat_on="last_day")
    assert _when(manager.find(third_tue)) == "2026-11-17T18:00"
    assert _when(manager.find(last_fri)) == "2026-11-27T10:00"  # moved to the last Friday
    assert _when(manager.find(last_day)) == "2026-11-30T09:00"
    freezer.move_to("2026-11-30 12:00:00+01:00")
    for uid in (third_tue, last_fri, last_day):
        await _done(hass, uid)
    assert _when(manager.find(third_tue)) == "2026-12-15T18:00"
    assert _when(manager.find(last_fri)) == "2026-12-25T10:00"
    assert _when(manager.find(last_day)) == "2026-12-31T09:00"
    freezer.move_to("2027-01-02 12:00:00+01:00")
    await _done(hass, last_day)
    assert _when(manager.find(last_day)) == "2027-01-31T09:00"
    await _done(hass, third_tue)  # December's was missed: the next one after today
    assert _when(manager.find(third_tue)) == "2027-01-19T18:00"


async def test_count_from_done(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-01 08:00:00+01:00")
    entry, _ = await setup_integration(hass)
    manager = entry.runtime_data
    fixed = await add_task(hass, summary="Rent", start="2026-11-10 09:00:00", repeat="monthly")
    filt = await add_task(hass, summary="Filter", start="2026-11-10 09:00:00", repeat="monthly", repeat_every=3, repeat_from_done=True)
    pill = await add_task(hass, summary="Pill", start="2026-11-10 09:00:00", repeat="hourly", repeat_every=8, repeat_from_done=True)
    freezer.move_to("2026-11-14 20:30:00+01:00")  # ticked off four days late
    for uid in (fixed, filt, pill):
        await _done(hass, uid)
    assert _when(manager.find(fixed)) == "2026-12-10T09:00"  # the schedule
    assert _when(manager.find(filt)) == "2027-02-14T09:00"  # 3 months from the day it was done, usual time
    assert _when(manager.find(pill)) == "2026-11-15T04:30"  # 8 h from now
    # not used with weekdays
    both = await add_task(hass, summary="Gym", start="2026-11-16 18:00:00", repeat="weekly", repeat_days=["mon"], repeat_from_done=True)
    freezer.move_to("2026-11-19 10:00:00+01:00")
    await _done(hass, both)
    assert _when(manager.find(both)) == "2026-11-23T18:00"
    # the To-do list says how it repeats
    items = {i.summary: i.description for i in hass.data["entity_components"]["todo"].get_entity("todo.remindo").todo_items}
    assert items["Gym"] == "🔁 every week: Mon"
    assert items["Filter"] == "🔁 every 3 months (from ticking off)"
