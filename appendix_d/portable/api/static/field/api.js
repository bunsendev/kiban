export const el = (tag, text = "", parent) => {
  const n = document.createElement(tag);
  n.textContent = text;
  if (parent) parent.append(n);
  return n;
};
export const button = (text, action, parent, secondary = false) => {
  const n = el("button", text, parent);
  n.type = "button";
  n.onclick = action;
  if (secondary) n.className = "secondary";
  return n;
};
export function field(parent, text, type = "text", required = true) {
  const l = el("label", text, parent),
    n = el("input", "", l);
  n.type = type;
  n.required = required;
  return n;
}
export async function api(url, body) {
  const r = await fetch(
    url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const v = await r.json();
  if (!r.ok)
    throw new Error(
      typeof v.detail === "string"
        ? v.detail
        : "入力内容と接続を確認してください",
    );
  return v;
}
export async function download(url, body) {
  const endpoint = url.replace(/\/(issues-download|download)$/, "/export");
  const value = await api(endpoint, {
    ...body,
    kind: url.endsWith("issues-download") ? "issues" : "results",
  });
  const a = el("a", "", document.body);
  a.href = value.download_href;
  a.download = "予測結果と担当者判断.csv";
  a.click();
  a.remove();
}

export function displayTime(value) {
  if (!value) return "未確定";
  if (!value.includes("T")) return value;
  return (
    new Date(value).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) +
    "（日本時間）"
  );
}
