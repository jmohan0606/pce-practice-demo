import type { ReactNode } from "react";

/** Page title + meta line + optional controls slot (right-aligned). */
export default function PageHeader({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children?: ReactNode;
}) {
  return (
    <div className="pagehead">
      <div>
        <div className="t">{title}</div>
        {meta ? <div className="m">{meta}</div> : null}
      </div>
      {children ? <div className="ctl">{children}</div> : null}
    </div>
  );
}
