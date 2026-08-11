import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded text-[13px] transition-all disabled:pointer-events-none disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-pm-navy focus-visible:outline-offset-1",
  {
    variants: {
      variant: {
        default: "border border-pm-rule bg-white text-pm-ink hover:bg-pm-panel",
        primary: "bg-pm-navy text-white border border-pm-navy font-medium hover:bg-pm-navy-hi",
        ghost: "text-pm-slate hover:text-pm-ink",
      },
      size: {
        default: "px-3 py-[7px]",
        sm: "px-2.5 py-1.5 text-[12px]",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
