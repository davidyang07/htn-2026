/** Minimal class joiner — drops falsy entries. Deliberately not `clsx`: the
 * whole need is three lines, and this codebase adds dependencies only against
 * a concrete requirement. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
