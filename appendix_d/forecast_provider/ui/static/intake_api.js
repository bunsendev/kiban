import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadIntakeDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/imports"),
    request("/api/mappings"),
    request("/api/source-selections"),
    request("/api/normalizations"),
    request("/api/quality"),
    request("/api/mapping-dry-runs"),
    request("/api/mapping-dry-run-jobs"),
  ]).then(([session, imports, mappings, selections, normalizations, quality, dryRunCatalog, dryRunJobs]) => ({
    session,
    imports,
    mappings,
    selections,
    normalizations,
    quality,
    dryRuns: dryRunCatalog.items,
    dryRunConfigured: dryRunCatalog.configured,
    validDryRunCount: dryRunCatalog.valid_report_count,
    invalidDryRunCount: dryRunCatalog.invalid_report_count,
    dryRunJobs,
  }));
}

export function createMappingDryRunJob(payload) {
  return request("/api/mapping-dry-run-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadMappingDryRunJob(jobId) {
  return request(`/api/mapping-dry-run-jobs/${encoded(jobId)}`);
}

export function loadMappingDryRun(reportSha256) {
  return request(`/api/mapping-dry-runs/${encoded(reportSha256)}`);
}

export function loadImport(importId) {
  return request(`/api/imports/${encoded(importId)}`);
}

export function createImport(payload) {
  return request("/api/imports", { method: "POST", body: JSON.stringify(payload) });
}

export function createMapping(payload) {
  return request("/api/mappings", { method: "POST", body: JSON.stringify(payload) });
}

export function selectSource(payload) {
  return request("/api/source-selections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createNormalization(payload) {
  return request("/api/normalizations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadNormalization(normalizationId, status = "", offset = 0) {
  const id = encoded(normalizationId);
  const params = new URLSearchParams({ limit: "100", offset: String(offset) });
  if (status) params.set("status", status);
  return Promise.all([
    request(`/api/normalizations/${id}/summary`),
    request(`/api/normalizations/${id}/row-page?${params}`),
  ]).then(([summary, page]) => ({ summary, page }));
}
