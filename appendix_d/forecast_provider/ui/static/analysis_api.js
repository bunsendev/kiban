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
    request("/api/comparison-campaign-results?limit=50"),
    request("/api/model-drift-reviews?limit=200"),
    request("/api/model-drift-review-actions?limit=200"),
    request("/api/model-drift-review-action-events?limit=500"),
  ]).then(([
    session, snapshots, experiments, providers, runs, conformances, conformanceJobs,
    comparisons, workerStatus, campaigns, campaignResults, modelReviews,
    reviewActions, reviewActionEvents,
  ]) => ({
    session, snapshots, experiments, providers, runs, conformances, conformanceJobs,
    comparisons, workerStatus, campaigns, campaignResults, modelReviews,
    reviewActions, reviewActionEvents,
  }));
}

export function createModelDriftReview(payload) {
  return request("/api/model-drift-reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createReviewAction(payload) {
  return request("/api/model-drift-review-actions", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function updateReviewAction(actionId, payload) {
  return request(`/api/model-drift-review-actions/${encodeURIComponent(actionId)}/events`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function createCampaign(payload) {
  return request("/api/comparison-campaigns", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createCampaignBatch(payload) {
  return request("/api/comparison-campaign-batches", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function retryCampaignFinalization(campaignId) {
  return request(`/api/comparison-campaigns/${encodeURIComponent(campaignId)}/retry-finalization`, {
    method: "POST",
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
