import { test } from '@argo-video/cli';
import { resetCamera } from '@argo-video/cli';
import type { Locator, Page } from '@playwright/test';
import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import { extname, join } from 'node:path';

/**
 * Client proof film — "the one write".
 *
 * A fresh treatment: the real local app is framed as evidence in a dark
 * case-file window, and the argument (the engagement, the proof number and
 * the call to action) is drawn as ledger cards. No cursor, no camera moves,
 * hard cuts. The product stays the hero; the frame only names what to look at.
 */

const APP = 'http://127.0.0.1:8000';
const CALL = '/calls/call_summit_text_book_03';

/** Widen the 1180 px dashboard column without changing any content. */
const PRESENTATION_CSS = `
  main, #dashboard-live { max-width: 1740px !important; }
  body { font-size: 16px; }
  main .cards { grid-template-columns: repeat(4, minmax(0, 1fr)) !important; }
`;

/** The dark evidence frame and the evidence tag. */
const FRAME_CSS = `
  .argo-frame { position: fixed; inset: 0; pointer-events: none; z-index: 99999; }
  .argo-frame-border { position: absolute; inset: 20px; border: 1px solid rgba(12,20,36,0.30); }
  .argo-frame-tag {
    position: absolute; top: 20px; left: 48px; transform: translateY(-50%);
    background: #0a1120; color: #e8eef7;
    font-family: "Noto Sans Mono", monospace; font-size: 13px;
    letter-spacing: 0.16em; text-transform: uppercase;
    padding: 7px 12px; white-space: nowrap;
  }
  .argo-frame-meta {
    position: absolute; bottom: 20px; right: 48px; transform: translateY(50%);
    background: #0a1120; color: #8fa0b8;
    font-family: "Noto Sans Mono", monospace; font-size: 12px;
    letter-spacing: 0.14em; text-transform: uppercase;
    padding: 7px 12px; white-space: nowrap;
  }
  .argo-frame-headline {
    position: absolute; bottom: 44px; left: 48px;
    background: #0a1120; color: #e8eef7;
    font-family: "Noto Serif", Georgia, serif; font-size: 84px; line-height: 1.12;
    letter-spacing: -0.02em; padding: 20px 28px; max-width: 1700px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.4);
  }
  .argo-frame-headline .em { font-style: italic; color: #3d8bff; }
  .argo-frame-low {
    position: fixed; bottom: 44px; left: 48px; right: 48px;
    background: #0a1120; color: #e8eef7;
    font-family: "Noto Sans", system-ui, sans-serif; font-size: 48px; line-height: 1.3;
    letter-spacing: -0.01em; padding: 18px 24px; max-width: 1560px;
    border-left: 3px solid #3d8bff; box-shadow: 0 10px 40px rgba(0,0,0,0.4);
  }
  .argo-frame-low .em { color: #3d8bff; font-weight: 700; }
  .argo-evtag {
    position: absolute; z-index: 100000; pointer-events: none;
    font-family: "Noto Sans Mono", monospace; font-size: 14px;
    letter-spacing: 0.14em; text-transform: uppercase; white-space: nowrap;
    color: #e8eef7; background: #0a1120;
    border-left: 3px solid #3d8bff;
    padding: 8px 12px;
    box-shadow: 0 6px 24px rgba(0,0,0,0.35);
  }
`;

async function prepare(
  page: Page,
  path: string,
  label: string,
  headline?: string,
): Promise<void> {
  await page.goto(APP + path, { waitUntil: 'domcontentloaded' });
  await page.addStyleTag({ content: 'html { scroll-behavior: auto !important; }' });
  await page.addStyleTag({ content: PRESENTATION_CSS });
  await page.addStyleTag({ content: FRAME_CSS });
  await page.waitForTimeout(160);
  await page.evaluate(
    ({ text, line }) => {
      const el = document.createElement('div');
      el.className = 'argo-frame';
      el.innerHTML =
        `<div class="argo-frame-border"></div>` +
        `<div class="argo-frame-tag">${text}</div>` +
        (line ? `<div class="argo-frame-headline">${line}</div>` : '') +
        `<div class="argo-frame-meta">github.com/ArpanSM/forge-voice · local synthetic demo</div>`;
      document.body.appendChild(el);
    },
    { text: label, line: headline },
  );
}

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

/** Highlight one element and pin an evidence tag to its right. */
async function tag(page: Page, target: Locator, text: string, color = '#3d8bff'): Promise<void> {
  const box = await target.boundingBox();
  if (!box) return;
  await target.evaluate((el, value) => {
    el.style.outline = `2px solid ${value}`;
    el.style.outlineOffset = '3px';
    el.style.borderRadius = '8px';
    el.style.background = `${value}14`;
  }, color);
  await page.evaluate(({ box, text: label, color: value }) => {
    document.querySelectorAll('.argo-evtag').forEach((el) => el.remove());
    const el = document.createElement('div');
    el.className = 'argo-evtag';
    el.textContent = label;
    el.style.borderLeftColor = value;
    const left = Math.min(box.x + box.width + 18, window.innerWidth - 320);
    const minTop = window.scrollY + 72;
    const maxTop = window.scrollY + window.innerHeight - 64;
    const top = Math.max(minTop, Math.min(box.y + window.scrollY + box.height / 2 - 19, maxTop));
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    document.body.appendChild(el);
  }, { box, text, color });
}

async function retag(page: Page, label: string): Promise<void> {
  await page.evaluate((text) => {
    const tag = document.querySelector('.argo-frame-tag');
    if (tag) tag.textContent = text;
  }, label);
}

/** A large lower-third that carries the evidence at phone size. */
async function lowerThird(page: Page, html: string): Promise<void> {
  await page.evaluate((text) => {
    document.querySelectorAll('.argo-frame-low').forEach((el) => el.remove());
    const el = document.createElement('div');
    el.className = 'argo-frame-low';
    el.innerHTML = text;
    document.body.appendChild(el);
  }, html);
}

async function clearTags(page: Page): Promise<void> {
  await page.evaluate(() => {
    document.querySelectorAll('.argo-evtag').forEach((el) => el.remove());
    document.querySelectorAll('[style*="outline"]').forEach((el) => {
      const node = el as HTMLElement;
      if (node.classList.contains('argo-evtag')) return;
      node.style.outline = '';
      node.style.outlineOffset = '';
      node.style.background = '';
      node.style.borderRadius = '';
    });
  });
}

const COMPOSITION_PORT = 8127;
const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.ttf': 'font/ttf',
  '.png': 'image/png',
  '.wav': 'audio/wav',
};

/** Serve the project root so the drawn cards load without a per-scene server boot. */
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

test('client-proof', async ({ page, narration }) => {
  test.setTimeout(300_000);

  const markScene = (scene: string) => narration.mark(scene);
  const holdScene = async (scene: string, leadOutMs = 200) => {
    const wait = narration.durationFor(scene, { leadOutMs });
    if (wait > 0) await page.waitForTimeout(wait);
  };

  await page.setViewportSize({ width: 1920, height: 1080 });

  // 1 · the failure — the dashboard's slot-correctness alert.
  await prepare(
    page,
    '/dashboard',
    'EVIDENCE 01 — DASHBOARD',
    'A booking that doesn’t match the request<br>is a <span class="em">support ticket.</span>',
  );
  // Start recording after the first page is rendered, so frame 0 is the dashboard.
  await narration.startRecording(page);
  markScene('hook');
  await page.getByText('active alert').waitFor();
  const alert = page.locator('.banner.alert').first();
  await tag(page, alert, 'SLOT CORRECTNESS FAILURE', '#e05a5a');
  await holdScene('hook');
  await page.waitForTimeout(700);

  // 2 · the proof-of-concept label — the caller page, no call started.
  await prepare(page, '/', 'EVIDENCE 02 — CALLER PAGE');
  markScene('poc');
  await page.locator('#tenant').waitFor();
  await page.waitForTimeout(300);
  await tag(page, page.locator('#tenant'), 'SYNTHETIC TWO-TENANT CORPUS', '#3d8bff');
  await page.waitForTimeout(1400);
  await clearTags(page);
  const disclosure = page.locator('.card').filter({ hasText: 'Disclosure' }).first();
  await tag(page, disclosure, 'AI DISCLOSURE · RECORDED', '#3d8bff');
  await holdScene('poc');

  // 3 · the read-back — the real call record, transcript excerpt.
  await prepare(page, CALL, 'EVIDENCE 03 — CALL RECORD');
  markScene('call');
  const readback = page
    .locator('.transcript p.agent')
    .filter({ hasText: 'Just to confirm' })
    .first();
  await scrollElementTo(page, readback, 320, 800);
  await tag(page, readback, 'READ-BACK', '#3d8bff');
  await lowerThird(
    page,
    'Read-back: Air conditioning repair · Wed 11 Nov 12:00 PM · Dana · 88 Meridian Way',
  );
  await holdScene('call');

  // 4 · the one write — booking id, the book_appointment tool, and the retry.
  await retag(page, 'EVIDENCE 04 — THE WRITE');
  markScene('write');
  const bookingCard = page.locator('section.cards .card').filter({ hasText: 'Booking ID' });
  await scrollElementTo(page, bookingCard, 220, 800);
  await tag(page, bookingCard, 'ONE WRITE · bk_summit_0003', '#34c98e');
  await lowerThird(
    page,
    'lookup_customer → get_service_area → get_availability → book_appointment',
  );
  await page.waitForTimeout(900);
  await clearTags(page);
  const tool = page.locator('ol.timeline li').filter({ hasText: 'book_appointment' });
  await scrollElementTo(page, tool, 420, 700);
  await tag(page, tool, 'RETRY → bk_summit_0003 · SAME BOOKING', '#34c98e');
  await holdScene('write');

  // 5–7 · the turn, the proof number and the call to action.
  const compositionServer = await startCompositionServer();
  try {
    await page.goto(`http://127.0.0.1:${COMPOSITION_PORT}/compositions/client-proof.html`, {
      waitUntil: 'load',
    });
    markScene('whyme');
    await page.evaluate(() => {
      const tl = (window as unknown as { __timelines?: Record<string, any> }).__timelines?.[
        'client-proof'
      ];
      if (tl?.play) tl.play();
    });
    await holdScene('whyme');
    markScene('metric');
    await holdScene('metric');
    markScene('endcard');
    await holdScene('endcard');
    await page.waitForTimeout(900);
  } finally {
    await new Promise<void>((resolve) => compositionServer.close(() => resolve()));
  }

  await resetCamera(page);
});
