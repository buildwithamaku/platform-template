# The module generates its own key pair, used non-interactively to fetch the
# kubeconfig from server-1. The private key lands in state (encrypted at rest in
# the backend) and is written locally for the kubeconfig scp — treat it as
# break-glass only; day-to-day access is via kubeconfig + Tailscale (Phase 3).
resource "tls_private_key" "provisioner" {
  algorithm = "ED25519"
}

resource "local_sensitive_file" "provisioner_key" {
  content         = tls_private_key.provisioner.private_key_openssh
  filename        = "${path.root}/.gen/${var.cluster_name}-ssh"
  file_permission = "0600"
}

resource "hcloud_ssh_key" "provisioner" {
  name       = "${var.cluster_name}-provisioner"
  public_key = tls_private_key.provisioner.public_key_openssh
  labels     = local.common_labels
}

resource "hcloud_ssh_key" "extra" {
  for_each = { for idx, key in var.ssh_public_keys : idx => key }

  name       = "${var.cluster_name}-extra-${each.key}"
  public_key = each.value
  labels     = local.common_labels
}
