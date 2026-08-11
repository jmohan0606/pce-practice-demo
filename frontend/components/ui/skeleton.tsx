import * as React from "react";
import { cn } from "@/lib/utils";

/** Skeleton — the single shimmer primitive for the whole app. Compose it into
 * layout-shaped placeholders rather than hand-rolling animate-pulse divs. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-pm-rule-2", className)} {...props} />;
}
