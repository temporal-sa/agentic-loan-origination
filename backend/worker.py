import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from temporalio import worker
from dotenv import load_dotenv

# Import the actual workflows and activities
from workflows import SupervisorWorkflow
import activities
from utilities import get_temporal_client

load_dotenv()

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "loan-underwriter-queue")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))  # Configurable via env var


async def run_worker():
    # Create client using connection utility (supports both local and cloud)
    temporal_client = await get_temporal_client()

    # Create and run worker with ThreadPoolExecutor for parallel task processing
    w = worker.Worker(
        temporal_client,
        task_queue=TASK_QUEUE,
        workflows=[SupervisorWorkflow],
        activities=[
            activities.fetch_bank_account,
            activities.trigger_document_processing,
            # activities.check_document_status,  # Removed - no longer needed with Ollama
            activities.fetch_credit_report_cibil,
            activities.fetch_credit_report_experian,
            activities.income_assessment,
            activities.expense_assessment,
            activities.credit_assessment,
            activities.aggregate_and_decide
        ],
        activity_executor=ThreadPoolExecutor(max_workers=MAX_WORKERS),  # Enable parallel activity execution
    )

    print(f"Worker started, polling task queue: {TASK_QUEUE}")
    print(f"Activity executor configured with {MAX_WORKERS} worker threads")
    await w.run()


def main():
    # Use asyncio.run() which handles event loop creation/cleanup automatically
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("\nWorker stopped by user")


if __name__ == "__main__":
    main()
