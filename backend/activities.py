from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import os
import json
from pathlib import Path
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
async def trigger_document_processing(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger async BDA processing for a single document.

    ARCHITECTURE NOTE:
    - Temporal Activity: Triggers BDA processing and returns immediately
    - Async Pattern: Returns invocation ARN for status polling in workflow
    - This enables Temporal's durable timer sleep instead of blocking activity

    This activity:
    - Uploads document to S3
    - Invokes BDA async processing
    - Returns invocation ARN for tracking
    """
    try:
        applicant_id = payload.get("applicant_id")
        doc_type = payload.get("doc_type")
        local_path = payload.get("local_path")

        activity.logger.info(f"Triggering BDA processing for {doc_type}: {local_path}")

        # Initialize AWS clients
        region_name = os.getenv("AWS_REGION", "us-east-1")
        s3_client = boto3.client('s3', region_name=region_name)
        bda_runtime = boto3.client('bedrock-data-automation-runtime', region_name=region_name)

        # Get S3 bucket
        bucket_name = os.getenv("AWS_S3_BUCKET")
        if not bucket_name:
            activity.logger.warning("AWS_S3_BUCKET not set, using temporary bucket name")
            bucket_name = f"loan-underwriter-temp-{applicant_id[:8]}"

        # Get Data Automation project ARN
        project_arn = os.getenv("BEDROCK_DATA_AUTOMATION_PROJECT_ARN")
        if not project_arn:
            raise ValueError("BEDROCK_DATA_AUTOMATION_PROJECT_ARN environment variable not set.")

        file_path = Path(local_path)

        # Upload to S3
        s3_key = f"loan-underwriter-temp/input/{applicant_id}/{file_path.name}"
        s3_output_prefix = f"loan-underwriter-temp/output/{applicant_id}/{doc_type}"

        try:
            with open(file_path, 'rb') as f:
                s3_client.upload_fileobj(f, bucket_name, s3_key)
            activity.logger.info(f"Uploaded {doc_type} to S3: s3://{bucket_name}/{s3_key}")
        except Exception as upload_error:
            raise ApplicationError(
                f"S3 upload failed for {doc_type}: {str(upload_error)}",
                type="S3UploadError",
                non_retryable=False
            )

        # Invoke Bedrock Data Automation (async)
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

        return {
            "doc_type": doc_type,
            "invocation_arn": invocation_arn,
            "s3_key": s3_key,
            "bucket_name": bucket_name,
            "local_path": local_path,
            "status": "triggered"
        }

    except ClientError as e:
        raise ApplicationError(
            f"BDA invocation failed for {doc_type}: {str(e)}",
            type="BDAInvocationError",
            non_retryable=False
        )
    except Exception as e:
        raise ApplicationError(
            f"Failed to trigger document processing: {str(e)}",
            type="DocumentTriggerError",
            non_retryable=False
        )


@activity.defn
async def check_document_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check status of BDA processing for a single document.

    ARCHITECTURE NOTE:
    - Temporal Activity: Checks current status (non-blocking)
    - Called by workflow in a loop with durable timer sleep
    - Returns status and extracted data when complete

    This activity:
    - Polls BDA status using invocation ARN
    - Returns status: 'InProgress', 'Success', 'Failed', 'Cancelled'
    - Retrieves and saves extracted data when successful
    """
    try:
        invocation_arn = payload.get("invocation_arn")
        doc_type = payload.get("doc_type")
        local_path = payload.get("local_path")
        s3_key = payload.get("s3_key")
        bucket_name = payload.get("bucket_name")

        # Initialize AWS clients
        region_name = os.getenv("AWS_REGION", "us-east-1")
        s3_client = boto3.client('s3', region_name=region_name)
        bda_runtime = boto3.client('bedrock-data-automation-runtime', region_name=region_name)

        # Check status
        status_response = bda_runtime.get_data_automation_status(
            invocationArn=invocation_arn
        )

        status = status_response['status']
        activity.logger.info(f"BDA status for {doc_type}: {status}")

        if status == 'Success':
            # Retrieve and parse results
            output_s3_uri = status_response['outputConfiguration']['s3Uri']
            extracted_data = _retrieve_bda_results(s3_client, output_s3_uri)

            # Save JSON to local uploads directory
            file_path = Path(local_path)
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

            return {
                "doc_type": doc_type,
                "status": "success",
                "extracted_data": extracted_data,
                "json_path": str(json_path),
                "local_file": str(file_path)
            }

        elif status in ['Failed', 'Cancelled']:
            error_msg = status_response.get('errorMessage', 'Unknown error')
            activity.logger.error(f"BDA processing failed for {doc_type}: {error_msg}")
            return {
                "doc_type": doc_type,
                "status": "failed",
                "error": error_msg
            }

        else:
            # Still in progress
            return {
                "doc_type": doc_type,
                "status": "in_progress"
            }

    except ClientError as e:
        raise ApplicationError(
            f"Failed to check BDA status for {doc_type}: {str(e)}",
            type="BDAStatusCheckError",
            non_retryable=False
        )
    except Exception as e:
        raise ApplicationError(
            f"Failed to check document status: {str(e)}",
            type="DocumentStatusError",
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
    """
    Perform sophisticated expense assessment using AgentCore Code Interpreter.

    ARCHITECTURE NOTE:
    - Temporal Activity: Provides durable execution
    - AgentCore Code Interpreter: Executes Python code for spending pattern analysis
    - Strands Agent: Orchestrates behavioral analysis with LLM reasoning
    - Bedrock Data Automation: Extracted bank statement data (from fetch_documents)

    This analyzes spending behavior and financial discipline:
    - Spending velocity and patterns
    - Expense categorization from bank statements
    - Financial stress indicators
    - Behavioral risk assessment
    - Cross-validation with declared expenses
    """
    try:
        app = payload.get("application", {})
        bank = payload.get("bank", {})
        docs = payload.get("documents", {})

        activity.logger.info("Starting expense assessment with AgentCore Code Interpreter")

        # Extract bank statement data from BDA results
        bank_statement_data = None
        if docs and isinstance(docs, dict):
            processed_docs = docs.get("documents", [])
            for doc in processed_docs:
                if doc.get("type") == "bank_statement" and doc.get("status") == "success":
                    bank_statement_data = doc.get("extracted_data", {})
                    activity.logger.info(f"Found bank statement for expense analysis")
                    break

        # Initialize AgentCore Code Interpreter
        region_name = os.getenv("AWS_REGION", "us-east-1")
        code_interpreter_tool = AgentCoreCodeInterpreter(region=region_name)

        # Create Strands agent with code interpreter tool
        SYSTEM_PROMPT = """You are a financial behavior analyst specializing in spending pattern analysis for loan underwriting.
You have access to a Python code interpreter to perform detailed behavioral and expense analysis.
When analyzing expenses and spending patterns, write Python code to:
1. Categorize expenses by type (essential, variable, discretionary)
2. Calculate spending velocity and financial stress indicators
3. Analyze purchasing behavior patterns
4. Detect financial discipline and risk factors
5. Validate declared expenses against actual spending

Always execute calculations using code to ensure accuracy and provide behavioral insights."""

        agent = Agent(
            model=model.get_model(),
            tools=[code_interpreter_tool.code_interpreter],
            system_prompt=SYSTEM_PROMPT
        )

        # Prepare comprehensive analysis prompt
        analysis_prompt = f"""
Analyze this loan applicant's expense profile and spending behavior patterns:

**Loan Application:**
- Applicant ID: {app.get('applicant_id')}
- Declared Monthly Expenses: ${app.get('expenses', 0):,.2f}
- Declared Monthly Income: ${app.get('income', 0):,.2f}
- Requested Loan Amount: ${app.get('amount', 0):,.2f}

**Bank Account Data:**
- Current Balance: ${bank.get('accounts', [{}])[0].get('balance', 0):,.2f if bank.get('accounts') else 0}
- Account Type: {bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'}

**Bank Statement Data (Extracted by Bedrock Data Automation):**
{json.dumps(bank_statement_data, indent=2) if bank_statement_data else "No bank statement data available"}

**Analysis Required:**
Write Python code to perform comprehensive spending behavior analysis:

**1. EXPENSE CATEGORIZATION (from bank statement transactions):**
   Categories to analyze:
   - Essential expenses:
     * Housing (rent/mortgage, property tax)
     * Utilities (electricity, water, gas, internet)
     * Insurance (health, auto, life)
     * Loan payments (existing loans, credit cards)
   - Variable expenses:
     * Groceries and household items
     * Transportation (gas, public transit, car maintenance)
     * Healthcare (medical, pharmacy, dental)
     * Childcare/education
   - Discretionary spending:
     * Dining out and restaurants
     * Entertainment (movies, concerts, streaming services)
     * Shopping (clothing, electronics, non-essentials)
     * Travel and vacation
     * Subscriptions and memberships

   Calculate totals for each category and subcategory.

**2. SPENDING VELOCITY ANALYSIS:**
   - Identify deposit dates (likely income/paycheck)
   - Calculate days between deposit and when balance drops below 20% of deposit
   - Fast velocity (< 5 days) = high financial stress
   - Moderate velocity (5-15 days) = normal spending
   - Slow velocity (> 15 days) = good financial discipline

   Calculate average spending velocity over past 3 months.

**3. PURCHASE PATTERN ANALYSIS:**
   - Count small frequent transactions (< $20) vs. large purchases (> $200)
   - Analyze transaction timing:
     * Weekend spending (Friday-Sunday) - indicator of discretionary spending
     * Evening spending (after 6 PM) - impulse purchases
     * Payday spending (within 3 days of deposit) - spending discipline
   - Identify merchant categories (retail, restaurants, entertainment, etc.)
   - Calculate discretionary spending ratio: (discretionary / total_expenses) * 100

**4. FINANCIAL STRESS INDICATORS:**
   Detect red flags:
   - Minimum balance throughout month (if < $100 frequently = high stress)
   - Overdraft fees or NSF (insufficient funds) charges
   - Payday loans or cash advance transactions
   - Gambling transactions (casinos, lottery, betting)
   - Late payment fees on bills
   - Multiple balance transfers between accounts
   - Declining balance trend over 3+ months

   Count red flags and assess severity.

**5. SAVINGS DISCIPLINE:**
   - Check for automatic savings transfers (positive indicator)
   - Calculate savings buffer: month-end balance / monthly expenses
   - Buffer > 1.0 = emergency fund present (excellent)
   - Buffer 0.5-1.0 = some buffer (moderate)
   - Buffer < 0.5 = living paycheck to paycheck (risky)

   Analyze balance trend: increasing (good), stable (moderate), decreasing (concerning)

**6. EXPENSE VALIDATION:**
   - Compare declared expenses (${app.get('expenses', 0):,.2f}) vs. actual bank statement debits
   - Calculate discrepancy percentage: abs(declared - actual) / actual * 100
   - Flag if discrepancy > 20%
   - Identify reason for discrepancy (underestimated, cash spending, multiple accounts)

**7. BEHAVIORAL RISK SCORE (0-100, where 0 is lowest risk):**
   Risk factors (add points):
   - High discretionary spending (>30% of income): +20 points
   - Fast spending velocity (< 5 days): +15 points
   - Overdraft/NSF fees present: +20 points
   - Payday loans/cash advances: +25 points
   - Gambling transactions: +15 points
   - No savings buffer (< 0.5): +15 points
   - Declining balance trend: +10 points
   - Late payment fees: +10 points
   - Declared vs actual expense discrepancy > 20%: +10 points

   Positive factors (subtract points):
   - Automatic savings transfers: -10 points
   - Savings buffer > 1.0: -15 points
   - Low discretionary spending (< 20%): -10 points
   - Increasing balance trend: -10 points

   Final score: Sum all points (min 0, max 100)

**8. FINANCIAL DISCIPLINE ASSESSMENT:**
   Based on overall analysis:
   - Disciplined (score 0-30): Good spending habits, savings, low discretionary spending
   - Moderate (score 31-60): Balanced spending, some concerns, room for improvement
   - Undisciplined (score 61-100): Poor spending habits, high risk, financial stress

**Return structured analysis with:**
- Total actual monthly expenses (by category)
- Expense-to-income ratio (%)
- Discretionary spending ratio (%)
- Spending velocity (days)
- Savings buffer ratio
- Expense validation result (matches/discrepancy/red_flags)
- List of red flags detected (if any)
- Behavioral risk score (0-100)
- Financial discipline assessment (disciplined/moderate/undisciplined)
- Affordability of new loan payment
- Detailed reasoning and recommendations
"""

        # Execute analysis with AgentCore Code Interpreter
        activity.logger.info("Invoking AgentCore Code Interpreter for expense behavior analysis...")
        response = agent(analysis_prompt)

        # Extract response
        response_text = str(response.message["content"][0]["text"]) if response.message else "No response"
        activity.logger.info(f"AgentCore expense analysis completed: {response_text[:500]}...")

        # Parse response to extract structured data
        result = {
            "status": "success",
            "analysis_method": "agentcore_code_interpreter",
            "raw_analysis": response_text,
            "declared_expenses": app.get("expenses"),
        }

        # Extract key metrics from response using regex
        import re

        # Extract expense-to-income ratio
        expense_ratio_match = re.search(r'expense[- ]to[- ]income[:\s]+([0-9.]+)%?', response_text, re.IGNORECASE)
        if expense_ratio_match:
            result["expense_to_income_ratio"] = float(expense_ratio_match.group(1))
            result["affordability_ok"] = float(expense_ratio_match.group(1)) < 50  # < 50% is good

        # Extract discretionary ratio
        disc_match = re.search(r'discretionary[:\s]+([0-9.]+)%?', response_text, re.IGNORECASE)
        if disc_match:
            result["discretionary_ratio"] = float(disc_match.group(1))

        # Extract spending velocity
        velocity_match = re.search(r'velocity[:\s]+([0-9.]+)\s*day', response_text, re.IGNORECASE)
        if velocity_match:
            result["spending_velocity_days"] = float(velocity_match.group(1))

        # Extract savings buffer
        buffer_match = re.search(r'buffer[:\s]+([0-9.]+)', response_text, re.IGNORECASE)
        if buffer_match:
            result["savings_buffer"] = float(buffer_match.group(1))

        # Extract behavioral risk score
        behavior_risk_match = re.search(r'(?:behavioral\s+)?risk[_ ]score[:\s]+([0-9.]+)', response_text, re.IGNORECASE)
        if behavior_risk_match:
            result["behavioral_risk_score"] = float(behavior_risk_match.group(1))

        # Extract financial discipline
        if "undisciplined" in response_text.lower():
            result["financial_discipline"] = "undisciplined"
        elif "disciplined" in response_text.lower() and "undisciplined" not in response_text.lower():
            result["financial_discipline"] = "disciplined"
        else:
            result["financial_discipline"] = "moderate"

        # Check for red flags
        red_flags = []
        red_flag_keywords = {
            "overdraft": "overdraft_fees",
            "nsf": "insufficient_funds",
            "payday loan": "payday_loans",
            "cash advance": "cash_advances",
            "gambling": "gambling_transactions",
            "late payment": "late_payment_fees",
            "late fee": "late_payment_fees"
        }

        for keyword, flag_name in red_flag_keywords.items():
            if keyword in response_text.lower():
                red_flags.append(flag_name)

        if red_flags:
            result["red_flags"] = list(set(red_flags))  # Remove duplicates
            result["has_red_flags"] = True
        else:
            result["has_red_flags"] = False

        # Extract total expenses from analysis
        actual_expense_match = re.search(r'total[_ ](?:actual[_ ])?(?:monthly[_ ])?expenses[:\s]+\$?([0-9,.]+)', response_text, re.IGNORECASE)
        if actual_expense_match:
            result["actual_expenses"] = float(actual_expense_match.group(1).replace(',', ''))

        # Fallback: if no structured data extracted, use basic heuristic
        if "affordability_ok" not in result:
            expenses = app.get("expenses", 1000)
            disposable = app.get("income", 5000) - expenses
            result["affordability_ok"] = disposable > app.get("amount", 1000) / 12
            result["expenses"] = expenses
            result["fallback_method"] = "heuristic"

        activity.logger.info(f"Expense assessment result: {result}")
        return result

    except Exception as e:
        activity.logger.error(f"Expense assessment failed: {str(e)}")
        # Fallback to basic heuristic if AgentCore fails
        app = payload.get("application", {})
        expenses = app.get("expenses", 1000)
        disposable = app.get("income", 5000) - expenses

        return {
            "affordability_ok": disposable > app.get("amount", 1000) / 12,
            "expenses": expenses,
            "status": "fallback",
            "error": str(e),
            "analysis_method": "heuristic_fallback"
        }


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
