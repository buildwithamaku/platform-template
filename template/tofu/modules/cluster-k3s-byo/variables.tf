# Bring-your-own-nodes k3s (cloud = baremetal). Provisioning is NOT done here —
# you create the nodes on any host (InterServer, OVH, Vultr, on-prem, ...) and
# give this module their SSH-reachable IPs. It installs k3s over SSH and returns a
# kubeconfig, matching the output contract of cluster-k3s / cluster-doks. With no
# cloud load balancer, k3s's built-in ServiceLB (klipper) fulfils the ingress
# LoadBalancer on the node IP, and PVCs bind k3s's built-in local-path StorageClass.

variable "cluster_name" {
  type        = string
  description = "Cluster name (labels + kubeconfig filename)."
}

variable "control_plane_ip" {
  type        = string
  description = "Public IP of the pre-provisioned control-plane node (SSH-reachable as ssh_user). It is the API server; losing it takes cluster control down until restored (single-CP topology)."
}

variable "agent_ips" {
  type        = list(string)
  default     = []
  description = "Public IPs of pre-provisioned agent nodes. Empty = single-node cluster. Nodes must reach each other on 6443/tcp and 8472/udp (flannel vxlan)."
}

variable "ssh_user" {
  type        = string
  default     = "root"
  description = "SSH user with root (the install runs apt-get + the k3s installer)."
}

variable "ssh_private_key_path" {
  type        = string
  description = "Path to the private key that logs into every node as ssh_user."
}

variable "k3s_version" {
  type        = string
  default     = "v1.31.5+k3s1"
  description = "Pinned k3s version (INSTALL_K3S_VERSION)."
}

variable "api_tls_sans" {
  type        = list(string)
  default     = []
  description = "Extra SANs for the API server cert (e.g. a DNS name). The control-plane IP is always included."
}

variable "labels" {
  type        = map(string)
  default     = {}
  description = "Free-form labels (recorded for parity; not applied to a cloud API here)."
}
