#!/usr/bin/env node
/*
 * Record a captioned local proof player with Playwright's bundled ffmpeg.
 *
 * The player is an HTML storyboard built from real screenshots and documented
 * call records. It is not a live call recording; the page says so on screen.
 *
 *   NODE_PATH=/path/to/node_modules node scripts/record_proof.js \
 *     docs/proof/demo-player.html docs/proof/forge-voice-demo-90s.webm
 */
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const source = path.resolve(process.argv[2] || "docs/proof/demo-player.html");
  const target = path.resolve(process.argv[3] || "docs/proof/forge-voice-demo-90s.webm");
  const chromePath = process.env.CHROME_PATH || "/usr/bin/google-chrome";
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: path.dirname(target), size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();
  await page.goto(`file://${source}`, { waitUntil: "load" });
  const totalMs = await page.evaluate(() => window.__totalMs || 80000);
  console.log(`recording ${source} for ${Math.round(totalMs / 1000)}s`);
  await page.waitForTimeout(totalMs + 1200);
  const video = page.video();
  await page.close();
  await video.saveAs(target);
  await context.close();
  await browser.close();
  console.log(`saved ${target}`);
})();
