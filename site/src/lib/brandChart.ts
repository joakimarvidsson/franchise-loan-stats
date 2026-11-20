import { franchiseRate, summary, asof } from './data';
import { fyRange, fmtDate } from './format';
import { rateChartSvg, type ChartRow } from './chart';

/** Rows for a brand's comparison chart: the same four rows the brand page shows. */
export function brandChartRows(b: any): ChartRow[] {
  const ind = b.industry;
  return [
    { label: b.name, rate: b.seasoned.rate, n: b.seasoned.disbursed, me: true },
    ...(ind?.seasoned_rate ? [{ label: ind.name, rate: ind.seasoned_rate, n: ind.seasoned_disbursed, note: 'whole industry' }] : []),
    { label: 'All franchise-coded loans', rate: franchiseRate, n: summary.franchise.seasoned.disbursed },
    { label: 'All SBA 7(a) loans', rate: summary.all_7a.seasoned.rate, n: summary.all_7a.seasoned.disbursed },
  ];
}

export function brandChart(b: any, host: string) {
  return rateChartSvg({
    title: `${b.name}: SBA loan charge-off rate, loans approved ${fyRange(b.seasoned.from_fy, b.seasoned.to_fy)}`,
    rows: brandChartRows(b),
    source: `Source: ${host} · SBA 7(a) data as of ${fmtDate(asof)} · CC BY 4.0`,
  });
}
