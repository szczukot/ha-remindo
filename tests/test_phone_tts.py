"""Android phones that read the reminder aloud (Companion app: message "TTS")."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from .common import add_task, setup_integration, tick


def _spoken(calls) -> list[dict]:
    return [c.data["data"] for c in calls["notify"] if c.data.get("message") == "TTS"]


async def test_phone_reads_the_reminder(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 15:00:00+01:00")
    _, calls = await setup_integration(hass, phone_tts=["notify.mobile_app_test"], phone_tts_stream="alarm_stream")
    hass.states.async_set("group.people_in_home", "not_home")  # the phone is with its owner
    await add_task(hass, summary="Take out the bins", tts_message="Bins, please")
    await tick(hass, freezer, seconds=2)
    assert _spoken(calls) == [{"tts_text": "Bins, please", "media_stream": "alarm_stream"}]
    # the normal push with buttons is still sent
    assert any(c.data.get("message") == "Take out the bins" for c in calls["notify"])


async def test_phone_reading_only_when_chosen(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 15:00:00+01:00")
    _, calls = await setup_integration(hass)
    await add_task(hass, summary="Not chosen in the settings")
    await tick(hass, freezer, seconds=2)
    assert calls["notify"] and _spoken(calls) == []


async def test_phone_reading_not_at_night_or_for_silent_tasks(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 23:00:00+01:00")
    _, calls = await setup_integration(hass, phone_tts=["notify.mobile_app_test"])
    await add_task(hass, summary="Quiet hours", key="night")
    await tick(hass, freezer, seconds=2)
    assert calls["notify"] and _spoken(calls) == []
    freezer.move_to("2026-11-19 15:00:00+01:00")
    await add_task(hass, summary="Not spoken", key="silent", tts=False)
    await tick(hass, freezer, seconds=2)
    assert any(c.data.get("message") == "Not spoken" for c in calls["notify"])
    # by day the night's task is read again at its next reminder; the silent one never is
    assert "Not spoken" not in [d["tts_text"] for d in _spoken(calls)]


async def test_phone_reads_the_default_stream(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18 15:00:00+01:00")
    _, calls = await setup_integration(hass, phone_tts=["mobile_app_test"])
    await add_task(hass, summary="Water the plants")
    await tick(hass, freezer, seconds=2)
    assert _spoken(calls) == [{"tts_text": "Water the plants", "media_stream": "music_stream"}]


async def test_only_android_phones_are_offered(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry, _ = await setup_integration(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "phone_tts" not in flow["data_schema"].schema  # no phone app known
    MockConfigEntry(domain="mobile_app", title="Test", data={"device_name": "Test", "os_name": "iOS"}).add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "phone_tts" not in flow["data_schema"].schema
    MockConfigEntry(domain="mobile_app", title="Test", data={"device_name": "Test", "os_name": "Android"}).add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "phone_tts" in flow["data_schema"].schema
