import fs from 'node:fs';
import path from 'node:path';

const DIR = path.resolve(process.cwd(), '..', 'data', 'published');
const CHANGES = path.resolve(process.cwd(), '..', 'data', 'changes');

function load<T>(name: string): T {
  return JSON.parse(fs.readFileSync(path.join(DIR, name), 'utf-8')) as T;
}

/* The pipeline owns these shapes (pipelines/aggregate.py). Pages treat them as read-only records. */
export type Brand = any;
export type Industry = any;
export type Lender = any;
export type State = any;

export const brands: Brand[] = load('brands.json');
export const industries: Industry[] = load('industries.json');
export const lenders: Lender[] = load('lenders.json');
export const states: State[] = load('states.json');
export const summary: any = load('summary.json');
export const manifest: any = load('manifest.json');
export const brandsCsv: string = fs.readFileSync(path.join(DIR, 'brands.csv'), 'utf-8');
export const changes: any = fs.existsSync(path.join(CHANGES, 'latest.json'))
  ? JSON.parse(fs.readFileSync(path.join(CHANGES, 'latest.json'), 'utf-8'))
  : null;

export const brandBySlug = new Map<string, Brand>(brands.map((b) => [b.slug, b]));
export const stateByCode = new Map<string, State>(states.map((s) => [s.code, s]));
export const rated: Brand[] = brands
  .filter((b) => b.rank)
  .sort((a, b) => a.rank.position - b.rank.position);

export const franchiseRate = summary.franchise.seasoned.rate;
export const seasonedFrom: number = summary.windows.seasoned[0];
export const seasonedTo: number = summary.windows.seasoned[1];
export const recentFrom: number = summary.windows.recent[0];
export const recentTo: number = summary.windows.recent[1];
export const activityFrom: number = summary.windows.activity_from_fy;
export const asof: string = summary.asof;

/** Compact record for client-side search, the brands table and the compare tool. */
export function brandIndexRow(b: Brand) {
  return {
    s: b.slug,
    n: b.name,
    t: b.seasoned.tier,
    sd: b.seasoned.disbursed,
    sc: b.seasoned.charged_off,
    r: b.seasoned.rate,
    rd: b.seasoned.rate_dollar_pct,
    ad: b.all.disbursed,
    ac: b.all.charged_off,
    ar: b.all.rate,
    ra: b.recent.approved,
    ml: b.recent.median_loan,
    mr: b.recent.median_rate,
    mt: b.recent.median_term_months,
    i: b.industry?.name ?? null,
    ir: b.industry?.seasoned_rate ?? null,
    d: b.directory.listed,
    k: b.rank?.position ?? null,
  };
}
