/* Operator result review. All business strings enter the DOM as text. */
(() => {
  const root = document.getElementById('operator-results');
  const completed = document.createElement('details');
  const completedTitle = document.createElement('summary');
  completedTitle.textContent = '分析・確認内容を見直す'; completed.appendChild(completedTitle);
  const analysis = document.getElementById('analysis-result');
  analysis.parentNode.insertBefore(completed, analysis); completed.appendChild(analysis);
  completed.open = true; completed.hidden = true;
  document.addEventListener('portable-analysis-changed', () => {completed.hidden = false;});
  let warehouse = '', pinned = false;
  let source = '', rows = [], history = [], selected = new Set(), page = 0, generation = 0;
  const size = 30;
  const el = (tag, text, parent = root) => {
    const node = document.createElement(tag); if (text) node.textContent = text;
    parent.appendChild(node); return node;
  };
  el('h2', '4. 結果の確認・修正・フィードバック');
  el('p', '商品・倉庫ごとの日別予測です。修正しても元の予測は残ります。数量の単位は取込時に確認した単位です。');
  const context = el('p');
  const status = el('p'); status.setAttribute('role', 'status');
  const searchLabel = el('label', '商品・倉庫IDを検索');
  const search = el('input', '', searchLabel); search.type = 'search';
  const actions = el('div'); actions.className = 'result-actions';
  const button = (text, action, parent = actions) => {
    const node = el('button', text, parent); node.type = 'button'; node.onclick = action; return node;
  };
  button('検索に一致する商品を全選択', () => {filtered().forEach(r => selected.add(r.unique_id)); render();});
  button('選択を解除', () => {selected.clear(); render();});
  const allDownload = button('全件CSVをダウンロード', () => download(null));
  const chosenDownload = button('選択商品をCSVでダウンロード', () => download([...selected]));
  const count = el('p');
  const wrap = el('div'); wrap.className = 'table-wrap';
  const table = el('table', '', wrap);
  const head = el('tr', '', el('thead', '', table));
  ['選択', '商品・倉庫ID', '予測日', '元の予測', '確認後数量', '評価', '操作'].forEach(t => el('th', t, head));
  const body = el('tbody', '', table);
  const nav = el('div');
  const prev = button('前へ', () => {page--; render();}, nav);
  const next = button('次へ', () => {page++; render();}, nav);
  const form = el('form'); form.hidden = true;
  const target = el('h3', '', form);
  const field = (title, type, max) => {
    const label = el('label', title, form), input = el(type, '', label);
    if (max) input.maxLength = max; return input;
  };
  const actor = field('担当者', 'input', 100); actor.required = true;
  const quantity = field('修正後の数量（空欄なら元の予測を使用）', 'input');
  quantity.type = 'number'; quantity.min = '0'; quantity.step = 'any';
  const rating = field('予測への評価', 'select');
  const labels = {OK: '妥当', HIGH: '多い', LOW: '少ない', UNKNOWN: 'まだ判断できない'};
  Object.entries(labels).forEach(([v, t]) => {const o = el('option', t, rating); o.value = v;});
  const reason = field('修正理由（数量を修正する場合は必須）', 'input', 500);
  const comment = field('気づいたこと・改善してほしいこと', 'textarea', 1000);
  const save = el('button', '修正・フィードバックを保存', form); save.type = 'submit';
  button('閉じる', () => {form.hidden = true;}, form);
  const log = el('details'), summary = el('summary', 'この結果の修正・フィードバック履歴', log);
  const journal = el('ol', '', log);
  let editing = null;
  function filtered() {return rows.filter(r => r.unique_id.toLowerCase().includes(search.value.toLowerCase()));}
  function render() {
    const matches = filtered(); page = Math.min(page, Math.max(0, Math.ceil(matches.length / size) - 1));
    count.textContent = `${rows.length}日別結果／検索一致 ${matches.length}件／選択 ${selected.size}商品・倉庫／${page + 1}ページ`;
    body.replaceChildren();
    matches.slice(page * size, (page + 1) * size).forEach(row => {
      const tr = el('tr', '', body), td = el('td', '', tr), check = el('input', '', td);
      check.type = 'checkbox'; check.checked = selected.has(row.unique_id);
      check.setAttribute('aria-label', `${row.unique_id}を選択`);
      check.onchange = () => {check.checked ? selected.add(row.unique_id) : selected.delete(row.unique_id); render();};
      [row.unique_id, row.target_date, row.yhat, row.feedback?.quantity ?? '未設定',
        labels[row.feedback?.rating] || '未確認'].forEach(v => el('td', String(v), tr));
      button('修正・感想', () => edit(row), el('td', '', tr));
    });
    prev.disabled = page === 0; next.disabled = (page + 1) * size >= matches.length;
    chosenDownload.disabled = selected.size === 0; allDownload.disabled = !rows.length;
    summary.textContent = `この結果の修正・フィードバック履歴（${history.length}件）`;
    journal.replaceChildren();
    history.slice().reverse().forEach(h => el('li', `${h.created_at} ${h.unique_id} ${h.target_date}：`
      + `${h.original_quantity} → ${h.quantity ?? h.original_quantity}／${labels[h.rating]}／${h.actor}／${h.reason} ${h.comment}`, journal));
  }
  function edit(row) {
    editing = row; form.hidden = false; target.textContent = `${row.unique_id}／${row.target_date} の確認`;
    quantity.value = row.feedback?.quantity ?? ''; quantity.disabled = row.edit_state?.editable === false; target.textContent += '／' + (row.edit_state?.reason || ''); rating.value = row.feedback?.rating || 'UNKNOWN';
    reason.value = row.feedback?.reason || ''; comment.value = row.feedback?.comment || '';
    if (row.feedback?.actor) actor.value = row.feedback.actor;
    quantity.oninput = () => {reason.required = quantity.value !== '';}; quantity.oninput();
    form.scrollIntoView({block: 'center'}); quantity.focus();
  }
  async function request(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {const error = await response.json(); throw new Error(error.detail || '処理できませんでした');}
    return response;
  }
  function endpoint(suffix = '') {
    return source + suffix + (warehouse ? '?warehouse=' + encodeURIComponent(warehouse) : '');
  }
  async function reload(expectedSource = source, expectedWarehouse = warehouse) {
    const value = await (await request(endpoint())).json();
    if (source !== expectedSource || warehouse !== expectedWarehouse) return;
    rows = value.rows; history = value.history;
    const dates = rows.map(r => String(r.target_date).slice(0,10)).sort();
    context.textContent = `保存済みの予測${warehouse ? '／' + warehouse : ''}／予測期間 ${dates[0] || 'なし'} ～ ${dates.at(-1) || 'なし'}。現在取り込んでいるデータとは別の結果です。`;
    render();
  }
  async function download(selection) {
    try {
      const response = await request(endpoint('/download'), {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({selected: selection})});
      const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
      link.href = url; link.download = '予測結果.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      status.textContent = 'CSVを保存しました。元の予測と担当者修正値を両方含みます。';
    } catch (error) {status.textContent = error.message;}
  }
  form.onsubmit = async event => {
    event.preventDefault(); if (!editing) return;
    const currentSource = source, currentWarehouse = warehouse; save.disabled = true;
    try {
      const {saveWithNotice}=await import('/field/assets/api.js');
      await saveWithNotice(()=>request(endpoint('/feedback'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        unique_id: editing.unique_id, target_date: editing.target_date, revision: editing.feedback?.revision || 0,
        quantity: quantity.disabled ? (editing.feedback?.quantity ?? null) : (quantity.value === '' ? null : Number(quantity.value)), actor: actor.value,
        rating: rating.value, reason: reason.value, comment: comment.value,
      })}),'結果の修正とフィードバックを保存しました。元の予測は変更していません。');
      if (source !== currentSource || warehouse !== currentWarehouse) return;
      form.hidden = true; await reload(currentSource, currentWarehouse); status.textContent = '保存しました。修正はこの結果への担当者判断として記録されます。';
    } catch (error) {status.textContent = error.message;}
    finally {save.disabled = false;}
  };
  search.oninput = () => {page = 0; render();};
  window.PortableOperatorResults = {
    clear() {pinned = false; generation++; source = ''; rows = []; history = []; selected.clear(); form.hidden = true; root.hidden = true; completed.open = true;},
    async show(kind, reference, selectedWarehouse = '', explicit = false) {
      if (pinned && !explicit) return;
      if (explicit) pinned = true;
      const url = `/api/operator-results/${kind}/${encodeURIComponent(reference)}`;
      if (source === url && warehouse === selectedWarehouse) {root.hidden = false; return;}
      const token = ++generation; source = url; warehouse = selectedWarehouse; rows = []; history = []; selected.clear(); page = 0;
      form.hidden = true; root.hidden = false; status.textContent = '結果を読み込み中です'; render();
      try {await reload(url); if (token === generation) {completed.open = false; status.textContent = '結果を確認し、必要に応じて修正や感想を保存してください。';}}
      catch (error) {if (token === generation) {source = ''; status.textContent = error.message;}}
    },
  };
})();
