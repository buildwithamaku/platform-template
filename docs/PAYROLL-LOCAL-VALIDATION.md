# Independent payroll application: local validation

On 2026-10-12, the factory was exercised against an existing NestJS payroll
backend and Next.js frontend in two separate Git repositories. No app source
files were changed for this check.

The backend checkout was clean at
`d5bcb0c78e24158463971870a356b12ac7354308`. The frontend checkout was based on
`5cea31058723b2318a5103ea34fde83c29e1f7d8` with pre-existing uncommitted changes.
This is working-tree compatibility evidence, not a reproducible CI artifact or
a staging promotion attestation.

## Observed results

- Both existing Dockerfiles built successfully through `factory doctor`.
- Backend ran under its declared numeric non-root user. Frontend used the
  service's `run_as_user: 1000` override for its existing `USER node` image.
- The configured TypeORM migration command completed successfully against a
  disposable PostgreSQL 16 database using separate owner credentials.
- Backend `/healthz` and `/readyz`, and frontend `/`, passed HTTP probes over
  loopback-published ports on a dedicated Docker bridge network.
- The runtime database role was `app_rw`, with `rolsuper=false` and
  `rolbypassrls=false`. This does not itself prove tenant isolation.
- `factory onboard` generated a baremetal/InterServer-style bundle with two
  caller workflows and staging/production app overlays. All four overlays built
  with Kustomize. No server was provisioned and no app workflow was published.
- The test database, containers, network, tagged test images, and synthetic
  credential files were cleaned up. Docker build caches may remain.

## Findings incorporated into the factory

The initial internal Docker network did not expose requested host ports on this
Docker Desktop installation. Doctor now diagnoses unsupported probe networks
before building. A dedicated non-internal bridge worked.

The first backend startup correctly failed on a missing `CORS_ORIGINS` variable.
The test specification was corrected to declare all required production variables,
including CORS and SMTP references. Only synthetic test credentials were used.
The successful run had no failed doctor checks, while `live-integration` remained
explicitly unverified.

## Still required for release acceptance

The generated Infisical project reference and deployment-domain configuration
must be confirmed before using the bundle. An authorized disposable InterServer
host, SSH identity and test domain are still needed. The next run must prove
real bootstrap and secret delivery, public DNS/TLS/ingress, application data
write/read and tenant isolation, then promotion of the tested registry digests
through a reviewed production PR. Local health checks do not establish those
properties.
