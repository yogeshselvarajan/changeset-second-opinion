export interface RenderedPage {
  html: string;
  head: string;
  meta: { path: string; title: string; description: string; noindex?: boolean };
}
export function markStatic(head: string): string;
export function applyPage(template: string, rendered: RenderedPage, origin: string): string;
