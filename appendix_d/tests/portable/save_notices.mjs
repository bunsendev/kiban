import assert from 'node:assert/strict';
const notices=[];
globalThis.window={alert:message=>notices.push(message)};
const {saveWithNotice}=await import('../../portable/api/static/field/api.js');
let complete;
const pending=saveWithNotice(()=>new Promise(resolve=>{complete=resolve;}),'保存しました。');
await Promise.resolve();assert.equal(notices.length,0);
complete({saved:true});assert.deepEqual(await pending,{saved:true});
assert.deepEqual(notices,['保存しました。']);
const failure=new Error('synthetic-secret-never-display');
await assert.rejects(saveWithNotice(()=>Promise.reject(failure)),error=>error===failure);
assert.equal(notices.length,2);assert(notices[1].includes('保存を確認できません'));
assert(!notices.join('').includes('synthetic-secret'));
notices.length=0;
class Element extends EventTarget {
 constructor(tag){super();this.tagName=tag;this.children=[];this.style={};this.value='';}
 append(n){this.children.push(n);n.parent=this;}
 setAttribute(k,v){this[k]=v;}
 showModal(){this.open=true;}
 close(){this.dispatchEvent(new Event('close'));}
 remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
}
class Document extends EventTarget {createElement(tag){return new Element(tag);}}
globalThis.document=new Document();
let available=false,fail=false,unreadable=false;
globalThis.fetch=async(url,options={})=>{
 let value,ok=true;
 if(url==='/api/ai-credentials'){
  if(options.method==='POST'){
   assert.equal(JSON.parse(options.body).api_key,'sk-synthetic');
   if(fail){ok=false;value={detail:'保存できません'};}else{available=true;}
  }
  value??={saved:available,available:available&&!unreadable};
 }else if(url==='/api/ai-credentials/delete'){available=false;value={saved:false,available:false};}
 else throw new Error('unexpected endpoint');
 return {ok,json:async()=>value};
};
const all=n=>[n,...n.children.flatMap(all)];
const find=(n,text)=>all(n).find(x=>x.textContent===text);
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const {settings}=await import('../../portable/api/static/field/settings.js');
const host=new Element('main');settings({},host);await tick();
find(host,'AI・API設定').onclick();await tick();
const key=all(host).find(n=>n.type==='password'),save=find(host,'このPCに保存・変更');
key.value=' sk-synthetic ';await save.onclick();
assert.equal(key.value,'');assert.equal(notices.length,1);
assert(notices[0].includes('このPCに保存しました'));
assert(notices[0].includes('接続確認'));assert(!notices[0].includes('sk-synthetic'));
assert(all(host).some(n=>n.textContent?.includes('保存済み・このユーザーで読込確認済み')));
fail=true;key.value='sk-synthetic';await save.onclick();
assert.equal(notices.length,2);assert(notices[1].includes('確認できません'));
assert.equal(key.value,'sk-synthetic');assert.equal(save.disabled,false);
fail=false;unreadable=true;await save.onclick();
assert.equal(notices.length,3);assert(notices[2].includes('確認できません'));
unreadable=false;
all(host).find(n=>n.type==='checkbox').checked=true;
await find(host,'APIキーを削除').onclick();
assert.equal(notices.length,4);assert(notices[3].includes('削除しました'));
assert.equal(key.value,'');
console.log('PASS: pending write, success, failure, secret suppression, key save/readback/delete');
