import { request } from "./api.js";

export function loadResourceDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/runs?limit=200"),
    request("/api/resource-unit-prices"),
  ]).then(([session, runs, prices]) => ({ session, runs, prices }));
}

export function loadRunResources(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}/resources`);
}

export function createUnitPrice(payload) {
  return request("/api/resource-unit-prices", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
