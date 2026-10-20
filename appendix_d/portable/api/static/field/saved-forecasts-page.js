import { savedForecasts } from "./saved-forecasts.js";
const host = document.getElementById("saved-forecasts");
const refresh = await savedForecasts(host, async item => {
  await window.PortableOperatorResults.show(item.kind, item.reference, item.warehouse, true);
  document.getElementById("operator-results").scrollIntoView({block: "start"});
});
document.addEventListener("portable-analysis-changed", () => refresh());
document.addEventListener("portable-forecasts-updated", () => refresh());
