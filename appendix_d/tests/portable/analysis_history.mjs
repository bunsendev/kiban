import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import "../../portable/api/static/field/history-label.js";

const item = {analysis_id: "abc123456789" + "d".repeat(52),
  created_at: "2026-10-20T01:02:03Z", created_at_source: "analysis", warehouses: ["70301", "70302"],
  review: {status: "CONFIRMED_FOR_REFERENCE", pending_rows: 0}, rows: {auto_confirmed: 6047}};
const label = PortableAnalysisHistory.label(item);
assert(label.includes("2026/10/20 10:02:03 日本時間"));
assert(label.includes("70301・70302") && label.includes("ID abc123456789"));
assert(PortableAnalysisHistory.label({...item, created_at_source: "daily_run"}).includes("処理記録日時（旧版）"));
for (const value of [null, "bad"]) {
  assert(PortableAnalysisHistory.label({...item, created_at: value}).includes("記録なし（旧版）"));
}
class Element {
  constructor(tag){ this.tag=tag; this.children=[]; this.events={}; }
  replaceChildren(){ this.children=[]; }
  appendChild(child){ this.children.push(child); }
  addEventListener(event, action){ this.events[event]=action; }
}
const history = new Element("ul"); let opened = null;
const source = fs.readFileSync(new URL("../../portable/api/static/app.js", import.meta.url), "utf8");
const fn = source.slice(source.indexOf("async function refreshAnalyses()"),
  source.indexOf("document.getElementById('analysis-reload')"));
const context = vm.createContext({PortableAnalysisHistory,
  document:{getElementById:()=>history, createElement:tag=>new Element(tag)},
  fetch:async url=>({ok:true, json:async()=>url==="/api/business-archives"?[item]:item}),
  showAnalysis:report=>{opened=report;}, encodeURIComponent,
});
await vm.runInContext(fn + "refreshAnalyses()", context);
const button = history.children[0].children[0];
assert(button.textContent.includes(label));
assert(button.textContent.includes("CONFIRMED_FOR_REFERENCE") && button.textContent.includes("6,047"));
await button.events.click(); assert.equal(opened.analysis_id, item.analysis_id);
const field = fs.readFileSync(new URL("../../portable/api/static/field/upload.js", import.meta.url), "utf8");
assert(field.includes('import "./history-label.js"'));
assert(field.includes("PortableAnalysisHistory.label(r)"));
console.log("PASS analysis history JST/legacy/warehouse labels and actual history selection");
