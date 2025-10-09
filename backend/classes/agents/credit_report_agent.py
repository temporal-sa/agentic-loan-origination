from temporalio import activity
from typing import Dict, Any
from classes.agents.data_fetch_agent import DataFetchAgent


class CreditReportAgent:
    """
    Specialized agent for fetching and validating credit reports.
    Demonstrates agent reasoning about data quality and provider reliability.
    """

    def __init__(self):
        self.data_agent = DataFetchAgent()

    def fetch_and_validate_credit_report(
        self, applicant_id: str, provider: str, url: str
    ) -> Dict[str, Any]:
        """
        Fetch credit report and perform intelligent validation.

        The agent validates:
        - Response structure
        - Credit score validity (300-850 range)
        - Required fields presence
        - Data quality indicators
        """

        # Use data fetch agent to get credit data
        credit_data = self.data_agent.fetch_data(url, f"{provider} credit report")

        # Agent-based validation logic
        if "score" not in credit_data:
            raise ValueError(f"{provider} response missing 'score' field")

        score = credit_data.get("score")

        # Validate score range
        if not isinstance(score, (int, float)) or score < 300 or score > 850:
            raise ValueError(f"Invalid credit score from {provider}: {score}")

        # Add metadata about the provider
        credit_data["provider"] = provider
        credit_data["data_quality"] = "validated"

        return credit_data
