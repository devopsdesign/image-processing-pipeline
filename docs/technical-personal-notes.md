# Technical Personal Notes

## Project Identity
MediLens is a serverless image triage assistant for rural clinics. The goal is to make basic AI-assisted analysis available at low or zero cost when a clinic has only a phone, a camera, and limited bandwidth.

## Why This Architecture Fits the Use Case
- The system is event-driven, so it only runs when an image arrives.
- AWS Lambda removes the need for always-on infrastructure.
- S3 acts as a simple, durable intake and archival layer.
- Rekognition provides fast visual analysis without requiring a custom ML model to be trained.
- DynamoDB stores structured results for traceability and future audit needs.
- SNS provides lightweight alerting for staff and specialists.

## Design Choices
### 1. Serverless-first
This design avoids EC2, RDS, or container fleets, which would introduce unnecessary cost and maintenance overhead. For a portfolio project or low-volume clinic deployment, serverless is the best fit.

### 2. Free-tier awareness
For this demo, the architecture is intentionally simple and low-volume. The design keeps the stack lightweight by avoiding persistent compute and by using on-demand services.

### 3. Security by default
The infrastructure uses private S3 buckets, public access blocking, least-privilege IAM policies, and encrypted storage patterns. These are important for a healthcare-inspired use case even if the demo does not process real patient data.

## Security Notes
- S3 buckets are private and not publicly accessible.
- Lambda execution permissions are narrowly scoped.
- Only the minimum AWS actions required for processing are granted.
- CloudWatch logs provide observability for debugging and review.
- The architecture is designed to be extended with KMS encryption and stricter compliance controls later.

## Architecture Summary
1. A nurse uploads an image to an S3 input bucket.
2. An S3 event triggers AWS Lambda.
3. Lambda calls Rekognition for label, text, and face analysis.
4. Results are stored in DynamoDB and written to an output S3 bucket.
5. An SNS notification is sent to alert clinicians or administrators.

## Personal Reflection
This project is valuable because it shows how cloud-native design can solve a real-world access problem. It is not only about AI; it is about making technology available to people who otherwise would not have the budget or infrastructure to use it.
