import { defineConfig } from '@playwright/test';

// API-level E2E (no browsers): every test uses Playwright's `request` context to
// hit the backend's HTTP contract (§5.4). BASE_URL selects the target — an
// in-cluster Service (http://backend.data.svc) for the PostSync hooks, or a
// public/ephemeral URL for CI. Outputs go to /tmp so the image can run non-root.
const baseURL = process.env.BASE_URL || 'http://localhost:8080';

export default defineConfig({
  testDir: './tests',
  outputDir: '/tmp/pw-results',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  // Retries absorb the brief window where a rollout is mid-flight; a genuinely
  // broken deploy still fails after retries (that's the point of the smoke gate).
  retries: process.env.CI ? 3 : 0,
  reporter: [['list']],
  use: {
    baseURL,
    extraHTTPHeaders: { Accept: 'application/json' },
  },
});
