# Zadania z przypomnieniami (Home Assistant)

Lista zadań (encja `todo.zadania`), do której zadania dodają automatyzacje. Każde zadanie przypomina od podanego startu, co zadany interwał, dopóki nie odpowiesz: ✅ zrobione, ⏰ odłóż, ❌ nie robię.

## Instalacja
Skopiuj `custom_components/zadania` do `/config/custom_components/`, zrestartuj HA, dodaj integrację **Zadania z przypomnieniami** w *Ustawienia → Urządzenia i usługi*.

## Usługi
| Usługa | Pola |
|---|---|
| `zadania.add` | `summary`, `description`, `start` (`now` / data / data i godzina / puste = notatka), `interval` (min, 0 = raz), `key`, `repeat` (`none`/`daily`/`weekly`/`monthly`/`yearly`), `repeat_every`, `tts`, `tts_message`, `push`. Zwraca `uid`. |
| `zadania.done` / `zadania.dismiss` | `uid` albo `key` |
| `zadania.snooze` | `uid`/`key` + `minutes` albo `until` |
| `zadania.close_by_key` | `key` (cicho zamyka, np. brama się zamknęła) |

Zadanie cykliczne po zrobieniu (albo „nie robię”) wraca w następnym terminie.

## Przypomnienia
- push na wybrane telefony z przyciskami (znikają po każdej akcji, także po odhaczeniu na zwykłej liście To-do),
- powiadomienie w HA,
- komunikat TTS na tablecie/głośniku tylko gdy ktoś jest w domu i poza ciszą nocną.

## Zdarzenia
`zadania_created`, `zadania_reminded`, `zadania_done`, `zadania_snoozed`, `zadania_dismissed` (widoczne w dzienniku).

## Karty
Ładują się automatycznie z integracją (bez dodawania zasobu). W „Dodaj kartę” są dwie:

**Zadania – lista**: zadania do zrobienia, przyciski ✓ / odłóż / ✕, dodawanie ręczne.
```yaml
type: custom:zadania-card
title: Zadania
link: /dashboard-tablet/zadania-reguly   # opcjonalnie: przycisk „⚙ Reguły”
show_done: true                          # sekcje Zrobione / Odrzucone (zwinięte)
show_form: true                          # przycisk „＋ Dodaj zadanie”
```

**Zadania – reguły**: ustawianie „gdy coś się stanie → dodaj zadanie” (stan encji, próg liczbowy, wydarzenie w kalendarzu).
```yaml
type: custom:zadania-rules-card
title: Reguły zadań
link: /dashboard-tablet/zadania          # opcjonalnie: przycisk „← Zadania”
```

Każdą kartę można postawić na dowolnym widoku, np. listę na tablecie, a reguły na dashboardzie admina.

## Przykład: brama
```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.brama
    to: "on"
    for: "00:10:00"
    id: otwarta
  - trigger: state
    entity_id: binary_sensor.brama
    to: "off"
    id: zamknieta
actions:
  - choose:
      - conditions: [{condition: trigger, id: otwarta}]
        sequence:
          - action: zadania.add
            data: {summary: "Zamknij bramę garażową", key: brama, interval: 10}
    default:
      - action: zadania.close_by_key
        data: {key: brama}
```

## Testy
```
pip install pytest-homeassistant-custom-component
pytest
```
