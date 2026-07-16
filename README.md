# CloudSight Intake — Recruiter-Friendly Serverless Image Processing Starter

CloudSight Intake is a lightweight serverless image analysis project designed to feel practical, modern, and easy to explain in an interview. It uses AWS services to receive images, trigger processing automatically, analyze them with Rekognition, store structured results, and notify the user with a simple event-driven workflow.

## Why this project is strong for a recruiter
This project is useful because it shows more than just coding. It demonstrates:
- cloud-native design thinking
- event-driven architecture
- infrastructure as code with Terraform
- Python Lambda development
- secure and cost-conscious AWS decisions

It is especially good for a portfolio because it is easy to explain in one minute: “A file arrives, a function runs, the result is stored, and the workflow scales without managing servers.”

## What the app does
1. An image is uploaded to an S3 input bucket.
2. An S3 event triggers an AWS Lambda function.
3. Amazon Rekognition analyzes the image for labels, text, and faces.
4. The results are stored in DynamoDB and saved as JSON in S3.
5. An SNS notification can alert a user or team.

## Architecture overview
```text
[ User / Mobile / Field Device ] --> [ S3 Input Bucket ]
                                         |
                                         v
                              [ AWS Lambda ] --> [ Amazon Rekognition ]
                                         |
                                         +--> [ DynamoDB ]
                                         |
                                         +--> [ S3 Output Bucket ]
                                         |
                                         +--> [ SNS Notification ]
```

## Recruiter-friendly use cases
Here are two practical stories you can use when presenting the project:

1. Small business photo intake and quality checks
   - A local business receives photos from field staff or contractors.
   - The system labels and summarizes each image automatically.
   - This helps teams spot issues faster without building a full custom dashboard.

2. Community operations and issue reporting
   - Volunteers or staff upload photos from job sites, public spaces, or events.
   - The pipeline extracts useful metadata and flags important images for follow-up.
   - This is a strong example of using automation to make low-budget operations more efficient.

## Why this stays AWS free-tier friendly
This version is intentionally designed to stay lightweight and cost-aware:
- No EC2, RDS, or always-on containers are used.
- Lambda runs only when an upload happens.
- S3, DynamoDB, SNS, and CloudWatch are used in a low-volume, demo-friendly pattern.
- The Lambda function is kept intentionally small and efficient for a portfolio deployment.

> For a demo or interview deployment, this is a strong fit. For high-volume production workloads, usage should still be monitored carefully.

## Repository structure
```text
.
├── lambda/
│   └── index.py
├── terraform/
│   └── main.tf
├── docs/
│   ├── speaker-notes.md
│   ├── technical-personal-notes.md
│   └── use_cases/
└── README.md
```

## Quick start
1. Install AWS CLI and Terraform.
2. Configure your AWS credentials.
3. Run Terraform from the terraform directory.
4. Upload a sample image to the input S3 bucket.
5. Review the Lambda output, DynamoDB record, and S3 result file.

Example:
```bash
cd terraform
terraform init
terraform apply -var="sns_email=your-email@example.com"
```

## Interview talking points
- “This is a serverless event-driven workflow, which is a common production pattern.”
- “I chose AWS services that are easy to explain and keep the architecture simple.”
- “The project shows both infrastructure and application skills, not just one or the other.”
- “It is structured as a portfolio-ready starter that can be extended with OCR, moderation, or custom ML later.”

## Related documentation
- [docs/speaker-notes.md](docs/speaker-notes.md)
- [docs/technical-personal-notes.md](docs/technical-personal-notes.md)
- [docs/use_cases/use_case1.md](docs/use_cases/use_case1.md)
- [docs/use_cases/use_case2.md](docs/use_cases/use_case2.md)

