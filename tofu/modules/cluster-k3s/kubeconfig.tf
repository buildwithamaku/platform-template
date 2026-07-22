# Fetch the kubeconfig from server-1 once its API is ready, and rewrite the
# server URL from 127.0.0.1 to the API load balancer so it works from anywhere
# in api_allowed_cidrs. Runs on the machine executing OpenTofu (laptop or CI
# runner), which therefore needs ssh/scp and network access to the node.
resource "null_resource" "kubeconfig" {
  triggers = {
    server_id = hcloud_server.nodes[0].id
    lb_ip     = hcloud_load_balancer.api.ipv4
  }

  connection {
    type        = "ssh"
    host        = hcloud_server.nodes[0].ipv4_address
    user        = "root"
    private_key = tls_private_key.provisioner.private_key_openssh
    timeout     = "5m"
  }

  # Block until k3s has written the kubeconfig and the API reports ready.
  provisioner "remote-exec" {
    inline = [
      "until test -f /etc/rancher/k3s/k3s.yaml; do sleep 3; done",
      "until k3s kubectl get --raw='/readyz' >/dev/null 2>&1; do sleep 3; done",
    ]
  }

  # scp the file down and point it at the LB. sed -i.bak is portable (GNU + BSD).
  provisioner "local-exec" {
    command = <<-EOT
      install -d -m 700 "${path.root}/.gen"
      scp -i "${local_sensitive_file.provisioner_key.filename}" \
        -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        root@${hcloud_server.nodes[0].ipv4_address}:/etc/rancher/k3s/k3s.yaml \
        "${path.root}/.gen/kubeconfig-${var.cluster_name}.yaml"
      sed -i.bak 's#https://127.0.0.1:6443#https://${hcloud_load_balancer.api.ipv4}:6443#' \
        "${path.root}/.gen/kubeconfig-${var.cluster_name}.yaml"
      rm -f "${path.root}/.gen/kubeconfig-${var.cluster_name}.yaml.bak"
    EOT
  }

  depends_on = [
    hcloud_load_balancer_service.api,
    hcloud_load_balancer_target.servers,
  ]
}

data "local_file" "kubeconfig" {
  filename   = "${path.root}/.gen/kubeconfig-${var.cluster_name}.yaml"
  depends_on = [null_resource.kubeconfig]
}
