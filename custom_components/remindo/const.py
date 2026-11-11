"""Constants for the Remindo integration."""

from __future__ import annotations

DOMAIN = "remindo"
STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN

# Options (config entry options)
CONF_NOTIFY = "notify_targets"
CONF_PERSISTENT = "persistent_notification"
CONF_TTS_ENTITY = "tts_entity"
CONF_MEDIA_PLAYER = "media_player"
CONF_SCREEN_SWITCH = "screen_switch"
CONF_PRESENCE = "presence_entity"
CONF_TTS_DEFAULT = "tts_default"
CONF_QUIET_START = "quiet_start"
CONF_QUIET_END = "quiet_end"
CONF_DEFAULT_INTERVAL = "default_interval"
CONF_DEFAULT_TIME = "default_time"
CONF_PHONE_SNOOZE = "phone_snooze"
CONF_KEEP_HISTORY = "keep_history"
CONF_CLICK_URL = "click_url"
CONF_KEEP_DONE = "keep_done"
CONF_QUIET_PUSH = "quiet_push"
CONF_NOTIFY_DATA = "notify_data"

DEFAULTS = {
    CONF_NOTIFY: [],
    CONF_PERSISTENT: True,
    CONF_TTS_DEFAULT: True,
    CONF_QUIET_START: "22:00:00",
    CONF_QUIET_END: "07:00:00",
    CONF_DEFAULT_INTERVAL: 30,
    CONF_DEFAULT_TIME: "09:00:00",
    CONF_PHONE_SNOOZE: 10,
    CONF_KEEP_HISTORY: 50,
    CONF_CLICK_URL: "/todo?entity_id=todo.remindo",
    CONF_KEEP_DONE: True,
    CONF_QUIET_PUSH: False,
}

# Service fields
ATTR_UID = "uid"
ATTR_KEY = "key"
ATTR_SUMMARY = "summary"
ATTR_DESCRIPTION = "description"
ATTR_START = "start"
ATTR_INTERVAL = "interval"
ATTR_REPEAT = "repeat"
ATTR_REPEAT_EVERY = "repeat_every"
ATTR_TTS = "tts"
ATTR_PUSH = "push"
ATTR_MINUTES = "minutes"
ATTR_UNTIL = "until"
ATTR_TTS_MESSAGE = "tts_message"
ATTR_PHONES = "phones"
ATTR_SPEAKERS = "speakers"
ATTR_MAX_REMINDERS = "max_reminders"
ATTR_REMIND_UNTIL = "remind_until"
ATTR_KEEP_DONE = "keep_done"
ATTR_DONE_MESSAGE = "done_message"
ATTR_NOTIFY_DATA = "notify_data"
ATTR_LIST = "list"

REPEAT_NONE = "none"
REPEAT_OPTIONS = [REPEAT_NONE, "hourly", "daily", "weekly", "monthly", "yearly"]

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"

# Events
EVENT_CREATED = "remindo_created"
EVENT_REMINDED = "remindo_reminded"
EVENT_DONE = "remindo_done"
EVENT_SNOOZED = "remindo_snoozed"
EVENT_DISMISSED = "remindo_dismissed"

SIGNAL_UPDATED = f"{DOMAIN}_updated"

ACTION_PREFIX = "REMINDO"
ACTION_DONE = "DONE"
ACTION_SNOOZE = "SNOOZE"
ACTION_DISMISS = "DISMISS"

CARD_URL = "/remindo_static/remindo-card.js"
