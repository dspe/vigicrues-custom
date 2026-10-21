/** Vigicrues dashboard card. Self-contained: no CDN, framework or network request. */
const TYPES = ["hauteur", "debit", "tendance", "vigilance", "statut"];
const TRENDS = {
  hausse: { label: "En hausse", arrow: "↗" },
  baisse: { label: "En baisse", arrow: "↘" },
  stable: { label: "Stable", arrow: "→" },
};
const BAD_STATES = new Set(["unknown", "unavailable", "", null, undefined]);
const MAX_AGE = 2 * 60 * 60 * 1000;

export function normalizeConfig(config) {
  if (!config || (config.stations !== undefined &&
      (!Array.isArray(config.stations) || config.stations.some(id => typeof id !== "string" || !id.trim())))) {
    throw new Error("stations doit être une liste de codes de station, par exemple H413041010.");
  }
  return {
    ...config,
    type: "custom:vigicrues-card",
    title: typeof config.title === "string" ? config.title : "Vigicrues",
    ...(config.stations === undefined ? {} : { stations: [...new Set(config.stations)] }),
    show_vigilance: config.show_vigilance !== false,
    show_updated: config.show_updated !== false,
  };
}

function sensorType(entity) {
  const attrs = entity.attributes || {};
  if (attrs.integration === "vigicrues" && TYPES.includes(attrs.sensor_type)) return attrs.sensor_type;
  // Compatibility with 1.1.0, including renamed numeric entities.
  if (!attrs.station_name || !(attrs.data_status || entity.entity_id?.startsWith("sensor.vigicrues"))) return null;
  const unit = attrs.unit_of_measurement;
  if (["m", "cm", "mm"].includes(unit)) return "hauteur";
  if (["m³/s", "m³/h", "m3/s", "m3/h", "L/s", "l/s"].includes(unit)) return "debit";
  if (Object.hasOwn(TRENDS, entity.state) || attrs.tendance_debit !== undefined) return "tendance";
  if (["Vert", "Jaune", "Orange", "Rouge"].includes(entity.state)) return "vigilance";
  if (["ok", "degraded", "stale"].includes(entity.state)) return "statut";
  return TYPES.find(type => entity.entity_id?.endsWith(`_${type}`)) || null;
}

export function discoverStations(states = {}) {
  const stations = new Map();
  for (const [entityId, state] of Object.entries(states).sort(([a], [b]) => a.localeCompare(b))) {
    if (!state || !entityId.startsWith("sensor.")) continue;
    const attrs = state.attributes || {};
    if (!attrs.station_id) continue;
    const entity = { ...state, entity_id: entityId };
    const type = sensorType(entity);
    if (!type) continue;
    const id = String(attrs.station_id);
    if (!stations.has(id)) stations.set(id, { id, name: attrs.station_name || id, river: "", entities: {} });
    const station = stations.get(id);
    if (attrs.station_name) station.name = attrs.station_name;
    if (attrs.cours_eau) station.river = attrs.cours_eau;
    const previous = station.entities[type];
    if (!previous || (BAD_STATES.has(previous.state) && !BAD_STATES.has(entity.state))) station.entities[type] = entity;
  }
  return [...stations.values()].sort((a, b) => a.name.localeCompare(b.name, "fr", { numeric: true }));
}

function timestampAge(entity, now) {
  const date = entity?.attributes?.timestamp;
  const stamp = typeof date === "string" ? Date.parse(date) : NaN;
  return Number.isFinite(stamp) ? Math.max(0, now - stamp) : null;
}

function relativeAge(age) {
  return age === null ? "Date inconnue" : age < 60000 ? "À l’instant" : age < 3600000 ? `Il y a ${Math.floor(age / 60000)} min` : age < 86400000 ? `Il y a ${Math.floor(age / 3600000)} h` : `Il y a ${Math.floor(age / 86400000)} j`;
}

function metric(entity, trend, now, locale, timeZone, resource) {
  const numeric = !BAD_STATES.has(entity?.state) && String(entity?.state).trim() !== "" ? Number(entity.state) : NaN;
  const available = Number.isFinite(numeric);
  const age = timestampAge(entity, now);
  const lastCollection = Date.parse(entity?.attributes?.last_success?.[resource]);
  const collectionAge = Number.isFinite(lastCollection) ? Math.max(0, now - lastCollection) : null;
  const timestamp = entity?.attributes?.timestamp;
  let dateLabel = "Date de mesure inconnue";
  if (timestamp && Number.isFinite(Date.parse(timestamp))) {
    try {
      dateLabel = new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short", ...(timeZone ? { timeZone } : {}) }).format(new Date(timestamp));
    } catch { dateLabel = new Date(timestamp).toISOString(); }
  }
  return {
    entityId: entity?.entity_id || null,
    value: available ? new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(numeric) : "—",
    unit: entity?.attributes?.unit_of_measurement || "",
    available,
    stale: available && (entity?.attributes?.data_stale === true || age === null || age > MAX_AGE),
    source: entity?.attributes?.source === "hubeau" ? "Hub’Eau" : entity?.attributes?.source === "vigicrues" ? "Vigicrues" : "Source inconnue",
    backup: entity?.attributes?.source === "hubeau",
    dateLabel,
    ageLabel: relativeAge(age),
    collectionLabel: relativeAge(collectionAge),
    trend: available && Object.hasOwn(TRENDS, trend) ? TRENDS[trend] : null,
  };
}

export function stationView(station, now = Date.now(), locale = "fr", timeZone) {
  const entities = station.entities;
  const height = metric(entities.hauteur, entities.tendance?.state, now, locale, timeZone, "hauteur");
  const flow = metric(entities.debit, entities.tendance?.attributes?.tendance_debit, now, locale, timeZone, "debit");
  const measurements = [height, flow].filter(value => value.available);
  const status = entities.statut?.state || entities.hauteur?.attributes?.data_status || entities.debit?.attributes?.data_status;
  let health = "ok";
  if (!measurements.length) health = "unavailable";
  else if (measurements.every(value => value.stale)) health = "stale";
  else if (status === "stale" || status === "degraded" || measurements.length < 2 || measurements.some(value => value.stale || value.backup)) health = "degraded";
  const vigilance = entities.vigilance;
  const level = ["Vert", "Jaune", "Orange", "Rouge"].includes(vigilance?.state) ? vigilance.state : null;
  const lastVigilance = Date.parse(vigilance?.attributes?.last_success?.vigilance);
  return {
    id: station.id, name: station.name, river: station.river, height, flow, health,
    healthLabel: { ok: "Collecte OK", degraded: measurements.some(value => value.backup) ? "Source de secours" : "Collecte dégradée", stale: "Données anciennes", unavailable: "Mesures indisponibles" }[health],
    vigilance: level,
    vigilanceStale: level !== null && (vigilance.attributes?.data_stale === true || !Number.isFinite(lastVigilance) || now - lastVigilance > MAX_AGE),
    vigilanceEntityId: vigilance?.entity_id,
  };
}

const CSS = `
:host{display:block;container-type:inline-size;color:var(--primary-text-color,#182b39);font-family:var(--paper-font-body1_-_font-family,inherit)}
*{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#fff));border:var(--ha-card-border-width,1px) solid var(--ha-card-border-color,var(--divider-color,#dfe6ea));border-radius:var(--ha-card-border-radius,16px);box-shadow:var(--ha-card-box-shadow,none);overflow:hidden}
h2{font-size:20px;font-weight:600;margin:0;padding:22px 22px 6px}.station{padding:20px 22px}.station+.station{border-top:1px solid var(--divider-color,#e6ecef)}
.heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}.name{min-width:0}h3{font-size:17px;line-height:1.35;margin:0 0 5px;font-weight:600;overflow-wrap:anywhere}.subtitle,.footer{color:var(--secondary-text-color,#607482);font-size:12px;line-height:1.5}.badges{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;max-width:55%}
.badge{display:inline-flex;align-items:center;gap:5px;border-radius:16px;padding:5px 9px;font-size:11px;line-height:1.3;font-weight:600;background:var(--secondary-background-color,#edf2f5);white-space:normal;text-align:left;color:inherit}.badge[data-kind=ok]{background:color-mix(in srgb,#28836d 12%,var(--card-background-color,#fff));color:var(--primary-text-color,#1f6657)}.badge[data-kind=degraded],.badge[data-kind=stale]{background:color-mix(in srgb,#d89922 17%,var(--card-background-color,#fff))}.dot{width:7px;height:7px;flex-shrink:0;border-radius:100%;background:var(--secondary-text-color,#789)}
.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.metric{font:inherit;appearance:none;text-align:left;color:inherit;background:var(--secondary-background-color,#f3f7f9);border:1px solid transparent;border-radius:12px;padding:16px 14px;min-width:0;width:100%;cursor:pointer}.metric:disabled{cursor:default}.metric:hover:not(:disabled){border-color:var(--primary-color,#287b9c)}button:focus-visible{outline:3px solid var(--primary-color,#287b9c);outline-offset:2px}.metric.old{border-color:color-mix(in srgb,#d89922 55%,transparent)}.metric-label{font-size:12px;color:var(--secondary-text-color,#607482);display:block;margin-bottom:9px}.number{font-variant-numeric:tabular-nums;font-size:29px;font-weight:600;line-height:1.2;overflow-wrap:anywhere}.unit{font-size:12px;color:var(--secondary-text-color,#607482);margin-left:5px;white-space:nowrap}.trend{font-size:12px;margin-top:10px;display:flex;align-items:center;gap:6px;min-height:18px}.arrow{font-size:18px;color:var(--primary-color,#287b9c)}.footer{margin-top:12px;font-size:11px}.old-note{font-size:11px;font-weight:600;margin-top:7px;color:var(--primary-text-color,#78550b)}.empty{padding:22px;color:var(--secondary-text-color,#607482);line-height:1.6}.vigilance{border:0;cursor:pointer;font-family:inherit}.vigilance:disabled{cursor:default}
@container(max-width:340px){.station{padding:18px 16px}h2{padding:20px 16px 4px}.heading{flex-direction:column;gap:9px}.badges{max-width:100%;justify-content:flex-start}.metric{padding:14px 10px}.number{font-size:25px}}
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export class VigicruesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }
  static getConfigElement() { return document.createElement("vigicrues-card-editor"); }
  static getStubConfig() { return { type: "custom:vigicrues-card", title: "Vigicrues" }; }
  setConfig(config) { this._config = normalizeConfig(config); this._signature = null; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  connectedCallback() {
    this._render();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._render(), 60000);
  }
  disconnectedCallback() { clearInterval(this._timer); this._timer = null; }
  getCardSize() { return 1 + 4 * (this._views?.length || 1); }
  getGridOptions() { return { columns: 12, rows: "auto", min_columns: 6 }; }
  _moreInfo(entityId) {
    if (entityId) this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }
  _metric(view, label) {
    const button = el("button", `metric${view.stale ? " old" : ""}`);
    button.type = "button";
    button.disabled = !view.entityId;
    button.setAttribute("aria-label", `${label} : ${view.value} ${view.unit}${view.stale ? ", donnée ancienne" : ""}. Ouvrir les détails.`);
    button.addEventListener("click", () => this._moreInfo(view.entityId));
    button.append(el("span", "metric-label", label));
    const value = el("div");
    value.append(el("span", "number", view.value), el("span", "unit", view.available ? view.unit : ""));
    button.append(value);
    const trend = el("div", "trend");
    if (view.trend) {
      trend.append(el("span", "arrow", view.trend.arrow), el("span", "", view.trend.label));
    } else trend.append(el("span", "", "Tendance indisponible"));
    button.append(trend);
    if (!view.available) button.append(el("div", "old-note", "Mesure indisponible"));
    else if (view.stale) button.append(el("div", "old-note", "⚠ Dernière valeur connue"));
    const footer = el("div", "footer", view.available ? `${view.source}${this._config.show_updated ? ` · mesure : ${view.ageLabel.toLocaleLowerCase("fr")}` : ""}` : "");
    footer.title = view.dateLabel;
    if (view.available && this._config.show_updated) {
      footer.append(el("div", "", view.dateLabel));
      footer.append(el("div", "", `Collecte réussie : ${view.collectionLabel.toLocaleLowerCase("fr")}`));
    }
    button.append(footer);
    return button;
  }
  _render() {
    if (!this._config || !this._hass) return;
    const stations = discoverStations(this._hass.states);
    const selected = this._config.stations === undefined ? stations : this._config.stations.map(id => stations.find(s => s.id === id) || { id, name: `Station ${id}`, river: "", entities: {} });
    let locale = this._hass.locale?.language || this._hass.language || "fr";
    try { new Intl.NumberFormat(locale); } catch { locale = "fr"; }
    this._views = selected.map(s => stationView(s, Date.now(), locale, this._hass.config?.time_zone));
    const signature = JSON.stringify([this._config, this._views]);
    if (signature === this._signature) return;
    this._signature = signature;
    const style = el("style", "", CSS);
    const card = el("ha-card");
    if (this._config.title) card.append(el("h2", "", this._config.title));
    if (!this._views.length) card.append(el("div", "empty", this._config.stations === undefined ? "Aucune station Vigicrues détectée. Ajoutez une station dans Paramètres → Appareils et services → Vigicrues." : "Aucune station sélectionnée. Choisissez les stations dans l’éditeur de la carte."));
    for (const view of this._views) {
      const section = el("section", "station");
      section.setAttribute("aria-label", view.name);
      const heading = el("div", "heading");
      const name = el("div", "name");
      name.append(el("h3", "", view.name), el("div", "subtitle", [view.river, view.id].filter(Boolean).join(" · ")));
      const badges = el("div", "badges");
      const status = el("span", "badge", view.healthLabel);
      status.dataset.kind = view.health;
      status.title = view.health === "ok" ? "La dernière collecte a réussi. Les mesures peuvent être plus anciennes ; leur date est indiquée sous chaque valeur. Le seuil de données anciennes est de 2 heures." : view.healthLabel;
      badges.append(status);
      if (this._config.show_vigilance) {
        const vigilance = el("button", "badge vigilance");
        vigilance.type = "button";
        vigilance.disabled = !view.vigilanceEntityId;
        const dot = el("span", "dot");
        dot.style.backgroundColor = { Vert: "#29825b", Jaune: "#e0bc24", Orange: "#e57820", Rouge: "#d83c46" }[view.vigilance] || "#81909b";
        vigilance.append(dot, el("span", "", view.vigilance ? `Vigilance ${{ Vert: "verte", Jaune: "jaune", Orange: "orange", Rouge: "rouge" }[view.vigilance]}${view.vigilanceStale ? " · ancienne" : ""}` : "Vigilance inconnue"));
        vigilance.addEventListener("click", () => this._moreInfo(view.vigilanceEntityId));
        badges.append(vigilance);
      }
      heading.append(name, badges);
      const metrics = el("div", "metrics");
      metrics.append(this._metric(view.height, "Hauteur d’eau"), this._metric(view.flow, "Débit"));
      section.append(heading, metrics);
      card.append(section);
    }
    this.shadowRoot.replaceChildren(style, card);
  }
}

export class VigicruesCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); }
  setConfig(config) { this._config = normalizeConfig(config); this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _changed(updates) {
    this._config = { ...this._config, ...updates };
    if (this._config.stations === undefined) delete this._config.stations;
    this._signature = null;
    this.dispatchEvent(new CustomEvent("config-changed", { bubbles: true, composed: true, detail: { config: { ...this._config } } }));
    this._render();
  }
  _checkbox(label, checked, callback) {
    const row = el("label", "choice");
    const input = el("input");
    input.type = "checkbox"; input.checked = checked;
    input.addEventListener("change", () => callback(input.checked));
    row.append(input, el("span", "", label));
    return row;
  }
  _render() {
    if (!this._config || !this._hass) return;
    const stations = discoverStations(this._hass.states);
    const signature = JSON.stringify([this._config, stations.map(s => [s.id, s.name])]);
    if (signature === this._signature) return;
    this._signature = signature;
    const wrapper = el("div");
    const titleLabel = el("label", "title-label", "Titre");
    const title = el("input", "title");
    title.type = "text"; title.value = this._config.title;
    title.addEventListener("change", () => this._changed({ title: title.value }));
    titleLabel.append(title); wrapper.append(titleLabel);
    const auto = this._config.stations === undefined;
    wrapper.append(this._checkbox("Toutes les stations configurées (automatique)", auto, checked => this._changed({ stations: checked ? undefined : stations.map(s => s.id) })));
    wrapper.append(el("p", "hint", "Décochez le mode automatique pour choisir une ou plusieurs stations. Aucun nom d’entité à saisir."));
    if (!auto) {
      const list = el("fieldset");
      list.append(el("legend", "", "Stations à afficher"));
      const ids = [...new Set([...stations.map(s => s.id), ...this._config.stations])];
      if (!ids.length) list.append(el("p", "hint", "Aucune station détectée pour le moment."));
      for (const id of ids) {
        const station = stations.find(s => s.id === id);
        list.append(this._checkbox(station ? `${station.name} (${id})` : `${id} — introuvable`, this._config.stations.includes(id), checked => {
          const selection = new Set(this._config.stations);
          if (checked) selection.add(id); else selection.delete(id);
          this._changed({ stations: [...selection] });
        }));
      }
      wrapper.append(list);
    }
    wrapper.append(this._checkbox("Afficher la vigilance", this._config.show_vigilance, checked => this._changed({ show_vigilance: checked })));
    wrapper.append(this._checkbox("Afficher la date des mesures", this._config.show_updated, checked => this._changed({ show_updated: checked })));
    const style = el("style", "", ":host{display:block;color:var(--primary-text-color);font-family:inherit}.choice{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer}input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary-color,#287b9c);flex-shrink:0}.title-label{display:block;font-size:14px}.title{display:block;box-sizing:border-box;width:100%;padding:12px;margin:8px 0 16px;font:inherit;border-radius:8px;border:1px solid var(--divider-color,#bcc);background:var(--card-background-color,#fff);color:inherit}.hint{font-size:12px;line-height:1.5;color:var(--secondary-text-color,#667)}fieldset{border:1px solid var(--divider-color,#bcc);border-radius:8px;margin:14px 0;padding:8px 12px}legend{font-size:13px}");
    this.shadowRoot.replaceChildren(style, wrapper);
  }
}

if (!customElements.get("vigicrues-card")) customElements.define("vigicrues-card", VigicruesCard);
if (!customElements.get("vigicrues-card-editor")) customElements.define("vigicrues-card-editor", VigicruesCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "vigicrues-card")) window.customCards.push({
  type: "vigicrues-card", name: "Vigicrues", preview: true,
  description: "Hauteurs, débits et tendances d’une ou plusieurs stations, avec état des données.",
});
