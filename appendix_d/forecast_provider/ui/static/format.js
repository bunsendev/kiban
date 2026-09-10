export function shortId(value, size = 12) {
  if (!value) return "—";
  const text = String(value);
  return text.length <= size ? text : `${text.slice(0, size)}…`;
}

export function dateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function metric(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 3 }).format(value);
}

export function rate(value) {
  if (value === null || value === undefined) return "—";
  return `${metric(Number(value) * 100)}%`;
}

export function listText(values) {
  return (values || []).join(", ");
}

export function parseList(value) {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))];
}

export function statusTone(value) {
  if (["ADOPTED", "APPROVED", "PASSED", "SUCCEEDED", true].includes(value)) {
    return "positive";
  }
  if (["REJECTED", "FAILED", false].includes(value)) return "negative";
  if (["DRY_RUN", "RUNNING", "QUEUED", "PARTIAL"].includes(value)) return "warning";
  return "neutral";
}

export function decisionLabel(value) {
  const labels = {
    ADOPTED: "採用",
    REJECTED: "却下",
    APPROVED: "承認",
    PASSED: "合格",
    SUCCEEDED: "完了",
    DRY_RUN: "匿名検証",
    FAILED: "失敗",
    RUNNING: "実行中",
    QUEUED: "待機中",
  };
  return labels[value] || value || "未判断";
}
