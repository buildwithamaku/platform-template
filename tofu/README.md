# `tofu/` — Plane 1 (Infrastructure)

OpenTofu that provisions the cluster substrate and nothing more. The contract it
must satisfy for every cloud: **produce a reachable Kubernetes API + kubeconfig**.
Everything above that is GitOps (`clusters/`, added in Phase 2+).

See `docs/PLATFORM_FACTORY_PLAN.md` for the full plan and decision record.

```
tofu/
├── modules/
│   └── cluster-k3s/     # Hetzner VMs + k3s + API LB + firewall  (this phase)
└── live/
    └── staging/         # refclient staging: 1-node cluster
```

## First run (operator laptop)

```bash
cd tofu/live/staging

# 1. State backend (once): create an object-storage bucket, then:
cp backend.hcl.example backend.hcl        # fill bucket + endpoint
export AWS_ACCESS_KEY_ID=...              # object-storage keys
export AWS_SECRET_ACCESS_KEY=...
#   (or comment out backend.tf to smoke-test with local state first)

# 2. Inputs
cp terraform.tfvars.example terraform.tfvars   # set ssh_public_keys, api_allowed_cidrs
export TF_VAR_hcloud_token=...                  # Hetzner Cloud API token

# 3. Apply
tofu init -backend-config=backend.hcl
tofu apply

# 4. Acceptance test (Phase 1 exit criteria)
export KUBECONFIG=$PWD/kubeconfig
kubectl get nodes           # -> node(s) Ready
```

Teardown: `tofu destroy`. Re-apply should recreate cleanly.

## Prerequisites on the machine running tofu

`tofu` >= 1.6, plus `ssh`/`scp` and `kubectl` on PATH. The machine's public IP
must be in `api_allowed_cidrs` (the kubeconfig is fetched over SSH).

## Secrets / git hygiene

Never committed (git-ignored): `*.tfvars`, `backend.hcl`, `.gen/`, `kubeconfig`,
`.terraform/`, state files. Only `*.example` templates are tracked.
