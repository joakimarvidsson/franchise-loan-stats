export type Rate = { pct: number; lo: number; hi: number } | null;

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return Math.round(n).toLocaleString('en-US');
}

export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const a = Math.abs(n);
  if (a >= 1e9) return `$${(n / 1e9).toFixed(a >= 1e10 ? 1 : 2)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `$${Math.round(n / 1e3).toLocaleString('en-US')}K`;
  return `$${Math.round(n)}`;
}

export function fmtUsdFull(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return '$' + Math.round(n).toLocaleString('en-US');
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return '—';
  return `${n.toFixed(digits)}%`;
}

export function fmtRate(r: Rate): string {
  return r ? fmtPct(r.pct) : '—';
}

export function fmtInterval(r: Rate): string {
  return r ? `${r.lo.toFixed(1)}–${r.hi.toFixed(1)}%` : '';
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  return `${months[m - 1]} ${d}, ${y}`;
}

export function fyRange(from: number, to: number): string {
  return `FY${from}–FY${to}`;
}

export function plural(n: number, one: string, many?: string): string {
  return `${fmtInt(n)} ${n === 1 ? one : many ?? one + 's'}`;
}

/** "a" or "an" for a brand or industry name. */
export function article(word: string): string {
  return /^[aeiou8]/i.test(word.trim()) ? 'an' : 'a';
}
