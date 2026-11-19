// Post-build checks over the generated site. Fails the build on any structural problem.
import fs from 'node:fs';
import path from 'node:path';

const dist = path.resolve('dist');
const base = (process.env.BASE_PATH ?? '/franchise-loan-stats').replace(/\/$/, '');
const errors = [];
const pages = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.html')) pages.push(p);
  }
})(dist);

const exists = (href) => {
  let rel = href.split('#')[0].split('?')[0];
  if (!rel.startsWith(base + '/') && rel !== base) return null; // not ours
  rel = rel.slice(base.length);
  const f = path.join(dist, rel);
  return fs.existsSync(f) && fs.statSync(f).isFile() ? true : fs.existsSync(path.join(f, 'index.html'));
};

const titles = new Map();
const descs = new Map();
let links = 0;
for (const p of pages) {
  const html = fs.readFileSync(p, 'utf-8');
  const rel = path.relative(dist, p);
  const title = (html.match(/<title>([^<]*)<\/title>/) || [])[1];
  const desc = (html.match(/<meta name="description" content="([^"]*)"/) || [])[1];
  const canon = (html.match(/<link rel="canonical" href="([^"]*)"/) || [])[1];
  const h1 = (html.match(/<h1[\s>]/g) || []).length;
  if (!title) errors.push(`${rel}: missing title`);
  if (!desc || desc.length < 50) errors.push(`${rel}: missing or short description`);
  if (desc && desc.length > 320) errors.push(`${rel}: description too long (${desc.length})`);
  if (!canon) errors.push(`${rel}: missing canonical`);
  if (h1 !== 1) errors.push(`${rel}: expected exactly one h1, found ${h1}`);
  if (/undefined|NaN|\[object Object\]/.test(html.replace(/<script[\s\S]*?<\/script>/g, ''))) errors.push(`${rel}: rendered undefined/NaN/[object Object]`);
  if (rel !== '404.html') {
    if (title) titles.set(title, (titles.get(title) || []).concat(rel));
    if (desc) descs.set(desc, (descs.get(desc) || []).concat(rel));
  }
  for (const m of html.matchAll(/<a\s[^>]*href="([^"#][^"]*)"/g)) {
    const href = m[1];
    if (!href.startsWith('/')) continue;
    links++;
    if (exists(href) === false) errors.push(`${rel}: broken internal link ${href}`);
    if (exists(href) === null) errors.push(`${rel}: internal link outside base path ${href}`);
  }
  for (const m of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    try { JSON.parse(m[1]); } catch { errors.push(`${rel}: invalid JSON-LD`); }
  }
}
for (const [t, ps] of titles) if (ps.length > 1) errors.push(`duplicate title "${t}": ${ps.slice(0, 3).join(', ')}`);
for (const [d, ps] of descs) if (ps.length > 1) errors.push(`duplicate description: ${ps.slice(0, 3).join(', ')}`);
for (const f of ['sitemap-index.xml', 'robots.txt', 'data/brands-index.json', 'data/franchise-loan-stats-brands.csv', 'favicon.svg', 'og.png', '404.html']) {
  if (!fs.existsSync(path.join(dist, f))) errors.push(`missing ${f}`);
}
if (pages.length < 1500) errors.push(`only ${pages.length} pages built`);

if (errors.length) {
  console.error(`check-dist: ${errors.length} problem(s)`);
  for (const e of errors.slice(0, 60)) console.error(' - ' + e);
  process.exit(1);
}
console.log(`check-dist: ok — ${pages.length} pages, ${links} internal links verified`);
