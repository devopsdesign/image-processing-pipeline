variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix applied to every resource."
  type        = string
  default     = "cloudsight-intake"
}

variable "sns_email" {
  description = "Email address subscribed to the processing notification topic. A confirmation email is sent on first apply."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.sns_email))
    error_message = "sns_email must be a valid email address."
  }
}

variable "use_rekognition" {
  description = "Enable Amazon Rekognition analysis. false = metadata-only mode, which keeps the stack inside the AWS Always-Free tier (Rekognition free tier lasts only 12 months)."
  type        = bool
  default     = false
}

variable "input_retention_days" {
  description = "Days before objects under uploads/ in the input bucket are purged."
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda log group."
  type        = number
  default     = 7
}

variable "dlq_alarm_threshold" {
  description = "Number of visible messages in the DLQ that trips the backlog alarm."
  type        = number
  default     = 1
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
