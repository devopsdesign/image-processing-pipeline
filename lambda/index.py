import json
import boto3
import uuid
import os
from datetime import datetime

s3_client = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Keep the function lightweight and demo-friendly for low-volume AWS usage.
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET', 'placeholder-bucket')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'placeholder-table')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:us-east-1:123456789012:placeholder')
USE_REKOGNITION = os.environ.get('USE_REKOGNITION', 'false').lower() == 'true'

table = dynamodb.Table(DYNAMODB_TABLE)


def handler(event, context):
    """
    S3 Event trigger -> Process image with Rekognition -> Store results -> Send notification
    """
    try:
        # Parse S3 event
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']

        print(f"Processing image: s3://{bucket}/{key}")

        # Generate unique ID
        image_id = str(uuid.uuid4())

        # Call Rekognition
        results = analyze_image(bucket, key, image_id)

        # Store in DynamoDB
        store_results(image_id, key, results)

        # Save results to S3
        save_results_to_s3(image_id, key, results)

        # Send notification
        send_notification(image_id, key, results)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Image processed successfully',
                'image_id': image_id,
                'results': results
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        send_error_notification(key, str(e))
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def analyze_image(bucket, key, image_id):
    """
    Run a lightweight analysis. Rekognition is optional and can be enabled
    for richer AI insights while the default metadata mode keeps the demo
    inexpensive and easy to explain.
    """
    results = {
        'image_id': image_id,
        'image_key': key,
        'timestamp': datetime.utcnow().isoformat(),
        'labels': [],
        'text': [],
        'faces': [],
        'status': 'processed',
        'analysis_mode': 'metadata-only'
    }

    try:
        if USE_REKOGNITION:
            # Detect labels (objects, scenes)
            labels_response = rekognition_client.detect_labels(
                Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                MaxLabels=10,
                MinConfidence=70
            )
            results['labels'] = [
                {
                    'name': label['Name'],
                    'confidence': label['Confidence']
                }
                for label in labels_response['Labels']
            ]

            # Detect text
            text_response = rekognition_client.detect_text(
                Image={'S3Object': {'Bucket': bucket, 'Name': key}}
            )
            results['text'] = [
                {
                    'value': item['DetectedText'],
                    'confidence': item['Confidence']
                }
                for item in text_response['TextDetections']
                if item['Type'] == 'LINE'
            ]

            # Detect faces
            faces_response = rekognition_client.detect_faces(
                Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                Attributes=['ALL']
            )
            results['faces'] = [
                {
                    'face_id': i,
                    'confidence': face['Confidence'],
                    'emotions': [
                        {'type': e['Type'], 'confidence': e['Confidence']}
                        for e in face.get('Emotions', [])
                    ]
                }
                for i, face in enumerate(faces_response['FaceDetails'])
            ]
            results['analysis_mode'] = 'rekognition'

            print(f"Analysis complete: {len(results['labels'])} labels, "
                  f"{len(results['text'])} text items, {len(results['faces'])} faces")
        else:
            results['labels'] = [{'name': 'image-uploaded', 'confidence': 100.0}]
            results['text'] = []
            results['faces'] = []
            print('Using metadata-only analysis mode for a low-cost demo workflow')

    except Exception as e:
        print(f"Rekognition error: {str(e)}")
        results['status'] = 'partial_error'
        results['analysis_mode'] = 'metadata-only-fallback'

    return results


def store_results(image_id, image_key, results):
    """
    Store analysis results in DynamoDB
    ```"""
    item = {
        'image_id': image_id,
        'timestamp': results['timestamp'],
        'image_key': image_key,
        'status': results['status'],
        'label_count': len(results['labels']),
        'face_count': len(results['faces']),
        'text_count': len(results['text']),
        'results_json': json.dumps(results)
    }

    table.put_item(Item=item)
    print(f"Stored results in DynamoDB for {image_id}")


def save_results_to_s3(image_id, image_key, results):
    """
    Save JSON results to S3 output bucket
    """
    filename = f"results/{image_id}.json"

    s3_client.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=filename,
        Body=json.dumps(results, indent=2),
        ContentType='application/json'
    )

    print(f"Saved results to s3://{OUTPUT_BUCKET}/{filename}")


def send_notification(image_id, image_key, results):
    """
    Send SNS notification with results summary
    """
    message = f"""
Image Processing Complete!

Image ID: {image_id}
Image: {image_key}
Status: {results['status']}

Analysis Results:
- Labels found: {len(results['labels'])}
  {', '.join([l['name'] for l in results['labels'][:5]])}

- Text detected: {len(results['text'])} items
- Faces detected: {len(results['faces'])}

Results saved to: s3://{OUTPUT_BUCKET}/results/{image_id}.json
    """

    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"Image Processed: {image_key}",
        Message=message
    )

    print("Notification sent")


def send_error_notification(image_key, error):
    """
    Send error notification
    """
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"Image Processing Failed: {image_key}",
        Message=f"Error: {error}"
    )
