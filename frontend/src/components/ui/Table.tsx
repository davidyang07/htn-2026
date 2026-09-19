import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * Table shell. The horizontal scroll lives on this wrapper, never on the page
 * body — a wide data table must never push the whole layout sideways.
 */
export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 overflow-x-auto", className)}>
      <table className="w-full border-collapse text-left text-xs">{children}</table>
    </div>
  );
}

export function Th({
  children,
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <th
      scope="col"
      className={cn(
        "sticky top-0 z-10 whitespace-nowrap border-b border-line bg-surface px-3 py-2",
        "eyebrow text-left",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <td className={cn("border-b border-line/60 px-3 py-2 align-middle text-fg-muted", className)} {...rest}>
      {children}
    </td>
  );
}

export function Tr({
  children,
  className,
  onClick,
  selected,
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  selected?: boolean;
}) {
  return (
    <tr
      onClick={onClick}
      className={cn(
        "transition-colors duration-75",
        onClick && "cursor-pointer",
        selected ? "bg-accent-soft" : onClick && "hover:bg-raised",
        className,
      )}
    >
      {children}
    </tr>
  );
}

/** Monospaced identifier cell — agent ids, node ids, seeds. */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-2xs text-fg", className)}>{children}</span>;
}
