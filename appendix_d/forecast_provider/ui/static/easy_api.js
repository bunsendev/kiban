import { request } from "./api.js";

const encoded = (value) => encodeURIComponent(value);

export function loadEasySetup() {
  return Promise.all([
    request("/api/session"),
    request("/api/mappings"),
    request("/api/mapping-dry-run-sources"),
  ]).then(([session, mappings, sources]) => ({ session, mappings, sources }));
}

export function loadEasySources() {
  return request("/api/mapping-dry-run-sources");
}

export function loadEasySource(sourcePath) {
  return request(`/api/mapping-dry-run-sources?source_path=${encoded(sourcePath)}`)
    .then((catalog) => catalog.items[0] || null);
}

export function uploadEasySource(file) {
  const filename = encoded(file.name);
  const path = file.name.toLocaleLowerCase("en").endsWith(".zip")
    ? `/api/mapping-dry-run-bulk-uploads?filename=${filename}`
    : `/api/mapping-dry-run-uploads?filename=${filename}`;
  return request(path, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

export function startEasyAnalysis(selection, mappingId) {
  const isBatch = Boolean(selection.sourcePrefix);
  return request(isBatch ? "/api/mapping-dry-run-batches" : "/api/mapping-dry-run-jobs", {
    method: "POST",
    body: JSON.stringify(isBatch
      ? { source_prefix: selection.sourcePrefix, mapping_id: mappingId, sample_rows: 1000 }
      : { source_path: selection.sourcePath, mapping_id: mappingId, sample_rows: 1000 }),
  });
}

export function sendEasyOperationEvent(payload) {
  return request("/api/operation-events", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
