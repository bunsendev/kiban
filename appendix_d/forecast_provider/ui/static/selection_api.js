import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadSelectionDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/daily-builds"),
    request("/api/selection-candidate-jobs"),
    request("/api/selections"),
  ]).then(([session, builds, jobs, selections]) => ({ session, builds, jobs, selections }));
}

export function createCandidateJob(payload) {
  return request("/api/selection-candidate-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadCandidateJob(jobId) {
  const id = encoded(jobId);
  return Promise.all([
    request(`/api/selection-candidate-jobs/${id}`),
    request(`/api/selection-candidate-jobs/${id}/candidates`),
  ]).then(([job, candidates]) => ({ job, candidates }));
}

export function createSelection(payload) {
  return request("/api/selections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
