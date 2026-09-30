/* Renders deck.html to ../NagarVaani_Pitch_Deck.pdf (16:9, one slide per page).
   Usage:  npm i playwright && npx playwright install chromium
           LIVE_URL=https://your-app.onrender.com node build.mjs
   deck.html already contains the default live URL; $LIVE_URL, if set, replaces it in the PDF. */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = process.env.DECK_DIR || path.dirname(fileURLToPath(import.meta.url));
const live = process.env.LIVE_URL || 'https://nagarvaani-2i2l.onrender.com';
const DEFAULT_URL = 'https://nagarvaani-2i2l.onrender.com';
const html = fs.readFileSync(path.join(dir, 'deck.html'), 'utf8').replaceAll(DEFAULT_URL, live);
const tmp = path.join(dir, '.deck.build.html');
fs.writeFileSync(tmp, html);

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ['--no-sandbox'] } : {});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
await page.goto('file://' + tmp);
await page.waitForTimeout(800);
await page.pdf({ path: path.join(dir, '..', 'NagarVaani_Pitch_Deck.pdf'), width: '1280px', height: '720px', printBackground: true, pageRanges: '' });
await browser.close();
fs.unlinkSync(tmp);
console.log('Wrote docs/NagarVaani_Pitch_Deck.pdf for', live);
