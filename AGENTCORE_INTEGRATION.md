# AWS Bedrock AgentCore + Strands Integration

## Overview

This document describes the integration of **AWS Bedrock AgentCore** and **Bedrock Data Automation** into the Temporal Agentic Loan Underwriter project. The integration showcases how Temporal workflows orchestrate AI-powered document processing and financial analysis at scale.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER SUBMITS APPLICATION                      │
│                 (Streamlit UI with Document Uploads)             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  TEMPORAL WORKFLOW STARTED                       │
│                  (SupervisorWorkflow)                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  fetch_bank    │  │ fetch_docs     │  │ fetch_credit   │
│  (Strands)     │  │ (BDA OCR)      │  │ (Strands)      │
└────────────────┘  └────────────────┘  └────────────────┘
                             │
                    ┌────────┴────────┐
                    │  BEDROCK DATA   │
                    │  AUTOMATION     │
                    │  - Bank Stmt    │
                    │  - ID Card      │
                    │  - Pay Stub     │
                    │  - Address      │
                    └────────┬────────┘
                             │
                    JSON Metadata Saved
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ income_assess  │  │ expense_assess │  │ credit_assess  │
│ (AgentCore     │  │                │  │                │
│  Code Interp)  │  │                │  │                │
└────────────────┘  └────────────────┘  └────────────────┘
         │
         └────► AgentCore Code Interpreter
                - DTI Calculations
                - Trend Analysis
                - Risk Scoring
                - Python Execution
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              AGGREGATE & DECIDE (LLM Synthesis)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   HUMAN REVIEW (Streamlit UI)                    │
│                    - Approve / Reject                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Integration Points

### 1. **Document Upload (Step 1)**
**Location:** [ui/streamlit_app.py](ui/streamlit_app.py#L19-L81)

- **Feature:** File upload UI for 4 document types
  - Bank Statement (required)
  - Proof of ID (required)
  - Proof of Income (required)
  - Proof of Address (required)

- **Endpoint:** `POST /upload/{workflow_id}`
  - Saves files to `backend/uploads/{workflow_id}/`
  - Signals Temporal workflow when complete
  - Workflow resumes after document upload

**Key Code:**
```python
# Streamlit UI
bank_statement = st.file_uploader("Bank Statement (required)",
                                   type=["jpg", "jpeg", "png", "pdf"])
# ... other uploaders

# Backend saves and signals workflow
await wf.signal("documents_uploaded", {"document_paths": uploaded_files})
```

---

### 2. **Bedrock Data Automation OCR (Step 2)**
**Location:** [backend/activities.py](backend/activities.py#L65-L302)

#### **Activity:** `fetch_documents`

**Purpose:** Extract structured data from uploaded documents using AWS Bedrock Data Automation

**Features:**
- Processes local files (uploads to S3 temporarily)
- Uses public blueprints:
  - `bedrock-data-automation-public-bank-statement`
  - `bedrock-data-automation-public-us-driver-license`
  - `bedrock-data-automation-public-payslip`
- Async processing with status polling
- Saves extracted JSON to `backend/uploads/{workflow_id}/{doc_type}_extracted.json`
- Cleans up temporary S3 files after processing

**Configuration Required:**
```bash
BEDROCK_DATA_AUTOMATION_PROJECT_ARN=arn:aws:bedrock:us-east-1:123456789012:data-automation-project/your-project
AWS_S3_BUCKET=your-loan-underwriter-bucket
AWS_REGION=us-east-1
```

**Output Format:**
```json
{
  "documents": [
    {
      "type": "bank_statement",
      "status": "success",
      "extracted_data": {
        "segments": [
          {
            "matched_blueprint": "bedrock-data-automation-public-bank-statement",
            "inference_result": {
              "account_number": "...",
              "balance": "...",
              "transactions": [...]
            },
            "confidence": 0.95
          }
        ]
      },
      "json_path": "/path/to/bank_statement_extracted.json",
      "local_file": "/path/to/bank_statement.pdf"
    }
  ],
  "total_processed": 4,
  "successful": 4,
  "failed": 0
}
```

**Key Implementation:**
```python
# Invoke Bedrock Data Automation
response = bda_runtime.invoke_data_automation_async(
    dataAutomationConfiguration={
        "dataAutomationProjectArn": project_arn,
        "stage": "LIVE"
    },
    inputConfiguration={'s3Uri': f's3://{bucket}/{key}'},
    outputConfiguration={'s3Uri': f's3://{bucket}/{output}'},
    dataAutomationProfileArn=f'arn:aws:bedrock:{region}:aws:data-automation-profile/us.data-automation-v1'
)

# Poll for completion
while attempt < max_attempts:
    status_response = bda_runtime.get_data_automation_status(invocationArn=invocation_arn)
    if status_response['status'] == 'Success':
        extracted_data = _retrieve_bda_results(s3_client, output_s3_uri)
        # Save JSON locally
        break
```

---

### 3. **AgentCore Code Interpreter (Step 3)**
**Location:** [backend/activities.py](backend/activities.py#L374-L540)

#### **Activity:** `income_assessment`

**Purpose:** Sophisticated financial analysis using AgentCore Code Interpreter with Strands

**Features:**
- **DTI Ratio Calculation:** Debt-to-income analysis with 5-year loan assumptions
- **Trend Analysis:** Income stability over time from bank statements
- **Pattern Detection:** Irregular spending detection
- **Risk Scoring:** Statistical risk assessment (0-100 scale)
- **Data Validation:** Cross-validates declared income vs. bank statement data
- **Python Code Execution:** Runs calculations in sandboxed environment

**Integration Pattern:**
```python
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

# Initialize Code Interpreter
code_interpreter_tool = AgentCoreCodeInterpreter(region="us-east-1")

# Create Strands agent with tool
agent = Agent(
    model=model.get_model(),
    tools=[code_interpreter_tool.code_interpreter],
    system_prompt="""You are a financial analyst with code execution capabilities."""
)

# Execute analysis
response = agent(analysis_prompt)
```

**Analysis Prompt Template:**
```python
analysis_prompt = f"""
Analyze this loan applicant's income profile:

**Loan Application:**
- Requested Loan Amount: ${amount}
- Declared Monthly Income: ${income}
- Monthly Expenses: ${expenses}

**Bank Statement Data (from BDA):**
{json.dumps(bank_statement_extracted_data, indent=2)}

Write Python code to:
1. Calculate DTI ratio: (monthly_payment / income) * 100
2. Calculate disposable income after loan
3. Validate declared income vs. bank statement
4. Calculate risk score (0-100)
5. Determine affordability (affordable/marginal/risky)
"""
```

**Output Example:**
```json
{
  "status": "success",
  "analysis_method": "agentcore_code_interpreter",
  "income_ok": true,
  "dti_ratio": 28.5,
  "risk_score": 35,
  "affordability": "affordable",
  "raw_analysis": "Based on the analysis:\n\n1. DTI Ratio: 28.5% (Excellent - below 30% threshold)\n2. Disposable Income: $2,450/month after loan payment\n3. Income Validation: Consistent with bank statement data\n4. Risk Score: 35/100 (Low risk)\n5. Affordability: Affordable - applicant can comfortably afford monthly payments\n\nRecommendation: APPROVE"
}
```

**Fallback Strategy:**
- If AgentCore fails → Falls back to heuristic calculation
- Ensures workflow never blocks on AI service availability
- Marks result with `"analysis_method": "heuristic_fallback"`

---

## Workflow Changes

### **Phase 0: Document Upload Wait**
```python
# Wait for documents to be uploaded (10-minute timeout)
await workflow.wait_condition(lambda: self._documents_uploaded, timeout=timedelta(minutes=10))
application["document_paths"] = self._document_paths
```

### **Phase 1: Document Processing**
```python
docs = await workflow.execute_activity(
    "fetch_documents",
    application,  # Contains document_paths
    start_to_close_timeout=timedelta(minutes=15),  # OCR takes time
    retry_policy=self._default_retry_policy
)
```

### **Phase 2: Enhanced Assessment**
```python
income_task = workflow.execute_activity(
    "income_assessment",
    {"application": application, "bank": bank, "credit": credit, "documents": docs},
    start_to_close_timeout=timedelta(minutes=5),  # AgentCore needs time
    retry_policy=self._default_retry_policy
)
```

---

## Configuration

### **Environment Variables (.env)**

```bash
# AWS Region
AWS_REGION=us-east-1

# Bedrock Data Automation
BEDROCK_DATA_AUTOMATION_PROJECT_ARN=arn:aws:bedrock:us-east-1:123456789012:data-automation-project/loan-underwriter-bda
AWS_S3_BUCKET=loan-underwriter-docs-123456789012

# AWS Credentials (one of these methods)
# Method 1: AWS CLI
aws configure

# Method 2: Environment variables
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Method 3: IAM Role (if on EC2/ECS)
# Attach role with required policies
```

### **Required IAM Permissions**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeAgent",
        "bedrock:InvokeCodeInterpreter",
        "bedrock:GetAgentRuntimeSession"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-data-automation:InvokeDataAutomationAsync",
        "bedrock-data-automation:GetDataAutomationStatus",
        "bedrock-data-automation-runtime:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

---

## Setup Instructions

### **1. Create Bedrock Data Automation Project**

```bash
# Via AWS Console:
1. Go to AWS Console → Bedrock → Data Automation
2. Click "Create project"
3. Name: "loan-underwriter-bda"
4. Add public blueprints:
   - bedrock-data-automation-public-bank-statement
   - bedrock-data-automation-public-us-driver-license
   - bedrock-data-automation-public-payslip
5. Set stage to "LIVE"
6. Copy the project ARN

# Via AWS CLI:
aws bedrock-data-automation create-data-automation-project \
  --project-name loan-underwriter-bda \
  --project-stage LIVE \
  --custom-output-configuration '{"blueprints":[...]}'
```

### **2. Create S3 Bucket**

```bash
# Via AWS CLI:
aws s3 mb s3://loan-underwriter-docs-$(aws sts get-caller-identity --query Account --output text)

# Enable versioning (optional):
aws s3api put-bucket-versioning \
  --bucket loan-underwriter-docs-$(aws sts get-caller-identity --query Account --output text) \
  --versioning-configuration Status=Enabled
```

### **3. Install Dependencies**

```bash
pip install -r requirements.txt

# Key new dependencies:
# - boto3>=1.34.0 (AWS SDK)
# - bedrock-agentcore (AgentCore SDK)
# - strands-agents-tools (includes AgentCoreCodeInterpreter)
# - python-multipart>=0.0.6 (file upload support)
```

### **4. Update .env File**

```bash
cp .env.example .env
# Edit .env with your AWS configuration
```

### **5. Run the Application**

```bash
# Terminal 1: Start Temporal
temporal server start-dev

# Terminal 2: Start Worker
python -m backend.worker

# Terminal 3: Start API
uvicorn backend.main:app --reload --port 8000

# Terminal 4: Start UI
streamlit run ui/streamlit_app.py
```

---

## Testing the Integration

### **Test Document Upload**

1. Open Streamlit UI: http://localhost:8501
2. Fill in loan application details
3. Upload test documents:
   - Bank statement (PDF or image)
   - Driver's license (image)
   - Pay stub (PDF or image)
   - Utility bill for address proof (PDF or image)
4. Click "Submit Application"
5. Note the workflow ID returned

### **Monitor Processing**

```bash
# Check workflow logs
temporal workflow show --workflow-id loan-12345

# Check activity execution
temporal activity list --workflow-id loan-12345

# View workflow history
temporal workflow history --workflow-id loan-12345
```

### **Verify OCR Results**

```bash
# Check extracted JSON files
ls backend/uploads/loan-12345/
# Should see:
# - bank_statement.pdf
# - bank_statement_extracted.json
# - proof_of_id.jpg
# - proof_of_id_extracted.json
# ... etc

# View extracted data
cat backend/uploads/loan-12345/bank_statement_extracted.json | jq
```

### **Review Financial Analysis**

```bash
# In Streamlit UI, go to "Review" tab
# Enter workflow ID
# Click "Fetch Loan Details"
# View AI Analysis Summary showing:
# - DTI ratio
# - Risk score
# - Affordability assessment
# - Raw AgentCore analysis
```

---

## Demo Narrative

> *"This loan underwriting system showcases the cutting edge of AI orchestration:*
>
> - **Temporal** provides the durable workflow layer - handling retries, failures, human-in-the-loop, and long-running processes
> - **Strands Agents** deliver intelligent data fetching and reasoning for API interactions
> - **AWS Bedrock Data Automation** extracts structured data from documents with industry-specific blueprints
> - **AWS Bedrock AgentCore Code Interpreter** performs complex financial calculations with Python code execution
>
> *Together, they demonstrate how enterprises can build production AI systems that are **reliable** (Temporal), **intelligent** (Strands + Bedrock), and **scalable** (AgentCore)."*

---

## Key Benefits

### **1. Temporal Orchestration**
✅ Durable execution survives crashes
✅ Automatic retries for transient failures
✅ Human-in-the-loop with signals/queries
✅ Complete audit trail
✅ 10-minute wait for document upload without resource consumption

### **2. Bedrock Data Automation**
✅ Production-ready OCR with industry blueprints
✅ Structured data extraction (not just text)
✅ Confidence scores for validation
✅ Automatic document classification
✅ Multi-page document splitting

### **3. AgentCore Code Interpreter**
✅ Secure Python code execution
✅ Complex financial calculations (DTI, trends, risk)
✅ LLM reasoning + computational precision
✅ Strands integration for agentic workflows
✅ Fallback to heuristics if unavailable

### **4. Production Architecture**
✅ Local file processing (no permanent S3 storage required)
✅ Graceful error handling and fallbacks
✅ Comprehensive logging and observability
✅ Modular design for easy extension
✅ Configuration-driven setup

---

## Troubleshooting

### **BDA Processing Fails**

**Error:** `BEDROCK_DATA_AUTOMATION_PROJECT_ARN environment variable not set`

**Solution:**
1. Verify project ARN in `.env` file
2. Ensure project stage is "LIVE"
3. Check IAM permissions for `bedrock-data-automation:*`

### **AgentCore Code Interpreter Fails**

**Error:** `Code interpreter invocation failed`

**Solution:**
1. Check IAM permissions for `bedrock:InvokeCodeInterpreter`
2. Verify region matches Bedrock setup
3. Check CloudWatch logs for detailed error
4. System will fall back to heuristic calculation

### **Document Upload Timeout**

**Error:** `Workflow timeout waiting for documents`

**Solution:**
1. Default timeout is 10 minutes
2. Ensure documents are uploaded within window
3. Check network connectivity
4. Verify workflow signal is sent from upload endpoint

### **S3 Upload Fails**

**Error:** `S3 upload failed for bank_statement`

**Solution:**
1. Verify bucket exists: `aws s3 ls s3://your-bucket-name`
2. Check IAM permissions for S3 write
3. Ensure bucket is in same region as Bedrock
4. Check bucket policies don't block access

---

## File Structure

```
temporal-agentic-loan-underwriter/
├── backend/
│   ├── activities.py           # ✨ Updated: BDA + AgentCore integration
│   ├── workflows.py            # ✨ Updated: Document wait + enhanced payloads
│   ├── main.py                 # ✨ Updated: File upload endpoint
│   ├── uploads/                # ✨ New: Local document storage
│   │   └── {workflow_id}/
│   │       ├── bank_statement.pdf
│   │       ├── bank_statement_extracted.json
│   │       ├── proof_of_id.jpg
│   │       └── proof_of_id_extracted.json
├── ui/
│   └── streamlit_app.py        # ✨ Updated: File upload UI
├── .env.example                # ✨ Updated: AWS configuration
├── requirements.txt            # ✨ Updated: New dependencies
├── .gitignore                  # ✨ Updated: Ignore uploads/
└── AGENTCORE_INTEGRATION.md    # ✨ New: This document
```

---

## Next Steps

### **Enhancements**
1. Add expense assessment with AgentCore for bank statement debit analysis
2. Implement AgentCore Memory for applicant history across applications
3. Add AgentCore Browser Tool for employment verification
4. Create multi-agent runtime for specialized credit analysis
5. Implement AgentCore Gateway for API tool discovery

### **Production Readiness**
1. Add comprehensive error handling
2. Implement monitoring and alerts
3. Set up CloudWatch dashboards
4. Configure auto-scaling for workers
5. Add security scanning for uploaded documents

---

## Support

For questions or issues:
1. Check troubleshooting section above
2. Review AWS Bedrock documentation: https://docs.aws.amazon.com/bedrock/
3. Review AgentCore samples: https://github.com/awslabs/amazon-bedrock-agentcore-samples
4. Open an issue in the repository

---

**Last Updated:** 2025-01-11
**Integration Version:** 1.0
**AWS Bedrock Data Automation:** Production
**AWS Bedrock AgentCore:** Production
