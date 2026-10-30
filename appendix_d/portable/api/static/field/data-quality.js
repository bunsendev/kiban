import {api, el, field, button, displayTime} from './api.js';

const statuses = {NORMAL:'正常', WARNING:'警告・不足あり', ERROR:'重大な確認事項あり'};

export async function qualityPanel(ctx, parent, analysisId) {
  const root=el('section','',parent);root.className='quality-panel';
  el('h2','データの充足状況・不足一覧',root);
  const message=el('p','検証しています…',root);message.setAttribute('role','status');
  let check;
  try { check=await api(`/api/business-archives/${analysisId}/data-quality`); }
  catch(e){message.textContent=e.message;throw e;}
  message.className=`quality-${check.status.toLowerCase()}`;
  message.textContent=`${statuses[check.status]}／検証保存 ${displayTime(check.recorded_at)}`;
  el('p',`対象期間 ${check.required_start||'未確定'} ～ ${check.required_end||'未確定'} ／ 不足 ${check.missing_day_count}日・${check.missing_record_count}レコード ／ 出荷履歴充足率 ${check.coverage_percent===null?'対象なし':check.coverage_percent+'%'} ／ 通常予測可能 ${check.normal_series}商品・倉庫 ／ 暫定予測可能 ${check.provisional_series}商品・倉庫`,root);
  el('p',`最終データ基準日 ${check.latest_data_date||'未確定'} ／ 最終受信 ${check.last_received_at?displayTime(check.last_received_at):'旧版の受信日時は不明'} ／ 最終正常取込 ${check.last_successful_import_at?displayTime(check.last_successful_import_at):'未記録・確認待ち'} ／ 在庫の確認事項 ${check.inventory_attention_count||0}件`,root);
  el('p','受信時刻と在庫基準日は別です。過去の基準日は現在の在庫ではありません。数量0は正常、未受信・未確認の空欄は0へ変更しません。',root);
  const controls=el('div','',root);controls.className='actions';
  button('不足データを追加する',()=>ctx.run(()=>ctx.home()),controls,true);
  button('追加・修正後に再検証',()=>ctx.run(async()=>{
    await api(`/api/business-archives/${analysisId}/data-quality`,{});
    await ctx.open(analysisId);
  }),controls,true);
  const detail=el('details','',root);detail.open=check.missing_record_count>0||check.status==='ERROR';
  el('summary','不足・確認事項を一覧で見る',detail);
  const filters=el('div','',detail);filters.className='quality-filters';
  const wl=el('label','倉庫',filters), warehouse=el('select','',wl);
  el('option','すべて',warehouse).value='';
  for(const w of check.warehouses)el('option',w,warehouse).value=w;
  const jan=field(filters,'JAN・商品名で検索','search',false);
  const day=field(filters,'対象日','date',false);
  const cl=el('label','異常区分',filters),code=el('select','',cl);
  el('option','すべて',code).value='';
  for(const [k,v] of Object.entries(check.labels))el('option',v,code).value=k;
  const grouped=field(filters,'日付別にまとめる','checkbox',false);grouped.checked=true;
  const tableWrap=el('div','',detail);tableWrap.className='table-wrap';
  const count=el('p','',detail), table=el('table','',tableWrap);
  let offset=0,generation=0;
  const nav=el('div','',detail);nav.className='actions';
  const prev=button('前の50件',()=>{offset=Math.max(0,offset-50);ctx.run(load);},nav,true);
  const next=button('次の50件',()=>{offset+=50;ctx.run(load);},nav,true);
  async function load(){
    const token=++generation;
    const params=new URLSearchParams({warehouse:warehouse.value,jan:jan.value,day:day.value,
      code:code.value,group:String(grouped.checked),offset:String(offset),limit:'50'});
    const page=await api(`/api/data-quality/${check.id}/issues?${params}`);
    if(token!==generation)return;
    count.textContent=`該当 ${page.total}件／${page.total?offset+1:0}～${Math.min(offset+50,page.total)}件`;
    table.replaceChildren();const head=el('tr','',el('thead','',table));
    for(const label of ['日付','倉庫','商品','内容','状態','予測への影響'])el('th',label,head);
    const body=el('tbody','',table);
    for(const item of page.items){const row=el('tr','',body);
      for(const value of [item.date||'未確定',item.warehouse,
        grouped.checked?`${item.products}商品`:item.product_name+' '+item.jan,
        grouped.checked?item.codes.map(c=>check.labels[c]||c).join('／'):
          `${check.labels[item.code]||item.code}：${item.detail}`,
        item.state==='RESOLVED'?'補充済み（後続の検証で確認）':item.state==='NOT_RECHECKED'?'後続の検証範囲外・再確認が必要':'未補充・確認待ち',
        grouped.checked?(item.impacts||[]).join('／'):item.impact||'予測条件を確認してください'])el('td',value,row);
    }
    prev.disabled=offset===0;next.disabled=offset+50>=page.total;
  }
  button('条件で絞り込む',()=>{offset=0;ctx.run(load);},filters,true);
  for(const n of [warehouse,day,code,grouped])n.onchange=()=>{offset=0;ctx.run(load);};
  await load();
  const history=el('details','',root);el('summary','検証・予測方式・受信の履歴',history);
  const historyBody=el('div','',history);
  button('履歴を表示',()=>ctx.run(async()=>{
    const value=await api(`/api/business-archives/${analysisId}/data-quality/history`);
    historyBody.replaceChildren();
    for(const e of value.executions)el('p',`${displayTime(e.created_at)}／方式 ${e.mode}／${e.provisional?'暫定予測':'通常予測'}／${e.actor}／${e.status}／不足 ${e.missing_record_count}件`,historyBody);
    for(const r of value.receipts)el('p',`受信 ${displayTime(r.received_at)}／${r.method}／${r.result}／${r.files.length}ファイル`,historyBody);
    el('p',`検証版 ${value.checks.length}件。過去の検証・予測結果は保持しています。`,historyBody);
  }),history,true);
  return check;
}

export function methodFields(parent, check){
  const box=el('fieldset','',parent);el('legend','予測の進め方',box);
  const selection=[];
  for(const [mode,label] of [['A','不足を補充して通常予測（推奨・初期選択）'],
    ['B','推定補完して予測（今後対応）'],['C','欠損を残して暫定予測（対応モデルのみ）']]){
    const l=el('label','',box), radio=el('input','',l);radio.type='radio';radio.name='forecast-mode';radio.value=mode;
    radio.checked=mode==='A';radio.disabled=mode==='B'||(mode==='C'&&!check.methods.C.enabled);
    l.append(document.createTextNode(' '+mode+'：'+label));
    if(mode!=='A')el('small',check.methods[mode].reason,box);
    selection.push(radio);
  }
  const confirm=field(box,'欠損の内容と影響を確認し、暫定予測として利用します（出荷の自動確定はしません）','checkbox',false);
  const requestId=crypto.randomUUID();
  return ()=>{
    const mode=selection.find(r=>r.checked).value;
    if(mode==='C'&&!confirm.checked)throw new Error('暫定予測への同意を確認してください。');
    return {forecast_mode:mode,check_id:check.id,request_id:requestId,
      confirm_provisional:mode==='C'&&confirm.checked};
  };
}
