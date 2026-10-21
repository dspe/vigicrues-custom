import test from "node:test";
import assert from "node:assert/strict";
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => true, define: () => {} };
globalThis.window = {};
const { normalizeConfig, discoverStations, stationView } = await import("../../custom_components/vigicrues/www/vigicrues-card.js");
const NOW = Date.parse("2026-10-20T15:00:00Z");
function state(type, value, extra = {}) {
  return { state: value, attributes: { integration: "vigicrues", sensor_type: type, station_id: "H413041010", station_name: "St-Martin-de-Nigelles", cours_eau: "Drouette", timestamp: "2026-10-20T14:55:00Z", source: "vigicrues", data_stale: false, ...extra } };
}
function states() {
  return {
    "sensor.renamed_height": state("hauteur", "0.25", { unit_of_measurement: "m" }),
    "sensor.renamed_flow": state("debit", "0.5", { unit_of_measurement: "m³/s" }),
    "sensor.renamed_trend": state("tendance", "hausse", { tendance_debit: "baisse" }),
    "sensor.renamed_status": state("statut", "ok"),
    "sensor.renamed_vigilance": state("vigilance", "Vert", { last_success: { vigilance: "2026-10-20T14:55:00Z" } }),
  };
}
test("discovers renamed entities by stable attributes and groups them once", () => {
  const result = discoverStations(states());
  assert.equal(result.length, 1);
  assert.equal(result[0].name, "St-Martin-de-Nigelles");
  assert.equal(Object.keys(result[0].entities).length, 5);
  assert.equal(result[0].entities.hauteur.entity_id, "sensor.renamed_height");
});
test("renders separate trends and keeps Home Assistant's displayed unit", () => {
  const result = stationView(discoverStations(states())[0], NOW);
  assert.equal(result.height.value, "0,25");
  assert.equal(result.flow.unit, "m³/s");
  assert.equal(result.height.trend.label, "En hausse");
  assert.equal(result.flow.trend.label, "En baisse");
  assert.equal(result.height.ageLabel, "Il y a 5 min");
  assert.equal(result.health, "ok");
  assert.equal(result.vigilanceStale, false);
});
test("preserves a real zero and never turns unavailable into zero", () => {
  const input = states();
  input["sensor.renamed_flow"].state = "0";
  input["sensor.renamed_height"].state = "unavailable";
  const result = stationView(discoverStations(input)[0], NOW);
  assert.equal(result.flow.value, "0");
  assert.equal(result.height.value, "—");
  assert.equal(result.height.trend, null);
  assert.equal(result.health, "degraded");
});
test("marks Hub'Eau fallback and old cached measurements visibly", () => {
  const input = states();
  input["sensor.renamed_flow"].attributes.source = "hubeau";
  let result = stationView(discoverStations(input)[0], NOW);
  assert.equal(result.healthLabel, "Source de secours");
  assert.equal(result.flow.source, "Hub’Eau");
  for (const entity of Object.values(input)) entity.attributes.data_stale = true;
  result = stationView(discoverStations(input)[0], NOW);
  assert.equal(result.health, "stale");
  assert.equal(result.vigilanceStale, true);
});
test("ages measurements even if Home Assistant has not refreshed the states", () => {
  const result = stationView(discoverStations(states())[0], NOW + 3 * 3600000);
  assert.equal(result.health, "stale");
  assert.equal(result.height.stale, true);
  assert.equal(result.vigilanceStale, true);
});
test("missing dates and unknown vigilance are not described as current or green", () => {
  const input = states();
  delete input["sensor.renamed_height"].attributes.timestamp;
  input["sensor.renamed_vigilance"].state = "unavailable";
  const result = stationView(discoverStations(input)[0], NOW);
  assert.equal(result.height.stale, true);
  assert.equal(result.vigilance, null);
});
test("missing measurements produce an unavailable station rather than empty zeroes", () => {
  const result = stationView({ id: "missing", name: "Missing", entities: {} }, NOW);
  assert.equal(result.health, "unavailable");
  assert.equal(result.flow.value, "—");
});
test("supports multiple stations and ignores unrelated sensors", () => {
  const input = states();
  input["sensor.second"] = state("hauteur", "2", { station_id: "F700000103", station_name: "Paris" });
  input["sensor.other"] = { state: "1", attributes: { station_id: "OTHER", unit_of_measurement: "m" } };
  assert.deepEqual(discoverStations(input).map(s => s.id), ["F700000103", "H413041010"]);
});
test("keeps compatibility with version 1.1.0 sensor attributes", () => {
  const input = states();
  for (const entity of Object.values(input)) {
    delete entity.attributes.integration;
    delete entity.attributes.sensor_type;
    entity.attributes.data_status = "ok";
  }
  assert.equal(Object.keys(discoverStations(input)[0].entities).length, 5);
});
test("configuration distinguishes all stations from an explicit empty selection", () => {
  const frozen = Object.freeze({ stations: Object.freeze(["H413041010", "H413041010"]) });
  assert.deepEqual(normalizeConfig(frozen).stations, ["H413041010"]);
  assert.equal(normalizeConfig({}).stations, undefined);
  assert.deepEqual(normalizeConfig({ stations: [] }).stations, []);
  assert.throws(() => normalizeConfig({ stations: "H413041010" }));
  assert.throws(() => normalizeConfig({ stations: [null] }));
});

test("distinguishes a 45-minute measurement from a recent successful collection", () => {
  const input = states();
  for (const type of ["height", "flow"]) {
    const resource = type === "height" ? "hauteur" : "debit";
    const attrs = input[`sensor.renamed_${type}`].attributes;
    attrs.timestamp = new Date(NOW - 45 * 60000).toISOString();
    attrs.last_success = { [resource]: new Date(NOW - 2 * 60000).toISOString() };
  }
  const result = stationView(discoverStations(input)[0], NOW);
  assert.equal(result.healthLabel, "Collecte OK");
  assert.equal(result.height.ageLabel, "Il y a 45 min");
  assert.equal(result.height.collectionLabel, "Il y a 2 min");
  assert.equal(result.flow.collectionLabel, "Il y a 2 min");
  assert.equal(result.height.stale, false);
});

test("never invents a collection time when only the measurement date is known", () => {
  const result = stationView(discoverStations(states())[0], NOW);
  assert.equal(result.height.collectionLabel, "Date inconnue");
  assert.equal(result.flow.collectionLabel, "Date inconnue");
});
