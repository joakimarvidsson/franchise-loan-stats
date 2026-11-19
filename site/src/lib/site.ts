export const SITE = {
  name: 'Franchise Loan Stats',
  tagline: 'How SBA loans to each franchise brand have actually performed',
  contactEmail: 'franchiseloanstats@agentmail.to',
  repo: 'https://github.com/joakimarvidsson/franchise-loan-stats',
  // PostHog project key. Public by design (it only allows sending events).
  analytics: {
    key: 'phc_wW3bjnCuBtXHGmyQJkgMvJuNTdvSnt5hqBTa98RwWhMp',
    host: 'https://eu.i.posthog.com',
  },
  indexNowKey: '5f3c9d1e7a8b4c2f9e6d0a1b3c5d7e9f',
};

const base = import.meta.env.BASE_URL.replace(/\/$/, '');

/** Prefix an internal path with the deploy base and guarantee a trailing slash for pages. */
export function url(path: string): string {
  if (!path.startsWith('/')) path = '/' + path;
  const isFile = /\.[a-z0-9]+$/i.test(path);
  if (!isFile && !path.endsWith('/')) path += '/';
  return base + path;
}
