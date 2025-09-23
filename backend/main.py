from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from strands import Agent
from strands.models.ollama import OllamaModel
from temporalio.client import Client
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

app = FastAPI()

TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "loan-underwriter-queue")

# Initialize Strands Agent with Ollama model
try:
    ollama_model = OllamaModel(
        host=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
        model_id=os.getenv("OLLAMA_MODEL", "llama3.2:1b")  # Use faster model
    )
    strands_agent = Agent(model=ollama_model)
    strands_enabled = True
    print("Strands Agent initialized successfully")
except Exception as e:
    print(f"Warning: Failed to initialize Strands Agent: {e}")
    strands_agent = None
    strands_enabled = False


class LoanApplication(BaseModel):
    """Loan application data model for processing loan requests."""
    applicant_id: str = Field(description="Unique identifier for the loan applicant")
    name: str = Field(description="Full name of the loan applicant")
    amount: float = Field(description="Requested loan amount")
    income: Optional[float] = Field(default=None, description="Monthly income of the applicant")
    expenses: Optional[float] = Field(default=None, description="Monthly expenses of the applicant")


@app.post("/submit")
async def submit_application(app_data: dict):
    try:
        # Use Strands Agents for structured validation if available, otherwise use direct Pydantic validation
        if strands_enabled and strands_agent:
            try:
                validated_data = strands_agent.structured_output(
                    LoanApplication,
                    f"Validate this loan application data: {app_data}"
                )
                print(f"Received application (via Strands): {validated_data}")
            except Exception as strands_error:
                print(f"Strands validation failed, falling back to direct validation: {strands_error}")
                validated_data = LoanApplication(**app_data)
                print(f"Received application (direct): {validated_data}")
        else:
            validated_data = LoanApplication(**app_data)
            print(f"Received application (direct): {validated_data}")

        client = await Client.connect("localhost:7233", namespace=TEMPORAL_NAMESPACE)
        print("Connected to Temporal")

        handle = await client.start_workflow(
            "SupervisorWorkflow",
            validated_data.model_dump(),
            id=f"loan-{validated_data.applicant_id}",
            task_queue=TASK_QUEUE,
        )
        print(f"Workflow started: {handle.id}")
        return {"workflow_id": handle.id, "run_id": handle.run_id}
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{workflow_id}")
async def status(workflow_id: str):
    client = await Client.connect("localhost:7233", namespace=TEMPORAL_NAMESPACE)
    try:
        wf = client.get_workflow_handle(workflow_id)

        # Attempt to query the workflow for summary and final result (queries are optional)
        summary = None
        final = None
        try:
            summary = await wf.query("get_summary")
        except Exception:
            # query may not be implemented or workflow not at that stage
            summary = None

        try:
            final = await wf.query("get_final_result")
        except Exception:
            final = None

        # Also include describe() metadata to help debugging
        try:
            desc = await wf.describe()
        except Exception:
            desc = None

        return {"workflow_id": workflow_id, "summary": summary, "final_result": final, "describe": desc}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflow/{workflow_id}/summary")
async def get_summary(workflow_id: str):
    client = await Client.connect("localhost:7233", namespace=TEMPORAL_NAMESPACE)
    try:
        wf = client.get_workflow_handle(workflow_id)
        # call query - make sure query name matches the method name
        summary = await wf.query("get_summary")
        # Ensure response is JSON serializable
        result = {
            "workflow_id": workflow_id,
            "summary": summary if summary is not None else {"status": "pending"}
        }
        return result
    except Exception as e:
        print(f"Error in get_summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ReviewRequest(BaseModel):
    """Human review request for loan application processing."""
    action: str = Field(description="Review action to take (approve, reject, etc.)")
    note: str = Field(default="", description="Optional review notes or comments")


@app.post("/workflow/{workflow_id}/review")
async def human_review(workflow_id: str, review: dict):
    try:
        # Use Strands Agents for structured validation if available, otherwise use direct Pydantic validation
        if strands_enabled and strands_agent:
            try:
                validated_review = strands_agent.structured_output(
                    ReviewRequest,
                    f"Validate this review request data: {review}"
                )
                print(f"Review validated (via Strands): {validated_review}")
            except Exception as strands_error:
                print(f"Strands validation failed, falling back to direct validation: {strands_error}")
                validated_review = ReviewRequest(**review)
                print(f"Review validated (direct): {validated_review}")
        else:
            validated_review = ReviewRequest(**review)
            print(f"Review validated (direct): {validated_review}")

        client = await Client.connect("localhost:7233", namespace=TEMPORAL_NAMESPACE)
        wf = client.get_workflow_handle(workflow_id)
        # send signal
        await wf.signal("human_review", validated_review.model_dump())
        return {"workflow_id": workflow_id, "signaled": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflow/{workflow_id}/final")
async def get_final_result(workflow_id: str):
    client = await Client.connect("localhost:7233", namespace=TEMPORAL_NAMESPACE)
    try:
        wf = client.get_workflow_handle(workflow_id)
        final = await wf.query("get_final_result")
        # Ensure response is JSON serializable
        result = {
            "workflow_id": workflow_id,
            "final_result": final if final is not None else {"status": "not_ready"}
        }
        return result
    except Exception as e:
        print(f"Error in get_final_result: {e}")
        raise HTTPException(status_code=500, detail=str(e))
