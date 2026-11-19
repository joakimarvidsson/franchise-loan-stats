import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Moving to a custom domain is two variables: SITE_URL=https://example.com BASE_PATH=/
const site = process.env.SITE_URL || 'https://joakimarvidsson.github.io';
const base = process.env.BASE_PATH ?? '/franchise-loan-stats';

export default defineConfig({
  site,
  base,
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [sitemap()],
});
