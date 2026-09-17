import { request } from "./api.js";

export function loadAnalysisDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/snapshots?limit=200"),
    request("/api/experiments?limit=200"),
    request("/api/providers"),
    request("/api/runs?limit=200"),
    request("/api/provider-conformance-tests"),
    request("/api/provider-conformance-jobs"),
    request("/api/comparisons"),
    request("/api/worker-status"),
    request("/api/comparison-campaigns"),
  ]).then(([
    session, snapshots, experiments, providers, runs, conformances, conformanceJobs,
    comparisons, workerStatus, campaigns,
  ]) => ({
    session, snapshots, experiments, providers, runs, conformances, conformanceJobs,
    comparisons, workerStatus, campaigns,
  }));
}

export function createCampaign(payload) {
  return request("/api/comparison-campaigns", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createExperiment(payload) {
  return request("/api/experiments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createRun(experimentId) {
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({ experiment_id: experimentId }),
  });
}

export function createConformanceJob(experimentId) {
  return request("/api/provider-conformance-jobs", {
    method: "POST",
    body: JSON.stringify({ experiment_id: experimentId }),
  });
}

export function createComparison(payload) {
  return request("/api/comparisons", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
