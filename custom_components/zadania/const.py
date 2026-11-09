"""Stałe integracji Zadania."""

from __future__ import annotations

DOMAIN = "zadania"
STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN

# Opcje (config entry options)
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
    CONF_CLICK_URL: "/todo?entity_id=todo.zadania",
}

# Pola usług
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

REPEAT_NONE = "none"
REPEAT_OPTIONS = [REPEAT_NONE, "hourly", "daily", "weekly", "monthly", "yearly"]

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"

# Zdarzenia
EVENT_CREATED = "zadania_created"
EVENT_REMINDED = "zadania_reminded"
EVENT_DONE = "zadania_done"
EVENT_SNOOZED = "zadania_snoozed"
EVENT_DISMISSED = "zadania_dismissed"
EVENTS = [EVENT_CREATED, EVENT_REMINDED, EVENT_DONE, EVENT_SNOOZED, EVENT_DISMISSED]

SIGNAL_UPDATED = f"{DOMAIN}_updated"

ACTION_PREFIX = "ZADANIA"
ACTION_DONE = "DONE"
ACTION_SNOOZE = "SNOOZE"
ACTION_DISMISS = "DISMISS"

CARD_URL = "/zadania_static/zadania-card.js"
