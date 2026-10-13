import { api, el, field, button, saveWithNotice } from './api.js';

export async function masterPanel(ctx,parent){
  const box=el('details','',parent);el('summary','JANマスターを登録・選択する',box);
  el('p','XLSXの使用シートと適用開始日を指定してください。商品名・商品コード・JANコードの順、または商品名・JANコード・商品コードの表に対応します。過去シートは混ぜません。候補は原本と照合して選びます。',box);
  const file=field(box,'JANマスター（XLSX）','file');file.accept='.xlsx';
  const sheet=el('select','',el('label','使用シート',box));
  const day=field(box,'このマスターの適用開始日','date');
  const choice=el('select','',el('label','照合に使うマスター版',box));
  const state={choice};
  async function refresh(){
    choice.replaceChildren();const blank=el('option','選択してください',choice);blank.value='';
    for(const v of await api('/api/document-master')){const o=el('option',`${v.sheet} ／ ${v.effective_date}以降 ／ ${v.count}件 ／ ${v.version.slice(0,8)}`,choice);o.value=v.version;}
  }
  async function upload(headers){
    const f=file.files?.[0];if(!f)throw new Error('マスターを選択してください');
    if(f.size>10*1024*1024)throw new Error('10 MB以内で選択してください');
    const r=await fetch('/api/document-master',{method:'POST',headers,body:f});const v=await r.json();
    if(!r.ok)throw new Error(v.detail||'マスターを確認してください');return v;
  }
  button('使用できるシートを確認',()=>ctx.run(async()=>{
    const v=await upload({});sheet.replaceChildren();for(const name of v.sheets){const o=el('option',name,sheet);o.value=name;}
  }),box,true);
  button('この版を登録する',()=>ctx.run(async()=>{
    if(!sheet.value||!day.value)throw new Error('シートと適用開始日を指定してください');
    const v=await saveWithNotice(()=>upload({'X-Master-Sheet':encodeURIComponent(sheet.value),'X-Effective-Date':day.value}),'JANマスターを登録しました。候補の採用には原本確認が必要です。');
    await refresh();choice.value=v.version;ctx.message(`${v.count}件を登録しました。無効な明細：${v.invalid_rows}件。候補を選んでも原本確認は必要です。`);
  }),box);await refresh();return state;
}

export function masterChoice(ctx,parent,controls,state){
  const version=el('input','',parent);version.type='hidden';controls.master_version=version;
  const source=el('input','',parent);source.type='hidden';controls.master_cell=source;
  const list=el('div','',parent);
  button('JANマスターから候補を探す',()=>ctx.run(async()=>{
    const v=state.choice.value;if(!v)throw new Error('上のJANマスターで照合に使う版を選んでください');
    const row=Object.fromEntries(['jan','product_code','product_name'].map(k=>[k,controls[k].value]));
    const response=await api('/api/document-master/candidates',{version:v,row});list.replaceChildren();
    el('p','JANが途中までの場合も下6桁をJANコード表と照合します。候補は最大30件です。同じ下6桁の別商品があり得るため、商品名・商品コード・13桁JANと原本の日付に適した版を確認して選んでください。自動確定はしません。',list);
    if(!response.candidates.length)el('p','候補がありません。名前の表記を確認してください。',list);
    for(const p of response.candidates)button(`${p.match_basis||'候補'}：${p.product_name} ／ ${p.product_code} ／ ${p.jan}`,()=>{
      controls.jan.value=p.jan;controls.product_code.value=p.product_code;version.value=v;source.value=p.cell;controls.jan.dispatchEvent(new Event('input',{bubbles:true}));
      ctx.message('候補を入力しました。原本と商品・JANを照合してから保存してください。');
    },list,true);
  }),parent,true);
}
