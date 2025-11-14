"""
Document OCR prompts for granite3.2-vision model via Ollama.

This module contains prompts for extracting structured data from different document types.
"""

from enum import Enum
from typing import Dict


class DocumentType(Enum):
    """Enumeration of supported document types."""
    BANK_STATEMENT = "bank_statement"
    SALARY_SLIP = "salary_slip"
    ID_PROOF = "id_proof"


# Prompt templates for each document type
DOCUMENT_PROMPTS: Dict[str, str] = {
    DocumentType.BANK_STATEMENT.value: """You are an expert OCR system analyzing a bank statement image/PDF. Your task is to carefully read and extract ALL information from the ACTUAL document provided.

CRITICAL INSTRUCTIONS:
1. READ THE ACTUAL DOCUMENT carefully - do NOT use placeholder or example data
2. Extract REAL data you see in the image/PDF provided
3. If this is a multi-page PDF, examine ALL pages and extract ALL transactions from every page
4. Look at the actual text, numbers, and dates visible in the document
5. Return ONLY the data you actually see in the provided document

EXTRACT THE FOLLOWING FIELDS FROM THE ACTUAL DOCUMENT:

Required fields:
- account_holder_name: The actual customer/account holder name printed on the statement
- account_type: Type of account (e.g., "SAVINGS", "CURRENT", "CHECKING")
- account_number: The actual account number shown (may be partially masked like XXXXXX1234)
- statement_period: The date range of the statement (e.g., "2024-01-01 to 2024-01-31")
- opening_balance: The starting balance amount
- final_balance: The ending/closing balance amount
- total_credits: Sum of all credit/deposit transactions
- total_debits: Sum of all debit/withdrawal transactions
- transactions: Array of ALL transaction entries found across ALL pages

For each transaction, extract:
- date: Transaction date in YYYY-MM-DD format (or as shown in the document)
- description: Transaction description/narration exactly as shown
- type: "CREDIT" for deposits/incoming or "DEBIT" for withdrawals/outgoing
- amount: Transaction amount as a number

OUTPUT FORMAT:
Return valid JSON with this structure (fill with ACTUAL data from the document):
{
  "account_holder_name": "<extract from document>",
  "account_type": "<extract from document>",
  "account_number": "<extract from document>",
  "statement_period": "<extract from document>",
  "opening_balance": <number>,
  "final_balance": <number>,
  "total_credits": <number>,
  "total_debits": <number>,
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
- Extract ALL transactions from ALL pages (if multi-page PDF)
- Use the EXACT names, numbers, and dates you see in the document
- DO NOT invent or use example data
- If you cannot read a field clearly, extract your best reading of it
- Return ONLY valid JSON, no additional text before or after""",

    DocumentType.SALARY_SLIP.value: """You are an expert OCR system analyzing a salary slip/pay stub image/PDF. Your task is to carefully read and extract ALL information from the ACTUAL document provided.

CRITICAL INSTRUCTIONS:
1. READ THE ACTUAL DOCUMENT carefully - do NOT use placeholder or example data
2. Extract REAL data you see in the image/PDF provided
3. If this is a multi-page PDF, review ALL pages to extract complete information
4. Look at the actual text, numbers, and dates visible in the document
5. Return ONLY the data you actually see in the provided document

EXTRACT THE FOLLOWING FIELDS FROM THE ACTUAL DOCUMENT:

Required employee information:
- employee_name: The actual employee name printed on the slip
- employee_id: Employee ID/number (if shown)
- employer_name: Company/employer name
- pay_period: Pay period (e.g., "October 2024", "01/10/2024 - 31/10/2024")
- payment_date: Date of payment (if shown)

Required salary breakdown:
- gross_salary: Total salary before deductions
- earnings: Object containing breakdown of all earning components you find:
  * basic_salary: Basic pay component
  * house_rent_allowance: HRA component (if present)
  * special_allowance: Any special allowances (if present)
  * bonus: Bonus amount (if present)
  * other allowances: Any other earnings you see
- deductions: Object containing breakdown of all deduction components you find:
  * tax: Income tax/TDS deducted (if present)
  * provident_fund: PF/EPF deduction (if present)
  * health_insurance: Medical/health insurance (if present)
  * professional_tax: Professional tax (if present)
  * other: Any other deductions you see
- total_deductions: Sum of all deductions
- net_salary: Take-home pay (gross - deductions)

Optional if available:
- year_to_date: YTD earnings (if shown)

OUTPUT FORMAT:
Return valid JSON with this structure (fill with ACTUAL data from the document):
{
  "employee_name": "<extract from document>",
  "employee_id": "<extract from document or null>",
  "employer_name": "<extract from document>",
  "pay_period": "<extract from document>",
  "payment_date": "<extract from document or null>",
  "gross_salary": <number>,
  "earnings": {
    "basic_salary": <number>,
    "house_rent_allowance": <number or null>,
    "special_allowance": <number or null>,
    "bonus": <number or null>
  },
  "deductions": {
    "tax": <number or null>,
    "provident_fund": <number or null>,
    "health_insurance": <number or null>,
    "professional_tax": <number or null>,
    "other": <number or null>
  },
  "total_deductions": <number>,
  "net_salary": <number>,
  "year_to_date": <number or null>
}

IMPORTANT REMINDERS:
- Extract data from ALL pages if multi-page document
- Use the EXACT names, numbers, and dates you see in the document
- DO NOT invent or use example data
- All monetary amounts should be numbers without currency symbols
- If a field is not visible, use null
- Ensure gross_salary - total_deductions = net_salary matches the document
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
    "proof_of_income": "salary_slip",  # API uses proof_of_income, we process as salary_slip
    "pay_stub": "salary_slip",          # Alternative name
    "payslip": "salary_slip",           # Alternative name
    "proof_of_id": "id_proof",          # Alternative name
    "drivers_license": "id_proof",      # Alternative name
    "driver_license": "id_proof"        # Alternative name
}


def get_prompt_for_document(doc_type: str) -> str:
    """
    Get the OCR prompt for a specific document type.

    Args:
        doc_type: Document type (e.g., 'bank_statement', 'salary_slip', 'id_proof', 'proof_of_income')

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
