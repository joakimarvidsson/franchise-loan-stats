import { describe, expect, it } from 'vitest';
import { monthlyPayment, totalInterest, dscr, balanceAfter } from '../src/lib/calc';
import { fmtInt, fmtUsd, fmtPct, fmtInterval, fmtDate, article } from '../src/lib/format';
import { compareRates, brandSummary, brandDescription } from '../src/lib/text';

describe('loan maths', () => {
  it('matches a known amortisation: $100,000 at 6% over 30 years', () => {
    expect(monthlyPayment(100000, 6, 360)).toBeCloseTo(599.55, 2);
  });
  it('handles a zero rate', () => {
    expect(monthlyPayment(120000, 0, 120)).toBe(1000);
    expect(totalInterest(120000, 0, 120)).toBe(0);
  });
  it('returns 0 for nonsense input', () => {
    expect(monthlyPayment(0, 5, 120)).toBe(0);
    expect(monthlyPayment(1000, 5, 0)).toBe(0);
  });
  it('total interest is payments minus principal', () => {
    const p = monthlyPayment(350000, 10.5, 120);
    expect(totalInterest(350000, 10.5, 120)).toBeCloseTo(p * 120 - 350000, 6);
  });
  it('coverage ratio', () => {
    const annual = monthlyPayment(350000, 10.5, 120) * 12;
    expect(dscr(annual * 1.25, 350000, 10.5, 120)).toBeCloseTo(1.25, 6);
    expect(dscr(1000, 0, 5, 120)).toBeNull();
  });
  it('balance runs from principal to zero', () => {
    expect(balanceAfter(100000, 6, 360, 0)).toBeCloseTo(100000, 6);
    expect(balanceAfter(100000, 6, 360, 360)).toBe(0);
    expect(balanceAfter(100000, 6, 360, 180)).toBeGreaterThan(50000);
  });
});

describe('formatting', () => {
  it('numbers', () => {
    expect(fmtInt(1976761)).toBe('1,976,761');
    expect(fmtInt(null)).toBe('—');
    expect(fmtUsd(350000)).toBe('$350K');
    expect(fmtUsd(1250000)).toBe('$1.3M');
    expect(fmtUsd(36326583100)).toBe('$36.3B');
    expect(fmtPct(7.7)).toBe('7.7%');
    expect(fmtInterval({ pct: 7.7, lo: 7.5, hi: 8 })).toBe('7.5–8.0%');
    expect(fmtInterval(null)).toBe('');
  });
  it('dates and articles', () => {
    expect(fmtDate('2026-09-30')).toBe('September 30, 2026');
    expect(article('Anytime Fitness')).toBe('an');
    expect(article('Subway')).toBe('a');
  });
});

describe('claims are only as strong as the data', () => {
  const bench = { pct: 7.7, lo: 7.5, hi: 8.0 };
  it('says higher/lower only when intervals do not overlap', () => {
    expect(compareRates({ pct: 27.4, lo: 22, hi: 33.5 }, bench)).toBe('higher');
    expect(compareRates({ pct: 0.3, lo: 0.1, hi: 1.1 }, bench)).toBe('lower');
    expect(compareRates({ pct: 6.2, lo: 1.1, hi: 28.3 }, bench)).toBe('similar');
    expect(compareRates(null, bench)).toBe('unknown');
  });
  const mk = (tier: string, disbursed: number, co: number, rate: any) => ({
    name: 'Example Brand',
    seasoned: { from_fy: 2012, to_fy: 2021, disbursed, charged_off: co, rate, tier },
    all: { disbursed: 40, charged_off: 4, first_fy: 1995, last_fy: 2026, rate: { pct: 10, lo: 4, hi: 23 } },
  });
  it('rated brands get a rate sentence with the interval', () => {
    const s = brandSummary(mk('rated', 230, 63, { pct: 27.4, lo: 22, hi: 33.5 }), bench);
    expect(s).toContain('63 were later charged off: 27.4%');
    expect(s).toContain('95% interval 22.0–33.5%');
    expect(s).toContain('higher than the 7.7% rate');
  });
  it('limited brands are flagged as rough and unranked', () => {
    const s = brandSummary(mk('limited', 16, 1, { pct: 6.2, lo: 1.1, hi: 28.3 }), bench);
    expect(s).toContain('not clearly different from');
    expect(s).toContain('not ranked');
  });
  it('insufficient brands never get a seasoned rate', () => {
    const b = mk('insufficient', 4, 1, null);
    const s = brandSummary(b, bench);
    expect(s).toContain('too few to report');
    expect(s).not.toMatch(/25\.0%/);
    expect(brandDescription(b)).not.toContain('%');
  });
});

import { rateChartSvg } from '../src/lib/chart';
describe('embeddable chart', () => {
  const rows = [
    { label: 'Brand <A> & "B"', rate: { pct: 12.5, lo: 8, hi: 18 }, n: 40, me: true },
    { label: 'No rate', rate: null, n: 3 },
    { label: 'Benchmark', rate: { pct: 6, lo: 5.5, hi: 6.5 }, n: 1000, note: 'whole industry' },
  ];
  const { svg, height } = rateChartSvg({ title: 'Test chart', rows, source: 'Source: example' });
  it('skips rows without a rate and sizes to the rows shown', () => {
    expect(svg).not.toContain('No rate');
    expect(height).toBe(48 + 2 * 36 + 46);
  });
  it('escapes labels and prints each rate', () => {
    expect(svg).toContain('Brand &lt;A&gt; &amp; &quot;B&quot;');
    expect(svg).toContain('12.5%');
    expect(svg).toContain('6.0%');
    expect(svg).toContain('1,000 loans · whole industry');
  });
  it('is a standalone SVG document', () => {
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
    expect(svg).not.toMatch(/undefined|NaN/);
  });
});
