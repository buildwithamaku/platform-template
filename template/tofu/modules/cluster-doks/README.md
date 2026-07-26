# cluster-doks

Managed **DigitalOcean Kubernetes (DOKS)** cluster — the managed-cloud variant
(cf. `cluster-k3s`, self-managed k3s on Hetzner droplets). DO runs the control
plane; this provisions a VPC, the cluster, a default node pool, and an optional
GPU pool. The DO CCM + CSI ship with DOKS, so ingress LoadBalancers and CNPG
block-storage PVCs work with no extra config.

| Output | Meaning |
|---|---|
| `kubeconfig` | Raw kubeconfig (same contract as `cluster-k3s`) |
| `endpoint` | API endpoint |
| `cluster_id` | DOKS cluster id |

**Notes**
- **Kubeconfig expires.** `kube_config[0].raw_config` is TOKEN-based and DO expires
  it (~7 days) — unlike the long-lived client-cert kubeconfig `cluster-k3s` writes.
  The written `./kubeconfig` is fine for the one-shot `bootstrap.sh` right after
  apply; for ongoing use refresh it with `doctl kubernetes cluster kubeconfig save <cluster_name>`.
  So the `kubeconfig` output matches the k3s CONTRACT (same field) but not its lifetime.
- No SSH/cloud-init/k3s bootstrap — the control plane is managed. There is no
  `api_allowed_cidrs` equivalent (the API endpoint is public with cert auth);
  private admin access is via the Tailscale API-server proxy (D-09).
- Backups: use DO **Spaces** (S3-compatible) or Cloudflare R2 for CNPG
  `barmanObjectStore` — both are just an S3 endpoint + creds.
- GPU: set `gpu_node_size` (e.g. `gpu-h100x1-80gb`) to add a tainted GPU pool.
- Follow-ups: node-pool autoscaling (`auto_scale`/`min`/`max`), DO Managed
  Postgres wiring for `db_source = do-managed`.
