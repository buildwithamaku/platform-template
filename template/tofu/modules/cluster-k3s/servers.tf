resource "random_password" "k3s_token" {
  length  = 48
  special = false
}

# Spread nodes across distinct physical hosts so a single hardware failure can't
# take down etcd quorum.
resource "hcloud_placement_group" "this" {
  name   = var.cluster_name
  type   = "spread"
  labels = local.common_labels
}

resource "hcloud_server" "nodes" {
  count = var.server_count

  name               = "${var.cluster_name}-server-${count.index + 1}"
  server_type        = var.server_type
  image              = var.image
  location           = var.location
  placement_group_id = hcloud_placement_group.this.id
  firewall_ids       = [hcloud_firewall.this.id]

  ssh_keys = concat(
    [hcloud_ssh_key.provisioner.name],
    [for key in hcloud_ssh_key.extra : key.name],
  )

  # role=server is what the API load balancer's label selector matches on.
  labels = merge(local.common_labels, { role = "server" })

  network {
    network_id = hcloud_network.this.id
    ip         = cidrhost(var.subnet_cidr, 10 + count.index)
  }

  user_data = templatefile("${path.module}/templates/k3s-install.sh.tftpl", {
    node_ip            = cidrhost(var.subnet_cidr, 10 + count.index)
    k3s_token          = random_password.k3s_token.result
    k3s_version        = var.k3s_version
    api_lb_ip          = hcloud_load_balancer.api.ipv4
    is_init            = count.index == 0
    install_hcloud_ccm = var.install_hcloud_ccm
    hcloud_token       = var.hcloud_token
    hcloud_ccm_version = var.hcloud_ccm_version
    network_name       = hcloud_network.this.name
  })

  depends_on = [hcloud_network_subnet.this]
}
