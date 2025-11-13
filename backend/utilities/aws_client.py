import os
import boto3
from botocore.config import Config

def get_aws_session():
    """
    Get AWS session with profile from environment variable.
    
    Returns:
        boto3.Session: Configured AWS session
    """
    profile_name = os.getenv("AWS_PROFILE")
    
    if profile_name:
        return boto3.Session(profile_name=profile_name)
    else:
        return boto3.Session()

def get_s3_client():
    """Get S3 client with proper AWS profile configuration."""
    session = get_aws_session()
    region_name = os.getenv("AWS_REGION", "us-west-2")
    
    return session.client('s3', region_name=region_name)

def get_bedrock_data_automation_client():
    """Get Bedrock Data Automation Runtime client with proper AWS profile configuration."""
    session = get_aws_session()
    region_name = os.getenv("AWS_REGION", "us-west-2")
    
    return session.client('bedrock-data-automation-runtime', region_name=region_name)