# amakusolutions — Platform Template

A **platform factory**: given ~10 answers from a client discovery call, it stamps
out a complete production cloud platform — cluster, GitOps CD, secrets, database,
cache, observability, and BI — in under a day, on any cloud that can provide VMs.

The full design, decisions, and phase plan live in
**[`docs/PLATFORM_FACTORY_PLAN.md`](docs/PLATFORM_FACTORY_PLAN.md)** — read it first.

## Architecture in one line

Two planes: **Plane 1** (OpenTofu, thin, per-cloud) provisions a Kubernetes API;
**Plane 2** (Kubernetes + ArgoCD, identical everywhere) runs everything else from
Git. If it can run in the cluster, it does not go in OpenTofu.

## Repository layout

```
tofu/         # Plane 1 — cluster substrate (modules + per-env live roots)
clusters/     # Plane 2 — ArgoCD app-of-apps + platform + apps   (Phase 2+)
docs/         # plan, runbook
.github/      # CI
```

## Status

| Phase | What | State |
|-------|------|-------|
| 1 | Substrate: `cluster-k3s` (Hetzner) + refclient staging + CI | **done** — `apply`-verified |
| 2 | GitOps + secrets spine (ArgoCD, ESO/Infisical, Reloader) | **done** — acceptance-tested, merged |
| 3 | Edge + access (ingress-nginx, cert-manager, external-dns) — Tailscale deferred | **done** — green-lock verified on Hetzner |
| 4 | Data layer (CloudNativePG, Redis) | not started |
| 5 | Observability (kube-prometheus-stack, Loki, Tempo) | not started |
| 6 | App delivery (Kustomize, reusable CI, promotion flow) | not started |
| 7 | BI + E2E (Metabase, Playwright) | not started |
| 8 | Factory extraction (copier-ize, client #2) | not started |

## Getting started

See [`tofu/README.md`](tofu/README.md) to bring up the first cluster and run the
Phase 1 acceptance test (`kubectl get nodes` → Ready).
