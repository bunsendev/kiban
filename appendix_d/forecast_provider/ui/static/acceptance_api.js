import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadAcceptanceDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/daily-builds"),
    request("/api/selections"),
    request("/api/acceptance-cases"),
  ]).then(([session, builds, selections, cases]) => ({ session, builds, selections, cases }));
}

export function createAcceptanceCase(payload) {
  return request("/api/acceptance-cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadAcceptanceCase(caseId) {
  const id = encoded(caseId);
  return Promise.all([
    request(`/api/acceptance-cases/${id}`),
    request(`/api/acceptance-cases/${id}/checks`),
    request(`/api/acceptance-cases/${id}/decisions`),
  ]).then(([record, checks, decisions]) => ({ record, checks, decisions }));
}

export function createAcceptanceDecision(caseId, payload) {
  return request(`/api/acceptance-cases/${encoded(caseId)}/decisions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
