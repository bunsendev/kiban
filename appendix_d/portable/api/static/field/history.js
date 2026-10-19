/* Research controls do not alter operational forecasts or actuals. */
const $ = id => document.getElementById(id);
const labels = {seasonal_naive_7:'現行：前週同曜日', history_weekday_28_v1:'28日・同曜日平均', history_weekday_90_v1:'90日・同曜日平均', history_weekday_365_v1:'365日・同曜日平均', history_weekday_3y_v1:'3年上限・同曜日平均', history_seasonal_recent_3y_v1:'3年季節性＋直近28日'};
const n = v => v == null ? '算出不可' : Number(v).toLocaleString('ja-JP',{maximumFractionDigits:2});
let current = null, page = 0;
function cells(parent, values) {const tr=document.createElement('tr');for(const value of values){const td=document.createElement('td');td.textContent=value;tr.append(td);}parent.append(tr);}
async function api(url, options) {const r=await fetch(url,options),v=await r.json();if(!r.ok)throw Error(v.detail||'処理できませんでした');return v;}
async function refresh(selected) {
  const v=await api('/api/history-studies');$('studies').replaceChildren();$('builds').replaceChildren();
  for(const item of v.studies){const o=document.createElement('option');o.value=item.study_id;o.textContent=`${new Date(item.created_at).toLocaleString("ja-JP")}／${item.series}商品・倉庫／${item.unit_confirmed?'単位確認済み':'単位未確認'}`;$('studies').append(o);}
  for(const item of v.builds){const o=document.createElement('option');o.value=item.build_id;o.textContent=`${item.train_start} ～ ${item.train_end}／${item.build_id}`;$('builds').append(o);}
  if(selected)$('studies').value=selected;
  $('status').textContent=v.studies.length?'比較履歴を選んで表示してください。':'比較履歴はまだありません。';
}
function renderSeries(){
  const matches=(current?.quality||[]).filter(r=>r.unique_id.toLowerCase().includes($('search').value.toLowerCase()));
  page=Math.max(0,Math.min(page,Math.ceil(matches.length/50)-1));$('series').replaceChildren();
  const decisions=new Map((current?.selections||[]).map(r=>[r.unique_id,r]));
  for(const q of matches.slice(page*50,(page+1)*50)){const s=decisions.get(q.unique_id)||{};cells($('series'),[q.unique_id,q.start,q.end,q.observed_days,q.missing_days,labels[s.selection_choice]||s.selection_choice,n(s.holdout_baseline?.mae),n(s.holdout_candidate?.mae),!current.settings.unit_confirmed?'単位未確認・採用保留':s.adoption_status==='REVIEW_REQUIRED'?'候補・承認が必要':'現行維持／日数不足または改善なし']);}
  $('count').textContent=`${matches.length}商品・倉庫／${page+1}ページ。欠損はゼロ補完していません。`;
  $('prev').disabled=page===0;$('next').disabled=(page+1)*50>=matches.length;
}
async function load(){
  current=await api('/api/history-studies/'+encodeURIComponent($('studies').value));$('summary').replaceChildren();
  for(const [method,v] of Object.keys(labels).map(key=>[key,current.summary.SELECTION[key]])){const h=current.summary.HOLDOUT[method];cells($('summary'),[labels[method]||method,v.count,n(v.mae),h.count,n(h.mae),n(h.wape),n(h.mean_error)]);}
  const fixed=current.frozen_product_selection_holdout;
  $('metrics').textContent=`選定期間だけで決めた商品別方式：検証${fixed.count}件、MAE ${n(fixed.mae)}、WAPE ${n(fixed.wape)}%`;
  const p=current.provenance||{};$('basis').textContent=`単位：${current.settings.unit_confirmed?'確認済み':'未確認・数量集計は同一単位の仮定付き・正式採用保留'}／利用可能日時：${p.availability_mode||'入力日時'}／${current.settings.origins.length}起点・各${current.settings.horizon}日、末尾${current.settings.holdout_origins}起点は選定に未使用`;
  $('quality').textContent=`${current.quality.length}商品・倉庫。原本品質：${Object.entries(p.counts||{}).map(([key,value])=>( {conflicted_product_dates:'競合した商品日',excluded_rows:'対象外の行',explicit_zero_rows:'明示ゼロの行',invalid_jan_rows:'JAN不正の行',invalid_jan_or_shape_rows:'JAN・列不正の行',normalized_rows:'整理後の日次行',product_code_multiple_jans:'商品コードのJAN不一致',row_file_date_mismatch_rows:'業務日とファイル日の不一致',shipment_source_rows:'原本出荷行'}[key]||key)+'：'+n(value)).join('／')}`;
  $('excluded').textContent='比較対象外：'+JSON.stringify(current.excluded_targets);
  $('details').textContent=JSON.stringify({条件:current.settings,季節別:current.by_target_month,季節性あり:current.quality.filter(q=>q.seasonality?.applied).length},null,2);
  $('status').textContent='参考比較を表示しました。現場の方式・実績・修正値は変更していません。';page=0;renderSeries();
}
async function work(button, action){button.disabled=true;$('status').textContent='原本と全商品を確認・比較しています。完了までこの画面でお待ちください。';try{const r=await action();await refresh(r.study_id);await load();}catch(e){$('status').textContent=e.message;}finally{button.disabled=false;}}
$('load').onclick=()=>load().catch(e=>{$('status').textContent=e.message;});
$('upload').onclick=()=>work($('upload'),()=>{const file=$('archive').files[0];if(!file)throw Error('出荷履歴ZIPを選んでください');if(!$('assumption').checked)throw Error('利用可能日時の仮定を確認してください');return api('/api/history-studies/upload',{method:'POST',headers:{'Content-Type':'application/zip','x-history-unit':$('unit').value,'x-history-availability-confirmed':'true','x-history-unit-assumption-confirmed':String($('assumption').checked)},body:file});});
$('create').onclick=()=>work($('create'),()=>api('/api/history-studies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({build_id:$('builds').value,confirm_retrospective_availability_assumption:$('build-assumption').checked})}));
$('search').oninput=()=>{page=0;renderSeries();};$('prev').onclick=()=>{page--;renderSeries();};$('next').onclick=()=>{page++;renderSeries();};
refresh().catch(e=>{$('status').textContent=e.message;});renderSeries();
