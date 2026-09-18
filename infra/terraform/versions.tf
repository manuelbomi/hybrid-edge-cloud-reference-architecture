# ---------------------------------------------------------------------------
# ILLUSTRATIVE REFERENCE MODULE -- NOT TIED TO ANY SPECIFIC CLOUD ACCOUNT.
#
# This Terraform is meant to be read, not `terraform apply`-ed as-is. It shows
# one reasonable shape for the cloud side of this architecture (a container
# service behind a load balancer, with a managed relational database), using
# only generic, made-up names -- no real account IDs, no real domain names,
# no real customer data.
#
# Before this could be used against a real AWS account you would need to, at
# minimum:
#   - Configure a real backend for remote state (see the commented `backend`
#     block below) instead of local state.
#   - Fill in real values for every variable in variables.tf (VPC/subnet ids,
#     desired instance sizes, etc.) via a tfvars file or CI-injected variables.
#   - Review the security group rules and IAM permissions for your own
#     environment's security requirements.
#   - Point `container_image` at a real image in a real registry.
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Illustrative only -- local state is used by default so `terraform validate`
  # works with no setup. Before real use, configure a real backend, e.g.:
  #
  # backend "s3" {
  #   bucket         = "REPLACE_ME-terraform-state"
  #   key            = "hybrid-edge-cloud/cloud-ingest/terraform.tfstate"
  #   region         = "REPLACE_ME-region"
  #   dynamodb_table = "REPLACE_ME-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
