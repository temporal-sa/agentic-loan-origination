from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from datetime import timedelta
from typing import Dict, Any, Optional


@workflow.defn
class SupervisorWorkflow:
    def __init__(self) -> None:
        """
        Initializes the workflow instance with default state variables and a global retry policy for activities.

        Attributes:
            _human_decision_received (bool): Flag indicating if a human decision has been received via signal.
            _human_decision (Optional[Dict[str, Any]]): Stores the human decision data once received.
            _summary (Optional[Dict[str, Any]]): Stores a summary of the workflow's processing.
            _final_result (Optional[Dict[str, Any]]): Stores the final result of the workflow.
            _default_retry_policy (RetryPolicy): Configures exponential backoff retry policy for all activities.

        In Temporal, this constructor sets up the workflow's internal state and ensures that all activities
        executed within the workflow use a consistent retry policy to handle transient failures.
        """
        # Event that will be set by the human-review signal
        self._human_decision_received = False
        self._human_decision: Optional[Dict[str, Any]] = None
        self._summary: Optional[Dict[str, Any]] = None
        self._final_result: Optional[Dict[str, Any]] = None

        # Global retry policy with exponential backoff for all activities
        self._default_retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1), # The time to wait before the first retry attempt after a failure.
            maximum_interval=timedelta(seconds=10), # The maximum time to wait between retry attempts; the backoff will not exceed this value.
            backoff_coefficient=2.0, # The multiplier applied to the wait interval after each failed attempt (exponential backoff).
            maximum_attempts=4 # The maximum number of retry attempts before giving up.
        )

    @workflow.run
    async def run(self, application: Dict[str, Any]):
        # Orchestrate specialist agents
        # 1. Fetch external data
        bank = await workflow.execute_activity(
            "fetch_bank_account",
            application["applicant_id"],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=self._default_retry_policy
        )

        docs = await workflow.execute_activity(
            "fetch_documents",
            application["applicant_id"],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=self._default_retry_policy
        )

        # Try CIBIL first, fallback to Experian if it fails
        # This showcases Temporal's ability to handle provider failures gracefully
        try:
            credit = await workflow.execute_activity(
                "fetch_credit_report_cibil",
                application["applicant_id"],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    maximum_attempts=2  # Don't retry CIBIL, fail fast and fallback
                )
            )
        except ActivityError:
            # If CIBIL fails, fallback to Experian
            workflow.logger.info("CIBIL failed, falling back to Experian")
            credit = await workflow.execute_activity(
                "fetch_credit_report_experian",
                application["applicant_id"],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=self._default_retry_policy
            )

        # 2. Run specialist agents in parallel
        income_task = workflow.execute_activity(
            "income_assessment",
            {"application": application, "bank": bank, "credit": credit},
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=self._default_retry_policy
        )
        expense_task = workflow.execute_activity(
            "expense_assessment",
            {"application": application, "bank": bank},
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=self._default_retry_policy
        )
        credit_task = workflow.execute_activity(
            "credit_assessment",
            {"application": application, "credit": credit},
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=self._default_retry_policy
        )

        # Wait for all tasks to complete
        income_res = await income_task
        expense_res = await expense_task
        credit_res = await credit_task

        # 3. Make a mock decision using an LLM activity
        decision = await workflow.execute_activity(
            "aggregate_and_decide",
            {"application": application, "income": income_res, "expense": expense_res, "credit": credit_res, "docs": docs},
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=self._default_retry_policy
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
