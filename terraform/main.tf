terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ============================================================================
# VARIABLES
# ============================================================================

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "image-processing-pipeline"
}

variable "sns_email" {
  description = "Email for SNS notifications"
  type        = string
  sensitive   = true
}

# ============================================================================
# DATA SOURCES
# ============================================================================

data "aws_caller_identity" "current" {}

# ============================================================================
# S3 BUCKETS
# ============================================================================

resource "aws_s3_bucket" "input_bucket" {
  bucket = "${var.project_name}-input-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name    = "${var.project_name}-input"
    Project = "PortfolioDemo"
  }
}

resource "aws_s3_bucket" "output_bucket" {
  bucket = "${var.project_name}-output-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name    = "${var.project_name}-output"
    Project = "PortfolioDemo"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "input" {
  bucket = aws_s3_bucket.input_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket = aws_s3_bucket.output_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 Event Notification
resource "aws_s3_bucket_notification" "input_notification" {
  bucket     = aws_s3_bucket.input_bucket.id
  depends_on = [aws_lambda_permission.s3_invoke]

  # Block for JPG
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".jpg"
  }

  # Block for JPEG
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".jpeg"
  }

  # Block for PNG
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".png"
  }

  # Block for GIF
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
    filter_suffix       = ".gif"
  }
}

# ============================================================================
# IAM ROLE FOR LAMBDA
# ============================================================================

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-lambda-role"
    Project = "PortfolioDemo"
  }
}

# S3 access policy
resource "aws_iam_role_policy" "lambda_s3_policy" {
  name = "${var.project_name}-lambda-s3"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.input_bucket.arn,
          "${aws_s3_bucket.input_bucket.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.output_bucket.arn}/*"
      }
    ]
  })
}

# Rekognition access
resource "aws_iam_role_policy" "lambda_rekognition_policy" {
  name = "${var.project_name}-lambda-rekognition"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rekognition:DetectLabels",
          "rekognition:DetectText",
          "rekognition:DetectFaces"
        ]
        Resource = "*"
      }
    ]
  })
}

# DynamoDB access
resource "aws_iam_role_policy" "lambda_dynamodb_policy" {
  name = "${var.project_name}-lambda-dynamodb"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.results.arn
      }
    ]
  })
}

# SNS publish
resource "aws_iam_role_policy" "lambda_sns_policy" {
  name = "${var.project_name}-lambda-sns"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.notifications.arn
      }
    ]
  })
}

# CloudWatch logs
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ============================================================================
# LAMBDA FUNCTION
# ============================================================================
resource "aws_lambda_function" "processor" {
  filename         = "../lambda_function.zip"
  function_name    = "${var.project_name}-processor"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  source_code_hash = filebase64sha256("../lambda_function.zip")
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 512

  environment {
    variables = {
      OUTPUT_BUCKET  = aws_s3_bucket.output_bucket.id
      DYNAMODB_TABLE = aws_dynamodb_table.results.name
      SNS_TOPIC_ARN  = aws_sns_topic.notifications.arn
    }
  }

  tags = {
    Name    = "${var.project_name}-processor"
    Project = "PortfolioDemo"
  }

  # 🚀 THIS BLOCK PREVENTS THE "STILL CREATING..." HANG
  # It forces Terraform to wait for the IAM policies and Log Groups to be fully ready
  depends_on = [
    aws_iam_role.lambda_role,
    aws_iam_role_policy.lambda_sns_policy,
    aws_s3_bucket.output_bucket,
    aws_dynamodb_table.results,
    aws_sns_topic.notifications
  ]
}

resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.input_bucket.arn
}

# ============================================================================
# DYNAMODB TABLE
# ============================================================================

resource "aws_dynamodb_table" "results" {
  name           = "${var.project_name}-results"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "image_id"
  range_key      = "timestamp"

  attribute {
    name = "image_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "StatusIndex"
    hash_key        = "status"
    projection_type = "ALL"
  }

  tags = {
    Name    = "${var.project_name}-results"
    Project = "PortfolioDemo"
  }
}

# ============================================================================
# SNS TOPIC
# ============================================================================

resource "aws_sns_topic" "notifications" {
  name = "${var.project_name}-notifications"

  tags = {
    Name    = "${var.project_name}-notifications"
    Project = "PortfolioDemo"
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.sns_email
}

# ============================================================================
# CLOUDWATCH LOG GROUP
# ============================================================================

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.processor.function_name}"
  retention_in_days = 7

  tags = {
    Name    = "${var.project_name}-lambda-logs"
    Project = "PortfolioDemo"
  }
}

# ============================================================================
# OUTPUTS
# ============================================================================

output "input_bucket" {
  description = "S3 input bucket name"
  value       = aws_s3_bucket.input_bucket.id
}

output "output_bucket" {
  description = "S3 output bucket name"
  value       = aws_s3_bucket.output_bucket.id
}

output "dynamodb_table" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.results.name
}

output "sns_topic_arn" {
  description = "SNS topic ARN"
  value       = aws_sns_topic.notifications.arn
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.processor.function_name
}

