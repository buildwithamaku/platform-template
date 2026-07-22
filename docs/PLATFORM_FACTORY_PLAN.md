# Platform Factory — Engineering Plan

| | |
|---|---|
| **Status** | Draft v1.0 |
| **Author** | David Amaku (with Claude) |
| **Date** | 2026-07-23 |
| **Audience** | Any engineer picking up this project cold |
| **Supersedes** | The per-cloud Terraform approach in the `maestroh-infra` repo |

---

## 1. Purpose

Build a **platform factory**: a template that, given ~10 answers from a client discovery call, produces a complete production cloud platform — cluster, CI/CD, secrets, database, cache, observability, BI — in under one day, on any cloud that can provide VMs (Hetzner, Hostinger, AWS, …).

The factory serves an agency model: many clients, each getting an identical, independently-owned platform. The client's repo **is** their infrastructure; nothing lives outside Git except data and one root credential.

### What "done" looks like

```bash
copier copy gh:amakusolutions/platform-template acme-platform   # answer ~10 questions
cd acme-platform/tofu/live/prod && tofu apply             # ~10 min: VMs, k3s, LB, DNS
./bootstrap.sh                                            # ArgoCD + one root secret
# ArgoCD reconciles the full platform from Git (~15 min)
# Fill secrets in Infisical, push app code → clients served same day
```

## 2. Goals and Non-Goals

### Goals
1. **One merge = one deploy.** Git is the only write path to any environment.
2. **Cloud-portable.** The cloud provides VMs + network + LB (or a managed cluster). Everything above that line is byte-identical across providers.
3. **Repeatable.** Client #2 through client #N are stamped, not rebuilt. Target: discovery call → serving traffic in < 1 day.
4. **Operable by one engineer.** A single person can onboard a client, debug a 2am incident (logs → trace → data layer, no SSH), and run DR.
5. **Adoptable.** Existing client codebases join with an 8-line CI file + a Dockerfile — no restructuring required.

### Non-Goals (v1)
- Multi-region / multi-cluster federation per client.
- Cross-repo full-stack PR preview environments (frontend PR previews run against staging backend; see §6.3).
- Windows workloads, serverless, or non-Kubernetes runtimes.
- Automated Infisical self-hosting bootstrap (v1 uses Infisical Cloud; see D-07).
- Migrating existing `maestroh-infra` deployments — this is a fresh build; salvage is listed in §9 Phase 1.

## 3. Key Decisions

Decisions already made and **not up for re-litigation** without a written counter-proposal. Rationale recorded so future engineers know *why*, not just *what*.

| ID | Decision | Choice | Rationale | Rejected alternatives |
|----|----------|--------|-----------|----------------------|
| D-01 | IaC tool | **OpenTofu** | Open-source Terraform fork; identical syntax; no BSL license risk for an agency shipping to clients | Terraform (license), Pulumi (per-client language sprawl) |
| D-02 | Cluster substrate (non-managed clouds) | **k3s**, 3 nodes, embedded etcd HA | Simple to stand up on any VM, tiny footprint, well-trodden. Prod default = 3 servers (HA); dev may run 1 | Talos (better GitOps purity, steeper learning curve — revisit later), managed-only (excludes Hetzner/Hostinger) |
| D-03 | GitOps controller | **ArgoCD** (app-of-apps) | UI answers "what is deployed right now" for any engineer or client demo; PreSync/PostSync hooks used for migrations and smoke tests | Flux (fine, but no UI by default; team familiarity favors Argo) |
| D-04 | Secrets backend | **Infisical** + External Secrets Operator + Stakater Reloader | UI + audit log + machine identities; ESO keeps cluster decoupled from backend choice; Reloader closes the loop (change → rollout) | SOPS-in-git (no UI/audit for non-engineers), AWS SM (breaks multi-cloud), Vault (operational weight) |
| D-05 | Postgres | **CloudNativePG** in-cluster; **RDS toggle** on AWS | CNPG gives declarative HA Postgres + WAL backups anywhere. Apps only ever see a `DATABASE_URL` secret, so the source is swappable per client | RDS-only (AWS lock-in), self-managed VMs (undifferentiated toil) |
| D-06 | Image tag promotion | **CI commits tag bump to platform repo** (GitHub App auth) | Every deploy is an explicit, revertible git commit; `git log clusters/` is the complete deploy history for all services | Argo Image Updater (implicit "a tag appeared" deploys; weaker audit; acceptable later for staging only) |
| D-07 | Infisical hosting | **Infisical Cloud** for v1 | Self-hosting creates a bootstrap circularity (Infisical can't hold its own secrets); defer until factory is proven | Self-hosted + SOPS root (valid, adds a phase) |
| D-08 | Observability stack | **Grafana LGTM-lite**: kube-prometheus-stack + Loki + Tempo + OTel Collector | One pane of glass, cross-linked metrics↔logs↔traces, all self-hosted, no per-seat cost | Datadog (cost per client), ELK (weight) |
| D-09 | Private admin access | **Tailscale** subnet router | Zero-config WireGuard mesh; scoped kubeconfigs; admin UIs (Grafana, ArgoCD, Redis Insight) never get public ingress | Raw WireGuard (manual key mgmt), Netbird (viable fallback if Tailscale pricing bites) |
| D-10 | Repo topology | **Platform repo per client** + app repos (mono or poly, client's choice) | App repos build images; ONLY the platform repo deploys. Mono vs poly becomes a copier checkbox, not an architecture decision | Single agency mega-repo (client ownership/handoff impossible) |
| D-11 | Ingress + TLS + DNS | ingress-nginx + cert-manager (Let's Encrypt) + external-dns (Cloudflare) | Boring, universal, automated end to end | Traefik (fine; nginx chosen for ubiquity of debugging knowledge) |
| D-12 | Registry | GHCR under agency org; per-client repos; pull secret via ESO | Free with GitHub, near CI | Per-client registries (only if client demands) |

## 4. Architecture

### 4.1 Two planes

```
┌────────────────────────────────────────────────────────────────┐
│ PLANE 2 — Platform + Apps (Kubernetes, GitOps, IDENTICAL       │
│ across all clouds)                                             │
│   ArgoCD · ESO+Infisical · Reloader · ingress-nginx ·          │
│   cert-manager · external-dns · Tailscale · CNPG · Redis ·     │
│   kube-prometheus-stack · Loki · Tempo · OTel · Metabase ·     │
│   client apps                                                  │
├────────────────────────────────────────────────────────────────┤
│ CONTRACT: a reachable K8s API + kubeconfig + node pool + LB    │
├────────────────────────────────────────────────────────────────┤
│ PLANE 1 — Infrastructure (OpenTofu, thin, PER-CLOUD)           │
│   hetzner: VMs + private net + LB + k3s                        │
│   aws:     EKS + VPC (+ optional RDS)                          │
│   hostinger/other: VMs + k3s                                   │
└────────────────────────────────────────────────────────────────┘
```

**The rule that keeps multi-cloud honest: if it can run in the cluster, it does not go in OpenTofu.** Plane 1's only job is to produce the contract line. This is exactly where the previous attempt (`maestroh-infra`) went sideways — 22 Terraform modules, AWS-only, most never wired.

### 4.2 Repo topology (per client)

```
acme-platform/                      # THE deployment hub. Owns all clusters.
├── tofu/
│   ├── modules/                    # vendored from template (cluster-k3s, cluster-eks, dns)
│   └── live/
│       ├── staging/                # small: 1–2 nodes
│       └── prod/                   # 3-node HA
├── clusters/
│   ├── bootstrap/                  # ArgoCD app-of-apps root Application
│   ├── platform/                   # one Argo Application per component (§4.3)
│   └── apps/
│       ├── frontend/ backend/ metabase/     # base manifests (Kustomize)
│       └── overlays/
│           ├── staging/            # image tags land here automatically
│           └── prod/               # image tags land here via approved PR
├── e2e/                            # Playwright; @smoke subset tagged
├── bootstrap.sh                    # installs ArgoCD, plants root secret (§6.1)
├── .github/workflows/
│   ├── tofu.yaml                   # plan on PR, gated apply on merge
│   └── e2e.yaml                    # staging full run + prod smoke
└── docs/RUNBOOK.md

acme-frontend/, acme-backend/       # (if polyrepo) — code, tests, Dockerfile,
                                    # 8-line CI calling the reusable workflow
```

App repos **never** contain k8s manifests and **never** talk to a cluster. Their CI ends at "image pushed."

### 4.3 Runtime stack

| Concern | Component | Namespace | Exposure |
|---|---|---|---|
| GitOps | ArgoCD | `argocd` | Tailscale only |
| Secrets sync | External Secrets Operator | `external-secrets` | — |
| Secret-change rollouts | Stakater Reloader | `reloader` | — |
| Ingress / TLS / DNS | ingress-nginx, cert-manager, external-dns | `ingress` | public LB |
| VPN / admin access | Tailscale subnet router | `tailscale` | — |
| Postgres | CloudNativePG operator + per-app `Cluster` CRs | `cnpg-system` / app ns | in-cluster |
| Cache | Redis (+ Redis Insight) | `redis` | Insight: Tailscale only |
| Metrics / alerts | kube-prometheus-stack | `monitoring` | Grafana: Tailscale (+ optional SSO ingress) |
| Logs | Loki + Grafana Alloy (DaemonSet) | `monitoring` | via Grafana |
| Traces | Tempo + OTel Collector | `monitoring` | via Grafana |
| Synthetic checks | Gatus (external URL probes) | `monitoring` | Tailscale |
| BI | Metabase (own CNPG app-db) | `metabase` | `bi.<domain>` + oauth2-proxy |

One Grafana is the single pane of glass: dashboards as code (ConfigMaps via sidecar), logs and traces cross-linked by `trace_id`.

## 5. Standards and Conventions

These are load-bearing — the factory's repeatability depends on every client following the same conventions.

### 5.1 Naming
- Clusters: `<client>-<env>` → `acme-prod`.
- Images: `ghcr.io/amakusolutions/<client>-<app>:sha-<7hex>` — **git SHA tags only**. Never `latest`, never mutable tags.
- K8s labels on everything: `app.kubernetes.io/name`, `app.kubernetes.io/part-of: <client>`, `env: <staging|prod>`.

### 5.2 Environments
- Exactly two per client in v1: `staging`, `prod`. (Dev is `docker compose` / local k3d — not a cluster we run.)
- Staging auto-deploys on merge to app-repo `main`. Prod deploys only via approved PR in the platform repo.

### 5.3 Secrets
- Infisical path scheme: `/<client>/<env>/<app>/KEY` → e.g. `/acme/prod/backend/STRIPE_SECRET_KEY`.
- One Infisical **machine identity per cluster**, scoped to `/<client>/<env>/**`. This credential is the *only* secret that exists outside the system (§6.1).
- Apps consume secrets **only** as env vars from ESO-managed `Secret`s. No secret files, no build-time secrets, no secrets in images or manifests — CI enforces with gitleaks.
- Every Deployment consuming secrets carries `reloader.stakater.com/auto: "true"`.

### 5.4 Application contract (what an app must provide to be deployable)
1. `Dockerfile` (multi-stage, non-root user, listens on `$PORT`).
2. Logs: **structured JSON to stdout**, including `level`, `msg`, `trace_id`.
3. `GET /healthz` (liveness) and `GET /readyz` (readiness).
4. OTel SDK wired to `$OTEL_EXPORTER_OTLP_ENDPOINT` (collector injects env via ConfigMap).
5. Migrations runnable as a one-shot command (`app migrate`) — executed as Argo **PreSync hook Job**, must be backward-compatible one version (old pods run during rollout).
6. `/metrics` Prometheus endpoint (or sidecar exporter) + a `ServiceMonitor` in its base manifests.

### 5.5 Git / CI
- Conventional commits. Platform repo `main` is protected; prod overlay changes require 1 approval + green CI.
- Cross-repo automation authenticates as a **GitHub App** (`amakusolutions-deployer`), never a personal PAT.
- Rollback = `git revert` of the tag-bump commit. There is no other rollback mechanism, deliberately.

## 6. Core Flows (specification)

### 6.1 Bootstrap chain — the ordering is the whole game
1. `tofu apply` → VMs, private network, LB, k3s installed (cloud-init), **kubeconfig output**.
2. `bootstrap.sh`:
   a. Installs ArgoCD (pinned Helm chart) with the app-of-apps root pointed at `clusters/bootstrap/`.
   b. Plants **exactly one** Secret: the Infisical machine-identity client ID/secret (from CI secret or operator prompt — never committed).
3. ArgoCD reconciles `clusters/platform/` in sync-wave order: ESO → cert-manager → ingress → Tailscale → CNPG/Redis → observability → Metabase.
4. ESO authenticates to Infisical with the root credential; every other secret in the system now flows from Git-declared `ExternalSecret`s.

After step 2b, no human touches a cluster. Total manual inputs for a new client: cloud API token, one Infisical credential, DNS delegation to Cloudflare.

### 6.2 App deploy (backend example, polyrepo)
```
dev merges PR in acme-backend
  → reusable workflow: lint, test, build, push ghcr.io/…:sha-abc123, gitleaks
  → workflow (as GitHub App) commits tag bump to acme-platform:clusters/apps/overlays/staging/
  → ArgoCD syncs staging:
      PreSync Job: `app migrate`   (fails ⇒ deploy never happens, old version serves)
      rolling Deployment update    (readiness-gated)
  → e2e.yaml runs full Playwright suite against staging
dev/lead opens promotion PR bumping the same tag in overlays/prod/  →  approval  →  merge
  → ArgoCD syncs prod  →  PostSync hook runs @smoke pack  →  failure alerts + revert
```

Monorepo clients: identical flow, the tag-bump commit just targets the same repo.

### 6.3 Cross-repo caveats (accepted for v1)
- Frontend PR previews (if enabled) target the **staging** backend. Full-stack cross-repo preview envs are out of scope until a client pays for the complexity.
- Contract drift between app repos is mitigated by: one-version-backward-compatible API discipline (already required for rolling deploys) + staging e2e gate.

### 6.4 Secret rotation
Ops edits value in Infisical UI (audit-logged) → ESO refresh (≤60s) updates the K8s Secret → Reloader rolling-restarts consuming Deployments → new value live in ~90s. No cluster access, no redeploy, no engineer required.

### 6.5 Incident debugging (the 2am test)
Alertmanager pages (5xx SLO burn) → Grafana/Loki `{app="backend",env="prod"} |= "error"` → log line carries `trace_id` → click-through to Tempo trace → identify slow span (e.g. Redis) → Tailscale → Redis Insight → inspect keys. Full chain from phone, zero SSH. **This flow is an acceptance test in Phase 5, not an aspiration.**

### 6.6 Client onboarding (the factory moment)
1. Discovery call → fill copier answers: client name, domain, cloud (`hetzner|aws|hostinger`), node size/count, apps (frontend? backend? metabase?), mono/polyrepo, registry org.
2. `copier copy` → new platform repo. CI secrets: cloud token, Infisical credential, GitHub App key.
3. `tofu apply` (staging, then prod) → `bootstrap.sh` each.
4. Create Infisical project `/<client>/`, fill app secrets.
5. Client app repos add the 8-line reusable-workflow CI file + Dockerfile (per §5.4 contract).
6. DNS delegation → certs auto-issue → first deploy flows through §6.2.

Target wall-clock: **< 1 day**. Measured, not vibes — Phase 8 acceptance.

## 7. What survives from `maestroh-infra`
- **Keep (adapted):** S3-compatible state backend pattern, tfsec/Checkov CI gates, pre-commit config, docs discipline, VPC design thinking (informs the AWS module).
- **Drop:** the ~16 unwired Terraform modules (EKS/RDS/ALB/KMS/backup/cloudwatch-* etc.) — they are Plane-1 solutions to Plane-2 problems; the `vpc-placeholder` wiring; per-env copy-pasted roots.
- This repo stays as-is for reference; the factory is a **new repository** (`amakusolutions/platform-template`).

## 8. Phase Plan

Build **one reference client end-to-end first** ("refclient", on Hetzner), extract the template second (Phase 8). Do not template before something real runs — that is how these projects die. Each phase gates on its acceptance test.

> Estimates assume one senior engineer, focused. Total ≈ 27 working days / 5–6 weeks.

### Phase 1 — Substrate (3–4d)
Tofu `cluster-k3s` module: Hetzner VMs (cloud-init), private network, LB, 3-server k3s embedded-etcd HA, firewall (K8s API allowlisted to Tailscale + CI), kubeconfig as output. `tofu/live/{staging,prod}` roots + state backend + `tofu.yaml` workflow (plan on PR, gated apply on merge, tfsec/checkov).
**Accept:** fresh `tofu apply` → `kubectl get nodes` from laptop shows 3 Ready nodes; teardown/recreate is clean.

### Phase 2 — GitOps + secrets spine (3d)
`bootstrap.sh` (idempotent); ArgoCD app-of-apps with sync waves; ESO + Infisical `ClusterSecretStore`; Reloader; sample `ExternalSecret` + dummy Deployment.
**Accept:** edit a value in Infisical UI → pod restarts with the new value, hands-off, ≤2 min.

### Phase 3 — Edge + access (2d)
ingress-nginx, cert-manager (LE prod + staging issuers), external-dns (Cloudflare), Tailscale subnet router; scoped read-only kubeconfig recipe for engineers (Lens/Headlamp works from here).
**Accept:** commit an Ingress → `https://test.<domain>` green-lock within minutes; ArgoCD/Grafana URLs resolve only over Tailscale.

### Phase 4 — Data layer (3d)
CNPG operator + prod-grade `Cluster` (3 instances, WAL + scheduled base backups to object storage); Redis + Redis Insight (Tailscale-only); connection secrets delivered via ESO.
**Accept:** kill the Postgres primary pod → auto-failover; **restore staging from backup to a point in time** and verify data. DR is tested now, not during an incident.

### Phase 5 — Observability (4d)
kube-prometheus-stack; Loki + Alloy; Tempo + OTel Collector; Grafana datasource cross-links (logs↔traces via `trace_id`, exemplars); dashboards-as-code baseline (cluster, ingress, CNPG, Redis, per-app); Alertmanager → Slack with page/ticket tiers; Gatus external probes.
**Accept:** run the full §6.5 chain on a synthetic error in a demo app: alert → log → trace → span, all in one Grafana. Test page reaches Slack.

### Phase 6 — App delivery (4d)
Reference frontend (Next.js) + backend (API + migrations) meeting the §5.4 contract; Kustomize bases + overlays; reusable `build-and-bump.yaml` workflow (**`workflow_call` from day one** — D-06/D-10); GitHub App for cross-repo write-back; PreSync migration hook; prod promotion PR flow with environment approval.
**Accept:** merge to refclient backend repo → staging live hands-off; promotion PR → prod live; failed migration blocks deploy with old version still serving; `git revert` rolls back cleanly.

### Phase 7 — BI + E2E (3d)
Metabase (own CNPG app-db, CNPG-managed `metabase_ro` role on product DB, oauth2-proxy at `bi.<domain>`); Playwright suite: full run on staging deploys, `@smoke` as prod PostSync hook wired to alerting.
**Accept:** Metabase queries prod data read-only (write attempt fails); an intentionally broken deploy is flagged by smoke within minutes of prod sync.

### Phase 8 — Factory extraction (5d)
Copier-ize refclient into `platform-template` (answers: name, domain, cloud, sizes, app toggles, mono/poly); `cluster-eks` variant + RDS toggle (same `DATABASE_URL` contract); `docs/RUNBOOK.md` (onboarding, rotation, DR, incident, offboarding/handoff); stamp **client #2 from scratch**.
**Accept:** client #2 from `copier copy` to serving HTTPS traffic with full observability in **< 1 working day**, executed by an engineer who didn't build the template, following only the runbook.

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Template drifts from stamped clients (fixes don't propagate) | High | Medium | Copier supports `copier update`; keep client-specific edits confined to `tofu/live/` + overlays; monthly template-sync chore |
| Infisical Cloud outage blocks secret changes | Low | Medium | ESO caches last-synced Secrets in-cluster — running apps unaffected; only *changes* blocked. Revisit self-hosting (D-07) post-v1 |
| Single-engineer bus factor | High | High | This document + RUNBOOK.md + Phase 8 acceptance explicitly requires a second engineer to execute onboarding |
| k3s upgrade breakage across many clients | Medium | Medium | Pin k3s version in template; upgrade staging first per client; one client canaries before fleet rollout |
| Hetzner LB/network quirks vs AWS assumptions | Medium | Low | Contract line (§4.1) is deliberately minimal; per-cloud quirks stay inside Plane-1 modules |
| Client demands cloud we don't support | Medium | Low | Any provider with VMs + one public IP works via `cluster-k3s`; only truly managed-only requirements need a new module |
| Secret sprawl / leaked credentials in app repos | Medium | High | gitleaks in reusable workflow (blocking); secrets only via ESO path (§5.3); machine identities scoped per client+env so blast radius is one environment |
| GitHub App key compromise | Low | High | App permissions limited to contents:write on platform repos only; key in CI secret store; rotate quarterly (runbook item) |

## 10. Open Questions (decide during build, owner: David)

1. **Tailscale vs Netbird** — if Tailscale per-seat pricing is unacceptable at client scale, Netbird self-hosted is the fallback (D-09). Decide by end of Phase 3.
2. **oauth2-proxy IdP** — Google Workspace per client vs agency-owned IdP for Metabase/Grafana SSO. Decide in Phase 7.
3. **Backup offsite target** — Hetzner Object Storage vs Backblaze B2 vs client-owned S3. Default proposal: B2 (cheap, provider-independent). Decide in Phase 4.
4. **Frontend RUM** — Grafana Faro for browser telemetry: v1 or backlog? Proposal: backlog unless a client asks.
5. **Per-PR preview environments** (single-repo case, ApplicationSet PR generator): backlog; revisit when a client team is large enough to collide on staging.

## 11. Glossary

| Term | Meaning |
|---|---|
| **Plane 1 / Plane 2** | Cloud infra (Tofu, per-cloud, thin) / everything Kubernetes (GitOps, identical everywhere) |
| **App-of-apps** | ArgoCD pattern: one root Application that declares all other Applications from Git |
| **ESO** | External Secrets Operator — syncs Infisical → K8s Secrets |
| **Reloader** | Watches Secrets/ConfigMaps, rolling-restarts consuming Deployments on change |
| **CNPG** | CloudNativePG — Postgres operator (HA, backups, managed roles) |
| **Tag-bump commit** | The git commit in the platform repo that changes an image tag — the unit of deployment and of rollback |
| **refclient** | The internal reference client built in Phases 1–7, extracted into the template in Phase 8 |

---

*Rules to hold the line on, verbatim from design review:*
1. *If it can run in the cluster, it does not go in Tofu.*
2. *Git is the only write path to clusters. The moment someone `kubectl edit`s prod, the factory's guarantee — "the repo **is** the client" — is broken.*
