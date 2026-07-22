module "cluster" {
  source = "../../modules/cluster-k3s"

  cluster_name = "refclient-staging"
  location     = "nbg1"

  # Staging is intentionally small: single node, no HA. Prod uses server_count = 3.
  server_count = 1
  server_type  = "cx22"

  ssh_public_keys   = var.ssh_public_keys
  api_allowed_cidrs = var.api_allowed_cidrs

  labels = {
    environment = "staging"
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
