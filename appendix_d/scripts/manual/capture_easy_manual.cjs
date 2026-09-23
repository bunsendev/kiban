const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [baseUrl, outputDirectory, samplePath] = process.argv.slice(2);
if (!baseUrl || !outputDirectory || !samplePath) {
  throw new Error("usage: node capture_easy_manual.cjs <base-url> <output-dir> <sample-csv>");
}

const edgePath = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const highlightStyle = "4px solid #ffad14";

async function capture(page, name, selector) {
  const target = selector ? page.locator(selector) : null;
  if (target) {
    await target.evaluate((element, outline) => {
      element.dataset.manualOutline = element.style.outline;
      element.dataset.manualOffset = element.style.outlineOffset;
      element.style.outline = outline;
      element.style.outlineOffset = "5px";
      element.scrollIntoView({ block: "center", inline: "center" });
    }, highlightStyle);
  }
  await page.screenshot({ path: path.join(outputDirectory, `${name}.png`) });
  if (target) {
    await target.evaluate((element) => {
      element.style.outline = element.dataset.manualOutline || "";
      element.style.outlineOffset = element.dataset.manualOffset || "";
      delete element.dataset.manualOutline;
      delete element.dataset.manualOffset;
    });
  }
}

(async () => {
  fs.mkdirSync(outputDirectory, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: edgePath });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 1,
    locale: "ja-JP",
    colorScheme: "light",
  });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/ui/easy`, { waitUntil: "networkidle" });
  await capture(page, "01_start", "#connection-panel");

  await page.locator("#api-token").fill("preview-token");
  await capture(page, "02_connect", "#connection-form");
  await page.locator("#connection-form button[type=submit]").click();
  await page.locator("#source-panel").waitFor({ state: "visible" });

  await capture(page, "03_choose_file", ".easy-file-picker");
  await page.locator("#source-file").setInputFiles(samplePath);
  await page.locator("#selected-summary").waitFor({ state: "visible" });
  await capture(page, "04_selected", "#selected-summary");
  await capture(page, "05_analyze", "#analyze-button");

  await page.locator("#analyze-button").click();
  await page.locator("#result-panel").waitFor({ state: "visible", timeout: 20_000 });
  await capture(page, "06_waiting", "#result-state");
  await page.locator("#result-state.success").waitFor({ state: "visible", timeout: 20_000 });
  const finalText = await page.locator("#result-title").innerText();
  if (!finalText.includes("データを利用できます")) {
    throw new Error(`manual flow did not complete successfully: ${finalText}`);
  }
  await capture(page, "07_result", "#result-state");
  await capture(page, "08_metrics", "#result-metrics");
  await capture(page, "09_reading", "#result-detail");
  await browser.close();
  process.stdout.write(`${finalText}\n`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
