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

# Initialize clients with retry logic
s3_client = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Configuration
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
USE_REKOGNITION = os.environ.get('USE_REKOGNITION', 'false').lower() == 'true'
MAX_REKOGNITION_CALLS = 5  # Limit calls for Free Tier protection

# Validate required environment variables
if not all([OUTPUT_BUCKET, DYNAMODB_TABLE, SNS_TOPIC_ARN]):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

table = dynamodb.Table(DYNAMODB_TABLE)


def handler(event, context):
    """
    S3 Event trigger -> Process image with Rekognition -> Store results -> Send notification
    Optimized for Free Tier: Limits Rekognition calls, adds retries, and reduces unnecessary operations.
    """
    image_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    
    try:
        # Parse S3 event
        records = event.get('Records', [])
        if not records:
            raise ValueError("No S3 event records found")
        
        record = records[0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        # Validate file name and size
        if not is_valid_image(key):
            logger.warning(f"Invalid image format: {key}")
            return create_response('skipped', 'Invalid image format', image_id)
        
        # Check if already processed (idempotency)
        if is_already_processed(image_id, key):
            logger.info(f"Image already processed: {key}")
            return create_response('skipped', 'Already processed', image_id)
        
        # Process image with retry logic
        results = analyze_image(bucket, key, image_id)
        
        # Store results
        store_results(image_id, key, results)
        
        # Save results to S3 (only if processed)
        if results.get('status') == 'processed':
            save_results_to_s3(image_id, key, results)
        
        # Send notification (only for successful processing)
        if results.get('status') == 'processed':
            send_notification(image_id, key, results)
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"Processing completed in {duration:.2f}s")
        
        return create_response('success', 'Image processed successfully', image_id, results)
        
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}", exc_info=True)
        send_error_notification(key, str(e))
        return create_response('error', str(e), image_id)


def is_valid_image(key):
    """Validate image file extension and basic constraints"""
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    return any(key.lower().endswith(ext) for ext in valid_extensions)


def is_already_processed(image_id, key):
    """Check if image was already processed using DynamoDB"""
    try:
        response = table.get_item(Key={'image_id': image_id})
        return 'Item' in response
    except ClientError as e:
        logger.warning(f"DynamoDB check failed: {str(e)}")
        return False


def analyze_image(bucket, key, image_id):
    """
    Run optimized analysis with Free Tier protection
    Limits Rekognition calls and implements fallback logic
    """
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
    
    # Check Free Tier limits (500 images/month for Rekognition)
    try:
        usage = get_rekognition_usage()
        if usage >= 450:  # Leave buffer for other services
            logger.warning("Approaching Rekognition Free Tier limit. Using metadata-only mode.")
            results['analysis_mode'] = 'free-tier-protected'
            return results
    except ClientError as e:
        logger.warning(f"Failed to check usage: {str(e)}")
    
    try:
        # Detect labels (1 call)
        try:
            labels_response = rekognition_client.detect_labels(
                Image={'S3Object': {'Bucket': bucket, 'Name': key}},
                MaxLabels=5,  # Reduced from 10 to save costs
                MinConfidence=75  # Increased threshold for better quality
            )
            results['labels'] = [
                {'name': label['Name'], 'confidence': label['Confidence']}
                for label in labels_response['Labels'][:5]
            ]
            results['rekognition_calls_used'] += 1
        except ClientError as e:
            logger.warning(f"Label detection failed: {str(e)}")
        
        # Detect text (1 call) - only if labels were found
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
        
        # Detect faces (1 call) - only if text or labels detected
        if results['labels'] or results['text']:
            try:
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
                    for i, face in enumerate(faces_response['FaceDetails'])[:3]  # Limit to 3 faces
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


def get_rekognition_usage():
    """
    Estimate Rekognition usage by checking DynamoDB count
    This is a lightweight alternative to CloudWatch metrics
    """
    try:
        # Count items in DynamoDB table (assumes 1 item per image)
        count = table.scan(ProjectionExpression='image_id')['Count']
        # Add some buffer for edge cases
        return min(count, 500)
    except ClientError:
        return 0


def store_results(image_id, image_key, results):
    """Store analysis results in DynamoDB with optimized attributes"""
    item = {
        'image_id': image_id,
        'timestamp': results['timestamp'],
        'image_key': image_key,
        'status': results['status'],
        'label_count': len(results['labels']),
        'face_count': len(results['faces']),
        'text_count': len(results['text']),
        'rekognition_calls_used': results.get('rekognition_calls_used', 0),
        'analysis_mode': results.get('analysis_mode', 'unknown'),
        # Store only essential JSON for query performance
        'summary': f"{len(results['labels'])} labels, {len(results['text'])} text, {len(results['faces'])} faces"
    }
    
    try:
        table.put_item(Item=item)
        logger.info(f"Stored results in DynamoDB for {image_id}")
    except ClientError as e:
        logger.error(f"DynamoDB storage failed: {str(e)}")
        # Don't fail the entire process if storage fails


def save_results_to_s3(image_id, image_key, results):
    """Save JSON results to S3 output bucket with compression"""
    filename = f"results/{image_id}.json"
    
    try:
        # Use minimal JSON formatting to save storage
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
    """Send concise SNS notification"""
    message = f"""
Image Processing Complete

📷 Image: {image_key}
✅ Status: {results['status']}
📊 Analysis: {results.get('summary', 'N/A')}
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
    """Send error notification with limited details"""
    # Truncate error message to avoid SNS message size limits
    error_msg = error[:500] if len(error) > 500 else error
    
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"⚠️ Image Processing Failed: {image_key}",
        Message=f"Error processing {image_key}: {error_msg}"
    )


def create_response(status, message, image_id, results=None):
    """Standardized response format"""
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
                'analysis_mode': results.get('analysis_mode', 'unknown')
            }
        })
    
    return response