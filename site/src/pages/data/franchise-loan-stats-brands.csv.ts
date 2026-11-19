import type { APIRoute } from 'astro';
import { brandsCsv } from '../../lib/data';

export const GET: APIRoute = () => new Response(brandsCsv, { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
