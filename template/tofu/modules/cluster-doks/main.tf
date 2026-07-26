# DOKS — managed control plane + node pools (the managed-cloud variant, vs the
# self-managed cluster-k3s on Hetzner). DO runs the control plane; we manage node
# pools + VPC. The DO cloud-controller-manager and CSI are built into DOKS, so
# ingress-nginx (type: LoadBalancer) gets a DO Load Balancer and CNPG PVCs bind to
# the default do-block-storage StorageClass — no extra wiring vs Hetzner. Outputs
# `kubeconfig` to match the cluster-k3s contract, so the live roots are symmetric.
data "digitalocean_kubernetes_versions" "this" {
  version_prefix = var.k8s_version_prefix
}

resource "digitalocean_vpc" "this" {
  name   = "${var.cluster_name}-vpc"
  region = var.region
}

resource "digitalocean_kubernetes_cluster" "this" {
  name         = var.cluster_name
  region       = var.region
  version      = data.digitalocean_kubernetes_versions.this.latest_version
  vpc_uuid     = digitalocean_vpc.this.id
  ha           = var.ha_control_plane
  auto_upgrade = false
  tags         = [for k, v in var.labels : "${k}:${v}"]

  node_pool {
    name       = "${var.cluster_name}-default"
    size       = var.node_size
    node_count = var.node_count
  }
}

# Optional GPU node pool for AI workloads (tainted so only GPU pods land there).
resource "digitalocean_kubernetes_node_pool" "gpu" {
  count      = var.gpu_node_size == "" ? 0 : 1
  cluster_id = digitalocean_kubernetes_cluster.this.id
  name       = "${var.cluster_name}-gpu"
  size       = var.gpu_node_size
  node_count = 1
  labels     = { gpu = "true" }

  taint {
    key    = "nvidia.com/gpu"
    value  = "present"
    effect = "NoSchedule"
  }
}
