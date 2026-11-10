/* Lovelace card: custom:remindo-card (Remindo integration) */
const VERSION = "0.9.0";

const I18N = {
  en: {
    title: "Tasks", today: "today", tomorrow: "tomorrow", just_now: "just now", min_ago: "{n} min ago", h_ago: "{n} h ago", d_ago: "{n} d ago",
    now: "now", now_again: "now · again {t}", now_no_more: "now · no more reminders", dismissed_ago: "skipped {t}", snoozed_until: "snoozed until ",
    done_ago: "done {t}", reminding_since: "reminding since {t}", every_min: "every {n} min", then_every: "then every {n} min again", snooze_hint: "Remind in {t}", snooze_hint_then: "Remind in {t}, then every {n} min again", snoozed_n: "snoozed {n}×",
    max_n: "max {n}× (so far {m})", until: "reminds until {t}", no_notify: "no notifications",
    btn_done: "Done", btn_tomorrow: "tomorrow {t}", btn_tomorrow_hint: "Remind again tomorrow at {t}", btn_tomorrow_hint_then: "Remind again tomorrow at {t}, then every {n} min again", btn_pick: "📅 pick…", btn_pick_hint: "Pick when to remind again", pick_label: "Remind again:", pick_ok: "Snooze", pick_past: "Pick a time in the future", btn_dismiss: "Skip",
    sec_now: "Now", sec_planned: "Scheduled", sec_notes: "Notes", sec_done: "Done", sec_dismissed: "Skipped", empty: "Nothing to do 🎉",
    add: "＋ Add task", what: "What needs doing?", remind: "Remind", from_now: "from now", in_1h: "in 1 h", tonight: "today 19:00",
    pick: "pick a time…", every: "every", until_done: "until I tick it off", note_hint: "no reminders — just a note on the list",
    stop: "stop reminding:", stop_never: "never (until ticked off)", stop_count: "after … times", stop_until: "at a specific time",
    repeat: "Repeat", repeat_hint: "after ticking off it comes back at the next due time", where: "Remind on:",
    where_hint: "🔊 speaks only when someone is home and outside quiet hours", cancel: "Cancel", save: "Add",
    repeat_needs_start: "A recurring task needs a due time", keep: "Keep on the list after done", keep_hint: "off = disappears once ticked off",
    u_min: ["minute", "minutes", "minutes"], u_hour: ["hour", "hours", "hours"], u_day: ["day", "days", "days"],
    u_week: ["week", "weeks", "weeks"], u_month: ["month", "months", "months"], u_year: ["year", "years", "years"],
    description: "Task list with reminders: tick off, snooze, add",
  },
  pl: {
    title: "Zadania", today: "dziś", tomorrow: "jutro", just_now: "przed chwilą", min_ago: "{n} min temu", h_ago: "{n} h temu", d_ago: "{n} d temu",
    now: "teraz", now_again: "teraz · znowu {t}", now_no_more: "teraz · już nie przypomina", dismissed_ago: "odrzucone {t}", snoozed_until: "odłożone do ",
    done_ago: "zrobione {t}", reminding_since: "przypomina od {t}", every_min: "co {n} min", then_every: "potem znowu co {n} min", snooze_hint: "Przypomnij za {t}", snooze_hint_then: "Przypomnij za {t}, potem znowu co {n} min", snoozed_n: "odłożone {n}×",
    max_n: "maks. {n}× (było {m})", until: "przypomina do {t}", no_notify: "bez powiadomień",
    btn_done: "Zrobione", btn_tomorrow: "jutro {t}", btn_tomorrow_hint: "Przypomnij jutro o {t}", btn_tomorrow_hint_then: "Przypomnij jutro o {t}, potem znowu co {n} min", btn_pick: "📅 wybierz…", btn_pick_hint: "Wybierz, kiedy przypomnieć ponownie", pick_label: "Przypomnij ponownie:", pick_ok: "Odłóż", pick_past: "Wybierz termin w przyszłości", btn_dismiss: "Nie robię",
    sec_now: "Teraz", sec_planned: "Zaplanowane", sec_notes: "Notatki", sec_done: "Zrobione", sec_dismissed: "Odrzucone", empty: "Nic do zrobienia 🎉",
    add: "＋ Dodaj zadanie", what: "Co trzeba zrobić?", remind: "Przypominaj", from_now: "od teraz", in_1h: "za 1 h", tonight: "dziś 19:00",
    pick: "wybierz termin…", every: "co", until_done: "dopóki nie odhaczę", note_hint: "bez przypomnień — zwykła notatka na liście",
    stop: "przestań przypominać:", stop_never: "nigdy (aż odhaczę)", stop_count: "po … razach", stop_until: "o konkretnej porze",
    repeat: "Powtarzaj", repeat_hint: "po odhaczeniu wróci w następnym terminie", where: "Gdzie przypominać:",
    where_hint: "🔊 mówi tylko, gdy ktoś jest w domu i nie trwa cisza nocna", cancel: "Anuluj", save: "Dodaj",
    repeat_needs_start: "Zadanie cykliczne musi mieć termin", keep: "Zostaw na liście po wykonaniu", keep_hint: "wyłączone = znika po odhaczeniu",
    u_min: ["minutę", "minuty", "minut"], u_hour: ["godzinę", "godziny", "godzin"], u_day: ["dzień", "dni", "dni"],
    u_week: ["tydzień", "tygodnie", "tygodni"], u_month: ["miesiąc", "miesiące", "miesięcy"], u_year: ["rok", "lata", "lat"],
    description: "Lista zadań z przypomnieniami: odhaczanie, odkładanie, dodawanie",
  },
};
let LANG = "en";
const pickLang = (hass) => {
  const l = String(hass?.locale?.language || hass?.language || navigator.language || "en").toLowerCase();
  return l.startsWith("pl") ? "pl" : "en";
};
const t = (key, vars = {}) => String((I18N[LANG] || I18N.en)[key] ?? I18N.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const plural = (n, forms) => {
  if (LANG !== "pl") return n === 1 ? forms[0] : forms[2];
  return forms[n === 1 ? 0 : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) ? 1 : 2];
};
const forms = (key) => (I18N[LANG] || I18N.en)[key] || I18N.en[key];
const locale = () => (LANG === "pl" ? "pl-PL" : undefined);

const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const hm = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `${t("today")} ${hm}`;
  if (d.toDateString() === tomorrow.toDateString()) return `${t("tomorrow")} ${hm}`;
  const opts = { day: "numeric", month: "short" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(locale(), opts) + ` ${hm}`;
};
const UNIT = { hourly: "u_hour", daily: "u_day", weekly: "u_week", monthly: "u_month", yearly: "u_year" };
const repeatLabel = (task) => {
  const n = Number(task.repeat_every || 1);
  const f = forms(UNIT[task.repeat]) || [task.repeat, task.repeat, task.repeat];
  return n <= 1 ? `${t("every")} ${f[0]}` : `${t("every")} ${n} ${plural(n, f)}`;
};
const hm = (iso) => (iso ? new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" }) : "");
const ago = (iso) => {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return t("just_now");
  if (min < 60) return t("min_ago", { n: min });
  const h = Math.floor(min / 60);
  return h < 24 ? t("h_ago", { n: h }) : t("d_ago", { n: Math.floor(h / 24) });
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const localIso = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
const tomorrowDate = () => { const d = new Date(); d.setDate(d.getDate() + 1); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

class RemindoCard extends HTMLElement {
  setConfig(config) {
    this._config = { show_done: true, show_form: true, ...config };
    this._tasks = [];
    this._formOpen = false;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const lang = pickLang(hass);
    if (lang !== LANG) { LANG = lang; this._forceRender = !this._formOpen; this._render(); }
    if (first || !this._unsub) this._subscribe();
  }

  connectedCallback() { if (this._hass && !this._unsub) this._subscribe(); this._tick = setInterval(() => this._render(), 60000); }
  disconnectedCallback() {
    clearInterval(this._tick);
    if (this._unsub) { this._unsub.then((u) => u()).catch(() => {}); this._unsub = null; }
  }

  _subscribe() {
    if (!this._hass || this._unsub) return;
    this._unsub = this._hass.connection
      .subscribeMessage((msg) => { this._tasks = msg.tasks || []; this._dismissed = msg.dismissed || []; this._opts = msg.options || {}; this._error = null; this._render(); },
        { type: "remindo/subscribe" })
      .catch((err) => { this._error = err.message || String(err); this._unsub = null; this._render(); setTimeout(() => this._subscribe(), 15000); });
  }

  getCardSize() { return 3 + this._tasks.length; }
  static getStubConfig() { return {}; }

  async _call(service, data) {
    try { await this._hass.callService("remindo", service, data); }
    catch (err) { this._error = err.message || String(err); this._render(); }
  }

  _groups() {
    const open = this._tasks.filter((t) => t.status === "open");
    const by = (k) => (a, b) => (a[k] || "9999").localeCompare(b[k] || "9999");
    return {
      now: open.filter((t) => t.active).sort(by("last_reminded")),
      planned: open.filter((t) => !t.active && t.start).sort(by("next_reminder")),
      notes: open.filter((t) => !t.start).sort(by("created")),
      done: this._tasks.filter((t) => t.status === "done").sort((a, b) => (b.closed || "").localeCompare(a.closed || "")).slice(0, 5),
    };
  }

  _row(task, kind) {
    // Most important: when. The rest in small print.
    let when = "";
    if (kind === "now") when = task.next_reminder ? t("now_again", { t: new Date(task.next_reminder).toDateString() === new Date().toDateString() ? hm(task.next_reminder) : fmtTime(task.next_reminder) }) : (task.interval ? t("now_no_more") : t("now"));
    else if (kind === "dismissed") when = t("dismissed_ago", { t: ago(task.at) });
    else if (kind === "planned") when = (task.snoozes && task.last_reminded ? t("snoozed_until") : "") + fmtTime(task.next_reminder || task.start);
    else if (kind === "done") when = t("done_ago", { t: ago(task.closed) });
    const meta = [];
    if (kind === "now") meta.push(t("reminding_since", { t: ago(task.last_reminded) }));
    if (task.interval && kind !== "done" && kind !== "notes") meta.push(t(kind === "planned" ? "then_every" : "every_min", { n: task.interval }));
    if (task.repeat && task.repeat !== "none") meta.push(`🔁 ${repeatLabel(task)}`);
    if (task.snoozes) meta.push(t("snoozed_n", { n: task.snoozes }));
    if (task.max_reminders && kind !== "done") meta.push(t("max_n", { n: task.max_reminders, m: task.reminders || 0 }));
    if (task.remind_until && kind !== "done") meta.push(t("until", { t: fmtTime(task.remind_until) }));
    if (kind !== "done" && kind !== "notes") {
      const where = [...(task.phone_labels || []).map((n) => `📱 ${n}`), ...(task.speaker_labels || []).map((n) => `🔊 ${n}`)];
      meta.push(where.length ? where.join(", ") : t("no_notify"));
    }
    const hint = (when) => t(task.interval ? "snooze_hint_then" : "snooze_hint", { t: when, n: task.interval });
    const btns = kind === "done" || kind === "dismissed" ? "" : `
      <div class="btns">
        <button class="ok" data-a="done" data-uid="${task.uid}" title="${t("btn_done")}">✓</button>
        ${kind !== "notes" ? `
        <button data-a="snooze" data-min="10" data-uid="${task.uid}" title="${hint("10 min")}">+10 min</button>
        <button data-a="snooze" data-min="60" data-uid="${task.uid}" title="${hint("1 h")}">+1 h</button>
        <button data-a="tomorrow" data-uid="${task.uid}" title="${t(task.interval ? "btn_tomorrow_hint_then" : "btn_tomorrow_hint", { t: this._morning(), n: task.interval })}">${t("btn_tomorrow", { t: this._morning() })}</button>
        <button data-a="pick" data-uid="${task.uid}" title="${t("btn_pick_hint")}">${t("btn_pick")}</button>` : ""}
        <button class="no" data-a="dismiss" data-uid="${task.uid}" title="${t("btn_dismiss")}">✕</button>
      </div>`;
    return `<div class="task ${kind}">
      <div class="txt"><div class="sum">${esc(task.summary)}</div>
        ${when ? `<div class="when">${esc(when)}</div>` : ""}
        ${task.description ? `<div class="desc">${esc(task.description)}</div>` : ""}
        <div class="meta">${esc(meta.join(" · "))}</div></div>${btns}${this._pick === task.uid ? this._picker(task) : ""}</div>`;
  }

  _morning() {
    return String(this._opts?.default_time || "09:00").slice(0, 5);
  }

  _picker(task) {
    const d = new Date(Date.now() + 3600e3);
    d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0);
    const min = localIso(new Date()).slice(0, 16);
    return `<div class="picker">
      <span>${t("pick_label")}</span>
      <input id="p-dt" type="datetime-local" min="${min}" value="${localIso(d).slice(0, 16)}" />
      <button class="ok" data-a="pick-ok" data-uid="${task.uid}">${t("pick_ok")}</button>
      <button data-a="pick-cancel">${t("cancel")}</button>
      ${task.interval ? `<span>${t("then_every", { n: task.interval })}</span>` : ""}
    </div>`;
  }

  _section(title, list, kind) {
    if (!list.length) return "";
    this._collapsed = this._collapsed || { done: true, dismissed: true };
    const closed = !!this._collapsed[kind];
    return `<div class="sec"><div class="sec-title" data-a="sec" data-k="${kind}">${closed ? "▸" : "▾"} ${title} <span>${list.length}</span></div>${closed ? "" : list.map((task) => this._row(task, kind)).join("")}</div>`;
  }

  _form() {
    if (!this._config.show_form) return "";
    if (!this._formOpen) return `<button class="add-btn" data-a="form">${t("add")}</button>`;
    const di = Number(this._opts?.default_interval ?? 30) || 30;
    return `<div class="form">
      <input id="f-sum" placeholder="${t("what")}" />
      <div class="frow">
        <label class="chk"><input type="checkbox" id="f-rem" checked /> ${t("remind")}</label>
        <span class="grp" id="f-rem-g"><select id="f-when">
          <option value="now">${t("from_now")}</option>
          <option value="1h">${t("in_1h")}</option>
          <option value="evening">${t("tonight")}</option>
          <option value="custom">${t("pick")}</option>
        </select>
        <input id="f-dt" type="datetime-local" style="display:none" />
        ${t("every")} <input id="f-int" type="number" min="1" value="${di % 60 === 0 ? di / 60 : di}" />
          <select id="f-int-u"><option value="1"${di % 60 === 0 ? "" : " selected"}></option><option value="60"${di % 60 === 0 ? " selected" : ""}></option></select></span>
        <span class="hint" id="f-rem-h">${t("until_done")}</span>
        <span class="hint" id="f-note-h" style="display:none">${t("note_hint")}</span>
      </div>
      <div class="frow" id="f-lim-row"><span class="chk"></span>
        <span class="grp">${t("stop")} <select id="f-lim"><option value="">${t("stop_never")}</option><option value="count">${t("stop_count")}</option><option value="until">${t("stop_until")}</option></select>
          <input id="f-lim-n" type="number" min="1" value="3" style="display:none" />
          <input id="f-lim-dt" type="datetime-local" style="display:none" /></span>
      </div>
      <div class="frow">
        <label class="chk"><input type="checkbox" id="f-rep-on" /> ${t("repeat")}</label>
        <span class="grp off" id="f-rep-g">${t("every")} <input id="f-every" type="number" min="1" value="1" />
          <select id="f-rep"><option value="hourly"></option><option value="daily" selected></option><option value="weekly"></option><option value="monthly"></option><option value="yearly"></option></select></span>
        <span class="hint" id="f-rep-h">${t("repeat_hint")}</span>
      </div>
      <div class="frow where" id="f-where">
        <span>${t("where")}</span>
        ${(this._opts?.phones || []).map((p) => `<label><input type="checkbox" class="f-phone" value="${esc(p.id)}" checked /> 📱 ${esc(p.name)}</label>`).join("")}
        ${(this._opts?.speakers || []).map((s) => `<label><input type="checkbox" class="f-spk" value="${esc(s.id)}" checked /> 🔊 ${esc(s.name)}</label>`).join("")}
      </div>
      <div class="hint" id="f-where-h">${t("where_hint")}</div>
      <div class="frow" id="f-keep-row">
        <label><input type="checkbox" id="f-keep" ${this._opts?.keep_done === false ? "" : "checked"} /> ${t("keep")}</label>
        <span class="hint">${t("keep_hint")}</span>
      </div>
      <div class="frow end">
        <button data-a="cancel">${t("cancel")}</button>
        <button class="ok" data-a="save">${t("save")}</button>
      </div></div>`;
  }

  _save() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const summary = $("f-sum").value.trim();
    if (!summary) { $("f-sum").focus(); return; }
    const when = $("f-when").value;
    const d = new Date();
    let start = "now";
    if (when === "1h") start = localIso(new Date(Date.now() + 3600e3));
    else if (when === "evening") { d.setHours(19, 0, 0, 0); start = localIso(d); }
    else if (when === "custom") start = $("f-dt").value ? `${$("f-dt").value}:00` : "now";
    if (!$("f-rem").checked) start = null;
    const pick = (cls) => [...this.shadowRoot.querySelectorAll(cls)].filter((c) => c.checked).map((c) => c.value);
    const interval = $("f-rem").checked ? Math.max(1, Number($("f-int").value || 1)) * Number($("f-int-u").value) : 0;
    const data = { summary, start, interval, phones: pick(".f-phone"), speakers: pick(".f-spk") };
    if (interval && $("f-lim").value === "count") data.max_reminders = Math.max(1, Number($("f-lim-n").value || 1));
    if (interval && $("f-lim").value === "until" && $("f-lim-dt").value) data.remind_until = `${$("f-lim-dt").value}:00`;
    data.keep_done = $("f-keep").checked;
    const rep = $("f-rep-on").checked ? $("f-rep").value : "none";
    if (rep !== "none") {
      if (start === null) { this._error = t("repeat_needs_start"); this._render(); return; }
      data.repeat = rep; data.repeat_every = Number($("f-every").value || 1);
    }
    this._formOpen = false;
    this._call("add", data);
  }

  _onClick(ev) {
    const b = ev.target.closest("button, .sec-title");
    if (!b) return;
    const uid = b.dataset.uid;
    switch (b.dataset.a) {
      case "done": return this._call("done", { uid });
      case "dismiss": return this._call("dismiss", { uid });
      case "snooze": return this._call("snooze", { uid, minutes: Number(b.dataset.min) });
      case "tomorrow": return this._call("snooze", { uid, until: `${tomorrowDate()}T${this._morning()}:00` });
      case "pick": this._pick = this._pick === uid ? null : uid; this._forceRender = true; this._render();
        return this.shadowRoot.getElementById("p-dt")?.focus();
      case "pick-cancel": this._pick = null; this._forceRender = true; return this._render();
      case "pick-ok": {
        const v = this.shadowRoot.getElementById("p-dt")?.value;
        if (!v || new Date(v) <= new Date()) { this._error = t("pick_past"); this._forceRender = true; return this._render(); }
        this._pick = null;
        return this._call("snooze", { uid, until: `${v}:00` });
      }
      case "form": this._formOpen = true; this._render(); this._unit(); return this.shadowRoot.getElementById("f-sum")?.focus();
      case "cancel": this._formOpen = false; this._forceRender = true; return this._render();
      case "save": return this._save();
      case "err": this._error = null; this._forceRender = true; return this._render();
      case "sec": this._collapsed[b.dataset.k] = !this._collapsed[b.dataset.k]; this._forceRender = true; return this._render();
    }
  }

  _onChange(ev) {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (ev.target.id === "f-when") $("f-dt").style.display = ev.target.value === "custom" ? "" : "none";
    this._unit();
  }

  _unit() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (!$("f-rem")) return;
    const label = (sel, n, map) => [...sel.options].forEach((o) => { o.textContent = plural(n, map[o.value]); });
    const on = (chk, grp, hint) => { $(grp).classList.toggle("off", !$(chk).checked); $(grp).querySelectorAll("input,select").forEach((e) => { e.disabled = !$(chk).checked; }); $(hint).style.visibility = $(chk).checked ? "" : "hidden"; };
    label($("f-int-u"), Number($("f-int").value || 1), { 1: forms("u_min"), 60: forms("u_hour") });
    label($("f-rep"), Number($("f-every").value || 1), { hourly: forms("u_hour"), daily: forms("u_day"),
      weekly: forms("u_week"), monthly: forms("u_month"), yearly: forms("u_year") });
    on("f-rem", "f-rem-g", "f-rem-h");
    $("f-rep-on").disabled = !$("f-rem").checked;
    if (!$("f-rem").checked) $("f-rep-on").checked = false;
    on("f-rep-on", "f-rep-g", "f-rep-h");
    $("f-note-h").style.display = $("f-rem").checked ? "none" : "";
    $("f-rem-h").style.display = $("f-rem").checked ? "" : "none";
    for (const id of ["f-where", "f-where-h", "f-lim-row"]) $(id).style.display = $("f-rem").checked ? "" : "none";
    $("f-keep-row").style.display = $("f-rep-on").checked ? "none" : "";
    $("f-lim-n").style.display = $("f-lim").value === "count" ? "" : "none";
    $("f-lim-dt").style.display = $("f-lim").value === "until" ? "" : "none";
  }


  _render() {
    if (!this.shadowRoot || !this._config) return;
    // Do not interrupt typing in the form (the list refreshes after it closes)
    if (this._formOpen && this.shadowRoot.querySelector(".form") && !this._forceRender) return;
    // Do not close the date picker while the user is choosing
    if (this._pick && this.shadowRoot.getElementById("p-dt") && !this._forceRender) return;
    this._forceRender = false;
    const g = this._groups();
    const empty = !g.now.length && !g.planned.length && !g.notes.length;
    this.shadowRoot.innerHTML = `<style>${RemindoCard.styles}</style>
      <ha-card>
        <div class="head"><span>${esc(this._config.title ?? t("title"))}</span>${g.now.length ? `<span class="badge">${g.now.length}</span>` : ""}
</div>
        ${this._error ? `<div class="err">${esc(this._error)} <button data-a="err">OK</button></div>` : ""}
        ${this._section(t("sec_now"), g.now, "now")}
        ${this._section(t("sec_planned"), g.planned, "planned")}
        ${this._section(t("sec_notes"), g.notes, "notes")}
        ${empty ? `<div class="empty">${t("empty")}</div>` : ""}
        ${this._config.show_done ? this._section(t("sec_done"), g.done, "done") : ""}
        ${this._config.show_done ? this._section(t("sec_dismissed"), [...(this._dismissed || [])].reverse().slice(0, 10), "dismissed") : ""}
        ${this._form()}
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").onclick = (e) => this._onClick(e);
    this.shadowRoot.querySelector("ha-card").onchange = (e) => this._onChange(e);
    const sum = this.shadowRoot.getElementById("f-sum");
    if (sum) { sum.onkeydown = (e) => { if (e.key === "Enter") this._save(); }; this._unit(); }
  }
}

RemindoCard.styles = `
  ha-card { padding: 12px 16px 16px; }
  .head { display:flex; align-items:center; gap:8px; font-size:20px; font-weight:500; margin-bottom:8px; }
  .badge { background: var(--error-color, #db4437); color:#fff; border-radius:12px; padding:0 9px; font-size:14px; line-height:22px; }
  .sec { margin-top: 10px; }
  .sec-title { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color: var(--secondary-text-color); margin-bottom:4px; cursor:pointer; user-select:none; padding:4px 0; }
  .task.dismissed .sum { text-decoration: line-through; opacity:.6; }
  .task.dismissed .when { font-weight:400; color: var(--secondary-text-color); }
  .sec-title span { opacity:.7; }
  .task { display:flex; align-items:center; gap:10px; padding:10px 8px; border-radius:10px; border-left:4px solid transparent; flex-wrap:wrap; }
  .task + .task { border-top: 1px solid var(--divider-color); }
  .task.now { border-left-color: var(--warning-color, #ff9800); background: color-mix(in srgb, var(--warning-color, #ff9800) 8%, transparent); }
  .task.done .sum { text-decoration: line-through; opacity:.6; }
  .txt { flex:1 1 220px; min-width:0; }
  .sum { font-size:18px; font-weight:500; line-height:1.25; }
  .when { font-size:15px; font-weight:600; color: var(--primary-color); margin-top:2px; }
  .task.now .when { color: var(--warning-color, #ff9800); }
  .task.done .when { font-weight:400; color: var(--secondary-text-color); }
  .desc { font-size:13px; color: var(--secondary-text-color); white-space: pre-line; }
  .meta { font-size:11px; color: var(--secondary-text-color); opacity:.75; margin-top:3px; }
  .btns { display:flex; gap:6px; flex-wrap:wrap; }
  button { font: inherit; font-size:14px; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color);
           border-radius:8px; padding:8px 12px; cursor:pointer; min-height:40px; }
  button:hover { background: var(--secondary-background-color); }
  button.ok { background: var(--success-color, #43a047); border-color: transparent; color:#fff; min-width:44px; }
  button.no { color: var(--error-color, #db4437); min-width:44px; }
  .empty { padding:16px 0; text-align:center; color: var(--secondary-text-color); }
  .add-btn { width:100%; margin-top:12px; }
  .form { margin-top:12px; display:flex; flex-direction:column; gap:8px; }
  .frow { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .frow.end { justify-content:flex-end; }
  input, select { font: inherit; font-size:15px; padding:8px; border-radius:8px; border:1px solid var(--divider-color);
                  background: var(--card-background-color); color: var(--primary-text-color); }
  #f-sum { width:100%; box-sizing:border-box; }
  .hint { font-size:12px; color: var(--secondary-text-color); }
  .chk { min-width:120px; font-weight:500; }
  .grp { display:inline-flex; gap:6px; align-items:center; flex-wrap:wrap; max-width:100%; min-width:0; }
  input[type=datetime-local] { max-width:100%; min-width:0; box-sizing:border-box; }
  .grp.off { opacity:.4; }
  input[type=number] { width:64px; }
  input[type=checkbox] { width:18px; height:18px; vertical-align:middle; }
  .picker { flex-basis:100%; display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding-top:6px; }
  .picker span { font-size:13px; color: var(--secondary-text-color); }
  .err { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); padding:8px; border-radius:8px; margin-bottom:8px; }
`;

if (!customElements.get("remindo-card")) {
  customElements.define("remindo-card", RemindoCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "remindo-card", name: "Remindo", description: I18N[pickLang({ language: document.documentElement.lang })].description, preview: false });
  console.info(`%c REMINDO-CARD %c ${VERSION} `, "background:#43a047;color:#fff", "");
}
