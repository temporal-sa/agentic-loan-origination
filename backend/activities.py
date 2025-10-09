from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import json
import os
from strands import Agent
from strands.models.ollama import OllamaModel
from strands_tools import http_request


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


class DataFetchAgent:
    """
    Specialized Strands agent for fetching data from external APIs.
    Demonstrates the inner loop of agent-based data acquisition within
    a Temporal activity (outer loop).
    """

    def __init__(self):
        """Initialize the data fetch agent with HTTP request capabilities."""
        self.agent = Agent(
            system_prompt="""You are a data acquisition specialist agent for a loan underwriting system.

Your responsibilities:
1. Make HTTP requests to external APIs
2. Validate the response data structure
3. Extract and parse JSON responses
4. Handle errors gracefully with detailed context
5. Return clean, structured data

When making requests:
- Use the http_request tool to fetch data
- Always validate that responses contain expected fields
- Parse JSON bodies correctly
- Report any data quality issues""",
            tools=[http_request]
        )

    def fetch_data(self, url: str, data_type: str) -> Dict[str, Any]:
        """
        Fetch data from an API endpoint using the Strands agent.

        Args:
            url: The API endpoint URL
            data_type: Type of data being fetched (for logging/errors)

        Returns:
            Parsed JSON response data
        """
        try:
            # Agent makes the HTTP request using its tool
            response = self.agent.tool.http_request(
                method="GET",
                url=url
            )

            # Extract body from response
            body_text = None
            for item in response.get("content", []):
                if isinstance(item, dict) and "text" in item:
                    if item["text"].startswith("Body:"):
                        body_text = item["text"][len("Body:"):].strip()
                        break

            if not body_text:
                raise ValueError(f"No body found in {data_type} API response")

            # Parse JSON
            parsed_data = json.loads(body_text)

            activity.logger.info(f"Successfully fetched {data_type} data: {parsed_data}")
            return parsed_data

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {data_type} API response: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to fetch {data_type} data: {str(e)}")


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
        activity.logger.info(f"Fetching bank account for applicant: {applicant_id}")

        # Initialize Strands agent for this activity execution
        data_agent = DataFetchAgent()

        # Agent fetches data from bank API
        url = f"http://localhost:3233/bank?applicant_id={applicant_id}"
        bank_data = data_agent.fetch_data(url, "bank account")

        # Validate essential fields
        if "accounts" not in bank_data:
            raise ValueError("Bank API response missing 'accounts' field")

        activity.logger.info(f"Successfully retrieved {len(bank_data.get('accounts', []))} bank accounts")
        return bank_data

    except Exception as e:
        # Raise ApplicationError to trigger Temporal's retry mechanism
        # Temporal will retry this activity based on the workflow's retry policy
        activity.logger.error(f"Bank account fetch failed: {str(e)}")
        raise ApplicationError(
            f"Failed to fetch bank account data: {str(e)}",
            type="BankAPIError",
            non_retryable=False  # Allow Temporal to retry
        )


@activity.defn
async def fetch_documents(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch applicant documents using Strands HTTP agent.

    ARCHITECTURE NOTE:
    - Temporal Activity: Provides durable execution and retry logic
    - Strands Agent: Intelligently fetches and validates document metadata

    In a production system, this would fetch documents from S3 or document storage.
    The agent could validate document types, check file sizes, verify formats, etc.
    """
    try:
        activity.logger.info(f"Fetching documents for applicant: {applicant_id}")

        # Initialize Strands agent for document fetching
        data_agent = DataFetchAgent()

        # Agent fetches document metadata from API
        url = f"http://localhost:3233/documents?applicant_id={applicant_id}"
        documents_data = data_agent.fetch_data(url, "documents")

        # Validate response structure
        if "documents" not in documents_data:
            raise ValueError("Documents API response missing 'documents' field")

        doc_count = len(documents_data.get("documents", []))
        activity.logger.info(f"Successfully retrieved {doc_count} documents")

        return documents_data

    except Exception as e:
        activity.logger.error(f"Document fetch failed: {str(e)}")
        raise ApplicationError(
            f"Failed to fetch documents: {str(e)}",
            type="DocumentAPIError",
            non_retryable=False
        )


class CreditReportAgent:
    """
    Specialized agent for fetching and validating credit reports.
    Demonstrates agent reasoning about data quality and provider reliability.
    """

    def __init__(self):
        self.data_agent = DataFetchAgent()

    def fetch_and_validate_credit_report(
        self, applicant_id: str, provider: str, url: str
    ) -> Dict[str, Any]:
        """
        Fetch credit report and perform intelligent validation.

        The agent validates:
        - Response structure
        - Credit score validity (300-850 range)
        - Required fields presence
        - Data quality indicators
        """
        activity.logger.info(f"Fetching credit report from {provider} for applicant: {applicant_id}")

        # Use data fetch agent to get credit data
        credit_data = self.data_agent.fetch_data(url, f"{provider} credit report")

        # Agent-based validation logic
        if "score" not in credit_data:
            raise ValueError(f"{provider} response missing 'score' field")

        score = credit_data.get("score")

        # Validate score range
        if not isinstance(score, (int, float)) or score < 300 or score > 850:
            raise ValueError(f"Invalid credit score from {provider}: {score}")

        # Add metadata about the provider
        credit_data["provider"] = provider
        credit_data["data_quality"] = "validated"

        return credit_data


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
    # TODO: this needs to use bedrock document automation using bank statement credits
    # TODO: payload contains application, bank, credit
    app = payload.get("application", {})
    bank = payload.get("bank", {})
    # simple heuristic
    balance = bank["accounts"][0]["balance"] if bank.get("accounts") else 0
    ratio = app.get("income", 5000) / max(app.get("amount", 1000), 1)
    result = {"income_ok": ratio > 2 or balance > 5000, "income": app.get("income")}
    return result


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
    # Initialize Ollama model with Strands
    try:
        ollama_model = OllamaModel(
            host=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            model_id=os.getenv("OLLAMA_MODEL", "llama3:latest")
        )
        agent = Agent(model=ollama_model)

        prompt_data = {
            "application": payload.get("application"),
            "assessments": payload.get("income"),
            "expense": payload.get("expense"),
            "credit": payload.get("credit"),
        }
        text = f"Summarize and give a suggested decision for this loan: {prompt_data}"
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
