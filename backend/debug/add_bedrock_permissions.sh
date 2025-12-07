#!/bin/bash

ROLE_NAME="LoanUnderwriterBedrockRole"
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)

echo "Creating new role: $ROLE_NAME"

# Create trust policy for the role
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::'$ACCOUNT_ID':root"},
            "Action": "sts:AssumeRole"
        }]
    }'

# Attach admin policy
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/AdministratorAccess"

# Add Bedrock permissions
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "BedrockDataAutomationAccess" \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "bedrock-data-automation:*",
                "bedrock-data-automation-runtime:*",
                "bedrock:InvokeAgent",
                "bedrock:InvokeCodeInterpreter",
                "bedrock:GetAgentRuntimeSession"
            ],
            "Resource": "*"
        }]
    }'

echo "Role created: arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"
echo "To assume this role, run:"
echo "aws sts assume-role --role-arn arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME --role-session-name BedrockSession"