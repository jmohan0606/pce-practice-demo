import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-[3px] px-[7px] py-[3px] text-[10.5px] font-semibold uppercase tracking-[0.03em] transition-colors",
  {
    variants: {
      variant: {
        default: "bg-pm-tag-bg text-pm-tag-tx",
        real: "bg-pm-real-bg text-pm-real-tx",
        derived: "bg-pm-der-bg text-pm-der-tx",
        aigen: "bg-pm-ai-bg text-pm-ai",
        pos: "bg-pm-pos-bg text-pm-pos",
        neg: "bg-pm-neg-bg text-pm-neg",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
