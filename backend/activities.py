import asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import os
import json
from pathlib import Path
from utilities import model
from utilities.prompts import (
    get_prompt_for_document,
    INCOME_ASSESSMENT_SYSTEM_PROMPT,
    EXPENSE_ASSESSMENT_SYSTEM_PROMPT,
    get_income_analysis_prompt,
    get_expense_analysis_prompt
)
from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter
from classes.agents import DataFetchAgent, CreditReportAgent
# Import BedrockModel for AWS Bedrock integration via Strands for Nova
from strands.models import BedrockModel
from utilities.aws_client import get_aws_session
from botocore.config import Config
import re


async def run_blocking_with_heartbeats(
    callable_fn,
    *args,
    heartbeat_interval: int = 60,
):
    """Run a blocking callable in the default executor

    Args:
        callable_fn: Blocking callable to run (e.g., agent invocation)
        *args: Positional args passed to callable_fn
        heartbeat_interval: Seconds between heartbeats

    Returns:
        The result returned by callable_fn

    Raises:
        CancelledError: If activity is cancelled by Temporal
    """
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, lambda: callable_fn(*args))

    # Wrap the future in a task that can be shielded
    task = asyncio.ensure_future(future)

    try:
        while not task.done():
            try:
                # Wait for either the task to complete or timeout for heartbeat
                return await asyncio.wait_for(asyncio.shield(task), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                activity.logger.debug(f"heartbeat")

        # Task completed while we were checking, return result
        return await task

    except asyncio.CancelledError:
        # Activity is being cancelled (Temporal timeout or workflow termination)
        # Cancel both the task and the underlying future
        task.cancel()
        future.cancel()
        activity.logger.info("Activity cancelled, cancelling executor future")
        raise


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
        bank_data = await data_agent.fetch_data(url, "bank account")

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

        # activity.logger.info(f"Processing single image file: {file_ext}")

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

        # activity.logger.info(f"OCR completed, response length: {len(response_text)} chars")

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

        # activity.logger.info(f"Saved extracted data to {json_path}")

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
        credit_data = await credit_agent.fetch_and_validate_credit_report(
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
        credit_data = await credit_agent.fetch_and_validate_credit_report(
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
                    # activity.logger.info(f"Found extracted bank statement data: {bank_statement_data}")
                    break

        # Initialize AgentCore Code Interpreter
        region_name = os.getenv("AWS_REGION", "us-east-1")
        code_interpreter_tool = AgentCoreCodeInterpreter(region=region_name)

        # Create Strands agent with code interpreter tool
        agent = Agent(
            model=model.get_model(),
            tools=[code_interpreter_tool.code_interpreter],
            system_prompt=INCOME_ASSESSMENT_SYSTEM_PROMPT
        )

        # Prepare comprehensive financial data using prompt template
        bank_balance = bank.get('accounts', [{}])[0].get('balance', 0) if bank.get('accounts') else 0
        account_type = bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'

        analysis_prompt = get_income_analysis_prompt(
            applicant_id=app.get('applicant_id'),
            loan_amount=app.get('amount', 0),
            monthly_income=app.get('income', 0),
            monthly_expenses=app.get('expenses', 0),
            bank_balance=bank_balance,
            account_type=account_type,
            bank_statement_data=bank_statement_data
        )

        # Execute analysis with AgentCore Code Interpreter (run in executor)
        activity.logger.info("Invoking AgentCore Code Interpreter for income analysis...")

        # Run the potentially-blocking agent call in the default executor and
        # send periodic heartbeats while waiting so Temporal doesn't time out
        response = await run_blocking_with_heartbeats(
            agent,
            analysis_prompt,
            heartbeat_interval=60
        )

        # Extract response
        response_text = str(response.message["content"][0]["text"]) if response.message else "No response"
        #activity.logger.info(f"AgentCore analysis completed: {response_text[:500]}...")

        # Return the analysis result
        result = {
            "status": "success",
            "analysis_method": "agentcore_code_interpreter",
            "raw_analysis": response_text,
            "income": app.get("income"),
            "loan_amount": app.get("amount"),
        }

        #activity.logger.info(f"Income assessment result: {result}")
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
        agent = Agent(
            model=model.get_model(),
            tools=[code_interpreter_tool.code_interpreter],
            system_prompt=EXPENSE_ASSESSMENT_SYSTEM_PROMPT
        )

        # Prepare comprehensive analysis prompt using prompt template
        bank_balance = bank.get('accounts', [{}])[0].get('balance', 0) if bank.get('accounts') else 0
        account_type = bank.get('accounts', [{}])[0].get('type', 'N/A') if bank.get('accounts') else 'N/A'

        analysis_prompt = get_expense_analysis_prompt(
            applicant_id=app.get('applicant_id'),
            declared_expenses=app.get('expenses', 0),
            monthly_income=app.get('income', 0),
            loan_amount=app.get('amount', 0),
            bank_balance=bank_balance,
            account_type=account_type,
            bank_statement_data=bank_statement_data
        )

        # Execute analysis with AgentCore Code Interpreter (run in executor)
        activity.logger.info("Invoking AgentCore Code Interpreter for expense behavior analysis...")

        # Run the potentially-blocking agent call in the default executor and
        # send periodic heartbeats while waiting so Temporal doesn't time out
        response = await run_blocking_with_heartbeats(
            agent,
            analysis_prompt,
            heartbeat_interval=60
        )

        # Extract response
        response_text = str(response.message["content"][0]["text"]) if response.message else "No response"
        # activity.logger.info(f"AgentCore expense analysis completed: {response_text[:500]}...")

        # Return the analysis result
        result = {
            "status": "success",
            "analysis_method": "agentcore_code_interpreter",
            "raw_analysis": response_text,
            "declared_expenses": app.get("expenses"),
        }

        # activity.logger.info(f"Expense assessment result: {result}")
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
            f"LLM call failed: {str(e)}",
            type="LLMError",
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
