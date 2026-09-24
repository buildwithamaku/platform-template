# A shared cluster token, generated once and planted on every node.
resource "random_password" "k3s_token" {
  length  = 48
  special = false
}

locals {
  # Both calls pass the full var set so templatefile never hits a missing-var
  # error regardless of which %{ if } branch renders.
  server_script = templatefile("${path.module}/templates/k3s-install-byo.sh.tftpl", {
    is_server   = true
    k3s_token   = random_password.k3s_token.result
    k3s_version = var.k3s_version
    node_ip     = var.control_plane_ip
    server_ip   = var.control_plane_ip
    tls_sans    = distinct(concat([var.control_plane_ip], var.api_tls_sans))
  })
}

# ── control plane: install k3s server over SSH ───────────────────────────────
resource "null_resource" "control_plane" {
  triggers = {
    ip     = var.control_plane_ip
    script = sha1(local.server_script)
  }

  connection {
    type        = "ssh"
    host        = var.control_plane_ip
    user        = var.ssh_user
    private_key = file(var.ssh_private_key_path)
  }

  provisioner "file" {
    content     = local.server_script
    destination = "/tmp/k3s-install.sh"
  }

  provisioner "remote-exec" {
    inline = ["chmod +x /tmp/k3s-install.sh", "/tmp/k3s-install.sh"]
  }
}

# ── agents: install k3s agent over SSH, joining the control plane ─────────────
resource "null_resource" "agents" {
  count = length(var.agent_ips)

  triggers = {
    ip     = var.agent_ips[count.index]
    server = var.control_plane_ip
  }

  depends_on = [null_resource.control_plane]

  connection {
    type        = "ssh"
    host        = var.agent_ips[count.index]
    user        = var.ssh_user
    private_key = file(var.ssh_private_key_path)
  }

  provisioner "file" {
    content = templatefile("${path.module}/templates/k3s-install-byo.sh.tftpl", {
      is_server   = false
      k3s_token   = random_password.k3s_token.result
      k3s_version = var.k3s_version
      node_ip     = var.agent_ips[count.index]
      server_ip   = var.control_plane_ip
      tls_sans    = []
    })
    destination = "/tmp/k3s-install.sh"
  }

  provisioner "remote-exec" {
    inline = ["chmod +x /tmp/k3s-install.sh", "/tmp/k3s-install.sh"]
  }
}
