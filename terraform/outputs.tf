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

output "api_base_url" {
  description = "Read-only HTTP API. GET {this}/images or GET {this}/images/<image_id>."
  value       = aws_apigatewayv2_api.read.api_endpoint
}

output "athena_workgroup" {
  description = "Athena workgroup for querying the results table."
  value       = aws_athena_workgroup.main.name
}

output "glue_database" {
  description = "Glue Data Catalog database holding the 'results' table."
  value       = aws_glue_catalog_database.results.name
}

output "budget_name" {
  description = "AWS Budgets monthly cost alert (80% actual / 100% forecasted -> email)."
  value       = aws_budgets_budget.monthly_cost.name
}

output "state_machine_arn" {
  description = "Step Functions state machine that orchestrates each upload (visual execution graph in the console)."
  value       = aws_sfn_state_machine.processor.arn
}

output "state_machine_console_url" {
  description = "Direct link to the state machine's execution list."
  value       = "https://${var.aws_region}.console.aws.amazon.com/states/home?region=${var.aws_region}#/statemachines/view/${aws_sfn_state_machine.processor.arn}"
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID - put in the app's secrets as COGNITO_USER_POOL_ID."
  value       = aws_cognito_user_pool.app.id
}

output "cognito_app_client_id" {
  description = "Cognito App Client ID - put in the app's secrets as COGNITO_CLIENT_ID."
  value       = aws_cognito_user_pool_client.app.id
}

output "owner_bootstrap_username" {
  description = "Bootstrap Owner login (email). Check that inbox for the Cognito temporary-password email."
  value       = aws_cognito_user.owner_bootstrap.username
}

output "app_iam_access_key_id" {
  description = "Access key ID for the app's IAM user - put in the app's secrets as AWS_ACCESS_KEY_ID."
  value       = aws_iam_access_key.app.id
}

output "app_iam_secret_access_key" {
  description = "Secret access key - put in the app's secrets as AWS_SECRET_ACCESS_KEY. Sensitive: only shown with -raw or terraform output -json."
  value       = aws_iam_access_key.app.secret
  sensitive   = true
}
