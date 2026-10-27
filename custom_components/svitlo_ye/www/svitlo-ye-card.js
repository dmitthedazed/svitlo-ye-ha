/* СвітлоЄ? card: today/tomorrow timeline of outages for one address.
 * Usage: type: custom:svitlo-ye-card, entity: sensor.<address>_schedule */
const COLORS = {
  available: "var(--success-color, #43a047)",
  outage: "var(--error-color, #db4437)",
  probable: "var(--warning-color, #ffa600)",
  unknown: "var(--disabled-color, #bdbdbd)",
};
const LABELS = {
  uk: {
    available: "Світло є", outage: "Відключення", probable: "Можливе відключення",
    unknown: "Невідомо", today: "Сьогодні", tomorrow: "Завтра", queue: "Черга",
    none: "Графік не опубліковано", next: "Далі", msg: "Повідомлення",
  },
  en: {
    available: "Power on", outage: "Outage", probable: "Possible outage",
    unknown: "Unknown", today: "Today", tomorrow: "Tomorrow", queue: "Queue",
    none: "Schedule not published", next: "Next", msg: "Messages",
  },
};
const toMin = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };

class SvitloYeCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity is required (sensor.*_schedule)");
    this._config = { show_tomorrow: true, show_messages: true, ...config };
  }
  getCardSize() { return this._config?.show_tomorrow === false ? 3 : 5; }
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && e.endsWith("_schedule") && hass.states[e].attributes.today);
    return { entity: entity || "sensor.dim_schedule" };
  }
  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const sig = st && `${st.state}|${st.last_updated}`;
    if (sig === this._sig && this._root) { this._tick(); return; }
    this._sig = sig;
    this._render();
  }
  connectedCallback() { this._timer = setInterval(() => this._tick(), 60000); }
  disconnectedCallback() { clearInterval(this._timer); }

  _t() { return LABELS[(this._hass?.language || "en").startsWith("uk") ? "uk" : "en"]; }

  _bar(intervals, isToday) {
    const segs = intervals.map((i) => {
      const s = toMin(i.start_time), e = toMin(i.end_time === "24:00" ? "24:00" : i.end_time) || 1440;
      const end = i.end_time.startsWith("00:00") ? 1440 : e;
      return `<div class="seg" style="left:${(s / 1440) * 100}%;width:${((end - s) / 1440) * 100}%;background:${COLORS[i.status] || COLORS.unknown}" title="${i.start_time}–${i.end_time}"></div>`;
    }).join("");
    const marker = isToday ? `<div class="now"></div>` : "";
    const ticks = [0, 6, 12, 18, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}</span>`).join("");
    return `<div class="bar">${segs}${marker}</div><div class="ticks">${ticks}</div>`;
  }

  _list(intervals) {
    return intervals.filter((i) => i.status === "outage" || i.status === "probable")
      .map((i) => `<span class="chip" style="border-color:${COLORS[i.status]}">${i.start_time}–${i.end_time}</span>`).join("") || "";
  }

  _render() {
    const st = this._hass.states[this._config.entity];
    if (!st) { this.innerHTML = `<ha-card><div class="pad">Entity not found: ${this._config.entity}</div></ha-card>`; return; }
    const t = this._t(), a = st.attributes;
    const section = (title, items, isToday) => `
      <div class="day"><div class="title">${title}</div>
      ${items.length ? this._bar(items, isToday) + `<div class="chips">${this._list(items)}</div>` : `<div class="muted">${t.none}</div>`}</div>`;
    const msgs = this._config.show_messages && a.messages?.length
      ? `<div class="msgs">${a.messages.map((m) => `<div>⚠ ${m}</div>`).join("")}</div>` : "";
    this.innerHTML = `
      <style>
        .pad{padding:16px} .head{display:flex;align-items:center;gap:12px;padding:16px 16px 4px}
        .dot{width:14px;height:14px;border-radius:50%} .state{font-size:1.2em;font-weight:500}
        .sub{color:var(--secondary-text-color);font-size:.9em} .day{padding:8px 16px}
        .title{font-weight:500;margin-bottom:6px}
        .bar{position:relative;height:18px;border-radius:9px;overflow:hidden;background:${COLORS.unknown}33}
        .seg{position:absolute;top:0;bottom:0} .now{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--primary-text-color)}
        .ticks{position:relative;height:14px;font-size:.7em;color:var(--secondary-text-color)}
        .ticks span{position:absolute;transform:translateX(-50%)} .ticks span:first-child{transform:none}
        .ticks span:last-child{transform:translateX(-100%)}
        .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
        .chip{border:1px solid;border-radius:12px;padding:2px 8px;font-size:.85em}
        .muted{color:var(--secondary-text-color);font-size:.9em}
        .msgs{padding:8px 16px 14px;font-size:.85em;color:var(--secondary-text-color)}
      </style>
      <ha-card>
        <div class="head"><div class="dot" id="dot"></div>
          <div><div class="state" id="state"></div><div class="sub" id="sub"></div></div></div>
        ${section(t.today, a.today || [], true)}
        ${this._config.show_tomorrow ? section(t.tomorrow, a.tomorrow || [], false) : ""}
        ${msgs}
      </ha-card>`;
    this._root = true;
    this._tick();
  }

  _tick() {
    const st = this._hass.states[this._config.entity];
    if (!st || !this._root) return;
    const t = this._t(), a = st.attributes;
    this.querySelector("#dot").style.background = COLORS[st.state] || COLORS.unknown;
    this.querySelector("#state").textContent = t[st.state] || st.state;
    const next = Object.values(this._hass.states).find((s) => s.entity_id.endsWith("_next_power_change") && s.attributes.next_power_state && s.entity_id.startsWith("sensor.") && (this._config.next_entity ? s.entity_id === this._config.next_entity : true) && s.entity_id.replace("_next_power_change", "_schedule") === this._config.entity);
    let sub = `${t.queue} ${a.queue ?? ""}`;
    if (next && next.state && !["unknown", "unavailable"].includes(next.state)) {
      const d = new Date(next.state);
      sub += ` · ${t.next}: ${d.toLocaleTimeString(this._hass.language, { hour: "2-digit", minute: "2-digit" })}`;
    }
    this.querySelector("#sub").textContent = sub;
    const now = this.querySelector(".now");
    if (now) {
      const p = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Kyiv" }));
      now.style.left = `${((p.getHours() * 60 + p.getMinutes()) / 1440) * 100}%`;
    }
  }
}
customElements.define("svitlo-ye-card", SvitloYeCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "svitlo-ye-card", name: "СвітлоЄ?", description: "Графік відключень на сьогодні й завтра" });
