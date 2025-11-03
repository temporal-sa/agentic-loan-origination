from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import os
import json
from pathlib import Path
from time import sleep
from utilities import model
from strands import Agent
from strands.models.ollama import OllamaModel
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from classes.agents import DataFetchAgent, CreditReportAgent
import boto3
from botocore.exceptions import ClientError


# ============================================================================
# DATA ACQUISITION PHASE - Strands HTTP Agents
# ============================================================================
# These activities demonstrate Strands agents making HTTP requests to external
# APIs with intelligent error handling and data validation. The agents can:
# - Make HTTP requests with proper error handling
# - Parse and validate API responses
# - Provide context-aware error messages
# - Handle malformed data gracefully
# ============================================================================


@activity.defn
async def fetch_bank_account(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch bank account data using Strands HTTP agent.

    ARCHITECTURE NOTE:
    - Temporal Activity (Outer Loop): Handles retries, timeouts, durability
    - Strands Agent (Inner Loop): Makes HTTP request, validates data

    This demonstrates the separation of concerns:
    - Temporal ensures the activity eventually succeeds/fails reliably
    - Strands agent handles the intelligent data fetching logic
    """
    try:
        # Initialize Strands agent for this activity execution
        data_agent = DataFetchAgent()

        # Agent fetches data from bank API
        url = f"http://localhost:3233/bank?applicant_id={applicant_id}"
        bank_data = data_agent.fetch_data(url, "bank account")

        # Validate essential fields
        if "accounts" not in bank_data:
            raise ValueError("Bank API response missing 'accounts' field")

        return bank_data

    except Exception as e:
        # Raise ApplicationError to trigger Temporal's retry mechanism
        # Temporal will retry this activity based on the workflow's retry policy
        raise ApplicationError(
            f"Failed to fetch bank account data: {str(e)}",
            type="BankAPIError",
            non_retryable=False  # Allow Temporal to retry
        )


@activity.defn
async def fetch_documents(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process uploaded documents using AWS Bedrock Data Automation (local files).

    ARCHITECTURE NOTE:
    - Temporal Activity: Provides durable execution and retry logic for OCR processing
    - Bedrock Data Automation: Extracts structured data from documents (bank statements, IDs, etc.)
    - Output: Saves extracted JSON metadata to backend/uploads/{workflow_id}/ for each document
    - Works directly with local files - automatically uploads to S3 only during processing

    This activity uses:
    - Public blueprints: bank-statement, us-driver-license, payslip
    - Custom extraction schemas for structured data
    - Async processing with status polling
    """
    try:
        applicant_id = payload.get("applicant_id")
        document_paths = payload.get("document_paths", {})

        if not document_paths:
            activity.logger.warning("No document paths provided, skipping OCR processing")
            return {"documents": [], "status": "no_documents_uploaded"}

        activity.logger.info(f"Processing {len(document_paths)} documents with Bedrock Data Automation")

        # Initialize AWS clients
        region_name = os.getenv("AWS_REGION", "us-east-1")
        s3_client = boto3.client('s3', region_name=region_name)
        bda_runtime = boto3.client('bedrock-data-automation-runtime', region_name=region_name)

        # Get S3 bucket (temporary storage for BDA processing)
        bucket_name = os.getenv("AWS_S3_BUCKET")
        if not bucket_name:
            activity.logger.warning("AWS_S3_BUCKET not set, will use temporary S3 bucket")
            # You can create a temporary bucket or use a default one
            bucket_name = f"loan-underwriter-temp-{applicant_id[:8]}"

        # Get Data Automation project ARN
        project_arn = os.getenv("BEDROCK_DATA_AUTOMATION_PROJECT_ARN")
        if not project_arn:
            raise ValueError("BEDROCK_DATA_AUTOMATION_PROJECT_ARN environment variable not set. "
                           "Please create a BDA project with bank-statement, us-driver-license, and payslip blueprints.")

        processed_documents = []

        # Process each document type
        for doc_type, local_path in document_paths.items():
            activity.logger.info(f"Processing {doc_type}: {local_path}")

            file_path = Path(local_path)

            # Read file as bytes for direct processing
            try:
                with open(file_path, 'rb') as f:
                    file_bytes = f.read()

                activity.logger.info(f"Read {len(file_bytes)} bytes from {doc_type}")

                # For BDA, we need to temporarily upload to S3 (BDA requirement)
                # But we'll clean it up after processing
                s3_key = f"loan-underwriter-temp/input/{applicant_id}/{file_path.name}"
                s3_output_prefix = f"loan-underwriter-temp/output/{applicant_id}/{doc_type}"

                try:
                    s3_client.upload_fileobj(
                        open(file_path, 'rb'),
                        bucket_name,
                        s3_key
                    )
                    activity.logger.info(f"Temporarily uploaded {doc_type} to S3 for BDA processing")
                except Exception as upload_error:
                    activity.logger.error(f"S3 upload failed for {doc_type}: {upload_error}")
                    processed_documents.append({
                        "type": doc_type,
                        "status": "upload_failed",
                        "error": str(upload_error)
                    })
                    continue

                # Invoke Bedrock Data Automation
                response = bda_runtime.invoke_data_automation_async(
                    dataAutomationConfiguration={
                        "dataAutomationProjectArn": project_arn,
                        "stage": "LIVE"
                    },
                    inputConfiguration={
                        's3Uri': f's3://{bucket_name}/{s3_key}'
                    },
                    outputConfiguration={
                        's3Uri': f's3://{bucket_name}/{s3_output_prefix}'
                    },
                    dataAutomationProfileArn=f'arn:aws:bedrock:{region_name}:aws:data-automation-profile/us.data-automation-v1'
                )

                invocation_arn = response['invocationArn']
                activity.logger.info(f"Started BDA processing for {doc_type}: {invocation_arn}")

                # Poll for completion (with timeout)
                max_attempts = 60  # 10 minutes max
                attempt = 0
                while attempt < max_attempts:
                    status_response = bda_runtime.get_data_automation_status(
                        invocationArn=invocation_arn
                    )

                    status = status_response['status']
                    if status == 'Success':
                        activity.logger.info(f"BDA processing completed for {doc_type}")

                        # Retrieve and parse results
                        output_s3_uri = status_response['outputConfiguration']['s3Uri']
                        extracted_data = _retrieve_bda_results(s3_client, output_s3_uri)

                        # Save JSON to local uploads directory (same folder as original file)
                        json_path = file_path.parent / f"{doc_type}_extracted.json"
                        with open(json_path, 'w') as f:
                            json.dump(extracted_data, f, indent=2)

                        activity.logger.info(f"Saved extracted data to {json_path}")

                        # Clean up temporary S3 files
                        try:
                            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
                            activity.logger.info(f"Cleaned up temporary S3 file: {s3_key}")
                        except Exception as cleanup_error:
                            activity.logger.warning(f"Failed to cleanup S3 file: {cleanup_error}")

                        processed_documents.append({
                            "type": doc_type,
                            "status": "success",
                            "extracted_data": extracted_data,
                            "json_path": str(json_path),
                            "local_file": str(file_path)
                        })
                        break
                    elif status in ['Failed', 'Cancelled']:
                        error_msg = status_response.get('errorMessage', 'Unknown error')
                        activity.logger.error(f"BDA processing failed for {doc_type}: {error_msg}")
                        processed_documents.append({
                            "type": doc_type,
                            "status": "processing_failed",
                            "error": error_msg
                        })
                        break
                    else:
                        # Still in progress
                        activity.logger.info(f"BDA processing {doc_type}: {status} (attempt {attempt + 1}/{max_attempts})")
                        sleep(10)
                        attempt += 1

                if attempt >= max_attempts:
                    activity.logger.error(f"BDA processing timeout for {doc_type}")
                    processed_documents.append({
                        "type": doc_type,
                        "status": "timeout",
                        "error": "Processing exceeded maximum wait time"
                    })

            except ClientError as bda_error:
                activity.logger.error(f"BDA invocation failed for {doc_type}: {bda_error}")
                processed_documents.append({
                    "type": doc_type,
                    "status": "invocation_failed",
                    "error": str(bda_error)
                })
            except Exception as file_error:
                activity.logger.error(f"File processing failed for {doc_type}: {file_error}")
                processed_documents.append({
                    "type": doc_type,
                    "status": "file_error",
                    "error": str(file_error)
                })

        return {
            "documents": processed_documents,
            "total_processed": len(processed_documents),
            "successful": len([d for d in processed_documents if d.get("status") == "success"]),
            "failed": len([d for d in processed_documents if d.get("status") != "success"])
        }

    except Exception as e:
        activity.logger.error(f"Document processing failed: {str(e)}")
        raise ApplicationError(
            f"Failed to process documents: {str(e)}",
            type="DocumentProcessingError",
            non_retryable=False
        )


def _retrieve_bda_results(s3_client, s3_uri: str) -> Dict[str, Any]:
    """
    Helper function to retrieve and parse Bedrock Data Automation results from S3.

    Args:
        s3_client: boto3 S3 client
        s3_uri: S3 URI of the output (s3://bucket/key)

    Returns:
        Parsed JSON containing extracted document data
    """
    # Parse S3 URI
    parts = s3_uri.replace('s3://', '').split('/')
    bucket = parts[0]
    key = '/'.join(parts[1:])

    # Fetch JSON from S3
    response = s3_client.get_object(Bucket=bucket, Key=key)
    job_result = json.loads(response['Body'].read())

    # Extract structured data from BDA output
    extracted_results = []

    if 'output_metadata' in job_result:
        for output_meta in job_result['output_metadata']:
            segment_metadata = output_meta.get('segment_metadata', [])

            for segment in segment_metadata:
                custom_output_path = segment.get('custom_output_path')
                if custom_output_path:
                    # Fetch the custom output
                    custom_parts = custom_output_path.replace('s3://', '').split('/')
                    custom_bucket = custom_parts[0]
                    custom_key = '/'.join(custom_parts[1:])

                    custom_response = s3_client.get_object(Bucket=custom_bucket, Key=custom_key)
                    custom_data = json.loads(custom_response['Body'].read())

                    extracted_results.append({
                        "matched_blueprint": custom_data.get("matched_blueprint"),
                        "inference_result": custom_data.get("inference_result"),
                        "confidence": custom_data.get("confidence_score")
                    })

    return {
        "segments": extracted_results,
        "raw_output": job_result
    }


@activity.defn
async def fetch_credit_report_cibil(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch credit report from CIBIL bureau using Strands agent.

    ARCHITECTURE NOTE - TEMPORAL'S FALLBACK PATTERN:
    - This activity is configured with LIMITED retries in the workflow
    - If it fails, Temporal orchestrates the fallback to Experian
    - The workflow layer handles the provider fallback logic
    - The agent layer handles data fetching and validation

    This demonstrates:
    - Temporal: Provider-level fallback orchestration (CIBIL -> Experian)
    - Strands: Data-level validation and quality checking
    """
    try:

        # Initialize credit report agent
        credit_agent = CreditReportAgent()

        # Fetch and validate from CIBIL
        url = f"http://localhost:3233/cibil?applicant_id={applicant_id}"
        credit_data = credit_agent.fetch_and_validate_credit_report(
            applicant_id, "CIBIL", url
        )

        return credit_data

    except Exception as e:
        # Temporal will try Experian as fallback (see workflow)
        raise ApplicationError(
            f"Failed to fetch CIBIL credit report: {str(e)}",
            type="CibilAPIError",
            non_retryable=False
        )


@activity.defn
async def fetch_credit_report_experian(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch credit report from Experian bureau using Strands agent.

    ARCHITECTURE NOTE - FALLBACK PROVIDER:
    - This activity is called by Temporal when CIBIL fails
    - Demonstrates Temporal's orchestration of fallback strategies
    - The agent validates data the same way, ensuring consistency
    """
    try:

        # Initialize credit report agent (same validation logic)
        credit_agent = CreditReportAgent()

        # Fetch and validate from Experian
        url = f"http://localhost:3233/experian?applicant_id={applicant_id}"
        credit_data = credit_agent.fetch_and_validate_credit_report(
            applicant_id, "Experian", url
        )

        return credit_data

    except Exception as e:
        # Both providers failed - workflow will handle final failure
        raise ApplicationError(
            f"Failed to fetch Experian credit report: {str(e)}",
            type="ExperianAPIError",
            non_retryable=False
        )

@activity.defn
async def income_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform sophisticated income assessment using AgentCore Code Interpreter.

    ARCHITECTURE NOTE:
    - Temporal Activity: Provides durable execution
    - AgentCore Code Interpreter: Executes Python code for financial calculations
    - Strands Agent: Orchestrates analysis with LLM reasoning
    - Bedrock Data Automation: Extracted bank statement data (from fetch_documents)

    This replaces simple heuristics with:
    - DTI (Debt-to-Income) ratio analysis
    - Income trend analysis over time
    - Spending pattern detection
    - Statistical risk scoring
    - Validation against bank account data
    """
    try:
        app = payload.get("application", {})
        bank = payload.get("bank", {})
        docs = payload.get("documents", {})

        activity.logger.info("Starting income assessment with AgentCore Code Interpreter")

        # Extract bank statement data from BDA results
        bank_statement_data = None
        if docs and isinstance(docs, dict):
            processed_docs = docs.get("documents", [])
            for doc in processed_docs:
                if doc.get("type") == "bank_statement" and doc.get("status") == "success":
                    bank_statement_data = doc.get("extracted_data", {})
                    activity.logger.info(f"Found extracted bank statement data: {bank_statement_data}")
                    break

        # Initialize AgentCore Code Interpreter
        region_name = os.getenv("AWS_REGION", "us-east-1")
        code_interpreter_tool = AgentCoreCodeInterpreter(region=region_name)

        # Create Strands agent with code interpreter tool
        SYSTEM_PROMPT = """You are a financial analyst specializing in loan underwriting.
You have access to a Python code interpreter to perform complex financial calculations.
When analyzing income and loan affordability, write Python code to:
1. Calculate debt-to-income (DTI) ratios
2. Analyze income trends over time
3. Detect irregular spending patterns
4. Calculate statistical risk scores
5. Validate data consistency between sources

Always execute calculations using code to ensure accuracy."""

        agent = Agent(
            model=model.get_model(),
            tools=[code_interpreter_tool.code_interpreter],
            system_prompt=SYSTEM_PROMPT
        )

        # Prepare comprehensive financial data
        analysis_prompt = f"""
Analyze this loan applicant's income profile and calculate a comprehensive risk assessment:

**Loan Application:**
- Applicant ID: {app.get('applicant_id')}
- Requested Loan Amount: ${app.get('amount', 0):,.2f}
- Declared Monthly Income: ${app.get('income', 0):,.2f}
- Monthly Expenses: ${app.get('expenses', 0):,.2f}

**Bank Account Data:**
- Account Balance: ${bank.get('accounts', [{}])[0].get('balance', 0):,.2f if bank.get('accounts') else 0}
- Account Type: {bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'}

**Bank Statement Extracted Data (Bedrock Data Automation):**
{json.dumps(bank_statement_data, indent=2) if bank_statement_data else "No bank statement data available"}

**Analysis Required:**
Write Python code to:
1. Calculate monthly DTI ratio: (monthly_loan_payment / monthly_income) * 100
   - Assume 5% APR, loan term of 5 years for monthly payment calculation
   - DTI < 30% is excellent, 30-40% acceptable, >40% risky

2. Calculate disposable income after loan: income - expenses - monthly_loan_payment

3. Validate declared income against bank statement data (if available)
   - Check for consistency
   - Flag any discrepancies > 20%

4. Calculate income stability risk score (0-100, where 0 is lowest risk):
   - If bank statement shows consistent deposits: lower risk
   - If income varies significantly: higher risk

5. Determine loan affordability: Can applicant afford monthly payments?

Return a structured analysis with:
- DTI ratio (percentage)
- Disposable income after loan
- Income validation result (consistent/discrepancy/no_data)
- Risk score (0-100)
- Affordability assessment (affordable/marginal/risky)
- Detailed reasoning
"""

        # Execute analysis with AgentCore Code Interpreter
        activity.logger.info("Invoking AgentCore Code Interpreter for income analysis...")
        response = agent(analysis_prompt)

        # Extract response
        response_text = str(response.message["content"][0]["text"]) if response.message else "No response"
        activity.logger.info(f"AgentCore analysis completed: {response_text[:500]}...")

        # Parse the response to extract structured data
        # The agent should provide structured output, but we'll extract key metrics
        result = {
            "status": "success",
            "analysis_method": "agentcore_code_interpreter",
            "raw_analysis": response_text,
            "income": app.get("income"),
            "loan_amount": app.get("amount"),
        }

        # Try to extract key metrics from response (simple parsing)
        if "DTI" in response_text or "dti" in response_text.lower():
            # Extract DTI ratio if present
            import re
            dti_match = re.search(r'DTI[:\s]+([0-9.]+)%?', response_text, re.IGNORECASE)
            if dti_match:
                dti_ratio = float(dti_match.group(1))
                result["dti_ratio"] = dti_ratio
                result["income_ok"] = dti_ratio < 40  # DTI < 40% is acceptable

        # Extract risk score if present
        risk_match = re.search(r'risk[_ ]score[:\s]+([0-9.]+)', response_text, re.IGNORECASE)
        if risk_match:
            result["risk_score"] = float(risk_match.group(1))

        # Extract affordability
        if "affordable" in response_text.lower():
            result["affordability"] = "affordable"
        elif "risky" in response_text.lower():
            result["affordability"] = "risky"
        else:
            result["affordability"] = "marginal"

        # Fallback: if no structured data extracted, use basic heuristic
        if "income_ok" not in result:
            balance = bank.get("accounts", [{}])[0].get("balance", 0) if bank.get("accounts") else 0
            ratio = app.get("income", 5000) / max(app.get("amount", 1000), 1)
            result["income_ok"] = ratio > 2 or balance > 5000
            result["fallback_method"] = "heuristic"

        activity.logger.info(f"Income assessment result: {result}")
        return result

    except Exception as e:
        activity.logger.error(f"Income assessment failed: {str(e)}")
        # Fallback to basic heuristic if AgentCore fails
        app = payload.get("application", {})
        bank = payload.get("bank", {})
        balance = bank.get("accounts", [{}])[0].get("balance", 0) if bank.get("accounts") else 0
        ratio = app.get("income", 5000) / max(app.get("amount", 1000), 1)

        return {
            "income_ok": ratio > 2 or balance > 5000,
            "income": app.get("income"),
            "status": "fallback",
            "error": str(e),
            "analysis_method": "heuristic_fallback"
        }


@activity.defn
async def expense_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    # TODO: this needs to use bedrock document automation using bank statement debits

    app = payload.get("application", {})
    bank = payload.get("bank", {})
    expenses = app.get("expenses", 1000)
    disposable = app.get("income", 5000) - expenses
    result = {"affordability_ok": disposable > app.get("amount", 1000) / 12, "expenses": expenses}
    return result


@activity.defn
async def credit_assessment(payload: Dict[str, Any]) -> Dict[str, Any]:
    credit = payload.get("credit", {})
    score = credit.get("score", 600)
    result = {"credit_ok": score > 620, "score": score}
    return result


@activity.defn
async def aggregate_and_decide(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        agent = Agent(model=model.get_model())

        prompt_data = {
            "application": payload.get("application"),
            "assessments": payload.get("income"),
            "expense": payload.get("expense"),
            "credit": payload.get("credit"),
        }
        text = f"You are a smart loan underwriting analyst. You have to understand all data, reason step by step and provide decision. Summarize and give a suggested decision for this loan: {prompt_data}"
        agent_response = agent(text)
        explanation = str(agent_response) if agent_response is not None else "No response from agent"
        llm_error = False

    except Exception as e:
        raise ApplicationError(
            f"Ollama LLM call failed: {str(e)}",
            type="OllamaLLMError",
            non_retryable=False
        )

    recommendation = (
        "manual_review"
        if llm_error
        else ("approve" if payload.get("credit", {}).get("score", 600) > 650 else "manual_review")
    )

    # Standardized decision contract returned to the workflow/UI
    decision = {
        "recommendation": recommendation,
        "explanation": explanation,
        "llm_error": llm_error,
        # include raw output for debugging / inspection
        "raw_output": explanation,
    }
    return decision
