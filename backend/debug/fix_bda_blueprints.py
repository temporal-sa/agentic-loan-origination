#!/usr/bin/env python3
"""
Script to add the missing US driver license blueprint to the BDA project.
"""

import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

def add_us_driver_license_blueprint():
    """Add US driver license blueprint to the existing BDA project."""
    
    region = os.getenv("AWS_REGION", "us-west-2")
    project_arn = os.getenv("BEDROCK_DATA_AUTOMATION_PROJECT_ARN")
    
    if not project_arn:
        print("❌ BEDROCK_DATA_AUTOMATION_PROJECT_ARN not set")
        return False
    
    try:
        bda = boto3.client('bedrock-data-automation', region_name=region)
        
        # Get current project configuration
        print(f"📄 Getting current BDA project configuration...")
        project = bda.get_data_automation_project(projectArn=project_arn)
        project_info = project['project']
        
        # Get current blueprints
        current_blueprints = project_info.get('customOutputConfiguration', {}).get('blueprints', [])
        print(f"✅ Current blueprints: {len(current_blueprints)}")
        
        # Check if US driver license blueprint already exists
        us_license_blueprint = f"arn:aws:bedrock:{region}:aws:blueprint/bedrock-data-automation-public-us-driver-license"
        
        blueprint_exists = any(
            bp['blueprintArn'] == us_license_blueprint 
            for bp in current_blueprints
        )
        
        if blueprint_exists:
            print("✅ US driver license blueprint already exists")
            return True
        
        # Add the missing blueprint
        new_blueprints = current_blueprints + [{
            "blueprintArn": us_license_blueprint,
            "blueprintStage": "LIVE"
        }]
        
        print(f"🔧 Adding US driver license blueprint...")
        
        # Update the project with the new blueprint
        response = bda.update_data_automation_project(
            projectArn=project_arn,
            projectStage="LIVE",
            standardOutputConfiguration=project_info['standardOutputConfiguration'],
            customOutputConfiguration={
                "blueprints": new_blueprints
            },
            overrideConfiguration=project_info.get('overrideConfiguration', {})
        )
        
        print(f"✅ Successfully added US driver license blueprint")
        print(f"✅ Project status: {response.get('status', 'Unknown')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error updating BDA project: {e}")
        return False

if __name__ == "__main__":
    print("🔧 Adding US Driver License Blueprint to BDA Project")
    print("=" * 60)
    
    success = add_us_driver_license_blueprint()
    
    if success:
        print("\n🎉 Blueprint added successfully!")
        print("You can now process US driver license documents.")
    else:
        print("\n❌ Failed to add blueprint. Please check the error above.")
    
    exit(0 if success else 1)