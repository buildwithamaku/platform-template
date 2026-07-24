import { test, expect } from '@playwright/test';

// @smoke — the critical path. This exact subset runs as a prod PostSync hook
// (`playwright test --grep @smoke`): if it fails, the prod sync fails and the
// old version keeps serving. Keep it minimal, fast, and dependency-light.

test('readyz returns 200 @smoke', async ({ request }) => {
  const res = await request.get('/readyz');
  expect(res.status()).toBe(200);
});

test('GET /api/widgets returns a valid widgets payload @smoke', async ({ request }) => {
  const res = await request.get('/api/widgets');
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body).toHaveProperty('widgets');
  expect(typeof body.widgets).toBe('number');
});
