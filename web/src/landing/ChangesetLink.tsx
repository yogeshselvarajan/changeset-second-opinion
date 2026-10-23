import type { ReactNode } from "react";

/** The public OpenStreetMap page of a changeset. A plain link: nothing is fetched from it. */
export function changesetUrl(id: number | string): string {
  return `https://www.openstreetmap.org/changeset/${id}`;
}

export function ChangesetLink({ id }: { id: number | string }) {
  return (
    <a
      href={changesetUrl(id)}
      rel="noopener noreferrer"
      className="font-mono underline underline-offset-4"
    >
      {id}
    </a>
  );
}

/** Writes a sentence that holds `{id}` with the changeset number turned into a link. */
export function withChangesetLink(template: string, id: number | string): ReactNode {
  const [before = "", after = ""] = template.split("{id}");
  return (
    <>
      {before}
      <ChangesetLink id={id} />
      {after}
    </>
  );
}
