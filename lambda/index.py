import json
import boto3
import uuid
import os
import logging
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
s3_client = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Configuration
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
USE_REKOGNITION = os.environ.get('USE_REKOGNITION', 'false').lower() == 'true'

# Validate required environment variables
if not all([OUTPUT_BUCKET, DYNAMODB_TABLE, SNS_TOPIC_ARN]):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

table = dynamodb.Table(DYNAMODB_TABLE)

def handler(event, context):
    image_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    
    try:
        records = event.get('Records', [])
        if not records:
            raise ValueError("No S3 event records found")
        
        record = records[0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        if not is_valid_image(key):
            logger.warning(f"Invalid image format: {key}")
            return create_response('skipped', 'Invalid image format', image_id)
        
        # Check if already processed (idempotency)
        if is_already_processed(image_id, key):
            logger.info(f"Image already processed: {key}")
            return create_response('skipped', 'Already processed', image_id)
        
        # Analyze Image
        results = analyze_image(bucket, key, image_id)
        
        # Store results (Summary is generated here based on actual data)
        store_results(image_id, key, results)
        
        if results.get('status') == 'processed':
            save_results_to_s3(image_id, key, results)
            send_notification(image_id, key, results)
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"Processing completed in {duration:.2f}s")
        
        return create_response('success', 'Image processed successfully', image_id, results)
        
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}", exc_info=True)
        send_error_notification(key, str(e))
        return create_response('error', str(e), image_id)

def is_valid_image(key):
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    return any(key.lower().endswith(ext) for ext in valid_extensions)

def is_already_processed(image_id, key):
    try:
        response = table.get_item(Key={'image_id': image_id})
        return 'Item' in response
    except ClientError as e:
        logger.warning(f"DynamoDB check failed: {str(e)}")
        return False

def analyze_image(bucket, key, image_id):
    results = {
        'image_id': image_id,
        'image_key': key,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'labels': [],
        'text': [],
        'faces': [],
        'status': 'processed',
        'analysis_mode': 'metadata-only',
        'rekognition_calls_used': 0
    }
    
    if not USE_REKOGNITION:
        logger.info('Using metadata-only analysis mode')
        return results
    
    try:
        # 1. Detect Labels
        try:
            labels_response = rekognition_client.detect_labels(
                Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                MaxLabels=5,
                MinConfidence=75
            )
            results['labels'] = [
                {'name': label['Name'], 'confidence': label['Confidence']}
                for label in labels_response['Labels'][:5]
            ]
            results['rekognition_calls_used'] += 1
        except ClientError as e:
            logger.warning(f"Label detection failed: {str(e)}")
        
        # 2. Detect Text (only if labels found to save calls)
        if results['labels']:
            try:
                text_response = rekognition_client.detect_text(
                    Image={'S3Object': {'Bucket': bucket, 'Name': key}}
                )
                results['text'] = [
                    {'value': item['DetectedText'], 'confidence': item['Confidence']}
                    for item in text_response['TextDetections']
                    if item['Type'] == 'LINE'
                ]
                results['rekognition_calls_used'] += 1
            except ClientError as e:
                logger.warning(f"Text detection failed: {str(e)}")
        
        # 3. Detect Faces (only if labels or text found)
        if results['labels'] or results['text']:
            try:
                faces_response = rekognition_client.detect_faces(
                    Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                    Attributes=['ALL']
                )
                # FIX: Slice the list BEFORE enumerating
                faces_list = faces_response['FaceDetails'][:3]
                results['faces'] = [
                    {
                        'face_id': i,
                        'confidence': face['Confidence'],
                        'emotions': [
                            {'type': e['Type'], 'confidence': e['Confidence']}
                            for e in face.get('Emotions', [])
                        ]
                    }
                    for i, face in enumerate(faces_list)
                ]
                results['rekognition_calls_used'] += 1
            except ClientError as e:
                logger.warning(f"Face detection failed: {str(e)}")
        
        if results['rekognition_calls_used'] > 0:
            results['analysis_mode'] = 'rekognition'
            logger.info(f"Analysis complete: {results['rekognition_calls_used']} Rekognition calls used")
        else:
            results['status'] = 'partial_error'
            results['analysis_mode'] = 'rekognition-fallback'
            
    except Exception as e:
        logger.error(f"Rekognition error: {str(e)}")
        results['status'] = 'partial_error'
        results['analysis_mode'] = 'metadata-only-fallback'
        results['rekognition_calls_used'] = 0
    
    return results

def store_results(image_id, image_key, results):
    # Generate summary based on ACTUAL data in results
    label_count = len(results.get('labels', []))
    face_count = len(results.get('faces', []))
    text_count = len(results.get('text', []))
    
    # Create a readable summary string
    summary_parts = []
    if label_count > 0:
        summary_parts.append(f"{label_count} labels")
    if text_count > 0:
        summary_parts.append(f"{text_count} text items")
    if face_count > 0:
        summary_parts.append(f"{face_count} faces")
    
    summary_str = ", ".join(summary_parts) if summary_parts else "No analysis data found"

    item = {
        'image_id': image_id,
        'timestamp': results['timestamp'],
        'image_key': image_key,
        'status': results['status'],
        'label_count': label_count,
        'face_count': face_count,
        'text_count': text_count,
        'rekognition_calls_used': results.get('rekognition_calls_used', 0),
        'analysis_mode': results.get('analysis_mode', 'unknown'),
        'summary': summary_str  # This is the key field that was showing 'n/a'
    }
    
    try:
        table.put_item(Item=item)
        logger.info(f"Stored results in DynamoDB for {image_id} - Summary: {summary_str}")
    except ClientError as e:
        logger.error(f"DynamoDB storage failed: {str(e)}")

def save_results_to_s3(image_id, image_key, results):
    filename = f"results/{image_id}.json"
    try:
        json_data = json.dumps(results, separators=(',', ':'))
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=filename,
            Body=json_data,
            ContentType='application/json'
        )
        logger.info(f"Saved results to s3://{OUTPUT_BUCKET}/{filename}")
    except ClientError as e:
        logger.error(f"S3 storage failed: {str(e)}")

def send_notification(image_id, image_key, results):
    summary = results.get('summary', 'No summary available')
    message = f"""
Image Processing Complete

📷 Image: {image_key}
✅ Status: {results['status']}
📊 Analysis: {summary}
🔍 Mode: {results.get('analysis_mode', 'unknown')}
📦 Results: s3://{OUTPUT_BUCKET}/results/{image_id}.json
    """
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Image Processed: {image_key}",
            Message=message
        )
        logger.info("Notification sent")
    except ClientError as e:
        logger.error(f"Notification failed: {str(e)}")

def send_error_notification(image_key, error):
    error_msg = error[:500] if len(error) > 500 else error
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"⚠️ Image Processing Failed: {image_key}",
        Message=f"Error processing {image_key}: {error_msg}"
    )

def create_response(status, message, image_id, results=None):
    response = {
        'statusCode': 200 if status == 'success' else 500,
        'body': json.dumps({
            'status': status,
            'message': message,
            'image_id': image_id
        })
    }
    
    if status == 'success' and results:
        response['body'] = json.dumps({
            'status': status,
            'message': message,
            'image_id': image_id,
            'results': {
                'label_count': len(results.get('labels', [])),
                'text_count': len(results.get('text', [])),
                'face_count': len(results.get('faces', [])),
                'analysis_mode': results.get('analysis_mode', 'unknown'),
                'summary': results.get('summary', 'N/A')
            }
        })
    
    return response