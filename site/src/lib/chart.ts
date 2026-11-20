import { fmtPct, type Rate } from './format';

export type ChartRow = { label: string; rate: Rate; n?: number; me?: boolean; note?: string };

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const trim = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

/**
 * A self-contained SVG of charge-off rates with 95% intervals, for other sites to embed.
 * Every number comes from the rows passed in; nothing is typed here.
 */
export function rateChartSvg(opts: { title: string; rows: ChartRow[]; source: string }): { svg: string; width: number; height: number } {
  const rows = opts.rows.filter((r) => r.rate);
  const width = 640;
  const left = 230, right = 70, top = 48, rowH = 36, foot = 46;
  const plotW = width - left - right;
  const height = top + rows.length * rowH + foot;
  const max = Math.max(10, ...rows.map((r) => Math.min(100, r.rate!.hi))) * 1.08;
  const x = (v: number) => (left + Math.max(0, Math.min(1, v / max)) * plotW).toFixed(1);
  const body = rows
    .map((r, i) => {
      const y = top + i * rowH;
      const rt = r.rate!;
      return [
        `<text x="${left - 10}" y="${y + 14}" text-anchor="end" font-size="13" fill="#0f172a"${r.me ? ' font-weight="700"' : ''}>${esc(trim(r.label, 32))}</text>`,
        r.n !== undefined ? `<text x="${left - 10}" y="${y + 28}" text-anchor="end" font-size="10.5" fill="#64748b">${r.n.toLocaleString('en-US')} loans${r.note ? ' · ' + esc(r.note) : ''}</text>` : '',
        `<rect x="${left}" y="${y + 4}" width="${(Number(x(rt.pct)) - left).toFixed(1)}" height="16" rx="2" fill="${r.me ? '#1d4ed8' : '#94a3b8'}"/>`,
        `<path d="M${x(rt.lo)} ${y + 12}H${x(rt.hi)}M${x(rt.lo)} ${y + 7}V${y + 17}M${x(rt.hi)} ${y + 7}V${y + 17}" stroke="#0f172a" stroke-width="1.5" fill="none"/>`,
        `<text x="${width - right + 8}" y="${y + 16}" font-size="13" fill="#0f172a">${fmtPct(rt.pct)}</text>`,
      ].join('');
    })
    .join('');
  const label = `${opts.title}: ${rows.map((r) => `${r.label} ${fmtPct(r.rate!.pct)}`).join('; ')}`;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" ` +
    `font-family="system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif" role="img" aria-label="${esc(label)}">` +
    `<rect width="100%" height="100%" fill="#ffffff"/>` +
    `<text x="16" y="28" font-size="15" font-weight="700" fill="#0f172a">${esc(trim(opts.title, 76))}</text>` +
    body +
    `<text x="16" y="${height - 26}" font-size="10.5" fill="#64748b">Share of disbursed SBA 7(a) loans later charged off. Black line: 95% confidence interval.</text>` +
    `<text x="16" y="${height - 10}" font-size="10.5" fill="#64748b">${esc(opts.source)}</text>` +
    `</svg>`;
  return { svg, width, height };
}
