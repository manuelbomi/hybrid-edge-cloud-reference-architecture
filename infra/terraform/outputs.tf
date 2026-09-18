output "alb_dns_name" {
  description = "Public DNS name of the ingest API load balancer."
  value       = aws_lb.ingest.dns_name
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster running the ingest API."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "Name of the ECS service running the ingest API."
  value       = aws_ecs_service.ingest_api.name
}

output "db_endpoint" {
  description = "Connection endpoint of the RDS instance (host:port)."
  value       = aws_db_instance.ingest.endpoint
  sensitive   = true
}
