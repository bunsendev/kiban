export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let token = "";

export function setToken(value) {
  token = value.trim();
}

export function clearToken() {
  token = "";
}

export async function request(path, options = {}) {
  if (!token) throw new ApiError(401, "API tokenを入力してください。");
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof Blob) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `API error (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // JSONではないエラーもstatusを維持して扱う。
    }
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? null : response.json();
}

export function loadDashboard() {
  return Promise.all([
    request("/api/session"),
    request("/api/comparisons"),
    request("/api/acceptance-cases"),
    request("/api/exports"),
    request("/api/adoptions"),
  ]).then(([session, comparisons, acceptances, exports, adoptions]) => ({
    session,
    comparisons,
    acceptances,
    exports,
    adoptions,
  }));
}

export function loadComparison(comparisonId) {
  return Promise.all([
    request(`/api/comparisons/${encodeURIComponent(comparisonId)}`),
    request(`/api/comparisons/${encodeURIComponent(comparisonId)}/adoption-context`),
  ]).then(([detail, context]) => ({ detail, context }));
}

export function createExport(comparisonId, payload) {
  return request(`/api/comparisons/${encodeURIComponent(comparisonId)}/exports`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createAdoption(payload) {
  return request("/api/adoptions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createAcceptanceDecision(caseId, payload) {
  return request(`/api/acceptance-cases/${encodeURIComponent(caseId)}/decisions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function downloadExport(record) {
  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const response = await fetch(`/api/exports/${encodeURIComponent(record.export_id)}`, {
    headers,
  });
  if (!response.ok) {
    let message = `CSV取得に失敗しました (${response.status})`;
    try {
      message = (await response.json()).detail || message;
    } catch {
      // JSONではないエラーも共通メッセージで扱う。
    }
    throw new ApiError(response.status, message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `comparison-${record.comparison_id}.csv`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
