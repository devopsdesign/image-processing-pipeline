# Use Case 1 — Small Business Photo Intake and Quality Checks

## The Business Problem
A small business often receives photos from field staff, vendors, or contractors. Those images may need to be reviewed quickly, categorized, or flagged for follow-up. Doing this manually can become slow and inconsistent.

## The Solution
This project provides a serverless workflow that can automatically receive and analyze incoming images. A team can upload photos to S3, run an automated analysis, and use the results to support operations without needing to maintain servers.

## How It Works
1. A staff member uploads a photo from a mobile device or desktop.
2. The image lands in an S3 bucket.
3. Lambda is triggered automatically.
4. Rekognition detects labels, text, and faces.
5. Results are written to DynamoDB and stored in S3 for reference.

## Why This Is Recruiter-Friendly
This use case is easy to explain because it connects cloud automation to a real business need: faster workflows and fewer manual bottlenecks.

## Why It Fits the Project
It stays aligned with the current implementation and keeps the architecture lightweight, event-driven, and suitable for a demo or interview deployment.
