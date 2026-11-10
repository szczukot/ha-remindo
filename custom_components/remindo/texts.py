"""Texts sent outside the HA frontend (push, persistent notification, logbook, todo
description). They follow the language set in Settings → System → General."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title": "📋 Task",
        "done": "✅ Done",
        "snooze": "⏰ +{minutes} min",
        "dismiss": "❌ Skip",
        "task": "Task: {summary}",
        "ev_created": "added",
        "ev_reminded": "reminded",
        "ev_done": "done",
        "ev_snoozed": "snoozed",
        "ev_dismissed": "skipped",
        "src_phone": "from phone",
        "src_card": "from card",
        "src_todo": "from To-do list",
        "src_auto": "automatically",
        "src_rule": "by rule",
        "src_expired": "date passed",
        "src_rule_removed": "rule deleted",
        "nth": ", time #{count}",
    },
    "pl": {
        "title": "📋 Zadanie",
        "done": "✅ Zrobione",
        "snooze": "⏰ +{minutes} min",
        "dismiss": "❌ Nie robię",
        "task": "Zadanie: {summary}",
        "ev_created": "dodano",
        "ev_reminded": "przypomniano",
        "ev_done": "zrobione",
        "ev_snoozed": "odłożono",
        "ev_dismissed": "nie robię",
        "src_phone": "z telefonu",
        "src_card": "z karty",
        "src_todo": "z listy To-do",
        "src_auto": "automatycznie",
        "src_rule": "z reguły",
        "src_expired": "termin minął",
        "src_rule_removed": "reguła usunięta",
        "nth": ", {count}. raz",
    },
}

# repeat unit: (one, few, many) — English uses one/many
_UNITS: dict[str, dict[str, tuple[str, str, str]]] = {
    "en": {
        "hourly": ("hour", "hours", "hours"),
        "daily": ("day", "days", "days"),
        "weekly": ("week", "weeks", "weeks"),
        "monthly": ("month", "months", "months"),
        "yearly": ("year", "years", "years"),
    },
    "pl": {
        "hourly": ("godzinę", "godziny", "godzin"),
        "daily": ("dzień", "dni", "dni"),
        "weekly": ("tydzień", "tygodnie", "tygodni"),
        "monthly": ("miesiąc", "miesiące", "miesięcy"),
        "yearly": ("rok", "lata", "lat"),
    },
}


def language(hass: HomeAssistant | None) -> str:
    lang = (getattr(getattr(hass, "config", None), "language", None) or "en").lower()
    return "pl" if lang.startswith("pl") else "en"


def text(hass: HomeAssistant | None, key: str, **kwargs) -> str:
    return _TEXTS[language(hass)][key].format(**kwargs)


def _plural_pl(n: int) -> int:
    if n == 1:
        return 0
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 1
    return 2


def repeat_label(hass: HomeAssistant | None, repeat: str, every: int) -> str:
    """'every 3 months' / 'co 3 miesiące'; 'every day' / 'co dzień'."""
    lang = language(hass)
    forms = _UNITS[lang].get(repeat, (repeat, repeat, repeat))
    word = "every" if lang == "en" else "co"
    if every <= 1:
        return f"{word} {forms[0]}"
    idx = (0 if every == 1 else 2) if lang == "en" else _plural_pl(every)
    return f"{word} {every} {forms[idx]}"
