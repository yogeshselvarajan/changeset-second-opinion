// Renders every raster icon from the mark in public/favicon.svg, and a placeholder og.png.
// Run with `npm run icons`; the outputs are committed so nobody needs sharp just to build.
import { Buffer } from "node:buffer";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import pngToIco from "png-to-ico";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");

const CANVAS = "#F6F5F2";
const INK = "#1B1A17";
const ACCENT = "#4E5BD8";

// The three bars of favicon.svg without the style block (a rasteriser has no dark scheme), cropped
// to their bounding box (x 4 to 28, y 6 to 27) so that "mark width" means the width of the bars.
const MARK = (ink, accent) => `
  <rect fill="${accent}" x="4" y="6" width="12" height="5" rx="2.5"/>
  <rect fill="${ink}" x="4" y="14" width="24" height="5" rx="2.5"/>
  <rect fill="${ink}" x="4" y="22" width="18" height="5" rx="2.5"/>`;
const MARK_BOX = { x: 4, y: 6, width: 24, height: 21 };

/** An svg of `size` square with the mark centred at `markShare` of the width on `background`. */
function iconSvg(size, markShare, background) {
  const markWidth = size * markShare;
  const scale = markWidth / MARK_BOX.width;
  const markHeight = MARK_BOX.height * scale;
  const dx = (size - markWidth) / 2 - MARK_BOX.x * scale;
  const dy = (size - markHeight) / 2 - MARK_BOX.y * scale;
  const fill = background ? `<rect width="${size}" height="${size}" fill="${background}"/>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  ${fill}
  <g transform="translate(${dx} ${dy}) scale(${scale})">${MARK(INK, ACCENT)}</g>
</svg>`;
}

async function png(svg, size) {
  return sharp(Buffer.from(svg), { density: 384 }).resize(size, size).png().toBuffer();
}

async function write(name, buffer) {
  await writeFile(join(pub, name), buffer);
  console.log(`wrote public/${name} (${buffer.length} bytes)`);
}

async function ogCard() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="${CANVAS}"/>
  <g transform="translate(72 72) scale(3)">${MARK(INK, ACCENT)}</g>
  <text x="192" y="118" font-family="Inter, Arial, sans-serif" font-size="32" font-weight="600"
        letter-spacing="-0.4" fill="${INK}">Changeset Second Opinion</text>
  <text x="72" y="280" font-family="Inter, Arial, sans-serif" font-size="50" font-weight="600"
        letter-spacing="-0.8" fill="${INK}">A second opinion on</text>
  <text x="72" y="342" font-family="Inter, Arial, sans-serif" font-size="50" font-weight="600"
        letter-spacing="-0.8" fill="${INK}">flagged OpenStreetMap</text>
  <text x="72" y="404" font-family="Inter, Arial, sans-serif" font-size="50" font-weight="600"
        letter-spacing="-0.8" fill="${INK}">edits.</text>
  <text x="72" y="470" font-family="Inter, Arial, sans-serif" font-size="28" fill="#4a4944">Evidence first; a human posts.</text>
</svg>`;
  const card = sharp(Buffer.from(svg), { density: 96 }).resize(1200, 630);
  // The right half of the case screen (the fact panel and the suggested lane), bottom right.
  const shot = join(pub, "screenshots", "case-light.webp");
  if (!existsSync(shot)) return card.png({ compressionLevel: 9 }).toBuffer();
  const crop = await sharp(shot)
    .extract({ left: 1045, top: 365, width: 545, height: 555 })
    .resize({ width: 470 })
    .png()
    .toBuffer();
  const framed = await sharp(crop)
    .extend({ top: 1, bottom: 1, left: 1, right: 1, background: "#E2DFD8" })
    .png()
    .toBuffer();
  return card
    .composite([{ input: framed, left: 680, top: 100 }])
    .png({ compressionLevel: 9 })
    .toBuffer();
}

await mkdir(pub, { recursive: true });
await readFile(join(pub, "favicon.svg")); // fail early if the source mark is missing

const flat = (size, share) => png(iconSvg(size, share, CANVAS), size);
await write("apple-touch-icon.png", await flat(180, 0.6));
await write("icon-192.png", await flat(192, 0.6));
await write("icon-512.png", await flat(512, 0.6));
await write("icon-maskable-512.png", await flat(512, 0.4));

const ico = await pngToIco(
  await Promise.all([16, 32, 48].map((s) => png(iconSvg(s, 0.75, null), s))),
);
await write("favicon.ico", ico);

// The social card: wordmark, the sentence, and the case screen when `npm run screenshots` has run.
await write("og.png", await ogCard());
