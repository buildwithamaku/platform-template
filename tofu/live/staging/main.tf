module "cluster" {
  source = "../../modules/cluster-k3s"

  cluster_name = "refclient-staging"
  location     = "nbg1"

  # Staging is intentionally small: single node, no HA. Prod uses server_count = 3.
  # NOTE: nbg1 does not offer the Intel CX line — use the AMD CPX equivalent
  # (cpx22 = 2 vCPU / 4 GB, same specs as cx22). CX types would need fsn1/hel1.
  server_count = 1
  server_type  = "cpx22"

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
