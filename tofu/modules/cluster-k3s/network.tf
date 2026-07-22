locals {
  # Hetzner network zone is derived from the location.
  network_zone = {
    nbg1 = "eu-central"
    fsn1 = "eu-central"
    hel1 = "eu-central"
    ash  = "us-east"
    hil  = "us-west"
    sin  = "ap-southeast"
  }[var.location]

  common_labels = merge(var.labels, {
    cluster    = var.cluster_name
    managed_by = "opentofu"
  })
}

resource "hcloud_network" "this" {
  name     = var.cluster_name
  ip_range = var.network_cidr
  labels   = local.common_labels
}

resource "hcloud_network_subnet" "this" {
  network_id   = hcloud_network.this.id
  type         = "cloud"
  network_zone = local.network_zone
  ip_range     = var.subnet_cidr
}
