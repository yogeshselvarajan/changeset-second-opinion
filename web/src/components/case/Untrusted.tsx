import { showControls } from "./caseModel";

/**
 * Text that came from a mapper or from OpenStreetMap, shown as plain text. It is a React text node
 * (never markup), isolated for bidirectional text, with invisible characters made visible. URLs in it
 * stay inert text: nothing here links to or fetches anything from evidence.
 */
export function Untrusted({
  value,
  className,
  block = false,
}: {
  value: string | null | undefined;
  className?: string;
  block?: boolean;
}) {
  const text = showControls(value ?? "");
  if (block) {
    return (
      <p dir="auto" className={`whitespace-pre-wrap break-words ${className ?? ""}`}>
        {text}
      </p>
    );
  }
  return <bdi className={`break-words ${className ?? ""}`}>{text}</bdi>;
}
