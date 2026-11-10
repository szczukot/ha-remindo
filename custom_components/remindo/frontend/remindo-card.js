/* Karta Lovelace: custom:remindo-card (integracja Remindo) */
const VERSION = "0.7.0";

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

class RemindoCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "Zadania", show_done: true, show_form: true, ...config };
    this._tasks = [];
    this._formOpen = false;
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
      .subscribeMessage((msg) => { this._tasks = msg.tasks || []; this._dismissed = msg.dismissed || []; this._opts = msg.options || {}; this._error = null; this._render(); },
        { type: "remindo/subscribe" })
      .catch((err) => { this._error = err.message || String(err); this._unsub = null; this._render(); setTimeout(() => this._subscribe(), 15000); });
  }

  getCardSize() { return 3 + this._tasks.length; }
  static getStubConfig() { return { title: "Zadania" }; }

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


  _render() {
    if (!this.shadowRoot || !this._config) return;
    // Nie przerywaj wpisywania w formularzu
    // (lista odświeży się po zamknięciu formularza)
    if (this._formOpen && this.shadowRoot.querySelector(".form") && !this._forceRender) return;
    this._forceRender = false;
    const g = this._groups();
    const empty = !g.now.length && !g.planned.length && !g.notes.length;
    this.shadowRoot.innerHTML = `<style>${RemindoCard.styles}</style>
      <ha-card>
        <div class="head"><span>${esc(this._config.title)}</span>${g.now.length ? `<span class="badge">${g.now.length}</span>` : ""}
</div>
        ${this._error ? `<div class="err">${esc(this._error)} <button data-a="err">OK</button></div>` : ""}
        ${this._section("Teraz", g.now, "now")}
        ${this._section("Zaplanowane", g.planned, "planned")}
        ${this._section("Notatki", g.notes, "notes")}
        ${empty ? `<div class="empty">Nic do zrobienia 🎉</div>` : ""}
        ${this._config.show_done ? this._section("Zrobione", g.done, "done") : ""}
        ${this._config.show_done ? this._section("Odrzucone", [...(this._dismissed || [])].reverse().slice(0, 10), "dismissed") : ""}
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
  .grp { display:inline-flex; gap:6px; align-items:center; }
  .grp.off { opacity:.4; }
  input[type=number] { width:64px; }
  input[type=checkbox] { width:18px; height:18px; vertical-align:middle; }
  .err { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); padding:8px; border-radius:8px; margin-bottom:8px; }
`;

if (!customElements.get("remindo-card")) {
  customElements.define("remindo-card", RemindoCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "remindo-card", name: "Remindo", description: "Lista zadań z przypomnieniami: odhaczanie, odkładanie, dodawanie", preview: false });
  console.info(`%c REMINDO-CARD %c ${VERSION} `, "background:#43a047;color:#fff", "");
}
