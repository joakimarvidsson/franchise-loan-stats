import type { APIRoute } from 'astro';
import { brands } from '../../lib/data';
import { brandChart } from '../../lib/brandChart';

export function getStaticPaths() {
  return brands.filter((b: any) => b.seasoned.rate).map((b: any) => ({ params: { slug: b.slug }, props: { b } }));
}

export const GET: APIRoute = ({ props, site }) => {
  const { svg } = brandChart(props.b, new URL(site!).host);
  return new Response(svg, { headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' } });
};
