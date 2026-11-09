/* Karta Lovelace: custom:zadania-card (integracja Zadania) */
const VERSION = "0.5.0";

const fmtTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const hm = d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `dziś ${hm}`;
  if (d.toDateString() === tomorrow.toDateString()) return `jutro ${hm}`;
  return d.toLocaleDateString("pl-PL", { day: "numeric", month: "short" }) + ` ${hm}`;
};
const ago = (iso) => {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "przed chwilą";
  if (min < 60) return `${min} min temu`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h} h temu` : `${Math.floor(h / 24)} d temu`;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const localIso = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
const tomorrowDate = () => { const d = new Date(); d.setDate(d.getDate() + 1); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

class ZadaniaCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "Zadania", show_done: true, show_form: true, ...config };
    this._tasks = [];
    this._formOpen = false;
    this._tab = "tasks";
    this._rules = [];
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
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
      .subscribeMessage((msg) => { this._tasks = msg.tasks || []; this._rules = msg.rules || []; this._dismissed = msg.dismissed || []; this._opts = msg.options || {}; this._error = null; this._render(); },
        { type: "zadania/subscribe" })
      .catch((err) => { this._error = err.message || String(err); this._unsub = null; this._render(); setTimeout(() => this._subscribe(), 15000); });
  }

  getCardSize() { return 3 + this._tasks.length; }
  static getStubConfig() { return { title: "Zadania" }; }

  async _call(service, data) {
    try { await this._hass.callService("zadania", service, data); }
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

  _row(t, kind) {
    // Najważniejsze: kiedy. Reszta drobnym drukiem.
    let when = "";
    if (kind === "now") when = t.next_reminder ? `teraz · znowu ${fmtTime(t.next_reminder).replace("dziś ", "")}` : (t.interval ? "teraz · już nie przypomina" : "teraz");
    else if (kind === "dismissed") when = `odrzucone ${ago(t.at)}`;
    else if (kind === "planned") when = (t.snoozes && t.last_reminded ? "odłożone do " : "") + fmtTime(t.next_reminder || t.start);
    else if (kind === "done") when = `zrobione ${ago(t.closed)}`;
    const meta = [];
    if (kind === "now") meta.push(`przypomina od ${ago(t.last_reminded)}`);
    if (t.interval && kind !== "done" && kind !== "notes") meta.push(`co ${t.interval} min`);
    if (t.repeat_label) meta.push(`🔁 ${t.repeat_label}`);
    if (t.snoozes) meta.push(`odłożone ${t.snoozes}×`);
    if (t.max_reminders && kind !== "done") meta.push(`maks. ${t.max_reminders}× (było ${t.reminders || 0})`);
    if (t.remind_until && kind !== "done") meta.push(`przypomina do ${fmtTime(t.remind_until)}`);
    if (kind !== "done" && kind !== "notes") {
      const where = [...(t.phone_labels || []).map((n) => `📱 ${n}`), ...(t.speaker_labels || []).map((n) => `🔊 ${n}`)];
      meta.push(where.length ? where.join(", ") : "bez powiadomień");
    }
    const btns = kind === "done" || kind === "dismissed" ? "" : `
      <div class="btns">
        <button class="ok" data-a="done" data-uid="${t.uid}" title="Zrobione">✓</button>
        ${kind !== "notes" ? `
        <button data-a="snooze" data-min="10" data-uid="${t.uid}">+10 min</button>
        <button data-a="snooze" data-min="60" data-uid="${t.uid}">+1 h</button>
        <button data-a="tomorrow" data-uid="${t.uid}">jutro</button>` : ""}
        <button class="no" data-a="dismiss" data-uid="${t.uid}" title="Nie robię">✕</button>
      </div>`;
    return `<div class="task ${kind}">
      <div class="txt"><div class="sum">${esc(t.summary)}</div>
        ${when ? `<div class="when">${esc(when)}</div>` : ""}
        ${t.description ? `<div class="desc">${esc(t.description)}</div>` : ""}
        <div class="meta">${esc(meta.join(" · "))}</div></div>${btns}</div>`;
  }

  _section(title, list, kind) {
    if (!list.length) return "";
    this._collapsed = this._collapsed || { done: true, dismissed: true };
    const closed = !!this._collapsed[kind];
    return `<div class="sec"><div class="sec-title" data-a="sec" data-k="${kind}">${closed ? "▸" : "▾"} ${title} <span>${list.length}</span></div>${closed ? "" : list.map((t) => this._row(t, kind)).join("")}</div>`;
  }

  _form() {
    if (!this._config.show_form) return "";
    if (!this._formOpen) return `<button class="add-btn" data-a="form">＋ Dodaj zadanie</button>`;
    const di = Number(this._opts?.default_interval ?? 30) || 30;
    return `<div class="form">
      <input id="f-sum" placeholder="Co trzeba zrobić?" />
      <div class="frow">
        <label class="chk"><input type="checkbox" id="f-rem" checked /> Przypominaj</label>
        <span class="grp" id="f-rem-g"><select id="f-when">
          <option value="now">od teraz</option>
          <option value="1h">za 1 h</option>
          <option value="evening">dziś 19:00</option>
          <option value="custom">wybierz termin…</option>
        </select>
        <input id="f-dt" type="datetime-local" style="display:none" />
        co <input id="f-int" type="number" min="1" value="${di % 60 === 0 ? di / 60 : di}" />
          <select id="f-int-u"><option value="1"${di % 60 === 0 ? "" : " selected"}>minut</option><option value="60"${di % 60 === 0 ? " selected" : ""}>godzin</option></select></span>
        <span class="hint" id="f-rem-h">dopóki nie odhaczę</span>
        <span class="hint" id="f-note-h" style="display:none">bez przypomnień — zwykła notatka na liście</span>
      </div>
      <div class="frow" id="f-lim-row"><span class="chk"></span>
        <span class="grp">przestań przypominać: <select id="f-lim"><option value="">nigdy (aż odhaczę)</option><option value="count">po … razach</option><option value="until">o konkretnej porze</option></select>
          <input id="f-lim-n" type="number" min="1" value="3" style="display:none" />
          <input id="f-lim-dt" type="datetime-local" style="display:none" /></span>
      </div>
      <div class="frow">
        <label class="chk"><input type="checkbox" id="f-rep-on" /> Powtarzaj</label>
        <span class="grp off" id="f-rep-g">co <input id="f-every" type="number" min="1" value="1" />
          <select id="f-rep"><option value="hourly">godzin</option><option value="daily" selected>dni</option><option value="weekly">tygodni</option><option value="monthly">miesięcy</option><option value="yearly">lat</option></select></span>
        <span class="hint" id="f-rep-h">po odhaczeniu wróci w następnym terminie</span>
      </div>
      <div class="frow where" id="f-where">
        <span>Gdzie przypominać:</span>
        ${(this._opts?.phones || []).map((p) => `<label><input type="checkbox" class="f-phone" value="${esc(p.id)}" checked /> 📱 ${esc(p.name)}</label>`).join("")}
        ${(this._opts?.speakers || []).map((s) => `<label><input type="checkbox" class="f-spk" value="${esc(s.id)}" checked /> 🔊 ${esc(s.name)}</label>`).join("")}
      </div>
      <div class="hint" id="f-where-h">🔊 mówi tylko, gdy ktoś jest w domu i nie trwa cisza nocna</div>
      <div class="frow end">
        <button data-a="cancel">Anuluj</button>
        <button class="ok" data-a="save">Dodaj</button>
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
    const rep = $("f-rep-on").checked ? $("f-rep").value : "none";
    if (rep !== "none") {
      if (start === null) { this._error = "Zadanie cykliczne musi mieć termin"; this._render(); return; }
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
      case "tomorrow": return this._call("snooze", { uid, until: tomorrowDate() });
      case "form": this._formOpen = true; this._render(); this._unit(); return this.shadowRoot.getElementById("f-sum")?.focus();
      case "cancel": this._formOpen = false; this._forceRender = true; return this._render();
      case "save": return this._save();
      case "err": this._error = null; this._forceRender = true; return this._render();
      case "sec": this._collapsed[b.dataset.k] = !this._collapsed[b.dataset.k]; this._forceRender = true; return this._render();
      case "tab": this._tab = b.dataset.tab; this._formOpen = this._ruleFormOpen = false; this._forceRender = true; return this._render();
      case "r-new": this._editRule = null; this._ruleFormOpen = true; this._forceRender = true; this._render(); return this.shadowRoot.getElementById("r-sum")?.focus();
      case "r-edit": this._editRule = (this._rules || []).find((r) => r.id === b.dataset.id); this._ruleFormOpen = true; this._forceRender = true; return this._render();
      case "r-cancel": this._ruleFormOpen = false; this._editRule = null; this._forceRender = true; return this._render();
      case "r-save": return this._saveRule();
      case "r-toggle": { const r = (this._rules || []).find((x) => x.id === b.dataset.id); return r && this._call("rule_save", { ...r, enabled: !r.enabled }); }
      case "r-del": { const r = (this._rules || []).find((x) => x.id === b.dataset.id); if (r && confirm(`Usunąć regułę „${r.summary}”?`)) this._call("rule_delete", { id: r.id }); return; }
    }
  }

  _onChange(ev) {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (ev.target.id === "f-when") $("f-dt").style.display = ev.target.value === "custom" ? "" : "none";
    this._unit();
    this._ruleUpdate();
  }

  _unit() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (!$("f-rem")) return;
    const pl = (n, forms) => forms[n === 1 ? 0 : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) ? 1 : 2];
    const label = (sel, n, map) => [...sel.options].forEach((o) => { o.textContent = pl(n, map[o.value]); });
    const on = (chk, grp, hint) => { $(grp).classList.toggle("off", !$(chk).checked); $(grp).querySelectorAll("input,select").forEach((e) => { e.disabled = !$(chk).checked; }); $(hint).style.visibility = $(chk).checked ? "" : "hidden"; };
    label($("f-int-u"), Number($("f-int").value || 1), { 1: ["minutę", "minuty", "minut"], 60: ["godzinę", "godziny", "godzin"] });
    label($("f-rep"), Number($("f-every").value || 1), { hourly: ["godzinę", "godziny", "godzin"], daily: ["dzień", "dni", "dni"],
      weekly: ["tydzień", "tygodnie", "tygodni"], monthly: ["miesiąc", "miesiące", "miesięcy"], yearly: ["rok", "lata", "lat"] });
    on("f-rem", "f-rem-g", "f-rem-h");
    $("f-rep-on").disabled = !$("f-rem").checked;
    if (!$("f-rem").checked) $("f-rep-on").checked = false;
    on("f-rep-on", "f-rep-g", "f-rep-h");
    $("f-note-h").style.display = $("f-rem").checked ? "none" : "";
    $("f-rem-h").style.display = $("f-rem").checked ? "" : "none";
    for (const id of ["f-where", "f-where-h", "f-lim-row"]) $(id).style.display = $("f-rem").checked ? "" : "none";
    $("f-lim-n").style.display = $("f-lim").value === "count" ? "" : "none";
    $("f-lim-dt").style.display = $("f-lim").value === "until" ? "" : "none";
  }


  // ------------------------------------------------------------- reguły
  _entityName(id) { return this._hass?.states[id]?.attributes?.friendly_name || id; }
  _stateLabel(id, value) {
    const st = this._hass?.states[id];
    try { if (st && this._hass.formatEntityState) return this._hass.formatEntityState(st, value); } catch (e) { /* stara wersja HA */ }
    return value;
  }
  _ruleText(r) {
    const name = this._entityName(r.entity_id);
    if (r.mode === "calendar") {
      const d = Number(r.days_before ?? 1);
      return `${d === 0 ? "W dniu" : d === 1 ? "Dzień przed" : `${d} dni przed`} wydarzeniem w ${name}${r.contains ? ` („${r.contains}”)` : ""}, o ${r.at_time || "18:00"}`;
    }
    const cond = r.mode === "above" ? `powyżej ${r.value}` : r.mode === "below" ? `poniżej ${r.value}` : `= ${this._stateLabel(r.entity_id, r.value)}`;
    return `Gdy ${name} ${cond}` + (r.for_minutes ? ` przez ${r.for_minutes} min` : "");
  }

  _rulesView() {
    const rules = [...(this._rules || [])].sort((a, b) => a.summary.localeCompare(b.summary));
    const rows = rules.map((r) => {
      const where = [...(r.phones ?? (this._opts?.phones || []).map((p) => p.id)).map((p) => `📱 ${(this._opts?.phones || []).find((x) => x.id === p)?.name || p}`),
        ...(r.speakers ?? (this._opts?.speakers || []).map((s) => s.id)).map((s) => `🔊 ${this._entityName(s)}`)];
      const meta = [r.interval === 0 ? "przypomina raz" : `co ${r.interval ?? this._opts?.default_interval ?? 30} min` + (r.max_reminders ? `, maks. ${r.max_reminders}×` : ""),
        r.auto_close ? "zamyka się samo" : "", where.length ? where.join(", ") : "bez powiadomień"].filter(Boolean);
      return `<div class="task rule ${r.enabled ? "" : "disabled"}">
        <div class="txt"><div class="sum">${esc(r.summary)}</div>
          <div class="when">${esc(this._ruleText(r))}</div>
          <div class="meta">${esc(meta.join(" · "))}</div></div>
        <div class="btns">
          <button data-a="r-toggle" data-id="${r.id}">${r.enabled ? "Wyłącz" : "Włącz"}</button>
          <button data-a="r-edit" data-id="${r.id}">Edytuj</button>
          <button class="no" data-a="r-del" data-id="${r.id}" title="Usuń">✕</button>
        </div></div>`;
    }).join("");
    return `<div class="sec">${rows || `<div class="empty">Brak reguł. Dodaj pierwszą, np. „gdy zmywarka skończy → wypakuj zmywarkę”.</div>`}</div>
      ${this._ruleFormOpen ? this._ruleForm() : `<button class="add-btn" data-a="r-new">＋ Dodaj regułę</button>`}`;
  }

  _ruleForm() {
    const r = this._editRule || {};
    const di = Number(r.interval ?? this._opts?.default_interval ?? 30) || 30;
    const ents = Object.values(this._hass?.states || {})
      .filter((st) => !/^(automation|script|scene|zone|person|update|button|event|tts|conversation|stt|wake_word|sun)\./.test(st.entity_id))
      .map((st) => `<option value="${esc(st.entity_id)}">${esc(st.attributes.friendly_name || "")}</option>`).join("");
    const phones = r.phones ?? (this._opts?.phones || []).map((p) => p.id);
    const speakers = r.speakers ?? (this._opts?.speakers || []).map((s) => s.id);
    return `<div class="form rform">
      <input id="r-sum" placeholder="Jakie zadanie dodać? np. Wypakuj zmywarkę" value="${esc(r.summary || "")}" />
      <div class="frow"><span class="chk">Gdy</span>
        <input id="r-ent" list="r-ents" placeholder="encja, np. sensor.zmywarka…" value="${esc(r.entity_id || "")}" style="flex:1;min-width:220px" />
        <datalist id="r-ents">${ents}</datalist></div>
      <div class="frow"><span class="chk"></span><span class="hint" id="r-ent-name"></span></div>
      <div class="frow"><span class="chk"></span>
        <select id="r-mode">
          <option value="state"${r.mode === "state" || !r.mode ? " selected" : ""}>ma stan</option>
          <option value="above"${r.mode === "above" ? " selected" : ""}>jest powyżej</option>
          <option value="below"${r.mode === "below" ? " selected" : ""}>jest poniżej</option>
          <option value="calendar"${r.mode === "calendar" ? " selected" : ""}>ma wydarzenie (kalendarz)</option>
        </select>
        <span class="grp" id="r-cal-g">
          <input id="r-days" type="number" min="0" value="${r.days_before ?? 1}" /> dni przed, o
          <input id="r-at" type="time" value="${esc(r.at_time || "18:00")}" />
          <input id="r-contains" placeholder="tylko gdy zawiera… (opcjonalnie)" value="${esc(r.contains || "")}" style="width:200px" />
        </span>
        <span class="grp" id="r-st-g">
        <input id="r-val" list="r-vals" value="${esc(r.value ?? "")}" placeholder="wartość" style="width:160px" />
        <datalist id="r-vals"></datalist>
        <span class="hint" id="r-val-l"></span>
        przez <input id="r-for" type="number" min="0" value="${r.for_minutes || 0}" /> min</span>
      </div>
      <div class="frow" id="r-cal-h"><span class="chk"></span><span class="hint">W treści zadania możesz użyć {wydarzenie}, np. „Wystaw śmietnik: {wydarzenie}”. Bez tego nazwa wydarzenia doda się na końcu.</span></div>
      <div class="frow">
        <label class="chk"><input type="checkbox" id="r-rep" ${r.interval === 0 ? "" : "checked"} /> Ponawiaj</label>
        <span class="grp" id="r-rep-g">co <input id="r-int" type="number" min="1" value="${di % 60 === 0 ? di / 60 : di}" />
          <select id="r-int-u"><option value="1"${di % 60 === 0 ? "" : " selected"}>minut</option><option value="60"${di % 60 === 0 ? " selected" : ""}>godzin</option></select></span>
        <span class="grp" id="r-max-g">maks. <input id="r-max" type="number" min="1" placeholder="∞" value="${r.max_reminders || ""}" /> razy</span>
        <span class="hint">(puste = aż odhaczę; bez ponawiania = przypomni raz)</span>
      </div>
      <div class="frow where">
        <span>Gdzie przypominać:</span>
        ${(this._opts?.phones || []).map((p) => `<label><input type="checkbox" class="r-phone" value="${esc(p.id)}" ${phones.includes(p.id) ? "checked" : ""} /> 📱 ${esc(p.name)}</label>`).join("")}
        ${(this._opts?.speakers || []).map((sp) => `<label><input type="checkbox" class="r-spk" value="${esc(sp.id)}" ${speakers.includes(sp.id) ? "checked" : ""} /> 🔊 ${esc(sp.name)}</label>`).join("")}
      </div>
      <div class="frow"><label><input type="checkbox" id="r-close" ${r.auto_close === false ? "" : "checked"} /> Zamknij zadanie samo, gdy warunek przestanie być spełniony</label></div>
      <div class="frow end">
        <button data-a="r-cancel">Anuluj</button>
        <button class="ok" data-a="r-save">${r.id ? "Zapisz" : "Dodaj regułę"}</button>
      </div></div>`;
  }

  _ruleUpdate() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (!$("r-ent")) return;
    const id = $("r-ent").value.trim(), st = this._hass?.states[id];
    $("r-ent-name").textContent = st ? `${st.attributes.friendly_name || id} — teraz: ${this._stateLabel(id, st.state)}` : (id ? "nie ma takiej encji" : "");
    const vals = new Set();
    if (st) {
      vals.add(st.state);
      (st.attributes.options || []).forEach((o) => vals.add(o));
      if (/^(binary_sensor|switch|input_boolean|light|fan)\./.test(id)) { vals.add("on"); vals.add("off"); }
      if (/^cover\./.test(id)) ["open", "closed", "opening", "closing"].forEach((v) => vals.add(v));
      if (/^lock\./.test(id)) ["locked", "unlocked"].forEach((v) => vals.add(v));
    }
    vals.delete("unavailable"); vals.delete("unknown");
    $("r-vals").innerHTML = [...vals].map((v) => `<option value="${esc(v)}">${esc(this._stateLabel(id, v))}</option>`).join("");
    if (/^calendar\./.test(id) && $("r-mode").dataset.auto !== id) { $("r-mode").value = "calendar"; $("r-mode").dataset.auto = id; }
    const cal = $("r-mode").value === "calendar";
    $("r-cal-g").style.display = cal ? "" : "none";
    $("r-cal-h").style.display = cal ? "" : "none";
    $("r-st-g").style.display = cal ? "none" : "";
    const v = $("r-val").value;
    $("r-val-l").textContent = $("r-mode").value === "state" && v && this._stateLabel(id, v) !== v ? `(${this._stateLabel(id, v)})` : "";
    const on = $("r-rep").checked;
    $("r-rep-g").classList.toggle("off", !on);
    $("r-rep-g").querySelectorAll("input,select").forEach((e) => { e.disabled = !on; });
  }

  _saveRule() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const summary = $("r-sum").value.trim(), entity_id = $("r-ent").value.trim(), value = $("r-val").value.trim();
    if (!summary) return $("r-sum").focus();
    if (!this._hass.states[entity_id]) { $("r-ent").focus(); $("r-ent-name").textContent = "Wybierz istniejącą encję z listy"; return; }
    const cal = $("r-mode").value === "calendar";
    if (!value && !cal) return $("r-val").focus();
    const pick = (cls) => [...this.shadowRoot.querySelectorAll(cls)].filter((c) => c.checked).map((c) => c.value);
    const data = { summary, entity_id, mode: $("r-mode").value, value, for_minutes: Number($("r-for").value || 0),
      auto_close: $("r-close").checked, enabled: this._editRule?.enabled ?? true,
      interval: $("r-rep").checked ? Math.max(1, Number($("r-int").value || 1)) * Number($("r-int-u").value) : 0,
      phones: pick(".r-phone"), speakers: pick(".r-spk"), max_reminders: Number($("r-max").value) || null };
    if (cal) Object.assign(data, { days_before: Number($("r-days").value || 0), at_time: $("r-at").value || "18:00", contains: $("r-contains").value.trim() || null, for_minutes: 0 });
    if (this._editRule?.id) data.id = this._editRule.id;
    this._ruleFormOpen = false; this._editRule = null; this._forceRender = true;
    this._call("rule_save", data);
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    // Nie przerywaj wpisywania w formularzu
    // (lista odświeży się po zamknięciu formularza)
    if ((this._formOpen || this._ruleFormOpen) && this.shadowRoot.querySelector(".form") && !this._forceRender) return;
    this._forceRender = false;
    const g = this._groups();
    const empty = !g.now.length && !g.planned.length && !g.notes.length;
    this.shadowRoot.innerHTML = `<style>${ZadaniaCard.styles}</style>
      <ha-card>
        <div class="head"><span>${esc(this._config.title)}</span>${g.now.length ? `<span class="badge">${g.now.length}</span>` : ""}
          <span class="tabs"><button class="tab ${this._tab === "tasks" ? "sel" : ""}" data-a="tab" data-tab="tasks">Zadania</button><button class="tab ${this._tab === "rules" ? "sel" : ""}" data-a="tab" data-tab="rules">Automatyczne${(this._rules || []).length ? ` (${this._rules.length})` : ""}</button></span></div>
        ${this._error ? `<div class="err">${esc(this._error)} <button data-a="err">OK</button></div>` : ""}
        ${this._tab === "rules" ? this._rulesView() : `
        ${this._section("Teraz", g.now, "now")}
        ${this._section("Zaplanowane", g.planned, "planned")}
        ${this._section("Notatki", g.notes, "notes")}
        ${empty ? `<div class="empty">Nic do zrobienia 🎉</div>` : ""}
        ${this._config.show_done ? this._section("Zrobione", g.done, "done") : ""}
        ${this._config.show_done ? this._section("Odrzucone", [...(this._dismissed || [])].reverse().slice(0, 10), "dismissed") : ""}
        ${this._form()}`}
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").onclick = (e) => this._onClick(e);
    this.shadowRoot.querySelector("ha-card").onchange = (e) => this._onChange(e);
    const sum = this.shadowRoot.getElementById("f-sum");
    if (sum) { sum.onkeydown = (e) => { if (e.key === "Enter") this._save(); }; this._unit(); }
    const rent = this.shadowRoot.getElementById("r-ent");
    if (rent) { rent.oninput = () => this._ruleUpdate(); this.shadowRoot.getElementById("r-val").oninput = () => this._ruleUpdate(); this._ruleUpdate(); }
  }
}

ZadaniaCard.styles = `
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
  .grp { display:inline-flex; gap:6px; align-items:center; }
  .grp.off { opacity:.4; }
  .tabs { margin-left:auto; display:flex; gap:4px; }
  .tab { min-height:32px; padding:4px 12px; font-size:13px; }
  .tab.sel { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  .task.rule.disabled { opacity:.5; }
  .rform .chk { min-width:60px; }
  input[type=number] { width:64px; }
  input[type=checkbox] { width:18px; height:18px; vertical-align:middle; }
  .err { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); padding:8px; border-radius:8px; margin-bottom:8px; }
`;

if (!customElements.get("zadania-card")) {
  customElements.define("zadania-card", ZadaniaCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "zadania-card", name: "Zadania", description: "Zadania z przypomnieniami", preview: false });
  console.info(`%c ZADANIA-CARD %c ${VERSION} `, "background:#43a047;color:#fff", "");
}
