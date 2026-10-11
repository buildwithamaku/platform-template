# Self-service release acceptance

The release is complete only when an independent containerized application is
deployed to staging on InterServer, verified through HTTPS and its database, and
promoted through a reviewed Git change using the same image. Static validation
does not meet that acceptance criterion.

## Execution path

1. `factory onboard` reads a deployment specification and local app checkouts
   (separate repositories or contexts in one repository). Validate inputs before
   creating any files. Render into a new directory; never overwrite app repos.
2. Generate the platform, caller workflows grouped by repository, recorded
   answers, and a secret inventory with consumers. No secret values in the spec.
3. `factory doctor` reports configured, verified, failed, and unverified checks
   separately. Container execution is opt-in; missing runtime evidence never
   becomes a passing check.
4. Provision explicitly, with a reviewed OpenTofu plan and named kube-context.
   Bootstrap staging only after images, credentials, and required configuration
   are ready. Validate ingress, TLS, application behavior, and database access.
5. Generate a production promotion PR only from a verified staging artifact.
   Verify production separately; do not equate an overlay edit with deployment.

## Findings from the current implementation

Implemented and covered by local CLI/render tests:

- Configurable ports, probes, migration command/arguments, optional migrations,
  runtime secrets, and separate owner credentials for migrations.
- Generated staging/prod roots select their own app overlays, secret-store
  environments, backup prefixes, DNS ownership and tailnet names.
- Runtime-agnostic Dockerfile delivery, optional Go/Node checks within service
  contexts, and digest-pinned staging images.
- Onboarded apps use declared health/readiness paths in generated PostSync
  probes. Reference widget/metrics assertions remain only in the reference suite.
  These probes do not establish database or business behavior correctness.
- Copier answers metadata is emitted for reproducible configuration tracking.
- `factory bootstrap` selects a context and environment explicitly, requires a
  clean published platform tree, and refuses to take over another environment
  or platform repository. Unit tests cover fresh-cluster and repeated execution;
  actual bootstrap remains unverified.

Still requiring implementation or live evidence:

- Publishing the generated platform repository and provisioning orchestration.
- Live verification of app connection PRs prepared by `factory connect`.
- Live validation of the implemented bootstrap, verification, app/database
  acceptance protocol, and promotion PR flow. Local tests exercise protocol
  failures and Git branch preparation; they do not establish a real deployment.
- Reliable regeneration of CLI-created environment roots when updating the
  underlying template.
- Existing single-worker Recreate deployment is not an exactly-once guarantee
  during failures. Applications need idempotency or fencing for critical jobs.
- BYO install validation is structural only. Live SSH, node networking, local
  storage, ingress, secret delivery, and recovery still require runtime evidence.

Local execution evidence for the independent payroll application is recorded in
[PAYROLL-LOCAL-VALIDATION.md](PAYROLL-LOCAL-VALIDATION.md). Builds, owner migrations,
non-root execution, both services' HTTP probes and generated overlays passed.
This does not replace the required InterServer acceptance run.

## Required verification

- CLI tests: invalid specs, path traversal, duplicate services, no-clobber output,
  mono/polyrepo workflow generation, actionable diagnostics and exit codes.
- Render tests: default and custom ports/probes/migrations/env, optional frontend,
  each supported cloud, staging/prod root separation, secret inventory accuracy.
- Container tests: build, numeric non-root UID, bind port, HTTP readiness,
  separate migration command, no environment-specific frontend URL.
- Integration: disposable InterServer node(s), explicit SSH identity, DNS test
  subdomain, platform GitHub repo/registry and Infisical identity. Use synthetic
  application data. Capture revisions, image digests, checks and teardown results.

The independent payroll repositories have been identified and tested locally.
Live acceptance inputs still needed: disposable node address and SSH identity,
test domain, and credentials through their normal secret stores. Never place
credential values in this document.
