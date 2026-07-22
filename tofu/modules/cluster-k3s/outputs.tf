output "kubeconfig" {
  description = "kubeconfig for the cluster, pointed at the API load balancer."
  value       = data.local_file.kubeconfig.content
  sensitive   = true
}

output "api_endpoint" {
  description = "Public k3s API endpoint (via the load balancer)."
  value       = "https://${hcloud_load_balancer.api.ipv4}:6443"
}

output "network_id" {
  description = "ID of the private network (consumed by hcloud-ccm and later modules)."
  value       = hcloud_network.this.id
}

output "server_public_ips" {
  description = "Public IPv4 of each server node."
  value       = hcloud_server.nodes[*].ipv4_address
}

output "server_private_ips" {
  description = "Private IPv4 of each server node."
  value       = [for i in range(var.server_count) : cidrhost(var.subnet_cidr, 10 + i)]
}

output "ssh_private_key" {
  description = "Break-glass SSH private key generated for the cluster."
  value       = tls_private_key.provisioner.private_key_openssh
  sensitive   = true
}
