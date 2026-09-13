import { request, setToken } from "./api.js";

const STORAGE_KEY = "kiban.oidc.pkce.v1";
const MAX_AGE_MS = 5 * 60 * 1000;

function randomValue(bytes = 32) {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return Array.from(value, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function base64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function challenge(verifier) {
  return base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
}

function callbackUri(path) {
  return `${window.location.origin}${path}`;
}

function cleanCallbackUrl(returnPath = "/ui") {
  history.replaceState(null, "", returnPath.startsWith("/ui") ? returnPath : "/ui");
}

async function startLogin(config) {
  const verifier = randomValue(48);
  const state = randomValue(32);
  const returnPath = window.location.pathname.startsWith("/ui/auth/") ? "/ui" : window.location.pathname;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ verifier, state, returnPath, createdAt: Date.now() }));
  const url = new URL(config.authorization_url);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.client_id);
  url.searchParams.set("redirect_uri", callbackUri(config.redirect_path));
  url.searchParams.set("scope", config.scopes.join(" "));
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", await challenge(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  window.location.assign(url);
}

async function finishLogin(config) {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("code") && !params.has("error")) return false;
  const raw = sessionStorage.getItem(STORAGE_KEY);
  sessionStorage.removeItem(STORAGE_KEY);
  let saved;
  try { saved = JSON.parse(raw); } catch { saved = null; }
  cleanCallbackUrl(saved?.returnPath);
  if (!saved || Date.now() - saved.createdAt > MAX_AGE_MS || params.get("state") !== saved.state) {
    throw new Error("OIDC stateを検証できませんでした。");
  }
  if (params.has("error")) throw new Error("IdPでログインを完了できませんでした。");
  const response = await fetch("/api/ui-auth/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code: params.get("code"),
      code_verifier: saved.verifier,
      redirect_uri: callbackUri(config.redirect_path),
    }),
  });
  if (!response.ok) throw new Error("OIDC code交換に失敗しました。");
  const token = await response.json();
  setToken(token.access_token);
  const session = await request("/api/session");
  document.getElementById("connection-form").hidden = true;
  document.getElementById("session-controls").hidden = false;
  document.getElementById("session-identity").textContent = `${session.subject} / ${session.roles.join(", ")}`;
  document.getElementById("refresh-button").click();
  return true;
}

export async function installPkceLogin() {
  const response = await fetch("/api/ui-auth/config");
  if (!response.ok) return;
  const config = await response.json();
  if (!config.enabled) return;
  const form = document.getElementById("connection-form");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button quiet oidc-login";
  button.textContent = "IdPでログイン";
  button.addEventListener("click", () => startLogin(config));
  form.append(button);
  try { await finishLogin(config); } catch (error) {
    form.hidden = false;
    button.textContent = error.message;
  }
}
