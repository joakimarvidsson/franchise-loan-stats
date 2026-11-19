// Production smoke test. Usage: node scripts/smoke.mjs [baseUrl]
// Verifies the live site serves the build that is in this checkout (same data date and brand count).
import fs from 'node:fs';

const base = (process.argv[2] || process.env.SITE_BASE_URL || 'https://joakimarvidsson.github.io/franchise-loan-stats').replace(/\/$/, '');
const summary = JSON.parse(fs.readFileSync(new URL('../data/published/summary.json', import.meta.url)));
const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const [y, m, d] = summary.asof.split('-').map(Number);
const asofText = `${months[m - 1]} ${d}, ${y}`;
const expectBrands = summary.counts.brand_pages;

const checks = [
  ['/', (t) => t.includes('Franchise Loan Stats') && t.includes(asofText)],
  ['/brands/', (t) => t.includes('brands-table')],
  ['/brands/subway/', (t) => /Subway franchise/.test(t) && t.includes('95% interval')],
  ['/rankings/', (t) => t.includes('Lowest charge-off rates')],
  ['/industries/', (t) => t.includes('ind-table')],
  ['/industries/limited-service-restaurants/', (t) => t.includes('Limited-Service Restaurants')],
  ['/lenders/', (t) => t.includes('lender-table')],
  ['/states/texas/', (t) => t.includes('Texas')],
  ['/compare/', (t) => t.includes('cmp-out')],
  ['/calculator/', (t) => t.includes('o-pay')],
  ['/methodology/', (t) => t.includes('Wilson')],
  ['/data/brands-index.json', (t) => JSON.parse(t).length === expectBrands],
  ['/data/franchise-loan-stats-brands.csv', (t) => t.split('\n').length >= expectBrands && t.startsWith('brand,slug')],
  ['/sitemap-index.xml', (t) => t.includes('<sitemapindex')],
  ['/sitemap-0.xml', (t) => (t.match(/<url>/g) || []).length >= expectBrands],
  ['/robots.txt', (t) => t.includes('Sitemap:')],
];

let failed = 0;
const results = [];
for (const [path, ok] of checks) {
  const url = base + path;
  let status = 0, pass = false, note = '';
  for (let attempt = 0; attempt < 3 && !pass; attempt++) {
    try {
      const r = await fetch(url, { headers: { 'User-Agent': 'franchise-loan-stats-smoke/1.0', 'Cache-Control': 'no-cache' } });
      status = r.status;
      const text = await r.text();
      pass = r.ok && ok(text);
      if (!pass) note = r.ok ? 'content check failed' : `HTTP ${status}`;
    } catch (e) { note = String(e).slice(0, 120); }
    if (!pass && attempt < 2) await new Promise((res) => setTimeout(res, 15000));
  }
  results.push({ path, status, pass, note });
  if (!pass) failed++;
  console.log(`${pass ? 'ok  ' : 'FAIL'} ${status} ${path}${note && !pass ? ' — ' + note : ''}`);
}
const nf = await fetch(base + '/this-page-does-not-exist-' + Date.now() + '/');
console.log(`${nf.status === 404 ? 'ok  ' : 'FAIL'} ${nf.status} unknown path returns 404`);
if (nf.status !== 404) failed++;
console.log(`\nsmoke: ${checks.length + 1 - failed}/${checks.length + 1} passed against ${base} (expects data as of ${summary.asof}, ${expectBrands} brands)`);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, `Smoke: ${checks.length + 1 - failed}/${checks.length + 1} passed against ${base}\n`);
process.exit(failed ? 1 : 0);
