# Testing the baremetal / bring-your-own-nodes path (InterServer & co.)

The `cloud=baremetal` path (`modules/cluster-k3s-byo`) installs k3s over SSH onto
nodes you provision yourself. This is how we gain confidence in it, from the checks
that run today to the live end-to-end run that only real nodes can prove.

## What is already proven (static — CI + local, no nodes)
`template-ci` and the local suite validate everything that doesn't require a running
host. All green today:

| Check | Proves |
|---|---|
| `copier` render of `examples/baremetal.copier-answers.yml` | the questionnaire flows for `cloud=baremetal`; region/node-sizing are correctly not asked yet still resolve for any reference |
| no stale `{{ copier-var }}`, no unrendered `[< >]` tokens | the template converted cleanly |
| `tofu validate` (baremetal staging + prod) | the `cluster-k3s-byo` module refs, provider set (null/random/local), variables and outputs all resolve; the live root is wired to outputs the module actually exposes |
| `tofu validate` (hetzner + DO unchanged) | no regression from the `elif baremetal` branches |
| `kubeconform` (baremetal manifests) | the rendered manifests are valid k8s; Hetzner LB annotations correctly absent |
| `templatefile` render of `k3s-install-byo.sh.tftpl` + `bash -n` (server & agent) | the generated install scripts are syntactically valid bash and emit a correct k3s `config.yaml` (klipper kept, only traefik disabled, tls-san populated, agent join + wait-loop) |

**What static checks CANNOT prove:** that k3s actually installs over SSH, that klipper
fulfils the ingress LoadBalancer on the node IP, that `local-path` binds PVCs, that
Argo reconciles the full platform, and that DNS/TLS/ingress serve. Those need a host.
(Same posture as the Hetzner/DO paths, whose live join was likewise deferred to a real cluster.)

## Cheap first test: ANY Debian box (not yet InterServer)
The baremetal path is **provider-agnostic**, so the *mechanism* can be proven on any
SSH-reachable Debian/Ubuntu host — a local VM (multipass/UTM), a throwaway $5 Vultr,
or even a spare Hetzner Cloud VM used as a "baremetal" node. Do this first; it
de-risks everything except InterServer's own networking.

## Phase 1 — single-node staging smoke (the core integration test)
Provision **one** node, run the real apply, and confirm the substitutions for the
cloud freebies actually work.

1. **Provision** 1 VPS (Debian 12/Ubuntu 22.04+), root SSH with your key. Open
   `80,443` publicly and `22,6443` to your IP. (InterServer: a cloud VPS from the panel.)
2. **Render** a test client: `copier copy --data-file examples/baremetal.copier-answers.yml ... byo-test`.
3. **tfvars**: in `tofu/live/staging`, set `control_plane_ip`, `agent_ips=[]`, `ssh_private_key_path`.
4. **Apply**: `tofu init && tofu apply` → assert: SSH connects, script uploads, k3s installs, `./kubeconfig` is written.
5. `KUBECONFIG=./kubeconfig kubectl get nodes` → **1 Ready node**.
6. **klipper** (the CCM-LB replacement): after ingress installs, `kubectl -n ingress get svc`
   → the ingress-nginx Service shows `EXTERNAL-IP = node IP`; `kubectl -n kube-system get ds | grep svclb`.
7. **local-path** (the CSI replacement): `kubectl get sc` → `local-path (default)`.
8. **Bootstrap**: populate Infisical, run `./bootstrap.sh` → Argo CD installs and syncs.
9. **Reconcile**: `kubectl -n argocd get applications` → all **Synced/Healthy**; CNPG cluster
   comes up with its PVC bound on local-path; valkey, loki, cert-manager, external-dns, tailscale up.
10. **DNS + TLS**: point `app`/`api` A records at the node IP (or a wildcard); confirm cert-manager
    issues (LE-staging on staging) and the app URL serves over TLS.
11. **App acceptance**: deploy the reference/test backend → PreSync migration runs, pod Ready,
    ingress serves; if `same_origin_api`, confirm `app.<domain>/api` reaches the backend; if
    `cap_db_app_role`, confirm a runtime write works under RLS.

**Exit criteria:** every Argo app Healthy, the app reachable over HTTPS on the node IP, a DB
write succeeds.

## Phase 2 — multi-node (agent join)
Add ≥1 agent VPS, set `agent_ips=[...]`, `tofu apply`. Assert: the agent reaches Ready, a pod
scheduled on the agent reaches a Service on the control plane (flannel vxlan over `8472/udp`).
This is where the inter-node port requirement is exercised.

## Phase 3 — failure / caveat verification (turn documented caveats into tests)
- **Block `8472/udp`** between nodes → agent join fails: proves the documented port requirement.
- **Stop the control-plane node** → API/control is down (single-CP = no HA): proves the caveat; restore and confirm recovery.
- **Reschedule a PVC-bound pod** → `local-path` volume stays node-local: proves the node-locality caveat (and that CNPG PITR-to-R2, not local-path, is the real durability story).

## Phase 4 — teardown
`tofu destroy` is largely a **no-op** for BYO (the nodes aren't tofu-managed) — you must
**delete the VPS on InterServer's panel** yourself (analogous to the Hetzner orphan-LB
gotcha). To reuse a node, run `/usr/local/bin/k3s-uninstall.sh` (server) or
`k3s-agent-uninstall.sh` (agent) first.

## InterServer-specific things to confirm (beyond the generic mechanism)
Once Phase 1 passes on a generic box, the only InterServer-specific unknowns are:
- Their VPS ships **root SSH** (or a sudo user — set `ssh_user`).
- **Public IPv4** is directly bound to the node (not behind a NAT/proxy that hides it).
- Their firewall/panel lets you open `80/443` (+ inter-node ports for multi-node).
- Egress to `get.k3s.io`, `ghcr.io`, and Cloudflare works from the node.

## Future: automate it
A gated CI job that provisions an ephemeral Debian VM (any provider with an API),
runs apply → bootstrap → the Phase-1 acceptance checks → destroy, would make this a
true end-to-end gate. Until then: the static gates above run on every PR, and a
documented manual Phase-1 run is the sign-off for the baremetal path.
