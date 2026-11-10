# Remindo — tasks that keep reminding you, for Home Assistant

🇬🇧 English · 🇵🇱 [Polski](README.pl.md)

A Home Assistant integration that turns "remember to…" into tasks that **keep reminding you** until you tick them off.

- 📋 **Task list** (`todo.remindo`), also visible in the standard To-do card and the calendar.
- ⏰ **Reminders every X minutes/hours** until you react, with a limit ("at most 3 times" or "until 22:00").
- 📱 **Push to phones** with ✅ Done / ⏰ Snooze / ❌ Skip buttons. After any action the notification disappears from every phone.
- 🔊 **Spoken announcement** (TTS) on a tablet or speaker, only when someone is home and outside quiet hours.
- 🔁 **Recurring tasks**: every N hours / days / weeks / months / years (e.g. "HRV filter every 3 months").
- 🤖 **Rules**: a task adds itself when a device reaches a state (dishwasher finished, garage open for 10 min, humidity > 70%) or the day before a calendar event (bin collection). It closes itself when the condition ends.
- 🗂️ **Lovelace card** shipped with the integration: Now / Scheduled / Notes / Done / Skipped, one-tap snooze, adding tasks by hand.
- 🌍 English and Polish.

## Installation

Requires Home Assistant **2026.11** or newer.

### Marketplace (recommended)
1. *Settings → **Marketplace*** → **⋮** menu → **Add from link**.
2. Paste `https://github.com/szczukot/ha-remindo` → **Remindo** → **Install**.
3. If Home Assistant asks for a restart (*Settings → System → Repairs*), restart it.
4. *Settings → Devices & services → Add integration → **Remindo*** (the Marketplace may open this step for you right after installing).

### Manual
Copy `custom_components/remindo` to `/config/custom_components/` (e.g. with the File editor or Samba add-on), restart Home Assistant and add the **Remindo** integration as in step 4.

## Configuration

When adding the integration (and later under *Configure*) you set:

| Option | Description |
|---|---|
| Push notification targets | `notify.mobile_app_*` services that receive the push |
| Persistent notification in HA | also show the bell notification in HA |
| TTS engine, media players | where announcements are spoken |
| Screen switch to turn on first | e.g. `switch.<tablet>_screen` from Fully Kiosk |
| Presence entity | e.g. a group of people; speech only when someone is home |
| Quiet hours | no spoken announcements (push still arrives) |
| Default interval, time for date-only tasks, snooze from phone | |
| Open when the notification is tapped | e.g. `/lovelace/remindo` |

## Card

Loaded automatically with the integration (no resource to add). In "Add card" pick **Remindo**:

```yaml
type: custom:remindo-card
title: Tasks       # optional, defaults to "Tasks" / "Zadania"
show_done: true    # Done / Skipped sections (collapsed)
show_form: true    # "＋ Add task" button
```

The add form:

```
☑ Remind  [from now ▾]  every [30] [minutes ▾]   until I tick it off
          stop reminding: [never ▾ / after … times / at a specific time]
☐ Repeat                every [5]  [days ▾]      after ticking off it comes back at the next due time
Remind on: ☑ 📱 phone  ☑ 🔊 tablet
```

With "Remind" unticked the task is a plain note on the list.

Snoozing a task: **+10 min**, **+1 h**, **tomorrow 09:00** (the "time for date-only tasks" option) or **📅 pick…** for any date and time. A snooze only moves the next reminder: after it the task reminds again at its normal interval (e.g. every 5 min) until you tick it off. Recurring tasks keep their schedule; after ticking off they come back at the next due time.

The card follows the language of the user's profile.

## Rules (tasks added automatically)

*Settings → Devices & services → Remindo → **＋ Add rule***. Three steps:

1. **When**: task text, entity, condition (*has state* / *above* / *below* / *calendar event*).
2. **Condition**: value (list of the entity's states) and "for at least N min"; for a calendar: how many days before and at what time.
3. **Reminders**: repeat interval, limit, phones, speakers, "close automatically when the condition ends".

Examples:

| Rule | Settings |
|---|---|
| Unload the dishwasher | `sensor.dishwasher_operation_state` has state `finished`; closes itself when the door opens |
| Close the garage | `binary_sensor.garage` has state `on` for 10 min; every 10 min, at most 6 times |
| Put the bins out | `calendar.waste`, 1 day before, 18:00 → "Put the bins out: Paper, Glass" (or put `{event}` in the text to place the event name yourself) |
| Air the bathroom | `sensor.bathroom_humidity` above 70 for 15 min |

Passing through `unavailable` / `unknown` (HA restart, Wi-Fi drop) never triggers a rule.

## Actions (for automations and scripts)

| Action | Fields |
|---|---|
| `remindo.add` | `summary`, `description`, `start` (`now` / date / date with time / empty = note), `interval` (min, 0 = once), `max_reminders`, `remind_until`, `key`, `repeat` (`none`/`hourly`/`daily`/`weekly`/`monthly`/`yearly`), `repeat_every`, `phones`, `speakers`, `tts_message`, `push`, `tts`. Returns `uid`. |
| `remindo.done`, `remindo.dismiss` | `uid` or `key` |
| `remindo.snooze` | `uid`/`key` + `minutes` or `until` |
| `remindo.close_by_key` | `key`: closes the task (e.g. the gate was closed) |

```yaml
action: remindo.add
data:
  summary: Replace the HRV filter
  start: "2026-12-01"
  repeat: monthly
  repeat_every: 3
  phones: [notify.mobile_app_phone]
  speakers: []
```

Reminders that were due while Home Assistant was down are sent about 30 seconds after it starts again.

## Entities and events

- `todo.remindo`: the list (ticking off in the regular To-do card closes the task and clears notifications),
- `sensor.remindo_active`: how many tasks are reminding right now (attribute `tasks` with their names),
- events `remindo_created`, `remindo_reminded`, `remindo_done`, `remindo_snoozed`, `remindo_dismissed`, described in the logbook.

## Language

Configuration screens, actions, error messages, push notifications and the logbook are available in English and Polish. Push, logbook and the To-do description use the language set in *Settings → System → General*; the card uses the user's profile language.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

Every push runs the tests, hassfest and repository validation on GitHub. A release is created automatically when a `vX.Y.Z` tag is pushed (it must match `version` in `manifest.json`).

## License

MIT
