import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const pub = join(__dirname, "..", "..", "public");
const read = (name: string) => readFileSync(join(pub, name));

/** Width and height from the IHDR chunk of a PNG (bytes 16 to 23, big endian). */
function pngSize(name: string): [number, number] {
  const bytes = read(name);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(bytes.subarray(12, 16).toString("ascii")).toBe("IHDR");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

describe("generated icons", () => {
  const cases: [string, [number, number]][] = [
    ["apple-touch-icon.png", [180, 180]],
    ["icon-192.png", [192, 192]],
    ["icon-512.png", [512, 512]],
    ["icon-maskable-512.png", [512, 512]],
    ["og.png", [1200, 630]],
  ];
  it.each(cases)("%s is %s pixels", (name, size) => {
    expect(pngSize(name)).toEqual(size);
  });

  it("the favicon holds 16, 32 and 48 pixel images", () => {
    const ico = read("favicon.ico");
    expect(ico.readUInt16LE(0)).toBe(0); // reserved
    expect(ico.readUInt16LE(2)).toBe(1); // icon type
    const count = ico.readUInt16LE(4);
    const sizes = Array.from({ length: count }, (_, i) => ico.readUInt8(6 + i * 16));
    expect(sizes.sort((a, b) => a - b)).toEqual([16, 32, 48]);
  });

  it("the social card stays small enough to unfurl quickly", () => {
    expect(read("og.png").length).toBeLessThan(300 * 1024);
  });
});

describe("manifest and robots", () => {
  it("the manifest names the three icons that exist", () => {
    const manifest = JSON.parse(read("site.webmanifest").toString("utf-8")) as {
      icons: { src: string; sizes: string; purpose?: string }[];
      start_url: string;
    };
    expect(manifest.start_url).toBe("/queue");
    for (const icon of manifest.icons) {
      const [w, h] = pngSize(icon.src.replace(/^\//, ""));
      expect(`${w}x${h}`).toBe(icon.sizes);
    }
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
  });

  it("robots.txt keeps the app out and points at the sitemap placeholder", () => {
    const text = read("robots.txt").toString("utf-8");
    for (const path of ["/api/", "/login", "/queue", "/case", "/history", "/config", "/settings"]) {
      expect(text).toContain(`Disallow: ${path}`);
    }
    for (const path of ["/", "/about", "/privacy", "/r/"]) {
      expect(text).toContain(`Allow: ${path}\n`);
    }
    expect(text).toContain("Sitemap: __CSO_PUBLIC_ORIGIN__/sitemap.xml");
  });

  it("the favicon source is the three-bar mark with a dark scheme switch", () => {
    const svg = read("favicon.svg").toString("utf-8");
    expect(svg.match(/<rect /g)).toHaveLength(3);
    expect(svg).toContain("prefers-color-scheme: dark");
  });
});
