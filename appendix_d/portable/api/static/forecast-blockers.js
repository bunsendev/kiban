function renderForecastBlockers(parent, value) {
  const add=(tag,text,host=parent)=>{const n=document.createElement(tag);n.textContent=text;host.appendChild(n);return n;};
  const blockers=value.blockers||[];
  add('p',`確認が必要な商品・倉庫 ${blockers.length}件。履歴不足は確認欄の入力だけでは解消しません。`);
  const reasons={
    HISTORY_LESS_THAN_28_DAYS:'確認済み出荷履歴が28日未満：過去の出荷CSVを追加してください',
    RECENT_SOURCE_DAYS_MISSING:'直近の出荷データに欠測：必要な日別CSVを確認してください',
    INVENTORY_SHIPMENT_AS_OF_MISMATCH:'在庫基準日と出荷最終日が違います：同じ基準日のデータを揃えてください'
  };
  const table=add('table','');table.style.width='100%';table.style.borderCollapse='collapse';
  const header=add('tr','',table);
  for(const label of ['倉庫・JAN','不足理由・対応','確認済み履歴','出荷期間・在庫基準日'])add('th',label,header);
  for(const item of blockers){
    const row=add('tr','',table);
    add('td',`${item.source_center||'倉庫未確認'} / ${item.jan||'JAN未確認'}`,row);
    add('td',(item.reason_codes||[]).map(code=>reasons[code]||code).join('／')||item.detail||item.status||'原本・確認条件を確認してください',row);
    const days=Number.isInteger(item.recognized_required_days)?item.recognized_required_days:Number.isInteger(item.observed_day_count)&&Number.isInteger(item.confirmed_zero_day_count)?item.observed_day_count+item.confirmed_zero_day_count:null;
    add('td',days===null?'未確認':`${days}日（必要28日以上）／不足 ${Math.max(0,28-days)}日`,row);
    add('td',`判定期間 ${item.required_start||item.train_start||'未確認'} ～ ${item.required_end||item.train_end||'未確認'} / 在庫 ${item.inventory_snapshot_date||'未確認'} / 不足日 ${(item.missing_required_dates||[]).join('、')||'日付未指定'}`,row);
  }
  add('p','過去データは初期導入時にIT担当者が一括投入できます。日別ファイルがない日を勝手に出荷0へ補完しないでください。');
}
