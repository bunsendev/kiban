import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { savedForecasts } from "../../portable/api/static/field/saved-forecasts.js";
class Node {
 constructor(tag){this.tagName=tag;this.children=[];this.value="";this.hidden=false;this.style={};this.dataset={};}
 append(n){this.children.push(n);n.parentNode=this;}
 appendChild(n){this.append(n);}
 insertBefore(n,b){this.children.splice(this.children.indexOf(b),0,n);n.parentNode=this;}
 replaceChildren(){this.children=[];}
 setAttribute(){} addEventListener(){} scrollIntoView(){} focus(){} click(){}
}
const nodes={"operator-results":new Node("section"),"analysis-result":new Node("section")};
const holder=new Node("main");holder.append(nodes["analysis-result"]);
globalThis.document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id],addEventListener(){}};
globalThis.window={};
const item={kind:"production",reference:"saved-sugito",warehouse:"杉戸",inventory_date:"2026-10-13",period:["2026-10-14","2026-10-27"],series_count:1,created_at:"2026-10-15T01:00:00Z"};
let opened=null, fetches=[];
globalThis.fetch=async (url,options)=>{
 fetches.push([String(url),options]);
 return {ok:true,json:async()=>({items:[item],warehouses:["杉戸"],total:1,unavailable_count:0})};
};
const root=new Node("main");
await savedForecasts(root,async v=>{opened=v;});
const flatten=n=>[n,...n.children.flatMap(flatten)];
const show=flatten(root).find(n=>n.textContent==="この予測を見る");
assert.equal(show.disabled,false);
await show.onclick();assert.deepEqual(opened,item);
assert(flatten(root).some(n=>n.textContent?.includes("在庫基準日 2026-10-13")));
assert(flatten(root).some(n=>n.textContent?.includes("別の倉庫に不足データ")));
fetches=[];
globalThis.fetch=async (url,options)=>{
 fetches.push([String(url),options]);
 return {ok:true,json:async()=>({rows:[{unique_id:"JAN::杉戸",target_date:"2026-10-14",yhat:2}],history:[]}),blob:async()=>new Blob(["csv"])};
};
vm.runInThisContext(fs.readFileSync(new URL("../../portable/api/static/operator-results.js",import.meta.url),"utf8"));
await window.PortableOperatorResults.show("production","saved-sugito","杉戸",true);
assert.equal(fetches[0][0],"/api/operator-results/production/saved-sugito?warehouse="+encodeURIComponent("杉戸"));
assert(flatten(nodes["operator-results"]).some(n=>n.textContent?.includes("保存済みの予測／杉戸")));
const count=fetches.length;
await window.PortableOperatorResults.show("production","new-kobe");
assert.equal(fetches.length,count,"background completion must not replace explicitly selected saved forecast");
const download=flatten(nodes["operator-results"]).find(n=>n.textContent==="全件CSVをダウンロード");
await download.onclick();
assert(fetches.at(-1)[0].includes("saved-sugito/download?warehouse="));
window.PortableOperatorResults.clear();
await window.PortableOperatorResults.show("production","new-kobe");
assert.equal(fetches.at(-1)[0],"/api/operator-results/production/new-kobe");
console.log("PASS saved warehouse/version selection, visible dates, scoped display/export and pinned-result race guard");
