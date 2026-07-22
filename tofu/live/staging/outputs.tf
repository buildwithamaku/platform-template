output "api_endpoint" {
  description = "k3s API endpoint."
  value       = module.cluster.api_endpoint
}

output "server_public_ips" {
  description = "Public IPv4 of the server node(s)."
  value       = module.cluster.server_public_ips
}

output "kubeconfig_path" {
  description = "Local path to the written kubeconfig."
  value       = local_sensitive_file.kubeconfig.filename
}
