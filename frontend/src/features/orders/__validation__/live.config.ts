import { defineConfig } from 'vitest/config';

/** Explicit isolated validation only; never selected by the application's normal Vitest config. */
export default defineConfig({
  define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('http://127.0.0.1:18768') },
  test: { environment: 'node', include: ['src/features/orders/__validation__/decision-live.check.ts'], maxWorkers: 1 },
});
