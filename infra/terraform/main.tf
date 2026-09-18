# ---------------------------------------------------------------------------
# Illustrative cloud-side infrastructure for the ingest API:
#   Application Load Balancer -> ECS Fargate service (cloud/ingest_api.py) -> RDS
#
# This mirrors the shape of cloud/ingest_api.py in this repo (a small HTTP API
# backed by a relational database) but at production cloud scale, swapping
# SQLite for a managed Postgres instance and running the API as a
# horizontally-scaled Fargate service behind a load balancer.
#
# See versions.tf for backend/state caveats and variables.tf for every input.
# ---------------------------------------------------------------------------

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# -----------------------------------------------------------------------
# Security groups
# -----------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Allow inbound HTTPS/HTTP to the ingest API load balancer"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from anywhere (redirected to HTTPS in production)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name_prefix}-alb-sg" })
}

resource "aws_security_group" "service" {
  name        = "${local.name_prefix}-service-sg"
  description = "Allow inbound traffic from the ALB to the ingest API tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "From ALB only"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name_prefix}-service-sg" })
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db-sg"
  description = "Allow inbound Postgres traffic from the ingest API tasks only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from ingest API tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name_prefix}-db-sg" })
}

# -----------------------------------------------------------------------
# Load balancer
# -----------------------------------------------------------------------

resource "aws_lb" "ingest" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  tags = merge(var.tags, { Name = "${local.name_prefix}-alb" })
}

resource "aws_lb_target_group" "ingest" {
  name        = "${local.name_prefix}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200"
  }

  tags = merge(var.tags, { Name = "${local.name_prefix}-tg" })
}

# NOTE: illustrative HTTP listener only. A real deployment terminates TLS
# here with an ACM certificate and a 443 listener, and redirects 80 -> 443.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.ingest.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ingest.arn
  }
}

# -----------------------------------------------------------------------
# ECS Fargate service running cloud/ingest_api.py
# -----------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = "${local.name_prefix}-cluster"
  tags = var.tags
}

resource "aws_iam_role" "task_execution" {
  name = "${local.name_prefix}-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ecs-tasks.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "ingest_api" {
  family                   = "${local.name_prefix}-ingest-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name  = "ingest-api"
      image = var.container_image
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        {
          name  = "INGEST_DB_PATH"
          value = "/data/cloud_ingest.db"
        }
      ]
      # In this illustrative module the database connection details would
      # be injected here too (host/port/secret ARN for credentials), once
      # cloud/ingest_api.py is adapted to speak to Postgres instead of a
      # local SQLite file.
      essential = true
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "ingest_api" {
  name            = "${local.name_prefix}-ingest-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ingest_api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ingest.arn
    container_name   = "ingest-api"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]

  tags = var.tags
}

# -----------------------------------------------------------------------
# RDS (managed database stand-in for the SQLite file used in the demo)
# -----------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = "${local.name_prefix}-db-subnets" })
}

resource "aws_db_instance" "ingest" {
  identifier     = "${local.name_prefix}-ingest-db"
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage      = 20
  storage_encrypted      = true
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]

  publicly_accessible = false
  multi_az            = false
  skip_final_snapshot = true
  deletion_protection = false

  tags = merge(var.tags, { Name = "${local.name_prefix}-ingest-db" })
}
