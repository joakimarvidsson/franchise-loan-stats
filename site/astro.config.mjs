import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// The address lives here, in scripts/check-dist.mjs (base path) and in scripts/smoke.mjs. SITE_URL and BASE_PATH override it.
const site = process.env.SITE_URL || 'https://franchiseloanstats.com';
const base = process.env.BASE_PATH ?? '/';

export default defineConfig({
  site,
  base,
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [sitemap()],
});
