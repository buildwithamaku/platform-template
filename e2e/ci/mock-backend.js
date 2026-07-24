// Minimal stand-in for the backend's HTTP contract (§5.4), used by the e2e.yaml
// PR gate (and handy for local dev). Set BROKEN=1 to simulate a bad deploy so the
// @smoke pack is proven to FAIL — the whole point of the smoke gate.
const http = require('http');
const broken = process.env.BROKEN === '1';
const port = process.env.PORT || 8080;

http
  .createServer((req, res) => {
    const u = req.url.split('?')[0];
    if (u === '/readyz')
      return broken ? (res.writeHead(500), res.end('db down')) : (res.writeHead(200), res.end('ok'));
    if (u === '/healthz') return (res.writeHead(200), res.end('ok'));
    if (u === '/metrics')
      return (res.writeHead(200, { 'content-type': 'text/plain' }), res.end('http_requests_total 5\n'));
    if (u === '/api/widgets')
      return broken
        ? (res.writeHead(500), res.end('err'))
        : (res.writeHead(200, { 'content-type': 'application/json' }), res.end(JSON.stringify({ widgets: 12 })));
    res.writeHead(404);
    res.end('not found');
  })
  .listen(port, () => console.log(`mock backend on :${port} (broken=${broken})`));
