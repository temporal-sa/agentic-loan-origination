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
    DocumentType.BANK_STATEMENT.value: """This is a bank statement that may span multiple pages. You are OCR software. You need to extract account holder name, account type, final balance, account number and array of ALL transactions from ALL pages. Final output will need to be JSON format.

Below is the sample example format:

{
  "account_holder_name": "Rahul Sharma",
  "account_type": "SAVINGS",
  "account_number": "XXXXXX1234",
  "statement_period": "2025-09-01 to 2025-09-30",
  "opening_balance": 25000.00,
  "final_balance": 30550.25,
  "total_credits": 15500.00,
  "total_debits": 9950.00,
  "transactions": [
    {
      "date": "2025-09-02",
      "description": "UPI/PhonePe/REF123456",
      "type": "DEBIT",
      "amount": 799.00
    },
    {
      "date": "2025-09-05",
      "description": "NEFT CREDIT SALARY ACME INDIA PVT LTD",
      "type": "CREDIT",
      "amount": 7500.00
    }
  ]
}

Instructions:
- If this is a multi-page document, look at ALL pages and extract ALL transactions from every page
- Combine transactions from all pages into a single transactions array, sorted by date
- Extract ALL transactions visible across all pages of the statement
- For transaction type, use "CREDIT" for deposits/credits and "DEBIT" for withdrawals/debits
- Use the exact account holder name as shown on the statement
- Include the statement period, opening balance, and final/closing balance
- Calculate total credits and total debits across all transactions
- Ensure no transactions are missed - check every page carefully
- Return ONLY valid JSON, no additional text or explanation""",

    DocumentType.SALARY_SLIP.value: """This is a salary slip/pay stub that may span multiple pages. You are OCR software. You need to extract employee information, salary details, and deductions from ALL pages. Final output will need to be JSON format.

Below is the sample example format:

{
  "employee_name": "Priya Patel",
  "employee_id": "EMP12345",
  "employer_name": "Tech Solutions Inc",
  "pay_period": "October 2024",
  "pay_date": "2024-10-31",
  "gross_salary": 85000.00,
  "earnings": {
    "basic_salary": 50000.00,
    "house_rent_allowance": 20000.00,
    "special_allowance": 10000.00,
    "bonus": 5000.00
  },
  "deductions": {
    "tax": 17000.00,
    "provident_fund": 10200.00,
    "health_insurance": 2500.00,
    "other": 1000.00
  },
  "total_deductions": 30700.00,
  "net_salary": 54300.00,
  "year_to_date_gross": 850000.00,
  "year_to_date_net": 543000.00
}

Instructions:
- If this is a multi-page document, review ALL pages to extract complete information
- Extract employee name, ID, and employer information
- Extract the pay period and payment date
- Extract gross salary (before deductions)
- Break down all earnings by category (basic, allowances, bonuses, etc.)
- Break down all deductions by category (tax, PF, insurance, etc.)
- Calculate or extract total deductions
- Extract net salary (take-home pay)
- Include year-to-date (YTD) figures if available
- All monetary amounts should be in numerical format (no currency symbols in the numbers)
- Ensure all data from all pages is included in the final JSON
- Return ONLY valid JSON, no additional text or explanation""",

    DocumentType.ID_PROOF.value: """This is a US driver's license. You are OCR software. You need to extract personal identification information from this document. Final output will need to be JSON format.

Below is the sample example format:

{
  "document_type": "US_DRIVERS_LICENSE",
  "full_name": "John Michael Smith",
  "first_name": "John",
  "middle_name": "Michael",
  "last_name": "Smith",
  "date_of_birth": "1985-03-15",
  "license_number": "D1234567",
  "state": "California",
  "address": {
    "street": "123 Main Street",
    "city": "Los Angeles",
    "state": "CA",
    "zip_code": "90001"
  },
  "issue_date": "2020-03-15",
  "expiration_date": "2028-03-15",
  "sex": "M",
  "height": "5'10\"",
  "weight": "170 lbs",
  "eye_color": "BRN",
  "restrictions": "NONE",
  "class": "C"
}

Instructions:
- Extract the full legal name and break it into first, middle, and last name components
- Extract date of birth in YYYY-MM-DD format
- Extract license number exactly as shown
- Extract the issuing state
- Extract complete address including street, city, state, and ZIP code
- Extract issue date and expiration date in YYYY-MM-DD format
- Extract physical characteristics: sex, height, weight, eye color
- Extract license class and any restrictions
- Return ONLY valid JSON, no additional text or explanation
- If any field is not visible or not present, use null for that field"""
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
