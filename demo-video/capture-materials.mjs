import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const OUT = 'huashu-film/materials';
mkdirSync(OUT, { recursive: true });

const PRESENTATION_CSS = `
  main, #dashboard-live { max-width: 1740px !important; }
  body { font-size: 16px; }
  main .cards { grid-template-columns: repeat(4, minmax(0, 1fr)) !important; }
`;
const ADMIN_CSS = `body { max-width: 1560px; font-size: 16px; } textarea { min-height: 64vh; font-size: 15px; }`;

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
  colorScheme: 'light',
});

const shoot = async (name) => {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(name);
};
const shootEl = async (name, locator) => {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
  await locator.screenshot({ path: `${OUT}/${name}.png` });
  console.log(name);
};
const prep = async (url, extra = '') => {
  await page.goto(`http://127.0.0.1:8000${url}`, { waitUntil: 'networkidle' });
  await page.addStyleTag({ content: 'html { scroll-behavior: auto !important; }' });
  await page.addStyleTag({ content: PRESENTATION_CSS + extra });
  await page.waitForTimeout(250);
};
const scrollTo = async (y) => {
  await page.evaluate((y) => window.scrollTo(0, y), y);
  await page.waitForTimeout(250);
};

// Dashboard.
await prep('/dashboard');
await shoot('01-dashboard');
await shootEl('dashboard-alert', page.locator('.banner.alert').first());
await shootEl('dashboard-metrics', page.locator('.cards').first());
await scrollTo(610);
await shoot('02-dashboard-table');

// Booked call.
await prep('/calls/call_summit_text_book_03');
await shoot('03-booked');
await shootEl('booked-cards', page.locator('section.cards').first());
const bookingId = page.locator('section.cards .card').filter({ hasText: 'Booking ID' });
await shootEl('booking-id', bookingId);
const readback = page.locator('.transcript p.agent').filter({ hasText: 'Just to confirm' }).first();
await scrollTo(300);
await shootEl('booked-readback', readback);
await scrollTo(620);
await shoot('04-booked-tools');
await shootEl('booked-timeline', page.locator('section.panel').filter({ hasText: 'Tool timeline' }));
await shootEl('booked-latency', page.locator('section.panel').filter({ hasText: 'Latency waterfall' }));

// Emergency.
await prep('/calls/call_harborlight_text_emergency_01');
await shoot('05-emergency');
await shootEl('emergency-triage', page.locator('section.panel').filter({ hasText: 'Emergency triage' }));
const ticket = page.locator('section.cards .card').filter({ hasText: 'Ticket ID' });
const transfer = page.locator('section.cards .card').filter({ hasText: 'Transfer' });
await shootEl('emergency-ticket', ticket);
await shootEl('emergency-transfer', transfer);
await scrollTo(600);
await shoot('06-emergency-tools');
await shootEl('emergency-timeline', page.locator('section.panel').filter({ hasText: 'Tool timeline' }));

// Weekly review.
await prep('/review');
await shoot('07-review');
await scrollTo(400);
await shoot('08-review-smoke');
const row = page.locator('tr').filter({ hasText: 'call_summit_text_book_03' });
await shootEl('review-row', row);

// Admin.
await prep('/admin/harborlight', ADMIN_CSS);
await shoot('09-admin');
await page.screenshot({
  path: `${OUT}/10-admin-yaml.png`,
  clip: { x: 168, y: 176, width: 1584, height: 712 },
});
console.log('10-admin-yaml');
await page.locator('.tenant').nth(1).click();
await page.waitForTimeout(500);
await page.addStyleTag({ content: ADMIN_CSS });
await shoot('11-admin-summit');

await browser.close();
