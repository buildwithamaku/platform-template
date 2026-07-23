variable "cluster_name" {
  type        = string
  description = "Cluster name, e.g. \"refclient-staging\". Prefixes every resource and is used as the Hetzner label selector value."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", var.cluster_name))
    error_message = "cluster_name must be lower-case alphanumeric with hyphens, 3-32 chars."
  }
}

variable "location" {
  type        = string
  default     = "nbg1"
  description = "Hetzner location: nbg1/fsn1/hel1 (EU), ash (US East), hil (US West), sin (Singapore)."
}

variable "server_count" {
  type        = number
  default     = 3
  description = "Number of k3s server (control-plane) nodes. 1 = single-node (dev/staging), 3/5 = HA embedded-etcd."

  validation {
    condition     = contains([1, 3, 5], var.server_count)
    error_message = "server_count must be 1, 3, or 5 (odd, for embedded-etcd quorum)."
  }
}

variable "server_type" {
  type        = string
  default     = "cpx32"
  description = "Hetzner server type. AMD CPX line (cpx22 2vCPU/4GB, cpx32 4vCPU/8GB) works in all EU locations incl. nbg1; the Intel CX line is NOT sold in nbg1. cax* for ARM (needs an arm64 image)."
}

variable "image" {
  type        = string
  default     = "ubuntu-24.04"
  description = "OS image. Must match the server_type architecture (x86 for cx*, arm for cax*)."
}

variable "k3s_version" {
  type        = string
  default     = "v1.31.4+k3s1"
  description = "Pinned k3s version. Upgrades are deliberate (see decision D-02); bump here and roll staging first."
}

variable "network_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "Private network range for the cluster."
}

variable "subnet_cidr" {
  type        = string
  default     = "10.0.1.0/24"
  description = "Subnet the nodes attach to. Node N gets the static private IP cidrhost(subnet_cidr, 10 + N)."
}

variable "ssh_public_keys" {
  type        = list(string)
  default     = []
  description = "Additional SSH public keys authorized on nodes for break-glass access. The module also generates its own key pair used to fetch the kubeconfig."
}

variable "api_allowed_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the k3s API (6443) and SSH (22) on the public interface. Phase 1: the operator's IP + CI. Phase 3: replaced by the Tailscale range."

  validation {
    condition     = length(var.api_allowed_cidrs) > 0
    error_message = "Provide at least one CIDR (e.g. \"1.2.3.4/32\"). Never use 0.0.0.0/0 for the API."
  }
}

variable "labels" {
  type        = map(string)
  default     = {}
  description = "Extra Hetzner labels applied to all resources. Keys must be alnum/-/_ (no slashes)."
}

variable "hcloud_token" {
  type        = string
  sensitive   = true
  description = "Hetzner Cloud API token. Passed to the init node so k3s can plant the `hcloud` Secret that hcloud-cloud-controller-manager uses. Same token you give the provider."
}

variable "install_hcloud_ccm" {
  type        = bool
  default     = true
  description = "Install hcloud-cloud-controller-manager at cluster bring-up so `type: LoadBalancer` Services get real Hetzner LBs (needed for ingress). When true, k3s runs with the external cloud provider; nodes stay tainted `uninitialized` until the CCM initializes them, so do NOT set true without the CCM."
}

variable "hcloud_ccm_version" {
  type        = string
  default     = "v1.34.0"
  description = "Pinned hcloud-cloud-controller-manager release. The network-aware ccm-networks.yaml is deployed so LoadBalancers target nodes by private IP. Its route controller is enabled by default: harmless on single-node staging, but on multi-node prod it overlaps flannel — disable CCM routes or adjust flannel-backend there."
}
