import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadReadinessDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/products"),
    request("/api/handling-periods"),
    request("/api/daily-builds"),
  ]).then(([session, products, periods, builds]) => ({
    session,
    products,
    periods,
    builds,
  }));
}

export function createHandlingPeriod(payload) {
  return request("/api/handling-periods", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadDailyBuild(buildId, filters = {}) {
  const id = encoded(buildId);
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value !== "" && value !== null && value !== undefined) query.set(name, value);
  }
  return Promise.all([
    request(`/api/daily-builds/${id}`),
    request(`/api/daily-builds/${id}/readiness`),
    request(`/api/daily-builds/${id}/completeness`),
    request(`/api/daily-builds/${id}/value-page?${query}`),
  ]).then(([build, readiness, completeness, page]) => ({
    build,
    readiness,
    completeness,
    page,
  }));
}
