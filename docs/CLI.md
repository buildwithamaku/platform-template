# Factory CLI — implementation in progress

Install from this checkout with `python3 -m pip install -e .`. Start with
`examples/onboarding.yaml` and supply your own repo identifiers, existing local
checkouts, and Copier answers. Paths resolve relative to the specification file.
Separate repositories, multiple contexts in one repository, and frontend-only
applications are supported. A frontend-only bundle omits backend resources,
backend E2E tooling, and the database unless Metabase is explicitly enabled.
Onboarding defaults Metabase off; enable it only when wanted. Backend-dependent
options such as same-origin API routing and scheduler workers require a backend.
Each service can set `branch` (default `main`); services sharing one repository
must agree on the delivery branch and use the same checkout.

```bash
factory doctor --spec /path/to/onboarding.yaml --json
factory onboard --spec /path/to/onboarding.yaml --template /path/to/platform-template --output /path/to/new-bundle
```

The output directory must not exist. The bundle contains:

- `platform/`: Copier-rendered platform repository.
- `connections/<owner>/<repo>/deliver.yml`: caller workflow per app repo; jobs
  are grouped when backend and frontend share a repository.
- `answers.yml`: supplied render answers (not a replacement for Copier metadata).
- `secrets-required.json`: remote secret keys discovered in rendered
  ExternalSecrets, with consumer filenames, and separate bootstrap/CI credentials.
- `readiness.json`: explicit outstanding runtime and deployment checks.

Each service's `config` declares `port`, `health_path`, `ready_path`, non-secret
`env` values, `secrets` (environment name → Infisical key), and `required_env`.
Backend `db_env` maps app variable names to connection-secret keys (host, port,
dbname, username, password, uri). Runtime uses the non-owner secret when
`cap_db_app_role` is enabled. Migration `command` and `args` are argument lists;
`migration.enabled: false` omits the Job. Migration `env`, `db_env` and `secrets`
are separate from the runtime mappings; owner credentials never enter web pods.

Generation neither provisions infrastructure nor modifies app repositories.
Generated bundles contain separate staging and production Application roots.
Set `PLATFORM_ENVIRONMENT=staging` or `prod` when bootstrapping the respective
cluster. Secret-store environments, backup prefixes, DNS ownership, and tailnet
names are separated. Live acceptance is still outstanding: do not deploy a
bundle merely because generation succeeds.

Delivery defaults to `language: container`: the Dockerfile determines the
runtime and build tools, so Python, Java, Rust and other containerized apps do
not need factory changes. Application CI must run its own tests. Optional
`language: node` and `language: go` run the existing npm or Go checks within the
service context before building the image. Delivery records the pushed image's
registry digest in staging, including its migration and worker containers, so
promotion can reuse an immutable artifact. Use `factory promote` to prepare a production PR from fresh staging evidence.

## Local container verification

```bash
factory doctor --spec /path/to/onboarding.yaml --runtime \
  --env-file backend=/private/path/runtime.env --network disposable-test-network \
  --run-migrations --migration-env-file backend=/private/path/owner.env --json
```

This builds images, verifies numeric non-root image USER, and starts disposable
containers with loopback-only published ports to check HTTP probes. It removes
its containers and tagged images afterwards. Supply dependency connections in
the test env files; never point migration tests at production. Migration
execution is opt-in and requires its own env file. Env file contents and process
logs are not included in reports. Docker build caches may remain.

Passing local probes proves local startup, not Kubernetes secret delivery, RLS
policies, DNS/TLS, or live database correctness. Those need integration evidence.

Generated PostSync tests use the backend's declared health and readiness paths
when onboarding an app. They require a 2xx response without following redirects.
They check service health only: add application acceptance tests for database
access and business workflows. A failed production PostSync check detects a
problem after rollout; it does not keep the previous version serving.

Doctor exit codes: `1` failed prerequisite, `2` malformed input, `3` incomplete
verification. Available tools are only "configured", not runtime-verified. A
Dockerfile is only a file-presence check unless `--runtime` is provided. Doctor
does not contact a cluster in this version.

See [release acceptance](SELF-SERVICE-PLAN.md) for the full outstanding scope.

## Bootstrap a published platform

Publish `platform/` as its own Git repository and the generated caller workflows
in the app repositories. Provision the selected infrastructure using the
rendered OpenTofu configuration. Before bootstrap, make the platform's local
HEAD match published `origin/main`, populate the remote secrets checklist, and
build/publish the app and E2E images. Bootstrap does not perform those steps.

```bash
factory bootstrap --platform /path/to/bundle/platform \
  --environment staging --context my-staging-cluster
```

Supply `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET` through your normal
secret manager; private platform repositories also require `GIT_TOKEN`.
The command validates local manifests, checks cluster access, and pins both
Helm and kubectl to the named context without changing your current context.
It refuses to replace a platform root assigned to another environment. Use a
separate cluster/context with `--environment prod` for production.

A successful bootstrap installs ArgoCD, plants credentials, and submits the
root Application. It is not evidence that application reconciliation, external
HTTPS, database access, or business acceptance tests passed.

## Read-only live verification

```bash
factory verify --platform /path/to/bundle/platform \
  --environment staging --context my-staging-cluster \
  --url https://app.staging.example.com/ > /tmp/staging-evidence.json
```

Use a clean committed platform checkout at the revision you intend to verify.
The report records that revision, context, timestamp, and expected image digests.
It checks each generated Argo Application's source, health, sync and operation
status; Git Applications must report the checked-out revision as Synced. Because Argo
does not run a new sync for an unchanged application, an older successful app
sync is accepted only when its archived Git revision renders identical app
manifests, including hooks. Missing history or changed manifests fails this
check; fetch the relevant commit or sync the changed application before retrying.
Application deployments must have all replicas updated and ready with matching
images pinned by digest. HTTPS checks use normal certificate validation and do
not follow redirects. Only generated application ingress hosts are accepted.
No cluster resources are modified and no response bodies or secrets are saved.

Exit `1` means a failed check; `3` means incomplete evidence. Without an
acceptance suite the report remains `promotion_ready: false`. A healthy cluster
and HTTP 200 are insufficient to certify an application's data behavior.

### Application-owned acceptance suite

Add `--acceptance-suite acceptance/run-tests` to run a reviewed executable
committed in the platform repository. This is opt-in execution of application
tests and may write synthetic test data; the suite owns cleanup. The factory
only runs it after infrastructure and HTTPS checks pass. It has a five-minute
timeout and receives JSON on stdin with `version`, `environment`, `context`,
`revision`, `images`, `urls`, and `requires_database`. Credentials remain in your runtime environment.

The suite must run real application and database assertions, exit zero, and
write one JSON object to stdout containing the input's `version`, `environment`,
`context`, and `revision`, plus:

```json
{"checks": [
  {"check": "application", "status": "passed", "assertions": 4},
  {"check": "database", "status": "passed", "assertions": 3}
]}
```

Counts must represent executed, successful assertions, not declared tests.
When `requires_database` is false (neither backend nor Metabase selected), the
suite may report the database check as `status: "not_applicable"` with zero
assertions. That exception is rejected for a platform with database consumers.
For a payroll app, cover authentication, a synthetic tenant's database
write/read, and rejection of cross-tenant access. The factory validates the
report protocol; reviewers must assess the suite's actual test coverage.
Arbitrary stdout/stderr and response bodies are withheld from the evidence.
The report records the entrypoint hash and platform revision. It rechecks
cluster health and image digests after the suite to detect a concurrent rollout.
Only passing staging checks and acceptance produce `promotion_ready: true`.
Production verification may exit zero but never becomes a staging promotion
source. These reports are local review evidence, not signed attestations.


## Promote verified staging images

```bash
factory promote --platform /path/to/bundle/platform \
  --context my-staging-cluster --url https://app.staging.example.com/ \
  --acceptance-suite acceptance/run-tests
```

This reruns verification and acceptance; it does not trust an old JSON report.
Published `origin/main` must match the verified revision. Every staging image
reference, including the E2E image, must have a digest. The command creates a
`codex/promote-*` branch in a temporary Git worktree, changes only production
image mappings, builds the resulting overlays, and commits verification evidence.
Your current branch and working tree stay in place. Review with
`git diff main..<returned-branch>`.

Add `--publish` to push that branch and open a GitHub PR with `gh`. Configure
Git author identity and GitHub credentials first. The command never merges the
PR or contacts the production cluster. If publication fails, its local branch
remains available for inspection and recovery. Review the acceptance tests and
migration compatibility before merging, then run production verification using
its separate context. Reverting images does not automatically undo migrations.


## Connect application repositories

After onboarding, prepare the caller workflow changes automatically:

```bash
factory connect --spec /path/to/onboarding.yaml --bundle /path/to/bundle
```

The command fetches each declared delivery branch, checks that `origin` matches
the declared GitHub repository, and creates one `codex/connect-factory-*` branch
per repository. Monorepo services share `.github/workflows/factory-deliver.yml`.
Existing files with different contents are never overwritten. Changes happen
in temporary Git worktrees; local unfinished app work remains untouched.
Generated workflow contents must match the current spec, so regenerate the
bundle if you change repository connections or build contexts.

Add `--publish` to push branches and open PRs. Before merging, populate the
caller secrets from `secrets-required.json`, authorize access to a private
reusable platform workflow, and configure GHCR pull access. This step does not
create secrets or weaken repository protection. Separate repositories can
produce separate PRs; if one publication fails, inspect the retained local
branches before retrying.
