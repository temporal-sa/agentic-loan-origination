import os
import boto3
from botocore.config import Config

def get_aws_session():
    """
    Get AWS session with profile from environment variable.

    Used by AgentCore Code Interpreter for financial analysis.

    Returns:
        boto3.Session: Configured AWS session
    """
    profile_name = os.getenv("AWS_PROFILE")

    if profile_name:
        return boto3.Session(profile_name=profile_name)
    else:
        return boto3.Session()

# Note: S3 and BDA clients removed - document processing now uses Ollama granite3.2-vision
# AWS is only used for AgentCore Code Interpreter (configured automatically via region)