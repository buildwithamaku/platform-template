# cluster-k3s-byo — bring-your-own-nodes k3s (cloud = baremetal)

Installs k3s over SSH onto nodes **you** provisioned (InterServer, OVH, Vultr,
on-prem — anywhere), when there is no cloud API/provider to create them. It is the
provider-agnostic sibling of `cluster-k3s` (Hetzner) and `cluster-doks` (DOKS), and
returns the same `kubeconfig` / `api_endpoint` / `server_public_ips` outputs.

## What it does
- `control_plane_ip` → installs a k3s **server** (the API server; single-CP topology).
- each `agent_ips[*]` → installs a k3s **agent** that joins the server.
- fetches + rewrites the kubeconfig to the control-plane public IP.

## What it deliberately does NOT do (vs the Hetzner module)
| Hetzner gave it | Here |
|---|---|
| cloud LB for the API | none — the control-plane IP is the endpoint (single CP) |
| CCM ingress LoadBalancer | **klipper** (k3s ServiceLB) fulfils it on the node IP |
| cloud block-storage CSI | **local-path** (k3s built-in) is the default StorageClass |
| cloud firewall / private net | your host firewall; flannel over the node IPs |

## Node prerequisites (yours to provision)
- A recent Debian/Ubuntu VPS/dedicated host, **root over SSH** with the key at
  `ssh_private_key_path`.
- Open between nodes: `6443/tcp` (API), `8472/udp` (flannel vxlan), `10250/tcp`
  (kubelet). Public: `80`/`443` on whichever node(s) DNS points at.
- A single node (no `agent_ips`) needs no inter-node ports.

## Caveats
- **Single control-plane** = no API HA; losing that node takes cluster control down
  until restored (data on `local-path` is node-local — back it up: CNPG PITR still
  applies to the app DB).
- Multi-node flannel uses **vxlan (unencrypted)** over the node network. If nodes
  cross the public internet, front them with a private network or switch to
  `flannel-backend: wireguard-native`.
