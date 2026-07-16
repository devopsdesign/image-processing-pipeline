# Use Case 2 — Community Operations and Issue Reporting

## The Business Problem
Nonprofits, local organizations, and small teams often collect photos from the field but do not have the time or budget to review every image manually. A simple triage workflow can help prioritize what matters most.

## The Solution
This project can serve as the foundation for a lightweight image triage workflow. Photos can be uploaded, analyzed, and summarized so a team can focus on the most important cases.

## How It Works
1. A volunteer or employee uploads a photo.
2. The image is stored in S3.
3. Lambda processes the image automatically.
4. Rekognition adds labels, text, and face information.
5. The results are saved in DynamoDB and can trigger a simple notification.

## Why This Is Recruiter-Friendly
This story shows practical problem-solving. It moves beyond just “I used AWS” and explains how the system helps people make faster decisions with less manual effort.

## Why It Fits the Project
It is a strong example of serverless automation for a low-budget team and matches the project’s free-tier-friendly design.
