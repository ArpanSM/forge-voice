#!/usr/bin/env node
/*
 * Capture the public proof screenshots from the running local web app.
 *
 * This is evidence from the real #7 dashboard/admin pages and the seeded #4 call
 * records. It never records a live call and never claims the pages are hosted.
 *
 *   PYTHONPATH=src python3.12 -m forge_voice.web.app &
 *   NODE_PATH=/path/to/node_modules node scripts/capture_proof.js
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

(async () => {
  const webUrl = process.env.FORGE_WEB_URL || "http://127.0.0.1:8000";
  const outDir = path.resolve(process.env.PROOF_OUT || "docs/proof/screenshots");
  const chromePath = process.env.CHROME_PATH || "/usr/bin/google-chrome";
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const shots = [
    ["/dashboard", "dashboard.png", true],
    ["/dashboard?tenant=summit", "dashboard-summit.png", true],
    ["/calls/call_summit_text_book_03", "call-booked.png", true],
    ["/calls/call_harborlight_text_emergency_01", "call-emergency.png", true],
    ["/calls/call_harborlight_text_emergency_01_noanswer", "call-emergency-callback.png", true],
    ["/review", "review.png", true],
    ["/admin", "admin.png", true],
    ["/admin/summit", "admin-summit.png", true],
    ["/", "browser-demo.png", false],
  ];
  for (const [route, name, fullPage] of shots) {
    await page.goto(`${webUrl}${route}`, { waitUntil: "networkidle" });
    await page.screenshot({ path: path.join(outDir, name), fullPage });
    console.log(`captured ${route} -> ${name}`);
  }

  // Viewport crops for the captioned walkthroughs. Full-page shots keep the review
  // evidence; these keep transcript/timeline text legible in a 1280x720 video.
  const videoPage = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const crops = [
    ["/dashboard", "video-dashboard.png", null],
    ["/calls/call_summit_text_book_03", "video-book-top.png", 0],
    ["/calls/call_summit_text_book_03", "video-book-readback.png", 420],
    ["/calls/call_harborlight_text_emergency_01", "video-emergency-top.png", 0],
    ["/calls/call_harborlight_text_emergency_01", "video-emergency-transcript.png", 560],
    ["/review", "video-review.png", null],
    ["/admin", "video-admin.png", 0],
    ["/admin", "video-admin-yaml.png", 550],
  ];
  for (const [route, name, scrollY] of crops) {
    await videoPage.goto(`${webUrl}${route}`, { waitUntil: "networkidle" });
    if (scrollY !== null) await videoPage.evaluate((y) => window.scrollTo(0, y), scrollY);
    await videoPage.screenshot({ path: path.join(outDir, name) });
    console.log(`captured ${route} -> ${name}`);
  }
  await browser.close();
})();
