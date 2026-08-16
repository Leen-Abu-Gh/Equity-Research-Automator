"""
extraction.py
-------------
Turns messy financial PDFs (10-Ks, annual reports, investor decks) into
clean, structured JSON using pdfplumber (text extraction) + the Claude API
(structured extraction).
"""

import json
import re
import pdfplumber
import anthropic

MODEL = "claude-sonnet-5"

EXTRACTION_SCHEMA = """
{
  "company_name": "string",
  "ticker": "string or null",
  "currency": "string, e.g. USD, AED, EUR",
  "units": "string, e.g. thousands, millions",
  "fiscal_years": ["FY2023", "FY2024", "FY2025"],
  "income_statement": {
    "revenue": [number, number, number],
    "cogs": [number, number, number],
    "gross_profit": [number, number, number],
    "sga": [number, number, number],
    "ebit": [number, number, number],
    "interest_expense": [number, number, number],
    "tax_expense": [number, number, number],
    "net_income": [number, number, number],
    "depreciation_amortization": [number, number, number]
  },
  "balance_sheet": {
    "total_debt": [number, number, number],
    "cash_and_equivalents": [number, number, number],
    "total_assets": [number, number, number],
    "total_equity": [number, number, number],
    "shares_outstanding": [number, number, number]
  },
  "cash_flow": {
    "capex": [number, number, number],
    "change_in_nwc": [number, number, number],
    "cash_from_operations": [number, number, number]
  }
}
"""

SYSTEM_PROMPT = f"""You are a financial data extraction engine used by an equity
research analyst. You will be given raw text pulled from one or more PDFs
(annual reports, income statements, balance sheets, cash flow statements,
investor presentations). Extract the financial data into this EXACT JSON
schema and return ONLY valid JSON, no prose, no markdown fences:

{EXTRACTION_SCHEMA}

Rules:
- Use the most recent 3 fiscal years available (or fewer if that's all
  that's present). Order arrays oldest -> newest.
- All monetary figures should be in the SAME unit — pick the unit the
  filing reports in and record it in "units".
- If a line item is genuinely not disclosed anywhere in the text, use null
  for that entry rather than guessing.
- "change_in_nwc" should be the year-over-year change (positive = cash
  outflow from working capital growth is fine to express as a negative
  number if that's how it affects cash flow — just be consistent).
- Do not invent a company name or ticker if it isn't in the text.
"""


def extract_pdf_text(file_path: str) -> str:
    """Pull all text out of a PDF (including tables, best-effort)."""
    chunks = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            chunks.append(text)
            # Also try to grab tables explicitly — they often carry the
            # actual financial statement numbers more reliably than raw text.
            for table in page.extract_tables() or []:
                for row in table:
                    row_text = " | ".join(c for c in row if c)
                    if row_text.strip():
                        chunks.append(row_text)
    return "\n".join(chunks)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def extract_financials(pdf_paths: list[str], api_key: str) -> dict:
    """
    Given one or more PDF file paths, extract combined text and ask Claude
    to return structured financials as a dict matching EXTRACTION_SCHEMA.
    """
    all_text = []
    for path in pdf_paths:
        all_text.append(f"--- Document: {path} ---\n")
        all_text.append(extract_pdf_text(path))
    combined_text = "\n\n".join(all_text)

    # Claude's context window is large, but keep a sane cap so we don't
    # send an enormous investor deck's worth of boilerplate.
    MAX_CHARS = 350_000
    if len(combined_text) > MAX_CHARS:
        combined_text = combined_text[:MAX_CHARS]

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here is the extracted document text:\n\n{combined_text}",
            }
        ],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    cleaned = _strip_code_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude's response wasn't valid JSON. Raw output:\n{raw_text}"
        ) from e

    return data
