# WildEye Technical Notes

## Architecture Intent
WildEye is designed as a lightweight, event-driven image analysis pipeline for conservation work. Its purpose is to reduce the manual effort involved in reviewing camera trap images.

## Core Services
- Amazon S3: image upload and storage
- AWS Lambda: event-driven processing
- Amazon Rekognition: object, label, and text detection
- Amazon DynamoDB: structured storage of results
- Amazon SNS: optional alerting for rare sightings or suspicious activity

## Why This Fits the Use Case
The architecture fits wildlife monitoring because it can process bursts of image uploads without needing a constantly running server. That makes it ideal for low-budget organizations and intermittent field activity.

## Security Considerations
- Restrict public access to buckets.
- Apply least-privilege Lambda permissions.
- Keep metadata auditable for operational review.
- Extend with more protective controls if the workflow becomes production-grade.

## Cost Positioning
The solution is positioned as highly affordable because it is serverless and event-driven. It avoids the fixed cost of 24/7 infrastructure while still enabling AI-assisted analysis when needed.
