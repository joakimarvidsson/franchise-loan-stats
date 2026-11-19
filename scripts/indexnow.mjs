// Tell IndexNow-enabled search engines (Bing, Yandex, Seznam, Naver and others) which URLs changed.
// Usage: node scripts/indexnow.mjs all|core   (reads site/dist/sitemap-0.xml after a build)
import fs from 'node:fs';

const mode = process.argv[2] || 'core';
const siteTs = fs.readFileSync(new URL('../site/src/lib/site.ts', import.meta.url), 'utf-8');
const key = siteTs.match(/indexNowKey: '([a-f0-9]+)'/)[1];
const xml = fs.readFileSync(new URL('../site/dist/sitemap-0.xml', import.meta.url), 'utf-8');
let urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
if (!urls.length) { console.error('no URLs in sitemap'); process.exit(1); }
const root = urls.reduce((a, b) => (a.length <= b.length ? a : b));
if (mode === 'core') urls = urls.filter((u) => u === root || /\/(brands|rankings|industries|lenders|states|data)\/$/.test(u.slice(root.length - 1)));
const host = new URL(root).host;
const body = { host, key, keyLocation: `${root}${key}.txt`, urlList: urls.slice(0, 10000) };
const r = await fetch('https://api.indexnow.org/indexnow', {
  method: 'POST', headers: { 'Content-Type': 'application/json; charset=utf-8' }, body: JSON.stringify(body),
});
console.log(`IndexNow ${mode}: submitted ${body.urlList.length} URLs for ${host} -> HTTP ${r.status}`);
// 200 and 202 both mean accepted. Anything else is reported but never fails a deploy.
if (![200, 202].includes(r.status)) console.log(await r.text().catch(() => ''));
