# Fetch the kubeconfig the control plane wrote (write-kubeconfig-mode 0644) and
# rewrite its server URL from the node-local 127.0.0.1 to the control-plane public
# IP, so it works from the machine running OpenTofu. Mirrors cluster-k3s. The .gen
# dir is git-ignored (**/.gen/) so the admin kubeconfig never lands in the repo.
resource "null_resource" "fetch_kubeconfig" {
  depends_on = [null_resource.control_plane]

  triggers = {
    cp = var.control_plane_ip
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -eu
      mkdir -p "${path.module}/.gen"
      scp -o StrictHostKeyChecking=accept-new -i "${var.ssh_private_key_path}" \
        "${var.ssh_user}@${var.control_plane_ip}:/etc/rancher/k3s/k3s.yaml" \
        "${path.module}/.gen/kubeconfig-${var.cluster_name}"
      sed -i.bak 's#https://127.0.0.1:6443#https://${var.control_plane_ip}:6443#' \
        "${path.module}/.gen/kubeconfig-${var.cluster_name}"
    EOT
  }
}

data "local_file" "kubeconfig" {
  depends_on = [null_resource.fetch_kubeconfig]
  filename   = "${path.module}/.gen/kubeconfig-${var.cluster_name}"
}
