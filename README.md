# Remindo — zadania z przypomnieniami dla Home Assistant

[🇬🇧 English summary below](#english)

Integracja do Home Assistant, która zamienia „pamiętaj, żeby…” w zadania, które **same przypominają**, dopóki ich nie odhaczysz.

- 📋 **Lista zadań** (`todo.remindo`), widoczna też w standardowej karcie To-do i kalendarzu.
- ⏰ **Przypomnienia co X minut/godzin**, aż zareagujesz, z limitem („maks. 3 razy” albo „do 22:00”).
- 📱 **Push na telefony** z przyciskami ✅ Zrobione / ⏰ Odłóż / ❌ Nie robię. Powiadomienie znika ze wszystkich telefonów po każdej akcji.
- 🔊 **Komunikat głosowy** (TTS) na tablecie lub głośniku, tylko gdy ktoś jest w domu i poza ciszą nocną.
- 🔁 **Zadania cykliczne**: co N godzin / dni / tygodni / miesięcy / lat (np. „filtr rekuperatora co 3 miesiące”).
- 🤖 **Reguły**: zadanie dodaje się samo, gdy urządzenie osiągnie stan (zmywarka skończyła, brama otwarta 10 min, wilgotność > 70%) albo dzień przed wydarzeniem w kalendarzu (wywóz śmieci). Zamyka się samo, gdy warunek minie.
- 🗂️ **Karta Lovelace** dostarczana z integracją: Teraz / Zaplanowane / Notatki / Zrobione / Odrzucone, odkładanie jednym kliknięciem, ręczne dodawanie zadań.

## Instalacja

Wymaga Home Assistant **2026.11** lub nowszego.

### Marketplace (zalecane)
1. *Ustawienia → **Marketplace*** → menu **⋮** → **Dodaj z linku**.
2. Wklej `https://github.com/szczukot/ha-remindo` → **Remindo** → **Zainstaluj**.
3. Zrestartuj Home Assistant, gdy pojawi się prośba w *Ustawienia → System → Naprawy*.
4. *Ustawienia → Urządzenia i usługi → Dodaj integrację → **Remindo***.

### Ręcznie
Skopiuj folder `custom_components/remindo` do `/config/custom_components/` (np. przez dodatek File editor albo Samba), zrestartuj HA i dodaj integrację **Remindo** jak w kroku 4.

## Konfiguracja

Przy dodawaniu integracji (i później w *Konfiguruj*) ustawiasz:

| Opcja | Opis |
|---|---|
| Telefony | encje `notify.mobile_app_*`, na które idzie push |
| Powiadomienie w HA | dodatkowo dzwoneczek w HA |
| Silnik TTS, głośniki/tablety | gdzie mówić komunikaty |
| Włącz ekran tabletu | np. `switch.<tablet>_screen` z Fully Kiosk |
| Obecność | np. `group.domownicy`; głos tylko gdy ktoś jest w domu |
| Cisza nocna | bez komunikatów głosowych (push nadal przychodzi) |
| Domyślny interwał, godzina dla zadań z samą datą, odłożenie z telefonu | |
| Po kliknięciu powiadomienia otwórz | np. `/lovelace/remindo` |

## Karta

Ładuje się automatycznie z integracją (bez dodawania zasobu). W „Dodaj kartę” wybierz **Remindo**:

```yaml
type: custom:remindo-card
title: Zadania
show_done: true    # sekcje Zrobione / Odrzucone (zwinięte)
show_form: true    # przycisk „＋ Dodaj zadanie”
```

Formularz dodawania:

```
☑ Przypominaj  [od teraz ▾]  co [30] [minut ▾]   dopóki nie odhaczę
               przestań przypominać: [nigdy ▾ / po … razach / o konkretnej porze]
☐ Powtarzaj                  co [5]  [dni ▾]     po odhaczeniu wróci w następnym terminie
Gdzie przypominać: ☑ 📱 telefon  ☑ 🔊 tablet
```

Odznaczone „Przypominaj” = zwykła notatka na liście.

## Reguły (zadania dodawane automatycznie)

*Ustawienia → Urządzenia i usługi → Remindo → **＋ Dodaj regułę***. Trzy kroki:

1. **Kiedy**: treść zadania, encja, warunek (*ma stan* / *powyżej* / *poniżej* / *wydarzenie w kalendarzu*).
2. **Warunek**: wartość (lista stanów encji) i „przez co najmniej N min”; dla kalendarza: ile dni przed i o której.
3. **Przypomnienia**: ponawianie, limit, telefony, głośniki, „zamknij samo, gdy warunek minie”.

Przykłady:

| Reguła | Ustawienia |
|---|---|
| Wypakuj zmywarkę | `sensor.zmywarka_operation_state` ma stan `finished`; zamyka się samo po otwarciu |
| Zamknij bramę garażową | `binary_sensor.brama` ma stan `on` przez 10 min; co 10 min, maks. 6 razy |
| Wystaw śmietnik | `calendar.odpady`, 1 dzień przed, 18:00 → „Wystaw śmietnik: Papier, Szkło” |
| Przewietrz łazienkę | `sensor.wilgotnosc_lazienka` powyżej 70 przez 15 min |

Przejście przez `unavailable` / `unknown` (restart HA, zanik Wi-Fi) nigdy nie wyzwala reguły.

## Usługi (do automatyzacji i skryptów)

| Usługa | Pola |
|---|---|
| `remindo.add` | `summary`, `description`, `start` (`now` / data / data z godziną / puste = notatka), `interval` (min, 0 = raz), `max_reminders`, `remind_until`, `key`, `repeat` (`none`/`hourly`/`daily`/`weekly`/`monthly`/`yearly`), `repeat_every`, `phones`, `speakers`, `tts_message`, `push`, `tts`. Zwraca `uid`. |
| `remindo.done`, `remindo.dismiss` | `uid` albo `key` |
| `remindo.snooze` | `uid`/`key` + `minutes` albo `until` |
| `remindo.close_by_key` | `key`: zamyka zadanie (np. brama się zamknęła) |

```yaml
action: remindo.add
data:
  summary: Wymień filtr w rekuperatorze
  start: "2026-12-01"
  repeat: monthly
  repeat_every: 3
  phones: [notify.mobile_app_telefon]
  speakers: []
```

## Encje i zdarzenia

- `todo.remindo`: lista (odhaczenie w zwykłej karcie To-do zamyka zadanie i czyści powiadomienia),
- `sensor.remindo_active`: ile zadań przypomina teraz (atrybut `tasks` z nazwami),
- zdarzenia `remindo_created`, `remindo_reminded`, `remindo_done`, `remindo_snoozed`, `remindo_dismissed`, opisane po polsku w dzienniku.

## Rozwój

```bash
pip install pytest-homeassistant-custom-component
pytest
```

---

## English

**Remindo**: tasks with reminders for Home Assistant: a to-do list whose items keep reminding you (push with action buttons, optional TTS when someone is home) until you mark them done, snooze or dismiss them. Supports recurring tasks, reminder limits, per-task phone/speaker targeting, and **rules** (Settings → Devices & services → Remindo → *Add rule*) that create tasks automatically when an entity reaches a state/threshold or before a calendar event, closing them when the condition ends. Install via *Settings → Marketplace → ⋮ → Add from link* (`https://github.com/szczukot/ha-remindo`, HA 2026.11+). Ships with a Lovelace card (`custom:remindo-card`). The UI is in Polish, with English translations for the configuration screens.

## Licencja

MIT
