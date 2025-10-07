import asyncio
import os
import sys
from temporalio import worker, client
from dotenv import load_dotenv

# Import the actual workflows and activities
from workflows import SupervisorWorkflow
import activities

load_dotenv()

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "loan-underwriter-queue")


async def run_worker():
    # Create client with explicit configuration
    temporal_client = await client.Client.connect(
        "localhost:7233",
        # Add any additional client configuration if needed
    )

    # Create and run worker
    w = worker.Worker(
        temporal_client,
        task_queue=TASK_QUEUE,
        workflows=[SupervisorWorkflow],
        activities=[
            activities.fetch_bank_account,
            activities.fetch_documents,
            activities.fetch_credit_report_cibil,
            activities.fetch_credit_report_experian,
            activities.income_assessment,
            activities.expense_assessment,
            activities.credit_assessment,
            activities.aggregate_and_decide
        ]
    )

    print("Worker started, polling task queue:", TASK_QUEUE)
    await w.run()


def main():
    # Use asyncio.run() which handles event loop creation/cleanup automatically
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("\nWorker stopped by user")


if __name__ == "__main__":
    main()
