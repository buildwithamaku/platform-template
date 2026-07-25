output "kubeconfig" {
  description = "Raw kubeconfig (matches the cluster-k3s output contract, so live roots are symmetric)."
  value       = digitalocean_kubernetes_cluster.this.kube_config[0].raw_config
  sensitive   = true
}

output "endpoint" {
  value = digitalocean_kubernetes_cluster.this.endpoint
}

output "cluster_id" {
  value = digitalocean_kubernetes_cluster.this.id
}
