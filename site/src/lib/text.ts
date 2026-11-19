import { fmtInt, fmtPct, fmtInterval, fyRange, plural } from './format';

type Rate = { pct: number; lo: number; hi: number } | null;

/** How a brand's seasoned rate compares with a benchmark, using interval overlap, not just the point value. */
export function compareRates(me: Rate, bench: Rate): 'lower' | 'higher' | 'similar' | 'unknown' {
  if (!me || !bench) return 'unknown';
  if (me.hi < bench.lo) return 'lower';
  if (me.lo > bench.hi) return 'higher';
  return 'similar';
}

export function comparePhrase(c: ReturnType<typeof compareRates>): string {
  return {
    lower: 'lower than',
    higher: 'higher than',
    similar: 'not clearly different from',
    unknown: 'not comparable with',
  }[c];
}

/** One factual paragraph describing a brand's seasoned record. Every number comes from the record. */
export function brandSummary(b: any, franchiseRate: Rate): string {
  const s = b.seasoned;
  const win = fyRange(s.from_fy, s.to_fy);
  if (s.tier === 'insufficient') {
    const a = b.all;
    const base = `Only ${plural(s.disbursed, 'disbursed SBA 7(a) loan')} coded to ${b.name} ${s.disbursed === 1 ? 'was' : 'were'} approved in ${win}, too few to report a charge-off rate for that period.`;
    if (a.disbursed >= 10 && a.rate) {
      return `${base} Across the whole public file (FY${a.first_fy}–FY${a.last_fy}), ${fmtInt(a.charged_off)} of ${fmtInt(a.disbursed)} disbursed loans were charged off (${fmtPct(a.rate.pct)}).`;
    }
    return base;
  }
  const r = s.rate as NonNullable<Rate>;
  let out = `Of the ${fmtInt(s.disbursed)} SBA 7(a) loans to ${b.name} franchisees that were approved in ${win} and disbursed, ${fmtInt(s.charged_off)} ${s.charged_off === 1 ? 'was' : 'were'} later charged off: ${fmtPct(r.pct)} (95% interval ${fmtInterval(r)}).`;
  if (franchiseRate) {
    const c = compareRates(r, franchiseRate);
    out += ` That is ${comparePhrase(c)} the ${fmtPct(franchiseRate.pct)} rate for all franchise-coded loans in the same period.`;
  }
  if (s.tier === 'limited') {
    out += ` With fewer than 30 loans the estimate is rough, so this brand is not ranked.`;
  }
  return out;
}

export function brandTitle(b: any): string {
  return `${b.name} franchise: SBA loan charge-off rate and lending history`;
}

export function brandDescription(b: any): string {
  const s = b.seasoned;
  if (s.rate) {
    return `${fmtInt(s.charged_off)} of ${fmtInt(s.disbursed)} SBA 7(a) loans to ${b.name} franchisees (${fyRange(s.from_fy, s.to_fy)}) were charged off: ${fmtPct(s.rate.pct)}. Loans by year, top lenders, typical loan size and industry comparison.`;
  }
  return `SBA 7(a) lending history for ${b.name} franchisees: ${fmtInt(b.all.disbursed)} disbursed loans since FY${b.all.first_fy}, outcomes by year, lenders and typical loan size.`;
}

export const STATE_NAMES: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut',
  DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois',
  IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland',
  MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana',
  NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York',
  NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania',
  PR: 'Puerto Rico', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas',
  UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
};
