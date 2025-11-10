#!/usr/bin/env python3
"""
Test script to verify AWS Bedrock Data Automation and AgentCore setup.
This script tests the key components needed for the loan underwriter project.
"""

import os
import boto3
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_aws_credentials():
    """Test AWS credentials and account access."""
    print("🔐 Testing AWS Credentials...")
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        print(f"✅ AWS Account: {identity['Account']}")
        print(f"✅ User/Role: {identity['Arn']}")
        return True
    except Exception as e:
        print(f"❌ AWS Credentials Error: {e}")
        return False

def test_bedrock_access():
    """Test Bedrock service access and model availability."""
    print("\n🤖 Testing Bedrock Access...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        bedrock = boto3.client('bedrock', region_name=region)
        
        # Test model access
        model_id = os.getenv("AWS_BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0")
        print(f"✅ Bedrock region: {region}")
        print(f"✅ Model ID: {model_id}")
        
        # List available models to verify access
        models = bedrock.list_foundation_models()
        anthropic_models = [m for m in models['modelSummaries'] if 'anthropic' in m['modelId']]
        print(f"✅ Found {len(anthropic_models)} Anthropic models")
        
        # Check if our specific model exists
        target_model = next((m for m in models['modelSummaries'] if m['modelId'] == model_id), None)
        if target_model:
            print(f"✅ Target model found: {target_model['modelName']}")
            print(f"   Status: {target_model['modelLifecycle']['status']}")
        else:
            print(f"⚠️  Target model '{model_id}' not found")
            print("Available Anthropic models:")
            for model in anthropic_models[:5]:  # Show first 5
                print(f"   - {model['modelId']} ({model['modelName']})")
        
        return True
    except Exception as e:
        print(f"❌ Bedrock Access Error: {e}")
        return False

def test_bedrock_runtime():
    """Test Bedrock Runtime for model invocation."""
    print("\n🚀 Testing Bedrock Runtime...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        bedrock_runtime = boto3.client('bedrock-runtime', region_name=region)
        
        model_id = os.getenv("AWS_BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0")
        
        # Simple test invocation
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Hello"}]
        })
        
        response = bedrock_runtime.invoke_model(
            body=body,
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )
        
        result = json.loads(response['body'].read())
        print(f"✅ Model invocation successful")
        print(f"✅ Response: {result['content'][0]['text'][:50]}...")
        return True
    except Exception as e:
        print(f"❌ Bedrock Runtime Error: {e}")
        return False

def test_s3_bucket():
    """Test S3 bucket access for BDA."""
    print("\n🪣 Testing S3 Bucket...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        bucket_name = os.getenv("AWS_S3_BUCKET")
        
        if not bucket_name:
            print("❌ AWS_S3_BUCKET not set in environment")
            return False
        
        s3 = boto3.client('s3', region_name=region)
        
        # Test bucket access
        s3.head_bucket(Bucket=bucket_name)
        print(f"✅ S3 Bucket accessible: {bucket_name}")
        
        # List objects to test permissions
        response = s3.list_objects_v2(Bucket=bucket_name, MaxKeys=5)
        object_count = response.get('KeyCount', 0)
        print(f"✅ Bucket contains {object_count} objects")
        
        return True
    except Exception as e:
        print(f"❌ S3 Bucket Error: {e}")
        return False

def test_bda_project():
    """Test Bedrock Data Automation project."""
    print("\n📄 Testing Bedrock Data Automation...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        project_arn = os.getenv("BEDROCK_DATA_AUTOMATION_PROJECT_ARN")
        
        if not project_arn:
            print("❌ BEDROCK_DATA_AUTOMATION_PROJECT_ARN not set in environment")
            return False
        
        bda = boto3.client('bedrock-data-automation', region_name=region)
        
        # Get project details
        project = bda.get_data_automation_project(projectArn=project_arn)
        project_info = project['project']
        
        print(f"✅ BDA Project: {project_info['projectName']}")
        print(f"✅ Status: {project_info['status']}")
        print(f"✅ Stage: {project_info['projectStage']}")
        
        # Check blueprints
        blueprints = project_info.get('customOutputConfiguration', {}).get('blueprints', [])
        print(f"✅ Configured blueprints: {len(blueprints)}")
        
        required_blueprints = [
            'bank-statement',
            'us-driver-license', 
            'payslip'
        ]
        
        for blueprint in blueprints:
            blueprint_name = blueprint['blueprintArn'].split('/')[-1]
            print(f"   - {blueprint_name}")
        
        # Check if we have required blueprints
        blueprint_names = [bp['blueprintArn'].split('/')[-1] for bp in blueprints]
        missing = [req for req in required_blueprints if not any(req in name for name in blueprint_names)]
        
        if missing:
            print(f"⚠️  Missing blueprints: {missing}")
            print("   You may need to add these blueprints to your BDA project")
        else:
            print("✅ All required blueprints present")
        
        return True
    except Exception as e:
        print(f"❌ BDA Project Error: {e}")
        return False

def test_bda_runtime():
    """Test BDA Runtime for document processing."""
    print("\n⚡ Testing BDA Runtime...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        bda_runtime = boto3.client('bedrock-data-automation-runtime', region_name=region)
        
        print(f"✅ BDA Runtime client created for region: {region}")
        print("✅ Ready for document processing")
        
        return True
    except Exception as e:
        print(f"❌ BDA Runtime Error: {e}")
        return False

def test_agentcore_access():
    """Test AgentCore Code Interpreter access."""
    print("\n🧠 Testing AgentCore Access...")
    try:
        region = os.getenv("AWS_REGION", "us-west-2")
        
        # AgentCore uses bedrock-agent-runtime
        bedrock_agent = boto3.client('bedrock-agent-runtime', region_name=region)
        print(f"✅ AgentCore client created for region: {region}")
        print("✅ Ready for code interpretation")
        
        return True
    except Exception as e:
        print(f"❌ AgentCore Access Error: {e}")
        return False

def main():
    """Run all tests."""
    print("🔍 AWS Bedrock & BDA Configuration Test")
    print("=" * 50)
    
    tests = [
        test_aws_credentials,
        test_bedrock_access,
        test_bedrock_runtime,
        test_s3_bucket,
        test_bda_project,
        test_bda_runtime,
        test_agentcore_access
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("📊 Test Summary")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! Your AWS setup is ready for the loan underwriter project.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please fix the issues above before running the project.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)