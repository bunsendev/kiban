import { request } from "./api.js";

export function loadShadowPreview(payload) {
  return request("/api/field-shadow/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
