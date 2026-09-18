variable "aws_region" {
  description = "AWS region to deploy the cloud ingestion stack into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used as a prefix for all resource names/tags."
  type        = string
  default     = "hybrid-edge-cloud-demo"
}

variable "environment" {
  description = "Deployment environment name, e.g. dev/staging/production."
  type        = string
  default     = "dev"
}

variable "vpc_id" {
  description = "VPC to deploy into. Placeholder value -- replace with a real VPC id before use."
  type        = string
  default     = "vpc-REPLACE_ME"
}

variable "public_subnet_ids" {
  description = "Public subnet ids for the load balancer. Placeholder values -- replace before use."
  type        = list(string)
  default     = ["subnet-REPLACE_ME_a", "subnet-REPLACE_ME_b"]
}

variable "private_subnet_ids" {
  description = "Private subnet ids for the ECS tasks and the database. Placeholder values -- replace before use."
  type        = list(string)
  default     = ["subnet-REPLACE_ME_c", "subnet-REPLACE_ME_d"]
}

variable "container_image" {
  description = "Container image for the ingest API, e.g. <account>.dkr.ecr.<region>.amazonaws.com/ingest-api:latest."
  type        = string
  default     = "REPLACE_ME/ingest-api:latest"
}

variable "container_port" {
  description = "Port the ingest API container listens on."
  type        = number
  default     = 8080
}

variable "desired_count" {
  description = "Number of Fargate task replicas to run for the ingest API."
  type        = number
  default     = 2
}

variable "task_cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 512
}

variable "db_engine_version" {
  description = "PostgreSQL engine version for the RDS instance."
  type        = string
  default     = "16.3"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "Name of the application database created on the RDS instance."
  type        = string
  default     = "ingest"
}

variable "db_username" {
  description = "Master username for the RDS instance."
  type        = string
  default     = "ingest_app"
}

variable "db_password" {
  description = "Master password for the RDS instance. In real use, source this from a secrets manager, never a plain tfvars file committed to version control."
  type        = string
  sensitive   = true
  default     = "REPLACE_ME_use_a_secrets_manager"
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default = {
    Project = "hybrid-edge-cloud-reference-architecture"
    Purpose = "illustrative-reference"
  }
}
