module "cluster" {
  source = "../../modules/cluster-k3s"

  cluster_name = "refclient-prod"
  location     = "nbg1"

  # Prod is HA: 3 servers with embedded-etcd quorum (decision D-02).
  server_count = 3
  server_type  = "cx32"

  ssh_public_keys   = var.ssh_public_keys
  api_allowed_cidrs = var.api_allowed_cidrs

  labels = {
    environment = "prod"
    part_of     = "refclient"
  }
}

# Write the kubeconfig next to the root so the acceptance test is a one-liner:
#   export KUBECONFIG=$PWD/kubeconfig && kubectl get nodes
resource "local_sensitive_file" "kubeconfig" {
  content         = module.cluster.kubeconfig
  filename        = "${path.module}/kubeconfig"
  file_permission = "0600"
}
