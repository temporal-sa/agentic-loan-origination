from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, Optional


@workflow.defn
class SupervisorWorkflow:
    def __init__(self) -> None:
        # Event that will be set by the human-review signal
        self._human_decision_received = False
        self._human_decision: Optional[Dict[str, Any]] = None
        self._summary: Optional[Dict[str, Any]] = None
        self._final_result: Optional[Dict[str, Any]] = None

    @workflow.run
    async def run(self, application: Dict[str, Any]):
        # Orchestrate specialist agents
        # 1. Fetch external data
        bank = await workflow.execute_activity(
            "fetch_bank_account", application["applicant_id"], start_to_close_timeout=timedelta(seconds=10)
        )

        docs = await workflow.execute_activity(
            "fetch_documents", application["applicant_id"], start_to_close_timeout=timedelta(seconds=10)
        )

        credit = await workflow.execute_activity(
            "fetch_credit_report", application["applicant_id"], start_to_close_timeout=timedelta(seconds=10)
        )

        # 2. Run specialist agents in parallel
        income_task = workflow.execute_activity(
            "income_assessment", {"application": application, "bank": bank, "credit": credit}, start_to_close_timeout=timedelta(seconds=30)
        )
        expense_task = workflow.execute_activity(
            "expense_assessment", {"application": application, "bank": bank}, start_to_close_timeout=timedelta(seconds=30)
        )
        credit_task = workflow.execute_activity(
            "credit_assessment", {"application": application, "credit": credit}, start_to_close_timeout=timedelta(seconds=30)
        )

        # Wait for all tasks to complete
        income_res = await income_task
        expense_res = await expense_task
        credit_res = await credit_task

        # 3. Make a mock decision using an LLM activity
        decision = await workflow.execute_activity(
            "aggregate_and_decide",
            {"application": application, "income": income_res, "expense": expense_res, "credit": credit_res, "docs": docs},
            start_to_close_timeout=timedelta(seconds=60),
        )

        # 4. Prepare summary for human review and expose via query
        summary = {
            "application": application,
            "bank": bank,
            "docs": docs,
            "credit": credit,
            "assessments": {"income": income_res, "expense": expense_res, "credit": credit_res},
            "suggested_decision": decision,
        }
        self._summary = summary

        # Wait for human review signal (approve/reject)
        await workflow.wait_condition(lambda: self._human_decision_received)
        decision = self._human_decision

        # Create final result
        final = {"summary": summary, "human_decision": decision}
        self._final_result = final
        return final

    @workflow.signal
    def human_review(self, decision: Dict[str, Any]):
        """Signal method called by the human reviewer UI to approve/reject.
        The decision dict might look like: {"action": "approve"|"reject", "note": "..."}
        """
        # set the decision so run() can continue
        self._human_decision = decision
        self._human_decision_received = True

    @workflow.query
    def get_summary(self) -> Optional[Dict[str, Any]]:
        if self._summary is None:
            return None
        # Ensure all values are JSON serializable
        return {
            "application": self._summary.get("application"),
            "bank": self._summary.get("bank"),
            "docs": self._summary.get("docs"),
            "credit": self._summary.get("credit"),
            "assessments": self._summary.get("assessments"),
            "suggested_decision": self._summary.get("suggested_decision")
        }

    @workflow.query
    def get_final_result(self) -> Optional[Dict[str, Any]]:
        if self._final_result is None:
            return None
        # Ensure all values are JSON serializable
        return {
            "summary": self._final_result.get("summary"),
            "human_decision": self._final_result.get("human_decision")
        }
