terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  name        = var.project_name
  account_id  = data.aws_caller_identity.current.account_id
  lambda_name = "${var.project_name}-processor"
  image_types = [".jpg", ".jpeg", ".png", ".gif"]

  doctor_email = var.doctor_email != "" ? var.doctor_email : var.sns_email
  owner_email  = var.owner_email != "" ? var.owner_email : var.sns_email

  tags = merge({
    Project   = "CloudSight Intake"
    ManagedBy = "Terraform"
  }, var.tags)
}

# ---------------------------------------------------------------------------
# S3 buckets
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "input" {
  bucket = "${local.name}-input-${local.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket" "output" {
  bucket = "${local.name}-output-${local.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "input" {
  bucket                  = aws_s3_bucket.input.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket                  = aws_s3_bucket.output.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "input" {
  bucket = aws_s3_bucket.input.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "output" {
  bucket = aws_s3_bucket.output.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Deny any request over plain HTTP - the buckets hold patient photos / results.
data "aws_iam_policy_document" "require_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["${aws_s3_bucket.input.arn}", "${aws_s3_bucket.input.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "input" {
  bucket = aws_s3_bucket.input.id
  policy = data.aws_iam_policy_document.require_tls.json
}

data "aws_iam_policy_document" "require_tls_output" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["${aws_s3_bucket.output.arn}", "${aws_s3_bucket.output.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "output" {
  bucket = aws_s3_bucket.output.id
  policy = data.aws_iam_policy_document.require_tls_output.json
}

resource "aws_s3_bucket_lifecycle_configuration" "input" {
  bucket = aws_s3_bucket.input.id

  rule {
    id     = "purge-uploads"
    status = "Enabled"

    filter {
      prefix = "uploads/"
    }

    expiration {
      days = var.input_retention_days
    }
  }
}

# ---------------------------------------------------------------------------
# Lambda package (pip install + zip, driven by scripts/build_lambda.sh)
# ---------------------------------------------------------------------------

resource "null_resource" "lambda_build" {
  triggers = {
    source       = filesha256("${path.module}/../lambda/index.py")
    requirements = filesha256("${path.module}/../lambda/requirements.txt")
    builder      = filesha256("${path.module}/../scripts/build_lambda.sh")
  }

  provisioner "local-exec" {
    command     = "bash ${path.module}/../scripts/build_lambda.sh"
    working_dir = path.module
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/build"
  output_path = "${path.module}/dist/lambda_function.zip"
  depends_on  = [null_resource.lambda_build]
}

# ---------------------------------------------------------------------------
# IAM (least privilege)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "ReadInputObjects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.input.arn}/uploads/*"]
  }

  statement {
    sid       = "WriteResultObjects"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.output.arn}/results/*"]
  }

  statement {
    sid = "Rekognition"
    actions = [
      "rekognition:DetectLabels",
      "rekognition:DetectText",
      "rekognition:DetectFaces",
      "rekognition:DetectModerationLabels",
    ]
    resources = ["*"]
  }

  statement {
    sid = "DynamoDBWriteAndDedupe"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.results.arn,
      "${aws_dynamodb_table.results.arn}/index/*",
    ]
  }

  statement {
    sid       = "PublishNotifications"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]
  }

  statement {
    sid       = "SendRichEmail"
    actions   = ["ses:SendRawEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.sns_email]
    }
  }

  statement {
    sid       = "SendToDeadLetterQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }

  statement {
    sid = "XRayTracing"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ScopedLogging"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.name}-lambda-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

# ---------------------------------------------------------------------------
# Lambda function
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_lambda_function" "processor" {
  function_name    = local.lambda_name
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  architectures    = ["x86_64"]
  memory_size      = 128
  timeout          = 15
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  # Caps concurrent invocations - at ~10 users this is far more than ever
  # needed, but it hard-bounds worst-case Rekognition spend and blast radius
  # from any runaway/abusive upload burst.
  reserved_concurrent_executions = var.lambda_reserved_concurrency

  tracing_config {
    mode = "Active"
  }

  # No dead_letter_config here - retry/DLQ is now owned by the Step Functions
  # state machine below (Retry + Catch), since Step Functions invokes this
  # Lambda synchronously rather than S3 invoking it asynchronously.

  environment {
    variables = {
      OUTPUT_BUCKET                = aws_s3_bucket.output.id
      DYNAMODB_TABLE               = aws_dynamodb_table.results.name
      SNS_TOPIC_ARN                = aws_sns_topic.notifications.arn
      USE_REKOGNITION              = tostring(var.use_rekognition)
      REKOGNITION_MIN_CONFIDENCE   = tostring(var.rekognition_min_confidence)
      MEDICAL_CONFIDENCE_THRESHOLD = tostring(var.medical_confidence_threshold)
      SES_FROM                     = var.sns_email
      NOTIFY_EMAIL                 = var.sns_email
      DOCTOR_EMAIL                 = local.doctor_email
    }
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda,
  ]
}

# ---------------------------------------------------------------------------
# Event trigger: S3 -> EventBridge -> Step Functions -> Lambda.
#
# Decouples the trigger from the processor (events are archivable/replayable
# on the bus) and moves retry/DLQ from Lambda's built-in async config to an
# explicit, visualisable state machine. The Lambda itself is unchanged - it
# still receives the same {"Records": [...]} shape it always has, built by
# the Pass state below.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket_notification" "input" {
  bucket      = aws_s3_bucket.input.id
  eventbridge = true
}

resource "aws_cloudwatch_event_rule" "image_uploaded" {
  name        = "${local.name}-image-uploaded"
  description = "New object under uploads/ in the input bucket"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.input.id] }
      object = { key = [{ prefix = "uploads/" }] }
    }
  })

  tags = local.tags
}

data "aws_iam_policy_document" "eventbridge_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge" {
  name               = "${local.name}-eventbridge-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "eventbridge_start_execution" {
  name = "${local.name}-eventbridge-start-execution"
  role = aws_iam_role.eventbridge.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.processor.arn
    }]
  })
}

resource "aws_cloudwatch_event_target" "processor" {
  rule     = aws_cloudwatch_event_rule.image_uploaded.name
  arn      = aws_sfn_state_machine.processor.arn
  role_arn = aws_iam_role.eventbridge.arn
}

# ---------------------------------------------------------------------------
# Step Functions - one Task invoking the existing Lambda, with Retry (mirrors
# the previous 2-attempt async policy) and a Catch that forwards to the same
# SQS DLQ on final failure.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid       = "InvokeProcessor"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.processor.arn]
  }

  statement {
    sid       = "SendToDeadLetterQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }

  statement {
    sid = "ExecutionLogging"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "${local.name}-sfn-policy"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.name}-processor"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_sfn_state_machine" "processor" {
  name     = "${local.name}-processor"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment = "CloudSight Intake - process one S3 upload, retry, DLQ on final failure"
    StartAt = "BuildS3Event"
    States = {
      BuildS3Event = {
        Type = "Pass"
        Parameters = {
          Records = [{
            s3 = {
              bucket = { "name.$" = "$.detail.bucket.name" }
              object = {
                "key.$"  = "$.detail.object.key"
                "eTag.$" = "$.detail.object.etag"
              }
            }
          }]
        }
        Next = "ProcessImage"
      }
      ProcessImage = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.processor.arn
          "Payload.$"  = "$"
        }
        ResultSelector = { "result.$" = "$.Payload" }
        TimeoutSeconds = 30
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          IntervalSeconds = 60
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "SendToDLQ"
        }]
        End = true
      }
      SendToDLQ = {
        Type     = "Task"
        Resource = "arn:aws:states:::sqs:sendMessage"
        Parameters = {
          QueueUrl        = aws_sqs_queue.dlq.id
          "MessageBody.$" = "$"
        }
        End = true
      }
    }
  })

  tags = local.tags
}

# ---------------------------------------------------------------------------
# SQS dead-letter queue + backlog alarm
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.tags
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dlq.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_lambda_function.processor.arn }
      }
    }]
  })
}

resource "aws_cloudwatch_metric_alarm" "dlq_backlog" {
  alarm_name          = "${local.name}-dlq-backlog"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.dlq_alarm_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Async Lambda invocations are failing and landing in the DLQ."
  alarm_actions       = [aws_sns_topic.notifications.arn]
  ok_actions          = [aws_sns_topic.notifications.arn]
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "results" {
  name         = "${local.name}-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "image_id"
  range_key    = "timestamp"

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
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  # Continuous backups for accidental-delete/overwrite recovery. Cost scales
  # with table size (pennies at this table's tiny size) - worth it given the
  # table holds patient screening records.
  point_in_time_recovery {
    enabled = true
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# SNS
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "notifications" {
  name = "${local.name}-notifications"
  tags = local.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.sns_email
}

# Only needed if the doctor's inbox differs from sns_email - the SNS plain-
# text side of a medical escalation is a topic-wide broadcast, not a per-
# message "To" address, so the doctor must be subscribed too when different.
resource "aws_sns_topic_subscription" "doctor" {
  count     = local.doctor_email != var.sns_email ? 1 : 0
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = local.doctor_email
}

# ---------------------------------------------------------------------------
# SES - used by the Lambda to send the HTML "image processed" email with the
# image embedded inline (SNS email is plain-text only). Sandbox mode is fine:
# from == to == var.sns_email, so verifying this one identity covers both.
# AWS emails a verification link on first apply - click it before rich emails work.
# ---------------------------------------------------------------------------

resource "aws_ses_email_identity" "notify" {
  email = var.sns_email
}

# ---------------------------------------------------------------------------
# CloudWatch dashboard
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda invocations / errors / throttles"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          period  = 300
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", local.lambda_name, { stat = "Sum" }],
            ["AWS/Lambda", "Errors", "FunctionName", local.lambda_name, { stat = "Sum" }],
            ["AWS/Lambda", "Throttles", "FunctionName", local.lambda_name, { stat = "Sum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda duration (ms)"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", local.lambda_name, { stat = "Average", label = "avg" }],
            ["AWS/Lambda", "Duration", "FunctionName", local.lambda_name, { stat = "p99", label = "p99" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB consumed capacity units"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.results.name, { stat = "Sum" }],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", aws_dynamodb_table.results.name, { stat = "Sum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "DLQ backlog (final-failure messages)"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.dlq.name, { stat = "Maximum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "Step Functions executions"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.processor.arn, { stat = "Sum" }],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.processor.arn, { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Cost guardrail - account-wide monthly budget with email alerts. Catches any
# spend (Rekognition/SES beyond the 12-month free tier, S3 storage growth,
# anything else in the account), not just this project's resources.
# ---------------------------------------------------------------------------

resource "aws_budgets_budget" "monthly_cost" {
  name         = "${local.name}-monthly-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.sns_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.sns_email]
  }
}

# ---------------------------------------------------------------------------
# Athena / Glue - ad-hoc SQL over the results JSON, no crawler needed since the
# schema is fixed and known. Query cost is capped per-query via the workgroup.
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_database" "results" {
  name = replace("${local.name}_catalog", "-", "_")
}

resource "aws_glue_catalog_table" "results" {
  name          = "results"
  database_name = aws_glue_catalog_database.results.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.output.id}/results/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "cloudsight-json"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "image_id"
      type = "string"
    }
    columns {
      name = "timestamp"
      type = "string"
    }
    columns {
      name = "image_key"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "analysis_mode"
      type = "string"
    }
    columns {
      name = "label_count"
      type = "int"
    }
    columns {
      name = "text_count"
      type = "int"
    }
    columns {
      name = "face_count"
      type = "int"
    }
    columns {
      name = "rekognition_calls"
      type = "int"
    }
    columns {
      name = "summary"
      type = "string"
    }
    columns {
      name = "mode"
      type = "string"
    }
    columns {
      name = "labels"
      type = "array<struct<name:string,confidence:double>>"
    }
    columns {
      name = "text"
      type = "array<struct<value:string,confidence:double>>"
    }
    columns {
      name = "faces"
      type = "array<struct<confidence:double>>"
    }
    columns {
      name = "calls"
      type = "int"
    }
  }
}

resource "aws_athena_workgroup" "main" {
  name = "${local.name}-workgroup"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824 # 1 GB hard cap per query

    result_configuration {
      output_location = "s3://${aws_s3_bucket.output.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Read API - HTTP API + Lambda for querying processed results (GET only, no
# auth - non-sensitive metadata only, throttled at the stage to bound cost).
# ---------------------------------------------------------------------------

data "archive_file" "reader" {
  type        = "zip"
  source_file = "${path.module}/../lambda/reader.py"
  output_path = "${path.module}/dist/reader.zip"
}

resource "aws_cloudwatch_log_group" "reader" {
  name              = "/aws/lambda/${local.name}-reader"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_iam_role" "reader" {
  name               = "${local.name}-reader-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "reader" {
  statement {
    sid     = "QueryResults"
    actions = ["dynamodb:Query", "dynamodb:Scan"]
    resources = [
      aws_dynamodb_table.results.arn,
      "${aws_dynamodb_table.results.arn}/index/*",
    ]
  }

  statement {
    sid = "XRayTracing"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ScopedLogging"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.reader.arn}:*"]
  }
}

resource "aws_iam_role_policy" "reader" {
  name   = "${local.name}-reader-policy"
  role   = aws_iam_role.reader.id
  policy = data.aws_iam_policy_document.reader.json
}

resource "aws_lambda_function" "reader" {
  function_name    = "${local.name}-reader"
  role             = aws_iam_role.reader.arn
  handler          = "reader.handler"
  runtime          = "python3.11"
  architectures    = ["x86_64"]
  memory_size      = 128
  timeout          = 10
  filename         = data.archive_file.reader.output_path
  source_code_hash = data.archive_file.reader.output_base64sha256

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.results.name
    }
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy.reader,
    aws_cloudwatch_log_group.reader,
  ]
}

resource "aws_apigatewayv2_api" "read" {
  name          = "${local.name}-read-api"
  protocol_type = "HTTP"

  # No cors_configuration: this now requires SigV4-signed AWS_IAM auth (below),
  # which a browser's anonymous fetch can't provide anyway - CORS would be
  # dead weight, not a mitigation.

  tags = local.tags
}

resource "aws_apigatewayv2_integration" "reader" {
  api_id                 = aws_apigatewayv2_api.read.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.reader.invoke_arn
  payload_format_version = "2.0"
}

# AWS_IAM auth: the results (filenames double as patient identifiers, plus
# medical/non_human/needs_review classification) are sensitive enough that
# this can no longer be a fully public, unauthenticated endpoint. Only a
# SigV4-signed caller with execute-api:Invoke on this API can reach it now -
# grant that explicitly to whichever IAM principal needs to call it.
resource "aws_apigatewayv2_route" "list_images" {
  api_id             = aws_apigatewayv2_api.read.id
  route_key          = "GET /images"
  target             = "integrations/${aws_apigatewayv2_integration.reader.id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_route" "get_image" {
  api_id             = aws_apigatewayv2_api.read.id
  route_key          = "GET /images/{image_id}"
  target             = "integrations/${aws_apigatewayv2_integration.reader.id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.read.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  tags = local.tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reader.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.read.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Cognito - authentication + role groups for the triage app.
#
# admin_create_user_config.allow_admin_create_user_only = true: no public
# self-signup. The Owner (bootstrapped below) creates every other account
# in-app via AdminCreateUser - appropriate for a fixed ~10-person community.
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "app" {
  name = "${local.name}-users"

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
    require_uppercase = true
  }

  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = local.tags
}

resource "aws_cognito_user_pool_client" "app" {
  name         = "${local.name}-app-client"
  user_pool_id = aws_cognito_user_pool.app.id

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  generate_secret = false # public client - called directly from the Streamlit backend

  access_token_validity  = 4
  id_token_validity      = 4
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_group" "owner" {
  name         = "owner"
  user_pool_id = aws_cognito_user_pool.app.id
  description  = "Full admin: user management, all patients, system dashboards"
  precedence   = 10
}

resource "aws_cognito_user_group" "poweruser" {
  name         = "poweruser"
  user_pool_id = aws_cognito_user_pool.app.id
  description  = "Local triage staff: review queue, upload on behalf of patients"
  precedence   = 20
}

resource "aws_cognito_user_group" "patient" {
  name         = "patient"
  user_pool_id = aws_cognito_user_pool.app.id
  description  = "Own uploads and own results only"
  precedence   = 30
}

# Bootstrap account so there is always at least one Owner able to log in and
# provision everyone else. Cognito emails the temporary password.
resource "aws_cognito_user" "owner_bootstrap" {
  user_pool_id = aws_cognito_user_pool.app.id
  username     = local.owner_email

  attributes = {
    email          = local.owner_email
    email_verified = true
  }

  desired_delivery_mediums = ["EMAIL"]
}

resource "aws_cognito_user_in_group" "owner_bootstrap" {
  user_pool_id = aws_cognito_user_pool.app.id
  username     = aws_cognito_user.owner_bootstrap.username
  group_name   = aws_cognito_user_group.owner.name
}

# ---------------------------------------------------------------------------
# App IAM user - the credentials the Streamlit backend actually runs as.
# Replaces an earlier ad-hoc, out-of-band IAM user that (on inspection) ended
# up with no permissions attached at all; this one is fully declared here so
# its access is reviewable and reproducible.
# ---------------------------------------------------------------------------

resource "aws_iam_user" "app" {
  name = "${local.name}-app"
  tags = local.tags
}

resource "aws_iam_access_key" "app" {
  user = aws_iam_user.app.name
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "UploadImages"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.input.arn}/uploads/*"]
  }

  statement {
    sid       = "ReadResults"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.output.arn}/results/*"]
  }

  statement {
    sid     = "QueryResults"
    actions = ["dynamodb:Query", "dynamodb:Scan", "dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.results.arn,
      "${aws_dynamodb_table.results.arn}/index/*",
    ]
  }

  # Admin-prefixed Cognito actions require IAM auth; the plain sign-in flow
  # (InitiateAuth / RespondToAuthChallenge / GetUser) does not and needs no
  # grant here - see app/app.py.
  statement {
    sid = "ManageUsers"
    actions = [
      "cognito-idp:AdminCreateUser",
      "cognito-idp:AdminAddUserToGroup",
      "cognito-idp:AdminRemoveUserFromGroup",
      "cognito-idp:AdminGetUser",
      "cognito-idp:AdminSetUserPassword",
      "cognito-idp:AdminDeleteUser",
      "cognito-idp:AdminListGroupsForUser",
      "cognito-idp:ListUsers",
      "cognito-idp:ListUsersInGroup",
    ]
    resources = [aws_cognito_user_pool.app.arn]
  }

  # Lets a Power User's "Escalate to doctor" button send a plain email
  # directly from the app, for a needs_review item they decide to escalate
  # manually (the Lambda's own escalation only fires automatically for
  # classification == "medical").
  statement {
    sid       = "ManualEscalationEmail"
    actions   = ["ses:SendEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.sns_email]
    }
  }
}

resource "aws_iam_user_policy" "app" {
  name   = "${local.name}-app-policy"
  user   = aws_iam_user.app.name
  policy = data.aws_iam_policy_document.app.json
}
