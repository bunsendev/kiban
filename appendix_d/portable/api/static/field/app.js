import { api, saveWithNotice } from "./api.js";
import { upload } from "./upload.js";
import { analysis } from "./progress.js";
import { results } from "./results.js";

const root = document.getElementById("screen"),
  status = document.getElementById("status");
let sequence = 0;
const flow = crypto.randomUUID();
const ctx = {
  root,
  step: 1,
  analysisId: null,
  resultId: null,
  dirty: false,
  timer: null,
  message(text, error = false) {
    status.textContent = text;
    status.className = error ? "error" : "";
  },
  async run(fn) {
    try {
      await fn();
    } catch (e) {
      ctx.message(e.message, true);
    }
  },
  enter(step) {
    if (ctx.timer) clearTimeout(ctx.timer);
    ctx.timer = null;
    ctx.step = step;
    root.dataset.step = String(step);
    root.className = "";
    root.replaceChildren();
    window.scrollTo(0, 0);
    ctx.message("");
    [...document.querySelectorAll("#steps li")].forEach((n, i) => {
      n.removeAttribute("aria-current");
      if (i === step - 1) n.setAttribute("aria-current", "step");
    });
    ctx.event("STEP_VIEWED");
  },
  event(name) {
    api("/api/field/events", {
      event_id: crypto.randomUUID(),
      flow_session_id: flow,
      screen: "field",
      event_name: name,
      step: ctx.step,
      sequence: ++sequence,
      outcome: "INFO",
      occurred_at: new Date().toISOString(),
      metadata: { flow_version: "field-v1" },
    }).catch(() => {});
  },
  async open(id) {
    ctx.analysisId = id;
    localStorage.setItem("field-analysis", id);
    await analysis(ctx);
  },
  async showResults() {
    if (
      ctx.dirty &&
      !confirm("未保存の条件があります。保存せずに結果へ進みますか？")
    )
      return;
    ctx.dirty = false;
    const v = await api(`/api/field/${ctx.analysisId}/results`);
    ctx.resultId = v.result_id;
    ctx.resultWarehouse = "";
    await results(ctx);
  },
  async openSaved(item) {
    if (ctx.dirty && !confirm("未保存の入力があります。保存済み結果へ移動しますか？")) return;
    const value = await api(`/api/field/saved-forecasts/${encodeURIComponent(item.reference)}/results`);
    await ctx.openResult(value.result_id, item.warehouse);
  },
  async openResult(resultId, warehouse = "") {
    const value = await api(`/api/field/results/${resultId}?limit=1`);
    ctx.analysisId = value.analysis_id;
    ctx.resultId = resultId;
    ctx.resultWarehouse = warehouse;
    ctx.dirty = false;
    await results(ctx);
  },
  async home() {
    if (ctx.dirty && !confirm("保存していない入力があります。戻りますか？"))
      return;
    ctx.dirty = false;
    await upload(ctx);
  },
};
window.addEventListener("beforeunload", (e) => {
  if (ctx.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
const help = document.getElementById("help-dialog");
document.getElementById("help").onclick = () => help.showModal();
document.getElementById("help-close").onclick = () => help.close();
document.getElementById("help-form").onsubmit = async (e) => {
  e.preventDefault();
  const msg = document.getElementById("help-status");
  try {
    await saveWithNotice(() => api("/api/field/feedback", {
      comment: e.target.elements.comment.value,
      step: ctx.step,
      analysis_id: ctx.analysisId,
    }), "改善意見をこのPCに保存しました。ご協力ありがとうございます。");
    msg.textContent = "このPCに保存しました。ご協力ありがとうございます。";
    e.target.reset();
  } catch (err) {
    msg.textContent = err.message;
  }
};
ctx.run(() => upload(ctx));
