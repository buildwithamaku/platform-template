# State is stored in an S3-compatible bucket (Hetzner Object Storage or AWS S3).
# Partial config: real values live in backend.hcl (git-ignored) and are supplied
# with `tofu init -backend-config=backend.hcl`.
#
# For a first local smoke test you may comment this whole block out to use the
# default local backend, then migrate state once the bucket exists.
terraform {
  backend "s3" {
    key = "refclient/prod/terraform.tfstate"

    # Hetzner Object Storage is not AWS, so skip the AWS-specific preflight checks.
    region                      = "eu-central-1"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    use_path_style              = true
  }
}
