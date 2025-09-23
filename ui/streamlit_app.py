import streamlit as st
import requests
from typing import Any, Dict, Optional

try:
    API_URL = st.secrets.get("api_url", "http://localhost:8000")
except:
    API_URL = "http://localhost:8000"


st.title("Agentic Loan Underwriter — Demo")

tab = st.tabs(["Submit", "Review"])


with tab[0]:
    with st.form("submit_form"):
        applicant_id = st.text_input("Applicant ID", "12345")
        name = st.text_input("Name", "Alice")
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
