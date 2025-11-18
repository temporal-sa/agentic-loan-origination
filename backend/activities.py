from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import os
import json
from pathlib import Path
from utilities import model
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from classes.agents import DataFetchAgent, CreditReportAgent
from document_prompts import get_prompt_for_document
# Import BedrockModel for AWS Bedrock integration via Strands for Nova
from strands.models import BedrockModel
from utilities.aws_client import get_aws_session
from botocore.config import Config
import re


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
    Process a single image document using AWS Bedrock Nova Pro vision model via Strands for OCR.

    ARCHITECTURE NOTE:
    - Temporal Activity: Provides durable execution
    - Strands BedrockModel: Simplified AWS Bedrock integration
    - AWS Bedrock Nova Pro: Vision model for document OCR

    This activity:
    - Reads a single image from local file
    - Sends image to AWS Bedrock Nova Pro via Strands BedrockModel
    - Extracts structured JSON data
    - Saves extracted JSON to local file
    """
    try:
        applicant_id = payload.get("applicant_id")
        doc_type = payload.get("doc_type")
        local_path = payload.get("local_path")

        activity.logger.info(f"Processing {doc_type} with AWS Bedrock Nova Pro (Strands): {local_path}")

        file_path = Path(local_path)

        # Verify file exists
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {local_path}")

        # Get the appropriate prompt for this document type
        try:
            ocr_prompt = get_prompt_for_document(doc_type)
        except ValueError as e:
            activity.logger.warning(f"Unknown document type {doc_type}, using generic OCR prompt")
            ocr_prompt = "Extract all text and structured information from this document. Return the data as valid JSON."

        # Determine file type
        file_ext = file_path.suffix.lstrip('.').lower()

        # Only accept image files - Strands supports: png, jpeg, gif, webp
        supported_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        if file_ext not in supported_formats:
            raise ValueError(f"Unsupported file format: {file_ext}. Only image files are supported: {', '.join(supported_formats)}")

        activity.logger.info(f"Processing single image file: {file_ext}")

        # Read image bytes
        with open(file_path, 'rb') as f:
            image_data = f.read()

        activity.logger.info(f"Image read, size: {len(image_data)} bytes")

        # Initialize Strands BedrockModel for Nova Pro

        model_id = os.getenv(
            "AWS_BEDROCK_NOVA_MODEL_ID",
            "arn:aws:bedrock:us-west-2:1111111111:inference-profile/us.amazon.nova-pro-v1:0"
        )

        activity.logger.info(f"Invoking AWS Bedrock Nova Pro via Strands with model: {model_id}")

        # Create BedrockModel with AWS session with increased timeout
        # Note: region_name is inherited from the boto_session, so we don't specify it separately
        

        # Configure boto client with increased timeout for large image processing
        boto_config = Config(
            read_timeout=300,  # 5 minutes for large images
            connect_timeout=60,
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        session = get_aws_session()
        bedrock_model = BedrockModel(
            boto_session=session,
            boto_client_config=boto_config,
            model_id=model_id,
            max_tokens=2560,
            temperature=1,
            top_p=1
        )

        # Create Strands Agent with BedrockModel
        agent = Agent(model=bedrock_model)

        # Normalize file extension for Strands ImageContent format
        image_format = file_ext if file_ext in ['png', 'jpeg', 'gif', 'webp'] else 'jpeg'
        if file_ext == 'jpg':
            image_format = 'jpeg'

        # Prepare content with ImageContent using Strands format
        # Pass content directly to agent as array of content blocks
        content = [
            {
                "image": {
                    "format": image_format,
                    "source": {
                        "bytes": image_data  # Strands handles encoding internally
                    }
                }
            },
            {"text": ocr_prompt}
        ]

        # Invoke agent with image and text content
        response = agent(content)

        # Extract response text from Strands AgentResult
        # AgentResult.message["content"] contains list of ContentBlock objects
        response_text = ""
        for block in response.message["content"]:
            if "text" in block:
                response_text += block["text"]

        activity.logger.info(f"OCR completed, response length: {len(response_text)} chars")

        # Parse JSON from response
        # Try to extract JSON from the response (model might include extra text)
        try:
            # First try direct JSON parse
            extracted_data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                extracted_data = json.loads(json_match.group(0))
            else:
                activity.logger.error(f"Failed to parse JSON from response: {response_text[:500]}")
                raise ValueError("Could not extract valid JSON from OCR response")

        # Save JSON to local file
        json_path = file_path.parent / f"{doc_type}_extracted.json"
        with open(json_path, 'w') as f:
            json.dump(extracted_data, f, indent=2)

        activity.logger.info(f"Saved extracted data to {json_path}")

        return {
            "doc_type": doc_type,
            "status": "success",
            "extracted_data": extracted_data,
            "json_path": str(json_path),
            "local_path": str(file_path)
        }

    except FileNotFoundError as e:
        raise ApplicationError(
            f"Document file not found for {doc_type}: {str(e)}",
            type="FileNotFoundError",
            non_retryable=True  # Don't retry if file doesn't exist
        )
    except json.JSONDecodeError as e:
        raise ApplicationError(
            f"Failed to parse OCR response as JSON for {doc_type}: {str(e)}",
            type="JSONParseError",
            non_retryable=False
        )
    except Exception as e:
        raise ApplicationError(
            f"Failed to process document {doc_type}: {str(e)}",
            type="DocumentProcessingError",
            non_retryable=False
        )


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
    - AWS Bedrock Nova Pro: Extracted bank statement data (from document processing)

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

        # Extract bank statement data from Bedrock Nova Pro OCR results
        bank_statement_data = None
        if docs and isinstance(docs, dict):
            processed_docs = docs.get("documents", [])
            for doc in processed_docs:
                if doc.get("doc_type") == "bank_statement" and doc.get("status") == "success":
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
- Account Balance: ${f"{bank.get('accounts', [{}])[0].get('balance', 0):,.2f}" if bank.get('accounts') else "0.00"}
- Account Type: {bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'}

**Bank Statement Extracted Data (AWS Bedrock Nova Pro OCR):**
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
    - AWS Bedrock Nova Pro: Extracted bank statement data (from document processing)

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

        # Extract bank statement data from Bedrock Nova Pro OCR results
        bank_statement_data = None
        if docs and isinstance(docs, dict):
            processed_docs = docs.get("documents", [])
            for doc in processed_docs:
                if doc.get("doc_type") == "bank_statement" and doc.get("status") == "success":
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
- Current Balance: ${f"{bank.get('accounts', [{}])[0].get('balance', 0):,.2f}" if bank.get('accounts') else "0.00"}
- Account Type: {bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'}

**Bank Statement Data (Extracted by AWS Bedrock Nova Pro OCR):**
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
        # "raw_output": explanation,
    }
    return decision
