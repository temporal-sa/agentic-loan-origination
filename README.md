# Agentic Loan Underwriter Demo

This repository demonstrates an agentic loan underwriting system built with Temporal workflows, Strands agent orchestration, Ollama LLM integration, and a Streamlit UI. The system simulates a loan underwriter copilot with specialist agents and supervisor orchestration for automated loan processing with human review capabilities.

## Architecture
- **FastAPI Backend**: REST API with endpoints for loan submission, workflow status checking, and human review
- **Temporal Workflows**: SupervisorWorkflow orchestrates the entire loan processing pipeline with durable execution
- **Strands HTTP Agents**: Reusable agent classes for intelligent data fetching with error handling and validation
  - `DataFetchAgent`: Generic HTTP data fetching with validation
  - `CreditReportAgent`: Specialized credit report validation with multi-provider support
- **Specialist Activities**: Mock data fetching (bank, documents, credit) and AI-powered assessments (income, expense, credit analysis)
- **Strands Integration**: Agent orchestration with structured output validation using Ollama models
- **Provider Fallback**: Temporal-orchestrated fallback from CIBIL to Experian for credit reports
- **Streamlit UI**: User interface for loan submission and underwriter review workflow
- **Environment Configuration**: Configurable Ollama and Temporal settings via `.env` file

## Sequence diagram
The diagram below shows the end-to-end flow: user submits via Streamlit, Streamlit calls FastAPI which starts a Temporal workflow. A worker executes activities (mock APIs and specialist agents), the workflow calls Ollama for a summary/decision, then the system awaits a human-review signal. The underwriter approves/rejects via the UI which signals the running workflow.

```mermaid
sequenceDiagram
	participant User as Applicant / Underwriter
	participant Streamlit as Streamlit UI
	participant FastAPI as FastAPI Backend
	participant Temporal as Temporal Server
	participant Worker as Temporal Worker
	participant Supervisor as SupervisorWorkflow
	participant DataAgent as DataFetchAgent
	participant CreditAgent as CreditReportAgent
	participant Mockoon as Mock APIs
	participant Ollama as Ollama (LLM)

	User->>Streamlit: Submit loan application
	Streamlit->>FastAPI: POST /submit (application data)
	FastAPI->>Temporal: start_workflow("SupervisorWorkflow", data, workflow_id)
	Temporal->>Worker: schedule activities on task queue

	Note over Worker, Supervisor: PHASE 1: Data Acquisition (Sequential)
	Worker->>DataAgent: fetch_bank_account(applicant_id)
	DataAgent->>Mockoon: HTTP GET /bank?applicant_id=X
	Mockoon-->>DataAgent: bank account data
	DataAgent-->>Worker: validated bank data

	Worker->>DataAgent: fetch_documents(applicant_id)
	DataAgent->>Mockoon: HTTP GET /documents?applicant_id=X
	Mockoon-->>DataAgent: document metadata
	DataAgent-->>Worker: validated documents

	Worker->>CreditAgent: fetch_credit_report_cibil(applicant_id)
	CreditAgent->>Mockoon: HTTP GET /cibil?applicant_id=X
	alt CIBIL Success
		Mockoon-->>CreditAgent: credit report data
		CreditAgent-->>Worker: validated credit (provider: CIBIL)
	else CIBIL Failure (after 2 retries)
		Note over Supervisor: Temporal orchestrates fallback
		Worker->>CreditAgent: fetch_credit_report_experian(applicant_id)
		CreditAgent->>Mockoon: HTTP GET /experian?applicant_id=X
		Mockoon-->>CreditAgent: credit report data
		CreditAgent-->>Worker: validated credit (provider: Experian)
	end

	Note over Worker, Supervisor: PHASE 2: Parallel Specialist Assessments
	par Income Assessment
		Worker->>Worker: income_assessment(app, bank, credit)
		Note over Worker: Heuristic: income/amount ratio > 2
		Worker->>Worker: income_ok + income value
	and Expense Assessment
		Worker->>Worker: expense_assessment(app, bank)
		Note over Worker: Heuristic: disposable income check
		Worker->>Worker: affordability_ok + expenses
	and Credit Assessment
		Worker->>Worker: credit_assessment(app, credit)
		Note over Worker: Heuristic: score > 620
		Worker->>Worker: credit_ok + score
	end

	Note over Worker, Supervisor: PHASE 3: Decision Aggregation with LLM
	Worker->>Ollama: aggregate_and_decide(all data)
	Note over Ollama: Strands Agent + Ollama Model
	Ollama-->>Worker: AI summary + recommendation
	Worker-->>Supervisor: Store summary with suggested decision

	Note over Supervisor: PHASE 4: Human-in-the-Loop Review
	Note over Supervisor: Workflow pauses, exposes queries

	User->>Streamlit: Navigate to Review tab
	Streamlit->>FastAPI: GET /workflow/{id}/summary
	FastAPI->>Temporal: query("get_summary")
	Temporal->>Supervisor: get_summary query
	Supervisor-->>Temporal: summary with assessments + AI decision
	Temporal-->>FastAPI: complete summary
	FastAPI-->>Streamlit: display summary JSON
	Streamlit-->>User: Show AI analysis + recommendation

	User->>Streamlit: Click Approve/Reject
	Streamlit->>FastAPI: POST /workflow/{id}/review {"action": "approve/reject"}
	FastAPI->>Temporal: signal("human_review", decision)
	Temporal->>Supervisor: receive human_review signal
	Note over Supervisor: Workflow continues and completes
	Supervisor-->>Temporal: finalize with human decision

	opt Final Status Check
		Streamlit->>FastAPI: GET /workflow/{id}/final
		FastAPI->>Temporal: query("get_final_result")
		Temporal->>Supervisor: get_final_result query
		Supervisor-->>Temporal: complete result
		Temporal-->>FastAPI: summary + human decision
		FastAPI-->>Streamlit: display final outcome
	end
```

## Prerequisites
- **Temporal Server**: Running locally (default at localhost:7233)
- **Ollama**: Local installation with model (default: `llama3.2:1b`, configurable via `.env`)
- **Mockoon**: Mock API server running on port 3233 (configuration available in `mockoon` folder)
- **Python 3.9+**: Required for all dependencies
- **Dependencies**: Install from `requirements.txt`

## Setup & Installation

1. **Clone and setup environment:**
```bash
git clone <repository-url>
cd temporal-agentic--loan-underwriter
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment variables:**
```bash
cp .env.example .env
# Edit .env to customize Ollama URL, model, and Temporal settings
```

3. **Start required services:**
   - Start Temporal server (see [Temporal docs](https://docs.temporal.io/dev-guide/))
   - Start Ollama with your preferred model (e.g., `ollama run llama3.2:1b`)
   - Start Mockoon with the configuration from the `mockoon` folder (import the JSON config file into Mockoon and start the mock API on port 3233)

4. **Launch the application:**

   **Terminal 1 - Temporal Worker:**
   ```bash
   python backend/worker.py
   ```

   **Terminal 2 - FastAPI Backend:**
   ```bash
   uvicorn backend.main:app --reload --port 8000
   ```

   **Terminal 3 - Streamlit UI:**
   ```bash
   streamlit run ui/streamlit_app.py
   ```

5. **Access the application:**
   - Streamlit UI: http://localhost:8501
   - FastAPI docs: http://localhost:8000/docs

## Key Features
- **Structured Data Validation**: Strands integration provides automatic validation of loan applications
- **Mock Data Services**: Simulated bank account, document, and credit report fetching
- **AI-Powered Analysis**: Specialist agents for income, expense, and credit assessment using Ollama
- **Human-in-the-Loop**: Workflow pauses for human underwriter review and decision
- **Durable Execution**: Temporal ensures reliable workflow execution with automatic retries
- **Real-time UI**: Streamlit interface for application submission and review workflow

## Project Structure
```
├── backend/
│   ├── main.py                              # FastAPI application and API endpoints
│   ├── workflows.py                         # Temporal SupervisorWorkflow definition
│   ├── activities.py                        # Temporal activities (data fetching & AI assessments)
│   ├── worker.py                            # Temporal worker process
│   └── classes/
│       └── agents/
│           ├── data_fetch_agent.py          # Strands agent for HTTP data fetching
│           └── credit_report_agent.py       # Strands agent for credit report validation
├── ui/
│   └── streamlit_app.py                     # Streamlit user interface
├── mockoon/                                 # Mock API configuration for local development
├── .env.example                             # Environment configuration template
└── requirements.txt                         # Python dependencies
```

## Development Notes
- **Mock Data Services**: Uses Mockoon for simulating bank, document, and credit bureau APIs
- **Agent Architecture**: Strands agents are organized in reusable classes under `backend/classes/agents/`
- **Separation of Concerns**:
  - Temporal activities handle durable execution and retry logic (outer loop)
  - Strands agents handle intelligent data fetching and validation (inner loop)
- **Provider Fallback Pattern**: Temporal workflow orchestrates CIBIL → Experian fallback for credit reports
- **Configurable LLM**: Ollama model selection via environment variables (default: `llama3.2:1b`)
- **Production Considerations**: Would require secure API integrations, authentication, and real data providers
- **Human-in-the-Loop**: Workflow supports binary approve/reject decisions with AI-generated explanations

## Contributing

We welcome contributions to improve this demo! Here's how you can help:

### Getting Started
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes and test locally
4. Commit with clear messages: `git commit -m "Add: description of changes"`
5. Push to your fork: `git push origin feature/your-feature-name`
6. Open a Pull Request with a clear description of your changes

### Contribution Ideas
- **Enhanced AI Models**: Integration with other LLM providers (OpenAI, Anthropic, etc.)
- **Real Integrations**: Replace mock activities with actual bank/credit APIs
- **UI Improvements**: Enhanced Streamlit interface or alternative frontend
- **Security Features**: Authentication, authorization, and data encryption
- **Testing**: Unit tests, integration tests, and workflow testing
- **Documentation**: API documentation, deployment guides, or tutorials
- **Performance**: Optimization and monitoring capabilities

### Code Standards
- Follow existing code style and patterns
- Add appropriate error handling and logging
- Update documentation for any new features
- Ensure all tests pass before submitting

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Copyright (c) 2025 Darshit Vora

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
