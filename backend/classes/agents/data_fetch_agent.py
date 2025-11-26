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

    async def fetch_data(self, url: str, data_type: str) -> Dict[str, Any]:
        """
        Fetch data from an API endpoint using the Strands agent.

        Args:
            url: The API endpoint URL
            data_type: Type of data being fetched (for logging/errors)

        Returns:
            Parsed JSON response data
        """
        try:
            # Agent makes the HTTP request using its tool asynchronously
            # The agent will reason and decide to use the http_request tool
            prompt = f"Make a GET request to {url}. Extract and return only the JSON response body, nothing else."
            result = await self.agent.invoke_async(prompt)

            # Access the final message from AgentResult
            if not result.message:
                raise ValueError(f"No response from agent for {data_type} API")

            # Extract text content from the message
            message_content = result.message.get("content", [])
            response_text = None

            for item in message_content:
                if isinstance(item, dict) and "text" in item:
                    response_text = item["text"]
                    break

            if not response_text:
                raise ValueError(f"No text content in agent response for {data_type} API")

            # Parse the JSON response
            parsed_data = json.loads(response_text)
            activity.logger.info(f"Successfully fetched {data_type} data: {parsed_data}")
            return parsed_data

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in {data_type} API response: {str(e)}"
            if response_text:
                error_msg += f". Response: {response_text[:200]}"
            raise ValueError(error_msg)
        except Exception as e:
            raise Exception(f"Failed to fetch {data_type} data: {str(e)}")
