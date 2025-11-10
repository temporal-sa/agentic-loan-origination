#!/usr/bin/env python3
"""
Test BDA permissions and find the correct profile ARN.
"""

import boto3
import os
from dotenv import load_dotenv

load_dotenv()

def test_bda_permissions():
    """Test BDA permissions and profile access."""
    
    region = os.getenv("AWS_REGION", "us-west-2")
    project_arn = os.getenv("BEDROCK_DATA_AUTOMATION_PROJECT_ARN")
    
    print(f"🔍 Testing BDA permissions in region: {region}")
    print(f"📄 Project ARN: {project_arn}")
    
    try:
        # Test bedrock-data-automation service
        bda = boto3.client('bedrock-data-automation', region_name=region)
        
        # Test project access
        project = bda.get_data_automation_project(projectArn=project_arn)
        print(f"✅ Project access: {project['project']['projectName']}")
        
        # Test bedrock-data-automation-runtime service
        bda_runtime = boto3.client('bedrock-data-automation-runtime', region_name=region)
        print(f"✅ BDA Runtime client created")
        
        # Try to find available profiles by testing different ARN formats
        profile_formats = [
            f"arn:aws:bedrock:{region}:aws:data-automation-profile/data-automation-v1",
            f"arn:aws:bedrock:{region}:aws:data-automation-profile/{region}.data-automation-v1",
            f"arn:aws:bedrock:{region}:aws:data-automation-profile/default",
            f"arn:aws:bedrock:{region}:aws:data-automation-profile/bedrock-data-automation-v1"
        ]
        
        print(f"\n🔍 Testing profile ARN formats...")
        for profile_arn in profile_formats:
            try:
                # Test with a minimal call (this will fail but might give us better error info)
                print(f"Testing: {profile_arn}")
                
                # We can't actually test invoke without a real file, but we can check the error
                response = bda_runtime.invoke_data_automation_async(
                    dataAutomationConfiguration={
                        "dataAutomationProjectArn": project_arn,
                        "stage": "LIVE"
                    },
                    inputConfiguration={
                        's3Uri': 's3://test-bucket/test-key'
                    },
                    outputConfiguration={
                        's3Uri': 's3://test-bucket/test-output'
                    },
                    dataAutomationProfileArn=profile_arn
                )
                print(f"✅ Profile ARN works: {profile_arn}")
                return profile_arn
                
            except Exception as e:
                error_msg = str(e)
                if "not authorized to access this resource" in error_msg:
                    print(f"❌ Access denied: {profile_arn}")
                elif "does not exist" in error_msg or "Invalid" in error_msg:
                    print(f"❌ Invalid ARN: {profile_arn}")
                elif "bucket" in error_msg.lower() or "key" in error_msg.lower():
                    print(f"✅ Profile ARN valid (S3 error expected): {profile_arn}")
                    return profile_arn
                else:
                    print(f"❓ Unknown error for {profile_arn}: {error_msg}")
        
        print(f"\n⚠️  No valid profile ARN found. Trying without profile ARN...")
        
        # Test without profile ARN
        try:
            response = bda_runtime.invoke_data_automation_async(
                dataAutomationConfiguration={
                    "dataAutomationProjectArn": project_arn,
                    "stage": "LIVE"
                },
                inputConfiguration={
                    's3Uri': 's3://test-bucket/test-key'
                },
                outputConfiguration={
                    's3Uri': 's3://test-bucket/test-output'
                }
            )
            print(f"✅ Works without profile ARN")
            return None
            
        except Exception as e:
            error_msg = str(e)
            if "dataAutomationProfileArn" in error_msg and "required" in error_msg:
                print(f"❌ Profile ARN is required")
            elif "bucket" in error_msg.lower():
                print(f"✅ Works without profile ARN (S3 error expected)")
                return None
            else:
                print(f"❌ Error without profile ARN: {error_msg}")
        
        return None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    result = test_bda_permissions()
    if result:
        print(f"\n🎉 Use this profile ARN: {result}")
    elif result is None:
        print(f"\n🎉 Use no profile ARN (omit the parameter)")
    else:
        print(f"\n❌ Could not determine correct profile ARN")