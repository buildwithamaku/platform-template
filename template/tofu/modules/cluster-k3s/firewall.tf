# Hetzner Cloud firewalls filter the PUBLIC interface only. Node-to-node traffic
# over the private network (flannel, etcd, kubelet, LB->target) is not filtered
# here, so we only need to allow public SSH + the k3s API from trusted CIDRs.
resource "hcloud_firewall" "this" {
  name   = var.cluster_name
  labels = local.common_labels

  rule {
    description = "SSH (break-glass + kubeconfig fetch)"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.api_allowed_cidrs
  }

  rule {
    description = "k3s API server"
    direction   = "in"
    protocol    = "tcp"
    port        = "6443"
    source_ips  = var.api_allowed_cidrs
  }

  rule {
    description = "ICMP (ping / path-MTU)"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = var.api_allowed_cidrs
  }

  # No "out" rules => all egress allowed (k3s needs to pull the installer + images).
}
