import fs from 'node:fs';
import path from 'node:path';

/**
 * Commercial placements. An offer renders only when its programme is approved AND a live URL is set.
 * Until then nothing is shown: no placeholder links, no pretend affiliate links.
 * Registry: /partners.json at the repository root (kept in sync with the private pipeline tracker).
 */
export type Partner = {
  id: string; name: string; status: string; placement: string[]; url: string | null;
  headline: string; body: string; cta: string; relationship: 'affiliate' | 'sponsor' | 'referral';
};
const file = path.resolve(process.cwd(), '..', 'partners.json');
const all: Partner[] = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf-8')).partners : [];

export function partnersFor(placement: string): Partner[] {
  return all.filter((p) => p.status === 'live' && p.url && p.placement.includes(placement));
}
