"use client";

import { useEffect, useRef, useState } from "react";

export type Size = { width: number; height: number };

/** Observed content-box size of an element. Charts need real pixel dimensions
 * rather than a scaled viewBox, or strokes and text distort with the aspect
 * ratio. */
export function useElementSize<T extends HTMLElement>(): [
  React.RefObject<T | null>,
  Size,
] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      setSize((prev) =>
        prev.width === box.width && prev.height === box.height
          ? prev
          : { width: box.width, height: box.height },
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, size];
}
