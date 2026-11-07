#!/usr/bin/env node
/*
 * Optional browser-origin proof for the local demo.
 *
 * Requires Node and Playwright (not a Python test dependency):
 *   cd /tmp && npm install playwright
 *   node scripts/browser_smoke.js
 *
 * It launches Chrome with a fake microphone, opens the real local page, presses
 * Start call, waits for a LiveKit connection and agent audio, and fails on page
 * errors. It is evidence for the browser path, not part of `make test`.
 */
const { chromium } = require("playwright");

(async () => {
  const webUrl = process.env.FORGE_WEB_URL || "http://localhost:8000";
  const chromePath = process.env.CHROME_PATH || "/usr/bin/google-chrome";
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const context = await browser.newContext({ permissions: ["microphone"] });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto(webUrl, { waitUntil: "networkidle" });
  await page.click("#start");
  await page.waitForFunction(
    () => document.querySelector("#status").textContent.includes("Connected to"),
    { timeout: 90000 },
  );
  await page.waitForTimeout(12000);
  const status = await page.textContent("#status");
  const transcript = await page.textContent("#transcript");
  console.log(JSON.stringify({ status, transcript, errors }, null, 2));
  await browser.close();
  if (errors.length) process.exitCode = 1;
})();
