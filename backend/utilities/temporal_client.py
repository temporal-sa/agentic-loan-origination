"""
Temporal Client Connection Utility

This module provides a unified interface for connecting to either:
1. Local Temporal server (default)
2. Temporal Cloud with API key authentication

The connection type is determined by the presence of TEMPORAL_API_KEY.
"""

import os
from temporalio.client import Client, TLSConfig
from typing import Optional


async def get_temporal_client(namespace: Optional[str] = None) -> Client:
    """
    Create and return a Temporal client connection.

    Automatically detects whether to connect to local Temporal or Temporal Cloud
    based on the presence of TEMPORAL_API_KEY environment variable.

    Args:
        namespace: Optional namespace override. If not provided, uses TEMPORAL_NAMESPACE

    Returns:
        Connected Temporal Client instance

    Environment Variables:
        TEMPORAL_ADDRESS: Server address
            - Local: localhost:7233 (default)
            - Cloud: namespace.account-id.tmprl.cloud:7233

        TEMPORAL_NAMESPACE: Namespace
            - Local: default (default)
            - Cloud: namespace.account-id

        TEMPORAL_API_KEY: API key for Temporal Cloud authentication (optional)
            - If set: Connects to Temporal Cloud with TLS and API key auth
            - If not set: Connects to local Temporal without authentication
    """

    # Get common configuration
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace_value = namespace or os.getenv("TEMPORAL_NAMESPACE", "default")
    api_key = os.getenv("TEMPORAL_API_KEY")

    if api_key:
        # Temporal Cloud configuration (with API key)
        print(f"Connecting to Temporal Cloud at {address} (namespace: {namespace_value})")

        # Connect to Temporal Cloud with TLS and API key authentication
        client = await Client.connect(
            address,
            namespace=namespace_value,
            tls=True,  # Enable TLS for cloud connection
            rpc_metadata={
                "temporal-namespace": namespace_value,
                "authorization": f"Bearer {api_key}"
            }
        )

        print(f"Successfully connected to Temporal Cloud")
        return client

    else:
        # Local Temporal configuration (no API key)
        print(f"Connecting to local Temporal at {address} (namespace: {namespace_value})")

        # Connect to local Temporal server (no TLS, no auth)
        client = await Client.connect(
            address,
            namespace=namespace_value
        )

        print(f"Successfully connected to local Temporal")
        return client
