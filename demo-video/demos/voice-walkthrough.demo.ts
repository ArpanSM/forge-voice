import { test } from '@argo-video/cli';
import {
  createHumanCursor,
  resetCamera,
  showOverlay,
} from '@argo-video/cli';
import type { Locator, Page } from '@playwright/test';
import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import { extname, join } from 'node:path';

const APP = 'http://127.0.0.1:8000';
const BOOK = '/calls/call_summit_text_book_03';
const EMERGENCY = '/calls/call_harborlight_text_emergency_01';
const COMPOSITION_PORT = 8127;

/**
 * The dashboard is designed for a 1180 px column. At 1920 px it would leave
 * half the frame empty and the table would read at ~11 px. This presentation
 * layer widens the real page without changing any content: same routes, same
 * cards, same records. Detail cards get four columns so long synthetic IDs
 * (em_harborlight_0001) stay on one line.
 */
const PRESENTATION_CSS = `
  main, #dashboard-live { max-width: 1740px !important; }
  body { font-size: 16px; }
  main .cards { grid-template-columns: repeat(4, minmax(0, 1fr)) !important; }
`;

const ADMIN_CSS = `
  body { max-width: 1560px; font-size: 16px; }
  textarea { min-height: 64vh; font-size: 15px; }
`;

/** One eased programme scroll. */
async function smoothScrollTo(page: Page, y: number, ms = 700): Promise<void> {
  await page.evaluate(
    async ({ y, ms }) => {
      const root = document.documentElement;
      const previous = root.style.scrollBehavior;
      root.style.scrollBehavior = 'auto';
      const start = window.scrollY;
      const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const target = Math.max(0, Math.min(max, y));
      const delta = target - start;
      const t0 = performance.now();
      await new Promise<void>((resolve) => {
        const step = (now: number) => {
          const p = Math.min(1, (now - t0) / ms);
          const eased = 1 - Math.pow(1 - p, 3);
          window.scrollTo(0, start + delta * eased);
          if (p < 1) requestAnimationFrame(step);
          else resolve();
        };
        requestAnimationFrame(step);
      });
      root.style.scrollBehavior = previous;
    },
    { y, ms },
  );
}

async function scrollElementTo(page: Page, target: Locator, top = 168, ms = 700): Promise<void> {
  const y = await target.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
  await smoothScrollTo(page, Math.round(y - top), ms);
}

/** A slow, visible pointer travel; the SVG arrow follows real mouse moves. */
async function glideTo(
  page: Page,
  target: Locator,
  steps = 10,
  stepMs = 70,
): Promise<void> {
  const box = await target.boundingBox();
  if (!box) return;
  const start = await page.evaluate(() => {
    const el = document.getElementById('argo-cursor');
    const left = el ? parseFloat(el.style.left) : NaN;
    const top = el ? parseFloat(el.style.top) : NaN;
    return {
      x: Number.isFinite(left) ? left : innerWidth * 0.86,
      y: Number.isFinite(top) ? top : innerHeight * 0.57,
    };
  });
  const dest = { x: box.x + box.width * 0.5, y: box.y + box.height * 0.5 };
  for (let i = 1; i <= steps; i += 1) {
    await page.mouse.move(
      start.x + ((dest.x - start.x) * i) / steps,
      start.y + ((dest.y - start.y) * i) / steps,
    );
    await page.waitForTimeout(stepMs);
  }
}

/** A CSS outline that travels with the content, not a fixed camera/spotlight. */
async function outline(target: Locator, color: string, radius = 14): Promise<void> {
  await target.evaluate(
    (el, { color, radius }) => {
      const node = el as HTMLElement;
      node.style.outline = `3px solid ${color}`;
      node.style.outlineOffset = '4px';
      node.style.borderRadius = node.style.borderRadius || `${radius}px`;
      node.style.boxShadow = `0 0 0 12px ${color}1a`;
    },
    { color, radius },
  );
}

/** A real mouse click on a link, with the SVG pointer already in place. */
async function clickWithCursor(page: Page, target: Locator): Promise<void> {
  const box = await target.boundingBox();
  if (!box) throw new Error('clickWithCursor: target has no box');
  const x = box.x + box.width * 0.35;
  const y = box.y + box.height * 0.55;
  await page.mouse.move(x, y, { steps: 5 });
  await page.waitForTimeout(120);
  await page.mouse.click(x, y, { delay: 70 });
}

async function prepare(page: Page, path: string, extraCss = ''): Promise<void> {
  await page.goto(APP + path, { waitUntil: 'domcontentloaded' });
  await page.addStyleTag({ content: 'html { scroll-behavior: auto !important; }' });
  await page.addStyleTag({ content: PRESENTATION_CSS + extraCss });
  await page.waitForTimeout(120);
}

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.ttf': 'font/ttf',
  '.png': 'image/png',
  '.wav': 'audio/wav',
};

/**
 * A tiny static server for the end-card compositions. `renderComposition()`
 * boots a server and waits for the page, which cost ~8 s per card while the
 * previous scene was still on screen. Serving the same real HTML from here
 * lets the demo cut, mark and play the card directly.
 */
async function startCompositionServer(): Promise<http.Server> {
  const root = process.cwd();
  const server = http.createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
    const file = join(root, urlPath);
    try {
      if (!file.startsWith(root) || !statSync(file).isFile()) throw new Error('not a file');
      res.writeHead(200, {
        'Content-Type': MIME[extname(file)] || 'application/octet-stream',
        'Cache-Control': 'no-store',
      });
      createReadStream(file).pipe(res);
    } catch {
      res.writeHead(404).end('not found');
    }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(COMPOSITION_PORT, '127.0.0.1', resolve);
  });
  return server;
}

test('voice-walkthrough', async ({ page, narration }) => {
  test.setTimeout(240_000);

  // Argo's durationFor() is time-aware and accounts for audio backlog from
  // earlier scenes, so a hold never cuts a clip.
  const markScene = (scene: string) => narration.mark(scene);
  const holdScene = async (scene: string, leadOutMs = 200) => {
    const wait = narration.durationFor(scene, { leadOutMs });
    if (wait > 0) await page.waitForTimeout(wait);
  };

  await page.setViewportSize({ width: 1920, height: 1080 });

  await prepare(page, '/dashboard');
  await page.getByText('2 active alerts').waitFor();

  const cursor = await createHumanCursor(page, {
    seed: 'forge-voice-walkthrough',
    size: 42,
    start: { x: 0.86, y: 0.57 },
  });
  const compositionServer = await startCompositionServer();

  try {
    await narration.startRecording(page);

    // 1 · hook — dashboard top: two alerts, metrics, then the table edge.
    markScene('hook');
    void showOverlay(page, 'hook', narration.durationFor('hook', { leadOutMs: 0 }));
    const alerts = page.locator('.banner.alert').first();
    await outline(alerts, '#d64545', 12);
    await glideTo(page, page.getByRole('button', { name: 'Evaluate alerts' }), 8, 70);
    await smoothScrollTo(page, 100, 6000);
    await glideTo(page, page.locator('.cards .card').filter({ hasText: 'P95 first audio' }), 8, 65);
    await smoothScrollTo(page, 160, 2600);
    await holdScene('hook');

    // 2 · dashboard metrics + recent calls. Click the real booked row as the cut.
    markScene('dashboard');
    await scrollElementTo(page, page.locator('.cards'), 150, 800);
    const bookingCard = page.locator('#dashboard-live .card').filter({ hasText: 'Booking rate' });
    const p95Card = page.locator('#dashboard-live .card').filter({ hasText: 'P95 first audio' });
    await outline(bookingCard, '#2f7ed8', 12);
    await outline(p95Card, '#2f7ed8', 12);
    await page.waitForTimeout(1200);
    await scrollElementTo(
      page,
      page.locator('section.panel').filter({ hasText: 'Recent calls' }),
      110,
      850,
    );
    const bookedRow = page.locator('tr').filter({ hasText: 'call_summit_text_book_03' });
    await outline(bookedRow, '#2c9a5e', 8);
    await glideTo(page, bookedRow.locator('a'), 10, 65);
    await holdScene('dashboard');
    await clickWithCursor(page, bookedRow.locator('a'));
    await page.getByRole('heading', { name: 'call_summit_text_book_03' }).waitFor();
    await page.addStyleTag({ content: PRESENTATION_CSS });

    // 3 · booked call: booking id, slot check, read-back, tools, first audio.
    markScene('booked');
    const bookingIdCard = page.locator('section.cards .card').filter({ hasText: 'Booking ID' });
    const slotCard = page.locator('section.cards .card').filter({ hasText: 'Slot check' });
    await glideTo(page, bookingIdCard, 8, 65);
    await outline(bookingIdCard, '#2c9a5e', 12);
    await outline(slotCard, '#2c9a5e', 12);
    await page.waitForTimeout(900);
    const readback = page
      .locator('.transcript p.agent')
      .filter({ hasText: 'Just to confirm' })
      .first();
    await scrollElementTo(page, readback, 300, 850);
    await outline(readback, '#2c9a5e', 10);
    await page.waitForTimeout(1500);
    await smoothScrollTo(page, 700, 900);
    const bookedTool = page.locator('ol.timeline li').filter({ hasText: 'book_appointment' });
    await outline(bookedTool, '#2f7ed8', 10);
    const firstAudio = page.locator('p.total');
    await outline(firstAudio, '#2c9a5e', 8);
    await page.waitForTimeout(2100);
    await holdScene('booked');

    // 4 · emergency: ticket + connected transfer, 911-first script, tools.
    await prepare(page, EMERGENCY);
    markScene('emergency');
    void showOverlay(page, 'emergency', narration.durationFor('emergency', { leadOutMs: 0 }));
    const transferCard = page.locator('section.cards .card').filter({ hasText: 'Transfer' });
    const ticketCard = page.locator('section.cards .card').filter({ hasText: 'Ticket ID' });
    await outline(transferCard, '#d64545', 12);
    await outline(ticketCard, '#d64545', 12);
    await glideTo(page, ticketCard, 9, 70);
    await page.waitForTimeout(1500);
    const triage = page.locator('section.panel').filter({ hasText: 'Emergency triage' });
    await scrollElementTo(page, triage, 140, 750);
    await outline(triage, '#d64545', 12);
    await page.waitForTimeout(1800);
    await smoothScrollTo(page, 640, 900);
    const transferTool = page
      .locator('ol.timeline li')
      .filter({ hasText: 'transfer_to_human' });
    await outline(transferTool, '#d64545', 10);
    await smoothScrollTo(page, 760, 600);
    await holdScene('emergency');

    // 5 · weekly review: sample, actions, smoke suite.
    await prepare(page, '/review');
    markScene('review');
    const reviewRow = page.locator('tr').filter({ hasText: 'call_summit_text_book_03' });
    await outline(reviewRow, '#2c9a5e', 8);
    const candidate = reviewRow.getByRole('button', { name: 'Create scenario candidate' });
    await outline(candidate, '#d99a1e', 8);
    await glideTo(page, candidate, 9, 70);
    await page.waitForTimeout(1500);
    const smoke = page.locator('section.panel').filter({ hasText: 'Run the smoke suite' });
    await scrollElementTo(page, smoke, 150, 800);
    await outline(smoke, '#d99a1e', 12);
    await page.waitForTimeout(1900);
    await holdScene('review');

    // 6 · admin: both tenants, YAML, validation.
    await prepare(page, '/admin/harborlight', ADMIN_CSS);
    markScene('admin');
    const tenants = page.locator('.tenant');
    await outline(tenants.nth(0), '#2f7ed8', 999);
    await outline(tenants.nth(1), '#2f7ed8', 999);
    await glideTo(page, tenants.nth(1), 9, 70);
    await page.waitForTimeout(700);
    const yaml = page.locator('#yaml');
    await outline(yaml, '#2f7ed8', 10);
    const validate = page.getByRole('button', { name: 'Validate, save and reload' });
    await outline(validate, '#2c9a5e', 10);
    await glideTo(page, validate, 10, 65);
    await page.waitForTimeout(1700);
    await holdScene('admin');

    await resetCamera(page);
    await cursor.dispose();

    // 7 · limits card — measured numbers, one live-audio miss named.
    // 8 · end card — tagline, repository, caveats. Both cards live in one
    // document so the cut is a swap, not a page load with a blank frame.
    await page.goto(`http://127.0.0.1:${COMPOSITION_PORT}/compositions/closing.html`, {
      waitUntil: 'load',
    });
    markScene('limits');
    await page.evaluate(() => {
      const tl = (window as unknown as { __timelines?: Record<string, any> }).__timelines?.closing;
      if (tl?.play) tl.play();
    });
    await page.waitForTimeout(10_500);
    markScene('end');
    await page.waitForTimeout(5_400);
  } finally {
    await cursor.dispose();
    await resetCamera(page);
    await new Promise<void>((resolve) => compositionServer.close(() => resolve()));
  }
});
