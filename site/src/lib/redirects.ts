/**
 * Brand pages that no longer exist because a reviewed alias merged them into another brand.
 * Each old address gets a small page that sends visitors (and search engines, via canonical)
 * to the brand it was merged into. Add a row whenever a merge retires a slug.
 */
export const RETIRED_BRAND_SLUGS: { from: string; to: string; oldName: string; since: string }[] = [
  { from: 'jakes-wayback-burgers', to: 'wayback-burgers', oldName: "Jake's Wayback Burgers", since: '2026-11-20' },
  { from: 'country-inns-and-suites-by-carlson', to: 'country-inn-and-suites-by-radisson', oldName: 'Country Inns & Suites by Carlson', since: '2026-11-20' },
  { from: 'one-hour-martinizing', to: 'martinizing-cleaners', oldName: 'One-Hour Martinizing', since: '2026-11-20' },
  { from: 'bright-star-healthcare-brightstar', to: 'brightstar-care', oldName: 'Bright Star Healthcare/Brightstar', since: '2026-11-20' },
  { from: 'rainbow-international-restoration-and-cleaning', to: 'rainbow-restoration', oldName: 'Rainbow International Restoration & Cleaning', since: '2026-11-20' },
];
