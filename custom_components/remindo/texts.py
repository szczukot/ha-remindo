"""Texts sent outside the HA frontend (push, persistent notification, logbook, todo
description), from messages/<language>.json. They follow the language set in
Settings → System → General; a language without a file falls back to English."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

# read once when the integration is imported (Home Assistant imports it outside the event loop)
_MESSAGES: dict[str, dict[str, Any]] = {
    f.stem: json.loads(f.read_text("utf-8")) for f in sorted((Path(__file__).parent / "messages").glob("*.json"))
}


def language(hass: HomeAssistant | None) -> str:
    """'de-CH' → 'de' when there is no 'de-ch' file; English when the language is missing."""
    lang = (getattr(getattr(hass, "config", None), "language", None) or "en").lower()
    if lang in _MESSAGES:
        return lang
    base = lang.split("-")[0]
    return base if base in _MESSAGES else "en"


def _get(lang: str, key: str) -> Any:
    return _MESSAGES[lang].get(key, _MESSAGES["en"][key])


def text(hass: HomeAssistant | None, key: str, **kwargs) -> str:
    texts = _MESSAGES[language(hass)]["texts"]
    return texts.get(key, _MESSAGES["en"]["texts"][key]).format(**kwargs)


def advance(hass: HomeAssistant | None, summary: str, start: Any, now: Any) -> str:
    """The heads-up text: "Today at 14:30: Dentist", "Tomorrow at …", "24.11. at …"."""
    lang = language(hass)
    texts = {**_MESSAGES["en"]["texts"], **_MESSAGES[lang]["texts"]}
    clock = start.strftime("%H:%M")
    days = (start.date() - now.date()).days
    if days <= 0:
        return texts["advance_today"].format(time=clock, summary=summary)
    if days == 1:
        return texts["advance_tomorrow"].format(time=clock, summary=summary)
    day = start.strftime(_get(lang, "date_format"))
    return texts["advance_date"].format(date=day, time=clock, summary=summary)


def plural_category(lang: str, n: int) -> str:
    """CLDR plural category for whole numbers, for the languages that have files."""
    if lang == "pl":
        if n == 1:
            return "one"
        return "few" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "many"
    if lang == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


def _form(forms: dict[str, str], lang: str, n: int) -> str:
    return forms.get(plural_category(lang, n)) or forms.get("other") or forms.get("many") or forms["one"]


def repeat_label(hass: HomeAssistant | None, repeat: str, every: int) -> str:
    """'every 3 months' / 'co 3 miesiące'; 'every day' / 'co dzień'."""
    lang = language(hass)
    forms = _get(lang, "units").get(repeat) or {"other": repeat}
    word = _get(lang, "every")
    # a unit may carry its own phrases where "every" changes with it ("jeden Tag", "toutes les 3 semaines")
    if every <= 1:
        return forms.get("every_one") or f"{word} {_form(forms, lang, 1)}"
    return (forms.get("every_n") or f"{word} {{n}} {_form(forms, lang, every)}").replace("{n}", str(every))


def pattern_label(
    hass: HomeAssistant | None, task_start, repeat: str, days: list[int] | None, on: str | None, from_done: bool
) -> str:
    """The part after "every week" / "every month": ": Mon, Thu", ", 3rd Tuesday", " (from ticking off)"."""
    lang = language(hass)
    if repeat == "weekly" and days:
        return ": " + ", ".join(_get(lang, "days")[d] for d in sorted(days))
    if repeat == "monthly" and on and on != "day" and task_start is not None:
        weekday = task_start.weekday()
        if on == "last_day":
            return ", " + _get(lang, "last_day")
        nth = (task_start.day - 1) // 7 + 1
        if on == "last_weekday" or nth == 5:
            return ", " + _get(lang, "last_days")[weekday]
        template = _get(lang, "on_nth")
        if isinstance(template, list):  # one per weekday where the words depend on it
            template = template[weekday]
        return ", " + template.replace("{n}", _get(lang, "nth")[nth - 1]).replace("{day}", _get(lang, "days_full")[weekday])
    if from_done:
        return f" ({_get(lang, 'from_done')})"
    return ""
