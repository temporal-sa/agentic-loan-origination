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

# Note: Document processing uses AWS Bedrock Nova Pro via Strands BedrockModel
# AWS session is used for:
#   - Bedrock Nova Pro vision model (document OCR)
#   - AgentCore Code Interpreter (financial analysis)