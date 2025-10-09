from temporalio import activity
from typing import Dict, Any
import json
from strands import Agent
from strands_tools import http_request


class DataFetchAgent:
    """
    Specialized Strands agent for fetching data from external APIs.
    Demonstrates the inner loop of agent-based data acquisition within
    a Temporal activity (outer loop).
    """

    def __init__(self):
        """Initialize the data fetch agent with HTTP request capabilities."""
        self.agent = Agent(
            system_prompt="""You are a data acquisition specialist agent for a loan underwriting system.

Your responsibilities:
1. Make HTTP requests to external APIs
2. Validate the response data structure
3. Extract and parse JSON responses
4. Handle errors gracefully with detailed context
5. Return clean, structured data

When making requests:
- Use the http_request tool to fetch data
- Always validate that responses contain expected fields
- Parse JSON bodies correctly
- Report any data quality issues""",
            tools=[http_request]
        )

    def fetch_data(self, url: str, data_type: str) -> Dict[str, Any]:
        """
        Fetch data from an API endpoint using the Strands agent.

        Args:
            url: The API endpoint URL
            data_type: Type of data being fetched (for logging/errors)

        Returns:
            Parsed JSON response data
        """
        try:
            # Agent makes the HTTP request using its tool
            response = self.agent.tool.http_request(
                method="GET",
                url=url
            )

            # Extract body from response
            body_text = None
            for item in response.get("content", []):
                if isinstance(item, dict) and "text" in item:
                    if item["text"].startswith("Body:"):
                        body_text = item["text"][len("Body:"):].strip()
                        break

            if not body_text:
                raise ValueError(f"No body found in {data_type} API response")

            # Parse JSON
            parsed_data = json.loads(body_text)

            activity.logger.info(f"Successfully fetched {data_type} data: {parsed_data}")
            return parsed_data

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {data_type} API response: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to fetch {data_type} data: {str(e)}")
