import type { APIRoute } from 'astro';
import { SITE } from '../lib/site';

// IndexNow ownership key file. https://www.indexnow.org/documentation
export function getStaticPaths() {
  return [{ params: { key: SITE.indexNowKey } }];
}
export const GET: APIRoute = () => new Response(SITE.indexNowKey, { headers: { 'Content-Type': 'text/plain' } });
