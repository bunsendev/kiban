(() => {
  const panel = document.getElementById('performance-panel');
  const output = document.getElementById('performance-result');
  const status = document.getElementById('performance-state');
  let analysis = null;
  async function refresh() {
    if (!analysis) return;
    const current = analysis;
    try {
      const response = await fetch(`/api/performance/${encodeURIComponent(current)}`);
      const value = await response.json();
      if (current !== analysis) return;
      if (!response.ok) throw new Error(value.detail || '計測を取得できませんでした');
      status.textContent = value.stages.length
        ? 'メモリはサーバー全体の250ms間隔の実測です。他の処理の影響を含み、PC全体の空き容量ではありません。'
        : '予測開始後に計測が記録されます。';
      const names = {inventory_and_reference: '在庫取込・予備予測', production_forecast: '正式予測'};
      output.textContent = value.stages.map(item => `${names[item.stage] || item.stage}：${item.status}\n`
        + `経過 ${item.elapsed_seconds ?? '計測中'} 秒／最大メモリ ${item.peak_rss_mb == null ? '未取得' : item.peak_rss_mb.toFixed(1) + ' MB'}\n`
        + `CPU時間 ${item.process_cpu_seconds ?? '計測中'} 秒／論理CPU ${item.logical_cpus}／総メモリ ${item.total_memory_mb == null ? '未取得' : Math.round(item.total_memory_mb) + ' MB'}\n`
        + (item.series_count == null ? '' : `対象 ${item.series_count} 商品・倉庫\n`)
      ).join('\n');
    } catch (error) {status.textContent = error.message;}
  }
  document.getElementById('performance-refresh').onclick = refresh;
  document.addEventListener('portable-analysis-changed', event => {
    analysis = event.detail?.analysisId; panel.hidden = !analysis; refresh();
  });
  setInterval(() => {if (analysis && panel.open) refresh();}, 3000);
})();
