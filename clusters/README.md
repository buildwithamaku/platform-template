# Plane 2 — GitOps (ArgoCD app-of-apps)

Everything Kubernetes lives here and is reconciled from Git by ArgoCD. If it can
run in the cluster, it does **not** go in `tofu/`.

## Layout

```
clusters/
├── bootstrap/            # the app-of-apps ROOT Application (applied by bootstrap.sh)
├── platform/            # one Argo Application per platform component, sync-wave ordered
│   ├── 00-external-secrets.yaml   # wave 0 — ESO (+ CRDs)
│   ├── 00-reloader.yaml           # wave 0 — Stakater Reloader
│   ├── 10-infisical-store.yaml    # wave 1 — deploys the ClusterSecretStore
│   └── 20-demo.yaml               # wave 2 — deploys the demo acceptance app
├── platform-config/
│   └── infisical/       # the ClusterSecretStore manifest (Infisical -> K8s Secrets)
└── apps/
    └── demo/            # ExternalSecret + dummy Deployment (Phase-2 acceptance target)
```

Sync waves guarantee ordering across Applications: ESO's CRDs (wave 0) exist
before the `ClusterSecretStore` (wave 1), which exists before the `ExternalSecret`
(wave 2).

## Bootstrap chain (§6.1)

`tofu apply` → `bootstrap.sh` → ArgoCD reconciles the rest from Git. `bootstrap.sh`
is the only imperative step and plants exactly one secret: the Infisical machine
identity. Inputs (env vars, never committed):

| Var | Purpose | Needed for |
|-----|---------|-----------|
| `GIT_TOKEN` | read access to this (private) repo | ArgoCD to pull git-sourced apps |
| `INFISICAL_CLIENT_ID` / `_SECRET` | Infisical machine identity | the ClusterSecretStore |

## Free local dev (k3d)

```bash
export GIT_TOKEN=<github read token>                 # this repo is private
export INFISICAL_CLIENT_ID=... INFISICAL_CLIENT_SECRET=...   # for the secret test
./scripts/k3d-local.sh
kubectl -n argocd get applications -w
```

`k3d-local.sh` points ArgoCD's **root** app at your current git branch. Caveat:
the git-sourced **child** apps (`infisical-store`, `demo`) pin `main` because
ArgoCD reads their manifests verbatim and cannot template them. So the full
end-to-end (Infisical → pod) flow validates against `main` — merge Phase 2, or
temporarily edit `targetRevision` in those two files for a pre-merge branch test.
The Helm-based platform apps (ESO, Reloader) validate on any branch immediately.

## Prerequisite: Infisical Cloud

1. Create a free account at <https://app.infisical.com> and a project.
2. Copy the **project slug** → replace `__INFISICAL_PROJECT_SLUG__` in
   `platform-config/infisical/cluster-secret-store.yaml`.
3. Add a **machine identity** (Universal Auth), grant it read on the project →
   copy its Client ID / Client Secret into the env vars above.
4. In the **Staging** environment, create a folder `refclient` and add a secret
   `GREETING` = `hello-world` inside it (so its path is `/refclient/GREETING`).

## Acceptance test (§6.4)

```bash
kubectl -n demo get externalsecret demo-secret        # SecretSynced
kubectl -n demo logs deploy/demo | tail -1            # GREETING=hello-world
# edit GREETING in the Infisical UI, then within ~90s:
kubectl -n demo logs deploy/demo | tail -1            # GREETING=<new value>
```

Pass = the pod restarts with the new value hands-off, ≤2 min, no cluster access.
