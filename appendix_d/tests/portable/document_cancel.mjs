import assert from 'node:assert/strict';
import {cancelControl} from '../../portable/api/static/field/document-cancel.js';
class Element{constructor(){this.children=[];this.hidden=false;}append(n){this.children.push(n);}setAttribute(){}}
globalThis.document={createElement:()=>new Element()};
const parent=new Element();let stopped=false,refreshed=0,sent=0,message='';
globalThis.fetch=async(url)=>{assert.equal(url,'/api/documents/test/cancel');sent++;return {ok:true,json:async()=>({cancelled:true})};};
const panel=cancelControl({run:fn=>fn(),message:t=>{message=t;}},parent,'test',v=>{stopped=v;},async()=>{refreshed++;});
assert(panel.hidden);await parent.children.at(-1).onclick();assert(!panel.hidden);
await panel.children.find(n=>n.textContent==='戻る').onclick();assert(panel.hidden);assert.equal(sent,0);
await parent.children.at(-1).onclick();await panel.children.find(n=>n.textContent==='取りやめる').onclick();
assert(stopped);assert.equal(sent,1);assert.equal(refreshed,1);assert.match(message,/取りやめました/);
globalThis.fetch=async()=>{throw new Error('network')};
await assert.rejects(panel.children.find(n=>n.textContent==='取りやめる').onclick());assert.equal(stopped,false);
console.log('PASS inline cancel confirmation, back, persisted cancellation, network error reset');
