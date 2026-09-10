output "input_bucket" {
  description = "Upload images to s3://<this>/uploads/ to trigger the pipeline."
  value       = aws_s3_bucket.input.id
}

output "output_bucket" {
  description = "Full result JSON is written to s3://<this>/results/<image_id>.json."
  value       = aws_s3_bucket.output.id
}

output "dynamodb_table" {
  description = "DynamoDB table holding the per-image processing summary."
  value       = aws_dynamodb_table.results.name
}

output "sns_topic_arn" {
  description = "SNS topic that publishes success / failure / alarm notifications."
  value       = aws_sns_topic.notifications.arn
}

output "sns_confirmation_reminder" {
  description = "Email notifications only arrive AFTER you confirm the subscription."
  value       = "Check ${var.sns_email} for 'AWS Notification - Subscription Confirmation' and click the link. Verify with: aws sns list-subscriptions-by-topic --topic-arn ${aws_sns_topic.notifications.arn} --query 'Subscriptions[].SubscriptionArn'"
}

output "ses_verification_reminder" {
  description = "Rich HTML email (inline image + labels) needs this SES identity verified."
  value       = "Check ${var.sns_email} for 'Amazon Web Services - Email Address Verification Request' and click the link. Verify with: aws ses get-identity-verification-attributes --identities ${var.sns_email}"
}

output "dlq_url" {
  description = "SQS dead-letter queue URL for failed async Lambda invocations."
  value       = aws_sqs_queue.dlq.id
}

output "lambda_function_name" {
  description = "Name of the processing Lambda."
  value       = aws_lambda_function.processor.function_name
}

output "dashboard_url" {
  description = "Direct link to the CloudWatch dashboard."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards/dashboard/${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "xray_traces_url" {
  description = "Direct link to the X-Ray trace list (CloudWatch console)."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#xray:traces/query"
}

output "xray_service_map_url" {
  description = "Direct link to the X-Ray service map."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#xray:service-map/map"
}
