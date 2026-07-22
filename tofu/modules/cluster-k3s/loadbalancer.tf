# Load balancer fronting the k3s API (6443). It gives us:
#   1. a stable registration endpoint for joining servers (HA pattern), and
#   2. a stable kube-apiserver endpoint for kubectl once >1 server exists.
# The public ingress LB for application traffic is created later by hcloud-ccm
# (Phase 3), not here.
resource "hcloud_load_balancer" "api" {
  name               = "${var.cluster_name}-api"
  load_balancer_type = "lb11"
  location           = var.location
  labels             = local.common_labels
}

resource "hcloud_load_balancer_network" "api" {
  load_balancer_id = hcloud_load_balancer.api.id
  network_id       = hcloud_network.this.id

  depends_on = [hcloud_network_subnet.this]
}

# Targets are selected by label, so servers are added/removed automatically as
# they come up. use_private_ip keeps API traffic on the private network.
resource "hcloud_load_balancer_target" "servers" {
  type             = "label_selector"
  load_balancer_id = hcloud_load_balancer.api.id
  label_selector   = "cluster=${var.cluster_name},role=server"
  use_private_ip   = true

  depends_on = [hcloud_load_balancer_network.api]
}

resource "hcloud_load_balancer_service" "api" {
  load_balancer_id = hcloud_load_balancer.api.id
  protocol         = "tcp"
  listen_port      = 6443
  destination_port = 6443

  health_check {
    protocol = "tcp"
    port     = 6443
    interval = 10
    timeout  = 5
    retries  = 3
  }
}
