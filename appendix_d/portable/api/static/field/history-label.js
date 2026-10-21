/* Shared by the standard screen and the four-step field screen. */
globalThis.PortableAnalysisHistory = {
  label(item) {
    const time = item.created_at && new Date(item.created_at);
    const date = time && !Number.isNaN(time.getTime())
      ? new Intl.DateTimeFormat("ja-JP", {
          timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
          hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
        }).format(time) + " 日本時間"
      : "記録なし（旧版）";
    const kind = item.created_at_source === "daily_run" ? "処理記録日時（旧版）" : "分析保存日時";
    const warehouses = item.warehouses?.join("・") || "倉庫記録なし";
    return `${kind} ${date}／${warehouses}／ID ${String(item.analysis_id || "").slice(0, 12)}`;
  },
};
