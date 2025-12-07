"""
Prompts for AWS Bedrock Nova Pro vision model and Strands agents.

This module contains prompts for:
- Document OCR (extracting structured data from different document types)
- Agent system prompts (for financial analysis agents)
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


# ============================================================================
# AGENT SYSTEM PROMPTS
# ============================================================================
# System prompts for Strands agents performing financial analysis

INCOME_ASSESSMENT_SYSTEM_PROMPT = """You are a financial analyst specializing in loan underwriting.
You have access to a Python code interpreter to perform complex financial calculations.
When analyzing income and loan affordability, write Python code to:
1. Calculate debt-to-income (DTI) ratios
2. Analyze income trends over time
3. Calculate statistical risk scores
4. Validate data consistency between sources

Always execute calculations using code to ensure accuracy."""

EXPENSE_ASSESSMENT_SYSTEM_PROMPT = """You are a financial behavior analyst specializing in spending pattern analysis for loan underwriting.
You have access to a Python code interpreter to perform detailed behavioral and expense analysis.
When analyzing expenses and spending patterns, write Python code to:
1. Categorize expenses by type (essential, variable, discretionary)
2. Calculate spending velocity and financial stress indicators
3. Validate declared expenses against actual spending
4. Detect financial discipline and risk factors
5. Validate declared expenses against actual spending

Always execute calculations using code to ensure accuracy and provide behavioral insights."""


# ============================================================================
# ANALYSIS PROMPT TEMPLATES
# ============================================================================
# Detailed analysis prompts for income and expense assessment

def get_income_analysis_prompt(applicant_id: str, loan_amount: float, monthly_income: float,
                                monthly_expenses: float, bank_balance: float, account_type: str,
                                bank_statement_data: dict = None) -> str:
    """Generate income analysis prompt with applicant data."""
    import json

    return f"""
Analyze this loan applicant's income profile and calculate a comprehensive risk assessment:

**Loan Application:**
- Applicant ID: {applicant_id}
- Requested Loan Amount: ${loan_amount:,.2f}
- Declared Monthly Income: ${monthly_income:,.2f}
- Monthly Expenses: ${monthly_expenses:,.2f}

**Bank Account Data:**
- Account Balance: ${bank_balance:,.2f}
- Account Type: {account_type}

**Bank Statement Extracted Data (AWS Bedrock Nova Pro OCR):**
{json.dumps(bank_statement_data, indent=2) if bank_statement_data else "No bank statement data available"}

**Analysis Required:**
Write Python code to:
1. Calculate monthly DTI ratio: (monthly_loan_payment / monthly_income) * 100
   - Assume 5% APR, loan term of 5 years for monthly payment calculation
   - DTI < 30% is excellent, 30-40% acceptable, >40% risky

2. Calculate disposable income after loan: income - expenses - monthly_loan_payment

3. Validate declared income against bank statement data (if available)
   - Check for consistency
   - Flag any discrepancies > 20%

4. Calculate income stability risk score (0-100, where 0 is lowest risk):
   - If bank statement shows consistent deposits: lower risk
   - If income varies significantly: higher risk

5. Determine loan affordability: Can applicant afford monthly payments?  

Return a structured analysis with:
- DTI ratio (percentage)
- Disposable income after loan
- Income validation result (consistent/discrepancy/no_data)
- Risk score (0-100)
- Affordability assessment (affordable/marginal/risky)
- Detailed reasoning
"""


def get_expense_analysis_prompt(applicant_id: str, declared_expenses: float, monthly_income: float,
                                 loan_amount: float, bank_balance: float, account_type: str,
                                 bank_statement_data: dict = None) -> str:
    """Generate expense analysis prompt with applicant data."""
    import json

    return f"""
Analyze this loan applicant's expense profile and spending behavior patterns:

**Loan Application:**
- Applicant ID: {applicant_id}
- Declared Monthly Expenses: ${declared_expenses:,.2f}
- Declared Monthly Income: ${monthly_income:,.2f}
- Requested Loan Amount: ${loan_amount:,.2f}

**Bank Account Data:**
- Current Balance: ${bank_balance:,.2f}
- Account Type: {account_type}

**Bank Statement Data (Extracted by AWS Bedrock Nova Pro OCR):**
{json.dumps(bank_statement_data, indent=2) if bank_statement_data else "No bank statement data available"}

**Analysis Required:**
Write Python code to perform comprehensive spending behavior analysis:

**1. EXPENSE CATEGORIZATION (from bank statement transactions):**
   Categories to analyze:
   - Essential expenses:
     * Housing (rent/mortgage, property tax)
     * Utilities (electricity, water, gas, internet)
     * Insurance (health, auto, life)
     * Loan payments (existing loans, credit cards)
   - Variable expenses:
     * Groceries and household items
     * Transportation (gas, public transit, car maintenance)
     * Healthcare (medical, pharmacy, dental)
     * Childcare/education
   - Discretionary spending:
     * Dining out and restaurants
     * Entertainment (movies, concerts, streaming services)
     * Shopping (clothing, electronics, non-essentials)
     * Travel and vacation
     * Subscriptions and memberships

   Calculate totals for each category and subcategory.

**2. SPENDING VELOCITY ANALYSIS:**
   - Identify deposit dates (likely income/paycheck)
   - Calculate days between deposit and when balance drops below 20% of deposit
   - Fast velocity (< 5 days) = high financial stress
   - Moderate velocity (5-15 days) = normal spending
   - Slow velocity (> 15 days) = good financial discipline

   Calculate average spending velocity over past 3 months.

**3. PURCHASE PATTERN ANALYSIS:**
   - Count small frequent transactions (< $20) vs. large purchases (> $200)
   - Analyze transaction timing:
     * Weekend spending (Friday-Sunday) - indicator of discretionary spending
     * Evening spending (after 6 PM) - impulse purchases
     * Payday spending (within 3 days of deposit) - spending discipline
   - Identify merchant categories (retail, restaurants, entertainment, etc.)
   - Calculate discretionary spending ratio: (discretionary / total_expenses) * 100

**4. FINANCIAL STRESS INDICATORS:**
   Detect red flags:
   - Minimum balance throughout month (if < $100 frequently = high stress)
   - Overdraft fees or NSF (insufficient funds) charges
   - Payday loans or cash advance transactions
   - Gambling transactions (casinos, lottery, betting)
   - Late payment fees on bills
   - Multiple balance transfers between accounts
   - Declining balance trend over 3+ months

   Count red flags and assess severity.   

**5. SAVINGS DISCIPLINE:**
   - Check for automatic savings transfers (positive indicator)
   - Calculate savings buffer: month-end balance / monthly expenses
   - Buffer > 1.0 = emergency fund present (excellent)
   - Buffer 0.5-1.0 = some buffer (moderate)
   - Buffer < 0.5 = living paycheck to paycheck (risky)

   Analyze balance trend: increasing (good), stable (moderate), decreasing (concerning)

**6. EXPENSE VALIDATION:**
   - Compare declared expenses vs. actual bank statement debits
   - Calculate discrepancy percentage: abs(declared - actual) / actual * 100
   - Flag if discrepancy > 20%
   - Identify reason for discrepancy (underestimated, cash spending, multiple accounts)

**7. BEHAVIORAL RISK SCORE (0-100, where 0 is lowest risk):**
   Risk factors (add points):
   - High discretionary spending (>30% of income): +20 points
   - Fast spending velocity (< 5 days): +15 points
   - Overdraft/NSF fees present: +20 points
   - Payday loans/cash advances: +25 points
   - Gambling transactions: +15 points
   - No savings buffer (< 0.5): +15 points
   - Declining balance trend: +10 points
   - Late payment fees: +10 points
   - Declared vs actual expense discrepancy > 20%: +10 points

   Positive factors (subtract points):
   - Automatic savings transfers: -10 points
   - Savings buffer > 1.0: -15 points
   - Low discretionary spending (< 20%): -10 points
   - Increasing balance trend: -10 points

   Final score: Sum all points (min 0, max 100)   

**8. FINANCIAL DISCIPLINE ASSESSMENT:**
   Based on overall analysis:
   - Disciplined (score 0-30): Good spending habits, savings, low discretionary spending
   - Moderate (score 31-60): Balanced spending, some concerns, room for improvement
   - Undisciplined (score 61-100): Poor spending habits, high risk, financial stress

**Return structured analysis with:**
- Total actual monthly expenses (by category)
- Expense-to-income ratio (%)
- Discretionary spending ratio (%)
- Spending velocity (days)
- Savings buffer ratio
- Expense validation result (matches/discrepancy/red_flags)
- List of red flags detected (if any)
- Behavioral risk score (0-100)
- Financial discipline assessment (disciplined/moderate/undisciplined)
- Affordability of new loan payment
- Detailed reasoning and recommendations
"""
