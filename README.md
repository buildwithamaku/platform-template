# platform-template — a GitOps platform factory

Answer ~15 questions and get a complete, production-shaped cloud platform as your own
GitOps repo: Kubernetes cluster, Argo CD, ingress + TLS + DNS, secrets, a Postgres
(CloudNativePG + point-in-time backups), cache, full observability, optional BI, and a
reusable app-delivery pipeline — on **Hetzner**, **DigitalOcean**, or **any VPS / dedicated /
on-prem host** (bring-your-own-nodes).

This repo is a [copier](https://copier.readthedocs.io) **template**. You don't fork it — you
*render an instance* from it.

```bash
pipx install copier        # or: uvx copier
copier copy --trust gh:buildwithamaku/platform-template <client>-platform
```

## How it fits together
```
platform-template (this factory) ──copier render──▶  <you>/<client>-platform  (GitOps repo; Argo CD watches it)
                                                              ▲
                                    image-tag bump │ (your deployer GitHub App)
                                                              │
                                     <you>/<client>-app  (your code) ──build-and-bump──┘
```
- **Plane 1 — infra** (`tofu/`): thin, per-cloud; provisions a Kubernetes API. Run once.
- **Plane 2 — GitOps** (`clusters/`): identical everywhere; Argo CD runs everything else from git.

## Start here
- **[`docs/ADOPTING.md`](docs/ADOPTING.md)** — full walkthrough: render your platform repo,
  set up accounts, provision + bootstrap, and connect your app repo(s).
- **[`examples/app-ci/`](examples/app-ci)** — ready-to-paste `deliver.yml` for your app repo
  (Go / Node, polyrepo / monorepo).
- **[`docs/TESTING-baremetal.md`](docs/TESTING-baremetal.md)** — how to validate the
  bring-your-own-nodes path (InterServer, OVH, on-prem).
- Each rendered client repo ships its own tailored `docs/RUNBOOK.md` and `docs/APP-CONTRACT.md`.

## What you answer
Identity (client, domain, GitHub org) · cloud + nodes · which apps (backend/frontend, serving
mode, public ingress, same-origin API) · capabilities (preview envs, event bus, pgvector,
two-role RLS DB, single-writer worker) · VPN, SSO IdP, DB source, prod hardening. Defaults are
sensible; `examples/*.copier-answers.yml` are worked answer sets.

## Design & internals
`docs/PLATFORM_FACTORY_PLAN.md` records the architecture, the numbered decisions (D-xx), and the
phase history.
