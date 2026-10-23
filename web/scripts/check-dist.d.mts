export function distProblems(input: {
  files: Record<string, string>;
  renderedTitles: Record<string, string | undefined>;
  sitemap: string;
  robots: string;
  shell: string;
}): string[];
