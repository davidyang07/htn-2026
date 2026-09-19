import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "default" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border font-medium " +
  "whitespace-nowrap transition-colors duration-100 " +
  "disabled:pointer-events-none disabled:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "border-accent-line bg-accent text-white hover:bg-accent-hover hover:border-accent-hover",
  default:
    "border-line-strong bg-raised text-fg hover:border-fg-subtle/50 hover:bg-overlay",
  ghost: "border-transparent bg-transparent text-fg-muted hover:bg-raised hover:text-fg",
  danger: "border-critical/40 bg-critical-soft text-critical hover:border-critical/70",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8 px-3 text-sm",
};

export function buttonClass(
  variant: ButtonVariant = "default",
  size: ButtonSize = "md",
  className?: string,
): string {
  return cn(BASE, VARIANTS[variant], SIZES[size], className);
}

export function Button({
  variant = "default",
  size = "md",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button type="button" className={buttonClass(variant, size, className)} {...rest}>
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "default",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {children}
    </Link>
  );
}

/** Segmented control — used for speed, filters and layer toggles. One shared
 * implementation so those three never diverge visually. */
export function SegmentedControl<T extends string | number>({
  value,
  options,
  onChange,
  disabled,
  ariaLabel,
  className,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string; title?: string }>;
  onChange: (value: T) => void;
  disabled?: boolean;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex h-7 items-center gap-0.5 rounded-md border border-line bg-raised p-0.5",
        disabled && "pointer-events-none opacity-40",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-6 rounded-sm px-2 text-2xs font-medium transition-colors duration-100",
              active
                ? "bg-overlay text-fg shadow-panel"
                : "text-fg-subtle hover:text-fg-muted",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
