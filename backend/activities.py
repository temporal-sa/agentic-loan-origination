from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import random
import json
import os
from strands import Agent, tool
from strands.models.ollama import OllamaModel
from strands_tools import http_request


@tool
def bank_api_caller(url: str) -> Dict[str, Any]:
    """
    A reusable tool that makes HTTP requests to banking APIs.
    Uses Strands agent with HTTP capabilities to fetch and process data.

    Args:
        url: The API endpoint URL to call

    Returns:
        API response data as dictionary
    """
    # Create specialized agent with HTTP request capability
    http_agent = Agent(
        system_prompt="You are a banking API assistant. Make HTTP requests and return only JSON response data from API as is nothing else.",
        tools=[http_request]
    )

    # Use agent to make HTTP request based on prompt
    response = http_agent.tool.http_request(
        method="GET",
        url=url
    )

    body_text = next((item["text"] for item in response["content"] if item["text"].startswith("Body:")), None)
    if body_text and body_text.startswith("Body:"):
        # Strip "Body:" prefix and whitespace
        body_json_str = body_text[len("Body:"):].strip()
        
    return json.loads(body_json_str)


@activity.defn
async def fetch_bank_account(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch bank account data using Strands HTTP request tooling.
    Demonstrates Strands agent capability to make HTTP requests.
    Raises ApplicationError if the API call fails, which will trigger retries.
    """
    try:
        # Use the reusable bank_api_caller tool
        url = f"http://localhost:3232/bank?applicant_id={applicant_id}"
        response = bank_api_caller(url=url)

        return response

    except Exception as e:
        # Raise ApplicationError to trigger Temporal's retry mechanism
        # When max attempts are exhausted, this will fail the activity and workflow
        raise ApplicationError(
            f"Failed to fetch bank account data: {str(e)}",
            type="BankAPIError",
            non_retryable=False  # Allow retries
        )


@activity.defn
async def fetch_documents(applicant_id: str) -> Dict[str, Any]:
    # TODO: we want to simulate document fetch from S3
    return {"documents": ["id_card.pdf", "paystub.pdf"]}


@activity.defn
async def fetch_credit_report_cibil(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch credit report from CIBIL bureau.
    Simulates API failure to demonstrate Temporal's error handling.
    """
    # Simulate CIBIL API failure
    raise ApplicationError(
        "CIBIL API temporarily unavailable",
        type="CIBILAPIError",
        non_retryable=False  # Don't retry CIBIL, fallback to Experian instead
    )


@activity.defn
async def fetch_credit_report_experian(applicant_id: str) -> Dict[str, Any]:
    """
    Fetch credit report from Experian bureau.
    This acts as a fallback when CIBIL fails.
    """
    # Simulate successful Experian response
    return {
        "score": random.randint(300, 850),
        "history": [],
        "provider": "Experian"
    }

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
