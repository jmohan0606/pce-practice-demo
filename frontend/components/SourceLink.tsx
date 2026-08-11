import type { ReactNode } from "react";

/** The document-citation thread: "Document · p. N · Section". */
export default function SourceLink({ href = "#", children }: { href?: string; children: ReactNode }) {
  return (
    <a className="src" href={href}>
      {children}
    </a>
  );
}
