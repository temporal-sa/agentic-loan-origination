"""
Document OCR prompts for AWS Bedrock Nova Pro vision model.

This module contains prompts for extracting structured data from different document types.
"""

from enum import Enum
from typing import Dict


class DocumentType(Enum):
    """Enumeration of supported document types."""
    BANK_STATEMENT = "bank_statement"
    ID_PROOF = "id_proof"


# Prompt templates for each document type
DOCUMENT_PROMPTS: Dict[str, str] = {
    DocumentType.BANK_STATEMENT.value: """You are an expert OCR system analyzing a bank statement image. Your task is to carefully read and extract ALL information from the ACTUAL document provided. Do not hallucinate or invent any data.
OUTPUT FORMAT:
Return valid JSON with this structure (fill with ACTUAL data from the document):
{
  "account_holder_name": "<extract from document>",
  "account_type": "<extract from document>",
  "account_number": "<extract from document>",
  "statement_period": "<extract from document>",
  "opening_balance": <number>,
  "final_balance": <number>,
  "transactions": [
    {
      "date": "<YYYY-MM-DD>",
      "description": "<extract exact description>",
      "type": "CREDIT or DEBIT",
      "amount": <number>
    }
  ]
}
IMPORTANT REMINDERS:
- Use the EXACT names, numbers, and dates you see in the document
- DO NOT invent or use example data
- If you cannot read a field clearly, extract your best reading of it
- Return ONLY valid JSON, no additional text before or after""",

    DocumentType.ID_PROOF.value: """You are an expert OCR system analyzing a US driver's license or ID card image. Your task is to carefully read and extract ALL information from the ACTUAL document provided.

CRITICAL INSTRUCTIONS:
1. READ THE ACTUAL DOCUMENT carefully - do NOT use placeholder or example data
2. Extract REAL data you see in the image provided
3. Look at the actual text, numbers, and dates visible on the license/ID
4. Return ONLY the data you actually see in the provided document

EXTRACT THE FOLLOWING FIELDS FROM THE ACTUAL DOCUMENT:

Required identification fields:
- document_type: Type of document (e.g., "US_DRIVERS_LICENSE", "STATE_ID", "ID_CARD")
- full_name: Complete legal name exactly as shown
- first_name: First name component
- middle_name: Middle name or initial (if present)
- last_name: Last name/surname
- license_number: License/ID number exactly as printed
- state: Issuing state/jurisdiction
- date_of_birth: Birth date in YYYY-MM-DD format
- issue_date: Date issued in YYYY-MM-DD format
- expiration_date: Expiration date in YYYY-MM-DD format

Address information:
- address: Complete address as shown (extract as object with street, city, state, zip_code)

Physical characteristics (if shown):
- sex: Gender marker (M/F/X)
- height: Height as shown
- weight: Weight as shown (if present)
- eye_color: Eye color code (e.g., BRN, BLU, GRN)
- hair_color: Hair color (if shown)

License details (if applicable):
- license_class: License class (e.g., "C", "D", "CDL")
- restrictions: Any restrictions codes (if shown)
- endorsements: Any endorsement codes (if shown)

OUTPUT FORMAT:
Return valid JSON with this structure (fill with ACTUAL data from the document):
{
  "document_type": "<extract from document>",
  "full_name": "<extract from document>",
  "first_name": "<extract from document>",
  "middle_name": "<extract from document or null>",
  "last_name": "<extract from document>",
  "license_number": "<extract from document>",
  "state": "<extract from document>",
  "date_of_birth": "<YYYY-MM-DD>",
  "address": {
    "street": "<extract from document>",
    "city": "<extract from document>",
    "state": "<state abbreviation>",
    "zip_code": "<extract from document>"
  },
  "issue_date": "<YYYY-MM-DD>",
  "expiration_date": "<YYYY-MM-DD>",
  "sex": "<M/F/X>",
  "height": "<extract as shown>",
  "weight": "<extract as shown or null>",
  "eye_color": "<extract from document>",
  "hair_color": "<extract from document or null>",
  "license_class": "<extract from document or null>",
  "restrictions": "<extract from document or null>",
  "endorsements": "<extract from document or null>"
}

IMPORTANT REMINDERS:
- Use the EXACT text, numbers, and dates you see in the document
- DO NOT invent or use example data
- If a field is not visible or not present on the document, use null
- Pay attention to date formats on the document and convert to YYYY-MM-DD
- Extract address components carefully (street, city, state, zip)
- Return ONLY valid JSON, no additional text before or after"""
}


# Document type aliases for backward compatibility and API mapping
DOCUMENT_TYPE_ALIASES = {
    "proof_of_id": "id_proof",          # Alternative name
    "drivers_license": "id_proof",      # Alternative name
    "driver_license": "id_proof"        # Alternative name
}


def get_prompt_for_document(doc_type: str) -> str:
    """
    Get the OCR prompt for a specific document type.

    Args:
        doc_type: Document type (e.g., 'bank_statement', 'id_proof')

    Returns:
        The prompt string for the document type

    Raises:
        ValueError: If document type is not supported
    """
    # Check if doc_type is an alias and map it to the canonical type
    canonical_type = DOCUMENT_TYPE_ALIASES.get(doc_type, doc_type)

    if canonical_type not in DOCUMENT_PROMPTS:
        raise ValueError(
            f"Unsupported document type: {doc_type}. "
            f"Supported types: {', '.join(list(DOCUMENT_PROMPTS.keys()) + list(DOCUMENT_TYPE_ALIASES.keys()))}"
        )

    return DOCUMENT_PROMPTS[canonical_type]
