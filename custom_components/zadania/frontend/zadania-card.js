/* Karta Lovelace: custom:zadania-card (integracja Zadania) */
const VERSION = "0.2.2";

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
      .subscribeMessage((msg) => { this._tasks = msg.tasks || []; this._opts = msg.options || {}; this._error = null; this._render(); },
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
    if (kind === "now") when = t.next_reminder ? `teraz · znowu ${fmtTime(t.next_reminder).replace("dziś ", "")}` : "teraz";
    else if (kind === "planned") when = (t.snoozes && t.last_reminded ? "odłożone do " : "") + fmtTime(t.next_reminder || t.start);
    else if (kind === "done") when = `zrobione ${ago(t.closed)}`;
    const meta = [];
    if (kind === "now") meta.push(`przypomina od ${ago(t.last_reminded)}`);
    if (t.interval && kind !== "done" && kind !== "notes") meta.push(`co ${t.interval} min`);
    if (t.repeat_label) meta.push(`🔁 ${t.repeat_label}`);
    if (t.snoozes) meta.push(`odłożone ${t.snoozes}×`);
    if (kind !== "done" && kind !== "notes") {
      const where = [...(t.phone_labels || []).map((n) => `📱 ${n}`), ...(t.speaker_labels || []).map((n) => `🔊 ${n}`)];
      meta.push(where.length ? where.join(", ") : "bez powiadomień");
    }
    const btns = kind === "done" ? "" : `
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
    return `<div class="sec"><div class="sec-title">${title} <span>${list.length}</span></div>${list.map((t) => this._row(t, kind)).join("")}</div>`;
  }

  _form() {
    if (!this._config.show_form) return "";
    if (!this._formOpen) return `<button class="add-btn" data-a="form">＋ Dodaj zadanie</button>`;
    return `<div class="form">
      <input id="f-sum" placeholder="Co trzeba zrobić?" />
      <div class="frow">
        <select id="f-when">
          <option value="now">od teraz</option>
          <option value="1h">za 1 h</option>
          <option value="evening">dziś 19:00</option>
          <option value="custom">wybierz termin…</option>
          <option value="none">bez przypomnień (notatka)</option>
        </select>
        <input id="f-dt" type="datetime-local" style="display:none" />
      </div>
      <div class="frow">
        <label>Przypominaj co <input id="f-int" type="number" min="0" value="${this._opts?.default_interval ?? 30}" /> min, dopóki nie odhaczę</label>
        <span class="hint">(0 = przypomnij tylko raz)</span>
      </div>
      <div class="frow">
        <label>Powtarzaj: <select id="f-rep">
          <option value="none">nie (jednorazowe)</option>
          <option value="daily">w dniach</option>
          <option value="weekly">w tygodniach</option>
          <option value="monthly">w miesiącach</option>
          <option value="yearly">w latach</option>
        </select></label>
        <label id="f-every-l" style="display:none">co <input id="f-every" type="number" min="1" value="1" /> <span id="f-unit">dzień</span></label>
        <span class="hint" id="f-rep-hint" style="display:none">(po odhaczeniu wróci w następnym terminie)</span>
      </div>
      <div class="frow where">
        <span>Gdzie przypominać:</span>
        ${(this._opts?.phones || []).map((p) => `<label><input type="checkbox" class="f-phone" value="${esc(p.id)}" checked /> 📱 ${esc(p.name)}</label>`).join("")}
        ${(this._opts?.speakers || []).map((s) => `<label><input type="checkbox" class="f-spk" value="${esc(s.id)}" checked /> 🔊 ${esc(s.name)}</label>`).join("")}
      </div>
      <div class="hint">🔊 mówi tylko, gdy ktoś jest w domu i nie trwa cisza nocna</div>
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
    else if (when === "none") start = null;
    const pick = (cls) => [...this.shadowRoot.querySelectorAll(cls)].filter((c) => c.checked).map((c) => c.value);
    const data = { summary, start, interval: Number($("f-int").value || 0), phones: pick(".f-phone"), speakers: pick(".f-spk") };
    const rep = $("f-rep").value;
    if (rep !== "none") {
      if (start === null) { this._error = "Zadanie cykliczne musi mieć termin"; this._render(); return; }
      data.repeat = rep; data.repeat_every = Number($("f-every").value || 1);
    }
    this._formOpen = false;
    this._call("add", data);
  }

  _onClick(ev) {
    const b = ev.target.closest("button");
    if (!b) return;
    const uid = b.dataset.uid;
    switch (b.dataset.a) {
      case "done": return this._call("done", { uid });
      case "dismiss": return this._call("dismiss", { uid });
      case "snooze": return this._call("snooze", { uid, minutes: Number(b.dataset.min) });
      case "tomorrow": return this._call("snooze", { uid, until: tomorrowDate() });
      case "form": this._formOpen = true; this._render(); return this.shadowRoot.getElementById("f-sum")?.focus();
      case "cancel": this._formOpen = false; return this._render();
      case "save": return this._save();
      case "err": this._error = null; return this._render();
    }
  }

  _onChange(ev) {
    const $ = (id) => this.shadowRoot.getElementById(id);
    if (ev.target.id === "f-when") $("f-dt").style.display = ev.target.value === "custom" ? "" : "none";
    if (ev.target.id === "f-rep" || ev.target.id === "f-every") this._unit();
  }

  _unit() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const rep = $("f-rep").value, n = Number($("f-every").value || 1);
    $("f-every-l").style.display = rep === "none" ? "none" : "";
    $("f-rep-hint").style.display = rep === "none" ? "none" : "";
    const forms = { daily: ["dzień", "dni", "dni"], weekly: ["tydzień", "tygodnie", "tygodni"],
      monthly: ["miesiąc", "miesiące", "miesięcy"], yearly: ["rok", "lata", "lat"] }[rep];
    if (!forms) return;
    const f = n === 1 ? 0 : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) ? 1 : 2;
    $("f-unit").textContent = forms[f];
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    // Nie przerywaj wpisywania w formularzu
    if (this._formOpen && this.shadowRoot.activeElement && this.shadowRoot.querySelector(".form")) return;
    const g = this._groups();
    const empty = !g.now.length && !g.planned.length && !g.notes.length;
    this.shadowRoot.innerHTML = `<style>${ZadaniaCard.styles}</style>
      <ha-card>
        <div class="head"><span>${esc(this._config.title)}</span>${g.now.length ? `<span class="badge">${g.now.length}</span>` : ""}</div>
        ${this._error ? `<div class="err">${esc(this._error)} <button data-a="err">OK</button></div>` : ""}
        ${this._section("Teraz", g.now, "now")}
        ${this._section("Zaplanowane", g.planned, "planned")}
        ${this._section("Notatki", g.notes, "notes")}
        ${empty ? `<div class="empty">Nic do zrobienia 🎉</div>` : ""}
        ${this._config.show_done ? this._section("Ostatnio zrobione", g.done, "done") : ""}
        ${this._form()}
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").onclick = (e) => this._onClick(e);
    this.shadowRoot.querySelector("ha-card").onchange = (e) => this._onChange(e);
    const sum = this.shadowRoot.getElementById("f-sum");
    if (sum) sum.onkeydown = (e) => { if (e.key === "Enter") this._save(); };
  }
}

ZadaniaCard.styles = `
  ha-card { padding: 12px 16px 16px; }
  .head { display:flex; align-items:center; gap:8px; font-size:20px; font-weight:500; margin-bottom:8px; }
  .badge { background: var(--error-color, #db4437); color:#fff; border-radius:12px; padding:0 9px; font-size:14px; line-height:22px; }
  .sec { margin-top: 10px; }
  .sec-title { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color: var(--secondary-text-color); margin-bottom:4px; }
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
