/* Accuracy read model: immutable forecasts, adjustments, and accepted actuals. */
const $ = id => document.getElementById(id);
let rows = [], page = 0, comparisonSource = "";
const reasons = {
  IDENTITY_OR_UNIT_UNKNOWN: '商品・倉庫・単位の対応不明',
  FORECAST_TIME_UNKNOWN: '予測作成日時の証拠なし',
  RETROSPECTIVE_FORECAST: '対象日以降に作成した参考予測',
  ACTUAL_UNCONFIRMED: '実績未確定', ACTUAL_CONFLICT: '実績取込値が競合',
  PREDICTION_MISSING: '元予測欠損', DUPLICATE_FORECAST_KEYS: '同じ日付の予測が複数あります',
};
const number = (v, missing = '算出不可') => v == null ? missing
  : Number(v).toLocaleString('ja-JP', {maximumFractionDigits: 2});
const states = {CONFIRMED: '確定', UNCONFIRMED: '未確定', CONFLICT: '競合'};
const stamp = value => value ? new Date(value).toLocaleString('ja-JP', {timeZone: 'Asia/Tokyo'}) : '不明';
function cell(tr, value) {
  const td = document.createElement('td'); td.textContent = value; tr.append(td);
}
async function api(url, options) {
  const response = await fetch(url, options), value = await response.json();
  if (!response.ok) throw Error(value.detail || '処理できませんでした');
  return value;
}
function render() {
  const body = $('rows'); body.replaceChildren(); $('exception-row').replaceChildren();
  for (const [index, row] of rows.slice(page * 100, (page + 1) * 100).entries()) {
    const option = document.createElement('option'); option.value = String(page * 100 + index);
    option.textContent = `${row.unique_id}／${row.target_date}／元 ${row.original_quantity}／修正 ${row.adjusted_quantity ?? '未設定'}`;
    $('exception-row').append(option);
  }
  for (const r of rows.slice(page * 100, (page + 1) * 100)) {
    const tr = document.createElement('tr');
    for (const value of [r.unique_id, r.target_date, stamp(r.forecast_created_at),
      number(r.original_quantity, '未設定'), number(r.adjusted_quantity, '未設定'),
      number(r.actual.quantity, '未確定'), states[r.actual.status], number(r.error),
      number(r.error_rate_percent), reasons[r.excluded_reason] || r.excluded_reason || '対象']) cell(tr, value);
    body.append(tr);
  }
  $('prev').disabled = page === 0; $('next').disabled = (page + 1) * 100 >= rows.length;
}
function groups(title, values) {
  const section = document.createElement('section'), heading = document.createElement('h3');
  heading.textContent = title; section.append(heading);
  const table = document.createElement('table'), head = document.createElement('tr');
  for (const text of ['商品・倉庫／日付', '件数', '平均誤差', 'MAE', 'WAPE%']) {
    const th = document.createElement('th'); th.textContent = text; head.append(th);
  }
  table.append(head);
  for (const [key, value] of Object.entries(values || {})) {
    const tr = document.createElement('tr');
    for (const v of [key, value.count, number(value.mean_error), number(value.mae), number(value.wape)]) cell(tr, v);
    table.append(tr);
  }
  section.append(table); $('groups').append(section);
}
async function init() {
  const value = await api('/api/forecast-verification'); $('sources').replaceChildren();
  for (const source of value.sources) {
    const option = document.createElement('option'); option.value = source.source;
    option.textContent = `${stamp(source.created_at)}／${source.model || 'モデル不明'}／${source.source}`;
    $('sources').append(option);
  }
  $('status').textContent = value.sources.length
    ? `${value.sources.length}履歴。締め時刻：${value.policy.cutoff || '未設定'}`
    : '比較用の予測履歴がまだ登録されていません。旧版の保存結果は変更せず、過去の予測を推測で復元しません。';
}
$('load').onclick = async () => {
  try {
    const query = new URLSearchParams({source: $('sources').value, start: $('start').value, end: $('end').value});
    const value = await api('/api/forecast-verification/compare?' + query);
    comparisonSource = $('sources').value;
    rows = value.rows; page = 0; render();
    $('metrics').textContent = `評価対象 ${value.count}件／総数 ${value.total || 0}件、平均誤差 ${number(value.mean_error)}、MAE ${number(value.mae)}、WAPE ${number(value.wape)}%`;
    const meta = value.metadata || {}, unit = {CASE: 'ボール', EACH: 'バラ'}[meta.unit] || meta.unit || '未確認';
    $('basis').textContent = `数量の単位：${unit}／予測に使用した期間：${meta.train_start || '不明'} ～ ${meta.train_end || '不明'}`;
    $('excluded').textContent = '対象外：' + (Object.entries(value.excluded || {})
      .map(([key, count]) => `${reasons[key] || key} ${count}件`).join('／') || 'なし');
    $('groups').replaceChildren(); groups('商品別', value.by_product); groups('日別', value.by_day);
    $('status').textContent = value.count ? '比較しました。少数データだけで実用精度を保証しません。'
      : '評価可能な確定実績と事前予測の組合せがありません。';
  } catch (error) { $('status').textContent = error.message; }
};
$('prev').onclick = () => { page--; render(); };
$('next').onclick = () => { page++; render(); };
const headers = () => ({'Content-Type': 'application/json', 'x-feedback-admin': $('admin').value});
$('policy').onclick = async () => {
  try {
    await api('/api/forecast-verification/policy', {method: 'POST', headers: headers(),
      body: JSON.stringify({cutoff: $('cutoff').value, actor: $('actor').value, reason: $('reason').value})});
    $('admin').value = ''; alert('締め時刻を保存しました。'); await init();
  } catch (error) { $('status').textContent = error.message; }
};
$('exception-save').onclick = async () => {
  try {
    const selected = rows[Number($('exception-row').value)];
    if (!selected) throw Error('比較して対象明細を選択してください');
    const source = $('sources').value, split = source.indexOf(':');
    if (source !== comparisonSource) throw Error('履歴を変更しました。先に比較を更新してください');
    const kind = source.slice(0, split), reference = source.slice(split + 1);
    if (!['run', 'production'].includes(kind)) throw Error('日次参考履歴の直接修正はできません。現場で使用したproduction履歴を選択してください');
    const url = '/api/operator-results/' + kind + '/' + encodeURIComponent(reference), value = await api(url);
    const row = value.rows.find(r => r.unique_id === selected.unique_id
      && String(r.target_date).slice(0, 10) === String(selected.target_date).slice(0, 10));
    if (!row) throw Error('対象を確認できません');
    if ((row.feedback?.quantity ?? null) !== (selected.adjusted_quantity ?? null))
      throw Error('修正数量が更新されています。先に比較を更新してください');
    if (!confirm('過去日や確定後の数量を例外として修正し、理由と変更履歴を保存しますか？')) return;
    const quantity = $('exception-quantity').value;
    await api(url + '/feedback', {method: 'POST', headers: headers(), body: JSON.stringify({
      unique_id: row.unique_id, target_date: row.target_date, revision: row.feedback?.revision || 0,
      quantity: quantity === '' ? null : Number(quantity), actor: $('actor').value, reason: $('reason').value,
      comment: '管理者による例外修正', rating: row.feedback?.rating || 'UNKNOWN', exceptional: true,
    })});
    $('admin').value = ''; alert('例外修正を保存しました。元の予測と実績は変更していません。'); $('load').click();
  } catch (error) { $('status').textContent = error.message; }
};
render();
init().catch(error => { $('status').textContent = error.message; });
