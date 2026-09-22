import { download, request } from "./api.js";

export function loadFeedback(days) {
  return Promise.all([
    request("/api/session"),
    request(`/api/operation-events/summary?days=${days}`),
    request(`/api/operation-events?days=${days}&limit=200`),
  ]).then(([session, summary, events]) => ({ session, summary, events }));
}

export function downloadFeedback(days) {
  return download(`/api/operation-events/export.csv?days=${days}`, "operation-events.csv");
}
