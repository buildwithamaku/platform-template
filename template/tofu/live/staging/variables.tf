variable "hcloud_token" {
  type        = string
  sensitive   = true
  description = "Hetzner Cloud API token. Supply via TF_VAR_hcloud_token or a git-ignored *.tfvars."
}

variable "ssh_public_keys" {
  type        = list(string)
  default     = []
  description = "Break-glass SSH public keys for engineers."
}

variable "api_allowed_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the k3s API + SSH. Phase 1: your public IP (e.g. \"203.0.113.7/32\") and the CI egress range."
}
