# Speaker Notes

## Opening
“Today I want to present CloudSight Intake, a serverless image processing starter that shows how to build a practical AWS workflow without overcomplicating the architecture.”

## The Problem
“Many teams need to process photos quickly, but they do not want to manage servers or pay for a heavy platform. A simple upload workflow can save time and reduce manual effort.”

## The Solution
“This project uses S3, Lambda, Rekognition, DynamoDB, and SNS to create a low-cost, event-driven pipeline. An image arrives, the function runs, the result is stored, and a notification can be sent automatically.”

## Why the Architecture Matters
“The value here is not just the image analysis. It is the design pattern: event-driven, modular, and easy to extend. That is exactly the kind of architecture recruiters like to hear about.”

## Security and Cost Awareness
“The project also shows that security and cost can be built into the design from the start. The storage is private, access is limited, and the system stays lightweight enough for a portfolio or demo deployment.”

## Why This Project Stands Out
“What makes this project compelling is that it balances technical depth with a clear business story. It is simple enough to explain, but strong enough to show real cloud engineering habits.”

## Closing
“This is more than a toy pipeline. It is a portfolio-ready example of how to turn a simple business problem into a modern, serverless cloud solution.”
