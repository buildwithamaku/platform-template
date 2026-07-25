# Module: `cluster-k3s`

Provisions a k3s cluster on Hetzner Cloud and returns a kubeconfig. This is a
**Plane 1** module (see `docs/PLATFORM_FACTORY_PLAN.md`): its only job is to hand
Plane 2 a working Kubernetes API. Everything above the cluster (ArgoCD, ESO,
ingress, observability, apps) is installed via GitOps, not here.

## What it creates

| Resource | Notes |
|---|---|
| `hcloud_network` + subnet | Private network; nodes get static IPs `cidrhost(subnet_cidr, 10+N)` |
| `hcloud_placement_group` (spread) | Nodes on distinct physical hosts for etcd HA |
| `hcloud_server` × `server_count` | k3s servers; embedded-etcd (`--cluster-init` on node 1) |
| `hcloud_load_balancer` (`-api`) | Stable 6443 endpoint for joins + kubectl |
| `hcloud_firewall` | Public 22/6443/ICMP restricted to `api_allowed_cidrs` |
| generated ED25519 SSH key | Break-glass + kubeconfig fetch |

Defaults chosen for the platform: flannel CNI, `traefik` and `servicelb`
disabled (ingress-nginx + hcloud-ccm come in Phase 3), kubeconfig written locally.

## Usage

```hcl
module "cluster" {
  source            = "../../modules/cluster-k3s"
  cluster_name      = "refclient-staging"
  location          = "nbg1"
  server_count      = 1          # 3 for HA prod
  server_type       = "cx22"
  api_allowed_cidrs = ["203.0.113.7/32"]
  ssh_public_keys   = ["ssh-ed25519 AAAA... you@laptop"]
}
```

## Key inputs

- `server_count` — 1 (dev/staging) or 3/5 (HA). Must be odd for etcd quorum.
- `server_type` — `cx22`/`cx32` (x86) or `cax11`/`cax21` (ARM; set `image` to an ARM image).
- `api_allowed_cidrs` — **required**, must not be `0.0.0.0/0`. Locks the API + SSH.
- `k3s_version` — pinned; bump deliberately and roll staging first.

## Outputs

`kubeconfig` (sensitive), `api_endpoint`, `network_id`, `server_public_ips`,
`server_private_ips`, `ssh_private_key` (sensitive).

## How the join works

Node 1 boots with `--cluster-init` (initializes etcd). Nodes 2..N wait for the
API LB to answer on 6443, then join via `--server https://<lb>:6443`. The LB
targets servers by the label `cluster=<name>,role=server`, so membership is
automatic. The kubeconfig is fetched from node 1 over SSH and its server URL is
rewritten to the LB IP.

## Operational notes / current limits

- **The machine running `tofu apply` must be in `api_allowed_cidrs`** (it SSHes to
  node 1 to fetch the kubeconfig). Phase 1: run applies from an operator laptop.
- The generated SSH private key and the kubeconfig are stored in state — keep the
  state backend encrypted and access-controlled.
- No cloud-controller-manager yet, so `LoadBalancer` Services and `Ingress` won't
  provision Hetzner LBs until Phase 3 wires hcloud-ccm + ingress-nginx.
- Adding nodes after node 1 is permanently gone is fine (joins go via the LB), but
  full etcd-quorum loss is a restore-from-backup event (Phase 4).
