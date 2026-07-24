import { test, expect } from '@playwright/test';

// Full suite (runs on staging deploys, and as the PR contract gate). Deeper than
// @smoke — exercises the rest of the §5.4 contract surface. NOT tagged @smoke, so
// `--grep @smoke` excludes these from the fast prod hook.

test('healthz returns 200', async ({ request }) => {
  const res = await request.get('/healthz');
  expect(res.status()).toBe(200);
});

test('metrics endpoint exposes http_requests_total', async ({ request }) => {
  const res = await request.get('/metrics');
  expect(res.status()).toBe(200);
  expect(await res.text()).toContain('http_requests_total');
});

test('widgets payload has the expected shape and JSON content-type', async ({ request }) => {
  const res = await request.get('/api/widgets');
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/json');
  const body = await res.json();
  expect(body).toMatchObject({ widgets: expect.any(Number) });
});

test('unknown route returns 404', async ({ request }) => {
  const res = await request.get('/no-such-route');
  expect(res.status()).toBe(404);
});
