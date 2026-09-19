import path from "node:path";

import { defineConfig } from "vitest/config";

// Mirrors the "@/*" -> "./src/*" path alias from tsconfig.json. Needed
// because vitest resolves modules independently of Next.js's build
// pipeline (which already understands tsconfig paths); without this, any
// value-level (non-type-only) `@/...` import fails to resolve under `vitest
// run`, even though it works fine under `next dev`/`next build`.
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
});
