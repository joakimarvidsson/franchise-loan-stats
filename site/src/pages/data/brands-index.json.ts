import type { APIRoute } from 'astro';
import { brands, brandIndexRow } from '../../lib/data';

export const GET: APIRoute = () =>
  new Response(JSON.stringify(brands.map(brandIndexRow)), { headers: { 'Content-Type': 'application/json' } });
