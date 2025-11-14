import os
from strands.models.ollama import OllamaModel
from strands.models import BedrockModel
from pydantic import BaseModel

def get_model() -> BaseModel:
    provider = os.getenv("MODEL_PROVIDER", "ollama")

    if provider == "ollama":
        return OllamaModel(
            host=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            model_id=os.getenv("OLLAMA_MODEL", "llama3:latest")
        )
    
    elif provider == "aws-bedrock":
        return BedrockModel(
            model_id=os.getenv("AWS_BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0"),
            region_name=os.getenv("AWS_REGION", "us-west-2")
        )
    
    else:
        raise ValueError(
            f"Unsupported MODEL_PROVIDER '{provider}'."
            "Expected 'ollama' or 'aws-bedrock'."
        )