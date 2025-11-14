import asyncio
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from datetime import timedelta
from typing import Dict, Any, Optional


@workflow.defn
class SupervisorWorkflow:
    """
    Temporal Supervisor Workflow for Loan Underwriting.

    ARCHITECTURE PATTERN - Temporal + Strands Coexistence:
    ═══════════════════════════════════════════════════════════════

    This workflow demonstrates the value proposition of combining:

    1. TEMPORAL (Orchestration Layer - Outer Loop):
       - Durable workflow execution (survives crashes, restarts)
       - Automatic retry policies for transient failures
       - Provider fallback strategies (CIBIL → Experian)
       - Human-in-the-loop with signals and queries
       - Parallel activity execution
       - Complete audit trail and observability
       - Time-based operations (timeouts, delays)

    2. STRANDS AGENTS (Intelligence Layer - Inner Loop):
       - HTTP requests with intelligent error handling
       - Data validation and quality assessment
       - Multi-agent collaboration within activities
       - Structured reasoning and decision-making
       - Tool usage (http_request etc.)
       - Context-aware logging and diagnostics

    ═══════════════════════════════════════════════════════════════

    WORKFLOW PHASES:
    ----------------
    Phase 1: Data Acquisition (Temporal orchestrates, Strands fetches)
             - Bank account data (HTTP agent)
             - Document metadata (HTTP agent)
             - Credit reports with fallback (HTTP agent + validation)

    Phase 2: Parallel Analysis (Temporal coordinates, Strands analyzes)
             - Income assessment
             - Expense assessment
             - Credit assessment

    Phase 3: Decision Making (Strands agent with LLM)
             - Aggregate all data
             - Generate recommendation

    Phase 4: Human Review (Temporal manages state)
             - Pause workflow
             - Wait for human signal
             - Resume with decision
    """

    def __init__(self) -> None:
        """
        Initialize the workflow with state management and retry policies.

        State Management:
            - _human_decision_received: Signal flag for human review completion
            - _human_decision: Stores the human reviewer's decision
            - _summary: Aggregated data for human review
            - _final_result: Complete workflow outcome
            - _document_paths: Paths to uploaded documents
            - _documents_uploaded: Flag indicating documents have been uploaded

        Retry Policy:
            - Exponential backoff with configurable parameters
            - Applied to all activities by default
            - Can be overridden per activity (e.g., CIBIL has limited retries)
        """
        # Human-in-the-loop state
        self._human_decision_received = False
        self._human_decision: Optional[Dict[str, Any]] = None
        self._summary: Optional[Dict[str, Any]] = None
        self._final_result: Optional[Dict[str, Any]] = None

        # Document upload state
        self._document_paths: Optional[Dict[str, str]] = None
        self._documents_uploaded = False

        # Global retry policy for activities
        # This is Temporal's mechanism for handling transient failures
        self._default_retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            maximum_attempts=10
        )

    async def _process_single_document(
        self,
        applicant_id: str,
        doc_type: str,
        local_path: str
    ) -> Dict[str, Any]:
        """
        Process a single document with Ollama granite3.2-vision.

        TEMPORAL PATTERN - SYNCHRONOUS ACTIVITY:
        - Processes document synchronously using Ollama
        - Each document processed independently in parallel
        - Failures isolated to single document (won't affect others)
        - No polling needed - returns immediately with results

        Args:
            applicant_id: Applicant identifier
            doc_type: Type of document (e.g., 'bank_statement', 'salary_slip', 'id_proof')
            local_path: Local file path to the document

        Returns:
            Processing result with status and extracted data
        """
        workflow.logger.info(f"Starting OCR processing for {doc_type} with Ollama granite3.2-vision")

        try:
            # Process document with Ollama granite3.2-vision
            # Temporal's retry policy handles transient failures
            result = await workflow.execute_activity(
                "trigger_document_processing",
                {
                    "applicant_id": applicant_id,
                    "doc_type": doc_type,
                    "local_path": local_path
                },
                start_to_close_timeout=timedelta(minutes=5),  # Vision models may take longer
                retry_policy=self._default_retry_policy
            )

            workflow.logger.info(f"OCR processing completed for {doc_type}: {result['status']}")
            return result

        except ActivityError as e:
            # Activity failed after all retry attempts
            workflow.logger.error(f"Activity error processing {doc_type}: {e}")
            return {
                "doc_type": doc_type,
                "status": "error",
                "error": str(e)
            }

    @workflow.run
    async def run(self, application: Dict[str, Any]):
        """
        Main workflow execution logic.

        This method orchestrates the entire loan underwriting process,
        demonstrating Temporal's orchestration capabilities combined with
        Strands agents' intelligence within each activity.
        """

        # ═══════════════════════════════════════════════════════════
        # PHASE 0: WAIT FOR DOCUMENT UPLOAD
        # ═══════════════════════════════════════════════════════════
        # Wait for documents to be uploaded before proceeding
        workflow.logger.info("Waiting for documents to be uploaded...")
        await workflow.wait_condition(lambda: self._documents_uploaded, timeout=timedelta(minutes=10))
        workflow.logger.info(f"Documents uploaded: {self._document_paths}")

        # Add document paths to application data for activities
        application["document_paths"] = self._document_paths

        # ═══════════════════════════════════════════════════════════
        # PHASE 1: DATA ACQUISITION
        # ═══════════════════════════════════════════════════════════
        # Temporal orchestrates the execution and retries
        # Strands agents handle HTTP requests and data validation

        # Activity 1: Fetch bank account data
        # - Temporal: Manages timeout, retries, durability
        # - Strands: Makes HTTP request, validates account structure
        bank = await workflow.execute_activity(
            "fetch_bank_account",
            application["applicant_id"],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=self._default_retry_policy
        )

        # Activity 2: Process documents with Ollama granite3.2-vision
        # ════════════════════════════════════════════════════════════
        # KEY ARCHITECTURE PATTERN - FAN-OUT PARALLEL PROCESSING:
        # - Fan-out: Launch all document processing tasks in parallel
        # - Use asyncio.gather() for concurrent execution (Temporal-safe)
        # - Each document processed independently with own retry policy
        # - Workflow orchestrates parallel execution and aggregates results
        # - Ollama granite3.2-vision extracts structured data synchronously
        # ════════════════════════════════════════════════════════════
        document_paths = application.get("document_paths", {})

        if document_paths:
            workflow.logger.info(f"Processing {len(document_paths)} documents in parallel with Ollama granite3.2-vision")

            # FAN-OUT: Create parallel tasks for each document
            document_tasks = [
                self._process_single_document(
                    application["applicant_id"],
                    doc_type,
                    local_path
                )
                for doc_type, local_path in document_paths.items()
            ]

            # Wait for all parallel document processing to complete
            # Temporal ensures durability - even if workflow restarts, completed tasks won't re-execute
            processed_documents = await asyncio.gather(*document_tasks)

            docs = {
                "documents": processed_documents,
                "total_processed": len(processed_documents),
                "successful": len([d for d in processed_documents if d.get("status") == "success"]),
                "failed": len([d for d in processed_documents if d.get("status") != "success"])
            }
        else:
            workflow.logger.warning("No document paths provided, skipping OCR processing")
            docs = {"documents": [], "status": "no_documents_uploaded"}

        # Activity 3: Fetch credit report with provider fallback
        # ════════════════════════════════════════════════════════
        # KEY ARCHITECTURE PATTERN - FALLBACK ORCHESTRATION:
        # - Temporal: Orchestrates provider-level fallback (CIBIL → Experian)
        # - Strands: Validates data quality consistently across providers
        # ════════════════════════════════════════════════════════
        try:
            # Try primary provider (CIBIL) with limited retries
            credit = await workflow.execute_activity(
                "fetch_credit_report_cibil",
                application["applicant_id"],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    maximum_attempts=2  # Fail fast to try fallback
                )
            )
        except ActivityError as e:
            # TEMPORAL ORCHESTRATION: Fallback to secondary provider
            credit = await workflow.execute_activity(
                "fetch_credit_report_experian",
                application["applicant_id"],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=self._default_retry_policy
            )

        # ═══════════════════════════════════════════════════════════
        # PHASE 2: PARALLEL SPECIALIST ASSESSMENTS
        # ═══════════════════════════════════════════════════════════
        # Temporal coordinates parallel execution
        # AgentCore Code Interpreter performs sophisticated financial analysis
        # TEMPORAL ORCHESTRATION: Launch activities in parallel
        # These are independent assessments that can run concurrently
        income_task = workflow.execute_activity(
            "income_assessment",
            {"application": application, "bank": bank, "credit": credit, "documents": docs},
            start_to_close_timeout=timedelta(minutes=5),  # AgentCore needs more time
            retry_policy=self._default_retry_policy
        )
        expense_task = workflow.execute_activity(
            "expense_assessment",
            {"application": application, "bank": bank, "documents": docs},
            start_to_close_timeout=timedelta(minutes=5),  # AgentCore needs more time
            retry_policy=self._default_retry_policy
        )
        credit_task = workflow.execute_activity(
            "credit_assessment",
            {"application": application, "credit": credit},
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=self._default_retry_policy
        )

        # Wait for all parallel tasks to complete
        income_res = await income_task
        expense_res = await expense_task
        credit_res = await credit_task

        # ═══════════════════════════════════════════════════════════
        # PHASE 3: DECISION AGGREGATION
        # ═══════════════════════════════════════════════════════════
        # Temporal ensures reliable execution
        # Strands agent (with LLM) synthesizes all data into a recommendation

        decision = await workflow.execute_activity(
            "aggregate_and_decide",
            {
                "application": application,
                "income": income_res,
                "expense": expense_res,
                "credit": credit_res,
                "docs": docs
            },
            start_to_close_timeout=timedelta(seconds=1200),
            retry_policy=RetryPolicy(
                maximum_interval=timedelta(seconds=10)
            )
        )

        # ═══════════════════════════════════════════════════════════
        # PHASE 4: HUMAN-IN-THE-LOOP REVIEW
        # ═══════════════════════════════════════════════════════════
        # TEMPORAL'S KEY STRENGTH: Durable wait for human signal
        # Workflow can pause for hours/days without consuming resources

        # Aggregate all data for human reviewer
        summary = {
            "application": application,
            "bank": bank,
            "docs": docs,
            "credit": credit,
            "assessments": {
                "income": income_res,
                "expense": expense_res,
                "credit": credit_res
            },
            "suggested_decision": decision,
        }
        self._summary = summary

        # TEMPORAL ORCHESTRATION: Durable wait for human signal
        # This is where Temporal shines - workflow can pause indefinitely
        await workflow.wait_condition(lambda: self._human_decision_received)

        # Human decision received via signal
        decision = self._human_decision

        # Create final result with all context
        final = {
            "summary": summary,
            "human_decision": decision
        }
        self._final_result = final

        return final

    @workflow.signal
    def documents_uploaded(self, data: Dict[str, Any]):
        """
        Signal handler for document upload completion.

        TEMPORAL SIGNAL PATTERN:
        - Signals allow external systems to communicate with running workflows
        - Document paths are provided after files are uploaded to backend/uploads/
        - Workflow resumes processing once documents are available

        Args:
            data: Document upload information
                  {"document_paths": {...}}
        """
        self._document_paths = data.get("document_paths")
        self._documents_uploaded = True
        workflow.logger.info(f"Received document paths via signal: {self._document_paths}")

    @workflow.signal
    def human_review(self, decision: Dict[str, Any]):
        """
        Signal handler for human review decisions.

        TEMPORAL SIGNAL PATTERN:
        - Signals allow external systems to communicate with running workflows
        - Non-blocking: caller returns immediately
        - Durable: signal is guaranteed to be processed even if workflow is mid-execution
        - State update: sets flag to resume workflow execution

        Args:
            decision: Human reviewer's decision
                     {"action": "approve"|"reject", "note": "..."}
        """
        self._human_decision = decision
        self._human_decision_received = True

    @workflow.query
    def get_summary(self) -> Optional[Dict[str, Any]]:
        """
        Query handler to retrieve workflow summary for human review.

        TEMPORAL QUERY PATTERN:
        - Queries allow synchronous read access to workflow state
        - Non-blocking: doesn't affect workflow execution
        - Consistent: always returns current workflow state
        - Used by UI to display data for review

        Returns:
            Summary dict with all assessment data, or None if not ready
        """
        if self._summary is None:
            return None
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
        """
        Query handler to retrieve final workflow result.

        Returns:
            Final result with summary and human decision, or None if not complete
        """
        if self._final_result is None:
            return None
        return {
            "summary": self._final_result.get("summary"),
            "human_decision": self._final_result.get("human_decision")
        }
