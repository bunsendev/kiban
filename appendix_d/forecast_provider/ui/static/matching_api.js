import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadMatchingDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/matching/jobs"),
    request("/api/products"),
    request("/api/matching/decisions"),
    request("/api/jan-mappings"),
    request("/api/normalizations"),
  ]).then(([session, jobs, products, decisions, mappings, normalizations]) => ({
    session,
    jobs,
    products,
    decisions,
    mappings,
    normalizations,
  }));
}

export function loadMatchingJob(jobId) {
  return request(`/api/matching/jobs/${encoded(jobId)}`);
}

export function createMatchingJob(payload) {
  return request("/api/matching/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function createProduct(payload) {
  return request("/api/products", { method: "POST", body: JSON.stringify(payload) });
}

export function createDecision(payload) {
  return request("/api/matching/decisions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createJanMapping(payload) {
  return request("/api/jan-mappings", { method: "POST", body: JSON.stringify(payload) });
}
