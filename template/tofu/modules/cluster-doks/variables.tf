variable "do_token" {
  type        = string
  sensitive   = true
  description = "DigitalOcean API token. Also used by the built-in DO CCM/CSI for LBs + volumes."
}

variable "cluster_name" {
  type = string
}

variable "region" {
  type        = string
  default     = "fra1"
  description = "DO region: fra1 (Frankfurt), ams3, lon1, nyc1/nyc3, sfo3, sgp1, syd1, ..."
}

variable "k8s_version_prefix" {
  type        = string
  default     = "1.31."
  description = "The latest DOKS version matching this prefix is selected."
}

variable "node_size" {
  type        = string
  default     = "s-2vcpu-4gb"
  description = "Default node-pool droplet size (s-2vcpu-4gb, s-4vcpu-8gb, s-8vcpu-16gb, ...). Use >= 8GB with Metabase."
}

variable "node_count" {
  type    = number
  default = 3
}

variable "gpu_node_size" {
  type        = string
  default     = ""
  description = "If set, add a 1-node GPU pool (e.g. gpu-h100x1-80gb), tainted nvidia.com/gpu. Empty = no GPU pool."
}

variable "ha_control_plane" {
  type        = bool
  default     = true
  description = "DOKS HA control plane (recommended for prod)."
}

variable "labels" {
  type    = map(string)
  default = {}
}
