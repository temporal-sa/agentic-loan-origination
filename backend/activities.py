from temporalio import activity
from temporalio.exceptions import ApplicationError
from typing import Dict, Any
import random
import os
from strands import Agent
from strands.models.ollama import OllamaModel


@activity.defn
async def fetch_bank_account(applicant_id: str) -> Dict[str, Any]:
    # Simulate open banking API call failure for first 2 attempts
    activity_info = activity.info()
    current_attempt = activity_info.attempt

    activity.heartbeat()

    # Simulate API failure for the first 2 attempts
    if current_attempt <= 2:
        raise ApplicationError(
            f"Open banking API call failed (attempt {current_attempt}/3)",
            type="OpenBankingAPIError",
            non_retryable=False
        )

    # Success on 3rd attempt and beyond
    return {"applicant_id": applicant_id, "accounts": [{"type": "checking", "balance": random.randint(1000, 20000)}]}


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
    activity.heartbeat()

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
    activity.heartbeat()

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

    # TODO: mock decision logic fallback; if LLM failed, force manual review
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
