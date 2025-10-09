import streamlit as st
import requests
from typing import Any, Dict, Optional

try:
    API_URL = st.secrets.get("api_url", "http://localhost:8000")
except:
    API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Intelligent Loan Underwriter",
    page_icon="",
)
st.title("Intelligent Loan Underwriter — Demo")

tab = st.tabs(["Submit", "Review", "Workflows"])


with tab[0]:
    with st.form("submit_form"):
        applicant_id = st.text_input("Applicant ID", "12345")
        name = st.text_input("Name", "Darshit")
        amount = st.number_input("Loan amount", value=5000.0)
        income = st.number_input("Declared income", value=6000.0)
        expenses = st.number_input("Monthly expenses", value=2000.0)
        submitted = st.form_submit_button("Submit")

    if submitted:
        payload = {
            "applicant_id": applicant_id,
            "name": name,
            "amount": amount,
            "income": income,
            "expenses": expenses,
        }
        try:
            r = requests.post(f"{API_URL}/submit", json=payload, timeout=10)
            r.raise_for_status()
            data = r.json()
            st.success("Workflow started")
            st.json(data)
        except Exception as e:
            st.error(f"Failed to start workflow: {e}")


with tab[1]:
    st.header("Human review")
    review_workflow_id = st.text_input("Workflow ID to review", "")

    summary_data = None
    if st.button("Fetch Loan Details") and review_workflow_id:
        try:
            r = requests.get(f"{API_URL}/workflow/{review_workflow_id}/summary", timeout=10)
            r.raise_for_status()
            summary_data = r.json()
            st.session_state[f"summary_{review_workflow_id}"] = summary_data
        except Exception as e:
            st.error(f"Failed to fetch summary: {e}")

    # Check if we have cached summary data
    if f"summary_{review_workflow_id}" in st.session_state:
        summary_data = st.session_state[f"summary_{review_workflow_id}"]

    if summary_data and review_workflow_id:
        summary = summary_data.get("summary", {})
        application = summary.get("application", {})
        assessments = summary.get("assessments", {})
        suggested_decision = summary.get("suggested_decision", {})


        # Display AI analysis summary from assessments
        if assessments:
            st.markdown("### 🤖 AI Analysis Summary")

            # Create columns for better layout
            assessment_cols = st.columns(len(assessments))

            for idx, (assessment_type, assessment_data) in enumerate(assessments.items()):
                if assessment_data:
                    with assessment_cols[idx]:
                        st.markdown(f"### {assessment_type.replace('_', ' ').title()}")

                        if isinstance(assessment_data, dict):
                            # Create a clean card-like display
                            for key, value in assessment_data.items():
                                if key.lower() in ['score', 'rating', 'risk']:
                                    # Highlight important metrics
                                    st.metric(label=key.replace('_', ' ').title(), value=str(value))
                                else:
                                    st.markdown(f"**{key.replace('_', ' ').title()}:** {value}")
                        else:
                            st.markdown(assessment_data)

            st.markdown("---")

        # Display loan application details
        st.markdown("## 📋 Loan Application Details")

        # Create a more organized layout with cards
        app_col1, app_col2, app_col3 = st.columns(3)

        with app_col1:
            st.markdown("#### 👤 Applicant Info")
            st.metric("Name", application.get("name", "N/A"))
            st.metric("ID", application.get("applicant_id", "N/A"))

        with app_col2:
            st.markdown("#### 💰 Financial Request")
            amount = application.get('amount', 0)
            st.metric("Requested Loan", f"${amount:,.2f}")

            # Calculate debt-to-income ratio if possible
            if application.get('income'):
                monthly_payment_est = (amount * 0.05) / 12  # Rough 5% APR estimate
                st.metric("Est. Monthly Payment", f"${monthly_payment_est:,.2f}")

        with app_col3:
            st.markdown("#### 📊 Financial Profile")
            income = application.get('income', 0)
            expenses = application.get('expenses', 0)

            st.metric("Monthly Income", f"${income:,.2f}")
            st.metric("Monthly Expenses", f"${expenses:,.2f}")

            if income and expenses:
                net_income = income - expenses
                if net_income > 0:
                    st.metric("Net Monthly Income", f"${net_income:,.2f}", delta="Positive")
                else:
                    st.metric("Net Monthly Income", f"${net_income:,.2f}", delta="Negative")

        st.markdown("---")


        # Show structured data for review
        with st.expander("📊 Detailed Review Data", expanded=True):
            if summary_data:
                # Create tabs for different data sections
                data_tabs = st.tabs(["🏦 External Tools", "📊 Assessment Details", "⚙️ Processing Info"])

                with data_tabs[0]:
                    st.markdown("#### External Data Sources")

                    # Credit Report Data
                    if "credit" in summary and summary["credit"]:
                        st.markdown("**📋 Credit Report**")
                        credit = summary["credit"]
                        if isinstance(credit, dict):
                            credit_col1, credit_col2 = st.columns(2)
                            with credit_col1:
                                for key, value in list(credit.items())[:len(credit.items())//2]:
                                    st.text(f"{key.replace('_', ' ').title()}: {value}")
                            with credit_col2:
                                for key, value in list(credit.items())[len(credit.items())//2:]:
                                    st.text(f"{key.replace('_', ' ').title()}: {value}")
                        else:
                            st.text(credit)
                        st.markdown("---")

                    # Bank Account Data
                    if "bank" in summary and summary["bank"]:
                        st.markdown("**🏛️ Bank Account Information**")
                        bank = summary["bank"]
                        if isinstance(bank, dict):
                            for key, value in bank.items():
                                st.text(f"{key.replace('_', ' ').title()}: {value}")
                        else:
                            st.text(bank)
                        st.markdown("---")

                    # Documents
                    if "docs" in summary and summary["docs"]:
                        st.markdown("**📄 Document Verification**")
                        docs = summary["docs"]
                        if isinstance(docs, dict):
                            for key, value in docs.items():
                                st.text(f"{key.replace('_', ' ').title()}: {value}")
                        else:
                            st.text(docs)

                with data_tabs[1]:
                    st.markdown("#### Detailed Assessment Results")

                    # Assessments from the workflow
                    if assessments:
                        for assessment_type, assessment_data in assessments.items():
                            if assessment_data:
                                st.markdown(f"**{assessment_type.replace('_', ' ').title()} Assessment Agent**")
                                if isinstance(assessment_data, dict):
                                    for key, value in assessment_data.items():
                                        st.text(f"• {key.replace('_', ' ').title()}: {value}")
                                else:
                                    st.text(f"• {assessment_data}")
                                st.markdown("---")

                    # Suggested Decision Details
                    if suggested_decision and isinstance(suggested_decision, dict):
                        st.markdown("**🤖 Supervisor Agent Decisioning**")
                        for key, value in suggested_decision.items():
                            st.text(f"• {key.replace('_', ' ').title()}: {value}")

                with data_tabs[2]:
                    st.markdown("#### Technical Processing Information")

                    # Workflow details
                    if "workflow_id" in summary_data:
                        st.text(f"Workflow ID: {summary_data['workflow_id']}")

                    if "status" in summary_data:
                        st.text(f"Status: {summary_data['status']}")

                    if "created_at" in summary_data:
                        st.text(f"Created: {summary_data['created_at']}")

                    if "updated_at" in summary_data:
                        st.text(f"Last Updated: {summary_data['updated_at']}")

        # Decision buttons
        st.markdown("## 💼 Make Your Decision")
        st.markdown("*Review all information above and make your final decision:*")

        decision_col1, decision_col2, decision_col3 = st.columns([2, 1, 2])

        with decision_col1:
            if st.button("✅ **APPROVE LOAN**", type="primary", use_container_width=True):
                try:
                    r = requests.post(f"{API_URL}/workflow/{review_workflow_id}/review",
                                    json={"action": "approve", "note": "Approved via UI"}, timeout=10)
                    r.raise_for_status()
                    st.success("✅ **Loan Approved Successfully!**")
                    st.balloons()
                except Exception as e:
                    st.error(f"Failed to signal approval: {e}")

        with decision_col3:
            if st.button("❌ **REJECT LOAN**", type="secondary", use_container_width=True):
                try:
                    r = requests.post(f"{API_URL}/workflow/{review_workflow_id}/review",
                                    json={"action": "reject", "note": "Rejected via UI"}, timeout=10)
                    r.raise_for_status()
                    st.error("❌ **Loan Rejected**")
                except Exception as e:
                    st.error(f"Failed to signal rejection: {e}")

    elif review_workflow_id:
        st.info("👆 Click 'Fetch Loan Details' to load the application for review")


with tab[2]:
    st.header("🔄 Loan Workflows")

    workflows_data = None

    col1, col2 = st.columns([1, 4])

    with col1:
        if st.button("🔄 Refresh Workflows", type="secondary"):
            with st.spinner("Loading workflows..."):
                try:
                    r = requests.get(f"{API_URL}/workflows", timeout=30)
                    r.raise_for_status()
                    workflows_data = r.json()
                    st.session_state["workflows_data"] = workflows_data
                    st.success(f"Loaded {len(workflows_data.get('workflows', []))} workflows")
                except Exception as e:
                    st.error(f"Failed to load workflows: {e}")

    with col2:
        st.info("Click 'Refresh Workflows' to load the latest loan applications and their status")

    # Check if we have cached workflows data
    if "workflows_data" in st.session_state:
        workflows_data = st.session_state["workflows_data"]

    if workflows_data and workflows_data.get("workflows"):
        workflows = workflows_data["workflows"]

        # Summary metrics
        st.subheader("📊 Summary")

        total_workflows = len(workflows)
        running_workflows = len([w for w in workflows if w["status"] in ["RUNNING", "WORKFLOW_EXECUTION_STATUS_RUNNING"]])
        completed_workflows = len([w for w in workflows if w["status"] in ["COMPLETED", "WORKFLOW_EXECUTION_STATUS_COMPLETED"]])
        approved_loans = len([w for w in workflows if w.get("human_decision") == "approve"])
        rejected_loans = len([w for w in workflows if w.get("human_decision") == "reject"])

        metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)

        with metric_col1:
            st.metric("Total Workflows", total_workflows)
        with metric_col2:
            st.metric("Running", running_workflows)
        with metric_col3:
            st.metric("Completed", completed_workflows)
        with metric_col4:
            st.metric("Approved", approved_loans)
        with metric_col5:
            st.metric("Rejected", rejected_loans)

        st.markdown("---")

        # Workflows table
        st.subheader("📋 Workflows Details")

        # Create a scrollable table using st.dataframe
        display_data = []

        for workflow in workflows:
            # Format the status with color indicators
            status = workflow.get("status", "Unknown").replace("WORKFLOW_EXECUTION_STATUS_", "")

            # Format loan amount
            loan_amount = workflow.get("loan_amount", 0)
            formatted_amount = f"${loan_amount:,.2f}" if loan_amount else "N/A"

            # Format timestamps
            start_time = workflow.get("start_time")
            formatted_start_time = start_time[:19].replace("T", " ") if start_time else "N/A"

            display_data.append({
                "Workflow ID": workflow.get("workflow_id", "N/A")[:20] + "...",
                "Applicant": workflow.get("applicant_name", "Unknown"),
                "Applicant ID": workflow.get("applicant_id", "Unknown"),
                "Loan Amount": formatted_amount,
                "Status": status,
                "Human Decision": workflow.get("human_decision", "Pending") or "Pending",
                "Started": formatted_start_time
            })

        # Display the table with custom styling
        st.dataframe(
            display_data,
            use_container_width=True,
            height=400,  # Make it scrollable
            column_config={
                "Workflow ID": st.column_config.TextColumn("Workflow ID", width="small"),
                "Applicant": st.column_config.TextColumn("Applicant", width="small"),
                "Applicant ID": st.column_config.TextColumn("ID", width="small"),
                "Loan Amount": st.column_config.TextColumn("Amount", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Human Decision": st.column_config.TextColumn("Decision", width="small"),
                "Started": st.column_config.TextColumn("Started", width="medium")
            }
        )

        # Workflow details expander
        st.markdown("---")
        st.subheader("🔍 Workflow Details")

        # Select a workflow to view details
        workflow_ids = [w["workflow_id"] for w in workflows]
        selected_workflow_id = st.selectbox(
            "Select a workflow to view detailed information:",
            [""] + workflow_ids,
            format_func=lambda x: x[:30] + "..." if len(x) > 30 else x if x else "Select a workflow..."
        )

        if selected_workflow_id:
            selected_workflow = next((w for w in workflows if w["workflow_id"] == selected_workflow_id), None)

            if selected_workflow:
                # Create tabs for different details
                detail_tabs = st.tabs(["📋 Application", "🤖 AI Analysis", "👤 Human Review", "⚙️ Technical"])

                with detail_tabs[0]:
                    st.markdown("#### Loan Application Details")
                    summary = selected_workflow.get("summary", {})
                    application = summary.get("application", {}) if summary else {}

                    app_col1, app_col2 = st.columns(2)
                    with app_col1:
                        st.text(f"Name: {application.get('name', 'N/A')}")
                        st.text(f"Applicant ID: {application.get('applicant_id', 'N/A')}")
                        st.text(f"Loan Amount: ${application.get('amount', 0):,.2f}")

                    with app_col2:
                        st.text(f"Monthly Income: ${application.get('income', 0):,.2f}")
                        st.text(f"Monthly Expenses: ${application.get('expenses', 0):,.2f}")
                        net_income = (application.get('income', 0) or 0) - (application.get('expenses', 0) or 0)
                        st.text(f"Net Income: ${net_income:,.2f}")

                with detail_tabs[1]:
                    st.markdown("#### AI Analysis Results")

                    # Get AI recommendation and summary from the proper location
                    summary = selected_workflow.get("summary", {})
                    suggested_decision = summary.get("suggested_decision", {}) if summary else {}

                    # Show additional suggested decision details if available
                    if suggested_decision:
                        st.markdown("**Additional AI Analysis:**")
                        for key, value in suggested_decision.items():
                            if value:
                                st.text(f"• {key.replace('_', ' ').title()}: {value}")

                    # Detailed assessments if available
                    if summary and summary.get("assessments"):
                        st.markdown("---")
                        st.markdown("**Detailed Assessments:**")
                        assessments = summary["assessments"]

                        for assessment_type, assessment_data in assessments.items():
                            if assessment_data:
                                st.markdown(f"**{assessment_type.replace('_', ' ').title()}:**")
                                if isinstance(assessment_data, dict):
                                    for key, value in assessment_data.items():
                                        st.text(f"  • {key.replace('_', ' ').title()}: {value}")
                                else:
                                    st.text(f"  • {assessment_data}")

                with detail_tabs[2]:
                    st.markdown("#### Human Review")

                    human_decision = selected_workflow.get("human_decision")
                    if human_decision:
                        st.markdown(f"**Decision:** {human_decision}")

                        final_result = selected_workflow.get("final_result", {})
                        if final_result and final_result.get("human_decision"):
                            human_review = final_result["human_decision"]
                            if human_review.get("note"):
                                st.markdown(f"**Note:** {human_review['note']}")
                    else:
                        st.info("No human decision recorded yet")

                        # Quick review buttons
                        if selected_workflow.get("status") in ["RUNNING", "WORKFLOW_EXECUTION_STATUS_RUNNING"]:
                            st.markdown("**Quick Review:**")
                            review_col1, review_col2 = st.columns(2)

                            with review_col1:
                                if st.button(f"✅ Approve {selected_workflow_id[:8]}...", key=f"approve_{selected_workflow_id}"):
                                    try:
                                        r = requests.post(f"{API_URL}/workflow/{selected_workflow_id}/review",
                                                        json={"action": "approve", "note": "Approved from workflows tab"}, timeout=10)
                                        r.raise_for_status()
                                        st.success("Loan approved!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed to approve: {e}")

                            with review_col2:
                                if st.button(f"❌ Reject {selected_workflow_id[:8]}...", key=f"reject_{selected_workflow_id}"):
                                    try:
                                        r = requests.post(f"{API_URL}/workflow/{selected_workflow_id}/review",
                                                        json={"action": "reject", "note": "Rejected from workflows tab"}, timeout=10)
                                        r.raise_for_status()
                                        st.success("Loan rejected!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed to reject: {e}")

                with detail_tabs[3]:
                    st.markdown("#### Technical Information")

                    tech_col1, tech_col2 = st.columns(2)

                    with tech_col1:
                        st.text(f"Workflow ID: {selected_workflow.get('workflow_id', 'N/A')}")
                        st.text(f"Run ID: {selected_workflow.get('run_id', 'N/A')}")
                        st.text(f"Status: {selected_workflow.get('status', 'N/A')}")

                    with tech_col2:
                        st.text(f"Start Time: {selected_workflow.get('start_time', 'N/A')}")
                        st.text(f"Close Time: {selected_workflow.get('close_time', 'N/A')}")

                    # Raw data expander
                    with st.expander("Raw Workflow Data"):
                        st.json(selected_workflow)

    else:
        st.info("No workflows loaded. Click 'Refresh Workflows' to load loan applications.")
