"use strict";

const API_ROOT = "/api/v1";
const state = {
  apiKey: sessionStorage.getItem("trading-system-api-key") || "",
  payloads: {},
};

const endpoints = {
  health: "/health",
  readiness: "/ready",
  positions: "/positions",
  opportunities: "/opportunities?limit=10",
  markets: "/markets/evaluations",
  performance: "/analytics/performance",
  assetStats: "/analytics/assets",
  coverage: "/market-data/universe-coverage",
  brief: "/assistant/brief",
  metrics: "/assistant/metrics",
};

function el(id) { return document.getElementById(id); }

function setNotice(message, isError = false) {
  const notice = el("notice");
  if (!message) {
    notice.classList.add("hidden");
    notice.textContent = "";
    return;
  }
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  notice.classList.remove("hidden");
}

function headers(hasBody = false) {
  const result = { Accept: "application/json" };
  if (hasBody) result["Content-Type"] = "application/json";
  if (state.apiKey) result["X-API-Key"] = state.apiKey;
  return result;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: options.method || "GET",
    headers: headers(Boolean(options.body)),
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = { error: { code: "INVALID_RESPONSE", message: "Response was not JSON" } };
  }
  if (!response.ok) {
    const error = payload?.error?.message || `HTTP ${response.status}`;
    throw new Error(error);
  }
  return payload;
}

function safeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function fmt(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderJson(targetId, payload) {
  const target = el(targetId);
  target.textContent = payload ? JSON.stringify(payload, null, 2) : "No data loaded.";
}

function tableColumns(rows) {
  const preferred = ["symbol", "canonical_symbol", "base_asset", "status", "direction", "score", "confidence", "entry_price", "current_price", "unrealized_pnl", "source", "provider_symbol", "price_deviation_percent", "reason"];
  const keys = new Set();
  rows.forEach((row) => Object.keys(safeObject(row)).forEach((key) => keys.add(key)));
  const ordered = preferred.filter((key) => keys.has(key));
  for (const key of keys) if (!ordered.includes(key)) ordered.push(key);
  return ordered.slice(0, 9);
}

function renderTable(targetId, rows) {
  const target = el(targetId);
  target.replaceChildren();
  if (!Array.isArray(rows) || rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No records available.";
    target.appendChild(empty);
    return;
  }
  const columns = tableColumns(rows);
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.replaceAll("_", " ");
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      td.textContent = fmt(row[column]);
      td.title = td.textContent;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  target.appendChild(table);
}

function metric(label, value, sub = "") {
  const card = document.createElement("div");
  card.className = "metric";
  const l = document.createElement("div"); l.className = "label"; l.textContent = label;
  const v = document.createElement("div"); v.className = "value"; v.textContent = fmt(value);
  const s = document.createElement("div"); s.className = "sub"; s.textContent = sub;
  card.append(l, v, s);
  return card;
}

function coveragePayload() {
  return safeObject(state.payloads.coverage?.universe_coverage);
}

function renderCoverage(targetId) {
  const target = el(targetId);
  target.replaceChildren();
  const coverage = coveragePayload();
  if (!Object.keys(coverage).length) {
    const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "Coverage data unavailable."; target.appendChild(empty); return;
  }
  const grid = document.createElement("div");
  grid.className = "coverage-grid";
  [
    ["(reference) Storm", coverage.reference_storm],
    ["Gate.io", coverage.gateio],
    ["yfinance", coverage.yfinance],
    ["No Data", coverage.no_data],
  ].forEach(([label, value]) => {
    const item = document.createElement("div"); item.className = "coverage-item";
    const name = document.createElement("span"); name.textContent = label;
    const count = document.createElement("strong"); count.textContent = fmt(value);
    item.append(name, count); grid.appendChild(item);
  });
  target.appendChild(grid);
  const progress = document.createElement("div"); progress.className = "progress";
  const bar = document.createElement("div");
  const percent = Number(coverage.coverage_percent || 0);
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  progress.appendChild(bar); target.appendChild(progress);
  const label = document.createElement("p"); label.className = "muted"; label.textContent = `Resolved ${fmt(coverage.resolved)} / ${fmt(coverage.reference_storm)} — ${fmt(percent)}% coverage`;
  target.appendChild(label);
  renderTable("markets-coverage", coverage.assets || []);
}

function renderSummary() {
  const target = el("summary-cards"); target.replaceChildren();
  const health = safeObject(state.payloads.health);
  const positions = state.payloads.positions?.positions || [];
  const opportunities = state.payloads.opportunities?.opportunities || [];
  const markets = state.payloads.markets?.markets || [];
  const coverage = coveragePayload();
  const readiness = safeObject(state.payloads.readiness?.readiness);
  target.append(
    metric("System", health.status || "unknown", `${health.mode || "—"} · ${health.version || "—"}`),
    metric("Positions", positions.length, "Open repository records"),
    metric("Ranking", opportunities.length, "Qualified opportunities"),
    metric("Data Coverage", `${fmt(coverage.coverage_percent || 0)}%`, `${fmt(coverage.resolved || 0)} / ${fmt(coverage.reference_storm || 0)}`),
    metric("Readiness", readiness.ready ?? readiness.status ?? "see details", "Backend diagnostics"),
  );
}

function renderAll() {
  renderSummary();
  const positions = state.payloads.positions?.positions || [];
  const opportunities = state.payloads.opportunities?.opportunities || [];
  const markets = state.payloads.markets?.markets || [];
  renderTable("dashboard-opportunities", opportunities);
  renderTable("ranking-table", opportunities);
  renderTable("all-markets-table", markets);
  renderTable("dashboard-positions", positions);
  renderTable("positions-table", positions);
  renderCoverage("dashboard-coverage");
  renderJson("performance-json", state.payloads.performance || null);
  renderJson("journal-json", state.payloads.performance || null);
  renderTable("asset-statistics-table", state.payloads.assetStats?.asset_statistics || []);
  renderJson("risk-json", state.payloads.readiness || null);
  renderJson("news-json", state.payloads.brief || null);
  renderJson("assistant-metrics-json", state.payloads.metrics || null);
  renderJson("system-json", { health: state.payloads.health || null, readiness: state.payloads.readiness || null, universe_coverage: state.payloads.coverage || null });
}

async function refreshAll() {
  setNotice("Refreshing dashboard…");
  const entries = Object.entries(endpoints);
  const results = await Promise.allSettled(entries.map(([, path]) => api(path)));
  let failures = 0;
  results.forEach((result, index) => {
    const [name] = entries[index];
    if (result.status === "fulfilled") state.payloads[name] = result.value;
    else { state.payloads[name] = null; failures += 1; }
  });
  renderAll();
  const healthOk = Boolean(state.payloads.health?.status === "ok");
  const badge = el("connection-badge");
  badge.textContent = healthOk ? "API connected" : "API unavailable";
  badge.className = `badge ${healthOk ? "good" : "bad"}`;
  if (failures) setNotice(`${failures} data source(s) were unavailable. Protected endpoints may require an API key.`, true);
  else setNotice("");
}

function switchView(view) {
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${view}`));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  const active = document.querySelector(`.nav-item[data-view="${view}"]`);
  el("view-title").textContent = active ? active.textContent : "Dashboard";
}

function installEvents() {
  el("nav").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (button) switchView(button.dataset.view);
  });
  el("refresh-all").addEventListener("click", refreshAll);
  el("save-key").addEventListener("click", () => {
    state.apiKey = el("api-key").value.trim();
    if (state.apiKey) sessionStorage.setItem("trading-system-api-key", state.apiKey);
    else sessionStorage.removeItem("trading-system-api-key");
    setNotice("API key updated for this browser session only.");
    refreshAll();
  });
  el("clear-key").addEventListener("click", () => {
    state.apiKey = ""; el("api-key").value = ""; sessionStorage.removeItem("trading-system-api-key");
    setNotice("Session API key cleared.");
  });
  el("assistant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = el("assistant-query").value.trim();
    if (!query) return;
    el("assistant-response").textContent = "Loading…";
    try {
      const payload = await api("/assistant/query", { method: "POST", body: { query } });
      renderJson("assistant-response", payload);
    } catch (error) {
      el("assistant-response").textContent = error instanceof Error ? error.message : "Assistant request failed";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  el("api-key").value = state.apiKey;
  installEvents();
  refreshAll();
});
