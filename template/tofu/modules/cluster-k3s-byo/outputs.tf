output "kubeconfig" {
  description = "kubeconfig for the cluster, pointed at the control-plane public IP."
  value       = data.local_file.kubeconfig.content
  sensitive   = true
}

output "api_endpoint" {
  description = "k3s API endpoint (the control-plane public IP)."
  value       = "https://${var.control_plane_ip}:6443"
}

output "server_public_ips" {
  description = "Public IPv4 of every node (control plane first, then agents)."
  value       = concat([var.control_plane_ip], var.agent_ips)
}
