from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from math import pow
from typing import Optional, List
import io
import os
import re

import pandas as pd
from PyPDF2 import PdfReader

app = FastAPI()

API_KEY = "123456"


def monthly_payment(principal: float, annual_rate: float, amort_years: int) -> float:
    if principal <= 0:
        return 0.0
    monthly_rate = annual_rate / 12
    n = amort_years * 12
    if monthly_rate == 0:
        return principal / n
    return principal * (monthly_rate * pow(1 + monthly_rate, n)) / (pow(1 + monthly_rate, n) - 1)


def verify_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def to_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = text.replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(text)
    except Exception:
        return default


def normalize_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def extract_currency_values(text: str) -> List[float]:
    matches = re.findall(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+\.[0-9]{2})", text)
    values = []
    for m in matches:
        try:
            values.append(float(m.replace(",", "")))
        except Exception:
            pass
    return values


def find_value_in_row(row_values) -> Optional[float]:
    numeric_values = []
    for v in row_values:
        val = to_float(v, default=None)
        if val is not None and val != 0:
            numeric_values.append(val)
    if not numeric_values:
        return None
    return max(numeric_values)


def parse_t12(file_bytes: bytes, filename: str) -> dict:
    result = {
        "gross_annual_income": None,
        "total_expenses": None,
        "noi": None,
        "notes": []
    }

    excel_kwargs = {"sheet_name": None, "header": None}
    if filename.lower().endswith(".xls"):
        excel_kwargs["engine"] = "xlrd"

    sheets = pd.read_excel(io.BytesIO(file_bytes), **excel_kwargs)

    income_keywords = ["total income", "gross income", "rental income", "total revenue"]
    expense_keywords = ["total expenses", "operating expenses", "total operating expenses"]
    noi_keywords = ["net operating income", "noi"]

    for _, df in sheets.items():
        df = df.fillna("")
        for _, row in df.iterrows():
            row_strings = [str(x).strip().lower() for x in row.tolist()]
            joined = " | ".join(row_strings)

            if result["gross_annual_income"] is None and any(k in joined for k in income_keywords):
                val = find_value_in_row(row.tolist())
                if val:
                    result["gross_annual_income"] = val

            if result["total_expenses"] is None and any(k in joined for k in expense_keywords):
                val = find_value_in_row(row.tolist())
                if val:
                    result["total_expenses"] = val

            if result["noi"] is None and any(k in joined for k in noi_keywords):
                val = find_value_in_row(row.tolist())
                if val:
                    result["noi"] = val

    if result["gross_annual_income"] is None:
        result["notes"].append("Could not confidently find gross annual income in T12.")
    if result["total_expenses"] is None:
        result["notes"].append("Could not confidently find total expenses in T12.")
    if result["noi"] is None:
        result["notes"].append("Could not confidently find NOI in T12.")

    return result


def parse_rent_roll(file_bytes: bytes, filename: str) -> dict:
    result = {
        "unit_count": None,
        "occupied_units": None,
        "monthly_rent": None,
        "pet_rent_monthly": 0.0,
        "utility_income_monthly": 0.0,
        "notes": []
    }

    excel_kwargs = {"sheet_name": 0}
    if filename.lower().endswith(".xls"):
        excel_kwargs["engine"] = "xlrd"

    df = pd.read_excel(io.BytesIO(file_bytes), **excel_kwargs)

    original_columns = list(df.columns)
    df.columns = [normalize_header(c) for c in df.columns]

    if len(df.columns) == 0:
        result["notes"].append("Rent roll has no readable columns.")
        return result

    unit_col = None
    for c in df.columns:
        if c in ["unit", "unit_number", "unit_no", "apt", "apartment"]:
            unit_col = c
            break

    status_col = None
    for c in df.columns:
        if c in ["status", "occupancy_status", "lease_status"]:
            status_col = c
            break

    current_rent_col = None
    for c in df.columns:
        if c in ["rent", "current_rent", "lease_rent", "contract_rent", "actual_rent", "base_rent"]:
            current_rent_col = c
            break

    pet_col = None
    for c in df.columns:
        if "pet" in c and "rent" in c:
            pet_col = c
            break

    utility_col = None
    for c in df.columns:
        if "utility" in c or "rubs" in c:
            utility_col = c
            break

    if unit_col:
        df = df[df[unit_col].notna()]
        df = df[df[unit_col].astype(str).str.strip() != ""]
        result["unit_count"] = int(len(df))
    else:
        result["unit_count"] = int(len(df))

    if status_col:
        occupied_mask = df[status_col].astype(str).str.lower().str.contains("occ|current|leased", regex=True, na=False)
        result["occupied_units"] = int(occupied_mask.sum())
    elif current_rent_col:
        occupied_mask = df[current_rent_col].apply(lambda x: to_float(x, 0) > 0)
        result["occupied_units"] = int(occupied_mask.sum())
    else:
        result["occupied_units"] = result["unit_count"]

    if current_rent_col:
        result["monthly_rent"] = float(df[current_rent_col].apply(to_float).sum())
    else:
        result["notes"].append(f"Could not confidently find a current rent column. Columns seen: {original_columns}")

    if pet_col:
        result["pet_rent_monthly"] = float(df[pet_col].apply(to_float).sum())

    if utility_col:
        result["utility_income_monthly"] = float(df[utility_col].apply(to_float).sum())

    return result


def parse_tax_receipt_pdf(file_bytes: bytes) -> dict:
    result = {
        "property_taxes": 0.0,
        "notes": []
    }

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        values = extract_currency_values(text)
        if values:
            result["property_taxes"] = max(values)
        else:
            result["notes"].append("No currency values found in tax receipt PDF.")
    except Exception as e:
        result["notes"].append(f"Could not parse tax receipt PDF: {str(e)}")

    return result


def run_strict_sop_analysis(data: dict) -> dict:
    assumptions_used = []
    red_flags = []
    extraction_notes = data.get("extraction_notes", [])

    purchase_price = float(data.get("purchase_price", 0))
    unit_count = int(data.get("unit_count", 0))
    gross_annual_income = float(data.get("gross_annual_income", 0))

    if purchase_price <= 0 or unit_count <= 0 or gross_annual_income <= 0:
        raise HTTPException(
            status_code=400,
            detail="purchase_price, unit_count, and gross_annual_income are required and must be greater than 0"
        )

    vacancy_rate = data.get("vacancy_rate")
    if vacancy_rate is None:
        vacancy_rate = 0.07
        assumptions_used.append("Vacancy set to 7% default because no vacancy_rate was provided.")
    else:
        vacancy_rate = float(vacancy_rate)

    property_taxes = data.get("property_taxes")
    if property_taxes is None:
        property_taxes = 0.0
        assumptions_used.append("Property taxes were not provided. Set to 0 temporarily; real analysis should use verified tax receipts.")
    else:
        property_taxes = float(property_taxes)

    insurance = data.get("insurance")
    if insurance is None:
        insurance = 0.0
        assumptions_used.append("Insurance was not provided. Set to 0 temporarily; real analysis should use actual or quoted insurance.")
    else:
        insurance = float(insurance)

    repairs_maintenance = data.get("repairs_maintenance")
    if repairs_maintenance is None:
        repairs_maintenance = 0.0
        assumptions_used.append("Repairs & maintenance not provided. Set to 0 temporarily.")
    else:
        repairs_maintenance = float(repairs_maintenance)

    payroll = float(data.get("payroll", 0))
    utilities = float(data.get("utilities", 0))
    landscaping = float(data.get("landscaping", 0))
    pest_control = float(data.get("pest_control", 0))
    admin_legal_accounting = float(data.get("admin_legal_accounting", 0))
    other_expenses = float(data.get("other_expenses", 0))

    management_rate = data.get("management_rate")
    if management_rate is None:
        management_rate = 0.06
        assumptions_used.append("Management fee set to 6% default because no management_rate was provided.")
    else:
        management_rate = float(management_rate)

    capex_per_door = data.get("capex_per_door")
    if capex_per_door is None:
        capex_per_door = 700.0
        assumptions_used.append("CapEx reserve set to $700/door default because no capex_per_door was provided.")
    else:
        capex_per_door = float(capex_per_door)
        if capex_per_door < 700:
            red_flags.append("CapEx reserve below $700/door.")
            assumptions_used.append("CapEx reserve provided below SOP floor; flagged as a red flag.")

    down_payment_pct = float(data.get("down_payment_pct", 0.25))
    interest_rate = float(data.get("interest_rate", 0.065))
    amort_years = int(data.get("amort_years", 30))

    effective_gross_income = gross_annual_income * (1 - vacancy_rate)

    management_fee = effective_gross_income * management_rate
    capex_reserve = unit_count * capex_per_door

    total_expenses = (
        property_taxes
        + insurance
        + repairs_maintenance
        + payroll
        + utilities
        + landscaping
        + pest_control
        + admin_legal_accounting
        + other_expenses
        + management_fee
        + capex_reserve
    )

    noi = effective_gross_income - total_expenses
    expense_ratio = total_expenses / gross_annual_income if gross_annual_income else 0

    loan_amount = purchase_price * (1 - down_payment_pct)
    monthly_debt_service = monthly_payment(loan_amount, interest_rate, amort_years)
    annual_debt_service = monthly_debt_service * 12

    dcr = noi / annual_debt_service if annual_debt_service else 0
    annual_cash_flow = noi - annual_debt_service
    monthly_cash_flow = annual_cash_flow / 12
    cash_flow_per_unit_per_month = monthly_cash_flow / unit_count if unit_count else 0

    monthly_gross_income = gross_annual_income / 12
    one_percent_rule_pass = monthly_gross_income >= (purchase_price * 0.01)

    if not one_percent_rule_pass:
        red_flags.append("Fails 1% rule.")

    if expense_ratio < 0.35:
        red_flags.append("Expense ratio below 35%, which is usually unrealistic.")
    elif expense_ratio < 0.40 or expense_ratio > 0.50:
        red_flags.append("Expense ratio is outside the 40% to 50% target range.")

    if vacancy_rate == 0:
        red_flags.append("Vacancy entered as 0%, which is unrealistic under SOP.")

    if dcr < 1.25:
        red_flags.append("DCR below 1.25.")
    if cash_flow_per_unit_per_month < 100:
        red_flags.append("Cash flow below $100/unit/month target.")

    target_noi_for_125_dcr = annual_debt_service * 1.25

    expense_load_ratio = total_expenses / effective_gross_income if effective_gross_income else 0
    if expense_load_ratio >= 1:
        price_at_125_dcr = 0
    else:
        target_egi_for_125_dcr = target_noi_for_125_dcr / (1 - expense_load_ratio)
        target_gross_income_for_125_dcr = target_egi_for_125_dcr / (1 - vacancy_rate) if vacancy_rate < 1 else 0
        price_at_125_dcr = purchase_price * (gross_annual_income / target_gross_income_for_125_dcr) if target_gross_income_for_125_dcr else 0

    if dcr >= 1.25 and cash_flow_per_unit_per_month >= 100:
        decision = "GO"
    elif dcr < 1.25 and price_at_125_dcr > 0:
        decision = "CONDITIONAL GO"
    else:
        decision = "NO-GO"

    return {
        "decision": decision,
        "purchase_price": round(purchase_price, 2),
        "unit_count": unit_count,
        "gross_annual_income": round(gross_annual_income, 2),
        "vacancy_rate": round(vacancy_rate, 4),
        "effective_gross_income": round(effective_gross_income, 2),
        "total_expenses": round(total_expenses, 2),
        "expense_ratio": round(expense_ratio, 4),
        "noi": round(noi, 2),
        "annual_debt_service": round(annual_debt_service, 2),
        "dcr": round(dcr, 4),
        "annual_cash_flow": round(annual_cash_flow, 2),
        "cash_flow_per_unit_per_month": round(cash_flow_per_unit_per_month, 2),
        "one_percent_rule_pass": one_percent_rule_pass,
        "recommended_price_for_125_dcr": round(price_at_125_dcr, 2),
        "assumptions_used": assumptions_used,
        "red_flags": red_flags,
        "extraction_notes": extraction_notes
    }


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(data: dict, x_api_key: str = Header(...)):
    verify_key(x_api_key)
    return run_strict_sop_analysis(data)


@app.post("/analyze-files")
async def analyze_files(
    x_api_key: str = Header(...),
    purchase_price: float = Form(...),
    t12_file: Optional[UploadFile] = File(None),
    rent_roll_file: Optional[UploadFile] = File(None),
    tax_receipts: Optional[str] = Form(None),
    insurance: Optional[float] = Form(None),
    repairs_maintenance: Optional[float] = Form(None),
    payroll: Optional[float] = Form(None),
    utilities: Optional[float] = Form(None),
    landscaping: Optional[float] = Form(None),
    pest_control: Optional[float] = Form(None),
    admin_legal_accounting: Optional[float] = Form(None),
    other_expenses: Optional[float] = Form(None),
    vacancy_rate: Optional[float] = Form(None),
    management_rate: Optional[float] = Form(None),
    capex_per_door: Optional[float] = Form(None),
    down_payment_pct: float = Form(0.25),
    interest_rate: float = Form(0.065),
    amort_years: int = Form(30),
):
    verify_key(x_api_key)

    extracted = {
        "purchase_price": purchase_price,
        "unit_count": 0,
        "gross_annual_income": 0.0,
        "property_taxes": 0.0,
        "insurance": insurance,
        "repairs_maintenance": repairs_maintenance,
        "payroll": payroll or 0.0,
        "utilities": utilities or 0.0,
        "landscaping": landscaping or 0.0,
        "pest_control": pest_control or 0.0,
        "admin_legal_accounting": admin_legal_accounting or 0.0,
        "other_expenses": other_expenses or 0.0,
        "vacancy_rate": vacancy_rate,
        "management_rate": management_rate,
        "capex_per_door": capex_per_door,
        "down_payment_pct": down_payment_pct,
        "interest_rate": interest_rate,
        "amort_years": amort_years,
        "extraction_notes": []
    }

    if t12_file is not None:
        t12_bytes = await t12_file.read()
        t12_data = parse_t12(t12_bytes, t12_file.filename or "")
        extracted["extraction_notes"].extend([f"T12: {n}" for n in t12_data["notes"]])

        if t12_data["gross_annual_income"] is not None:
            extracted["gross_annual_income"] = t12_data["gross_annual_income"]

    if rent_roll_file is not None:
        rr_bytes = await rent_roll_file.read()
        rr_data = parse_rent_roll(rr_bytes, rent_roll_file.filename or "")
        extracted["extraction_notes"].extend([f"Rent Roll: {n}" for n in rr_data["notes"]])

        if rr_data["unit_count"] is not None:
            extracted["unit_count"] = rr_data["unit_count"]

        if extracted["gross_annual_income"] == 0 and rr_data["monthly_rent"] is not None:
            monthly_total = (
                rr_data["monthly_rent"]
                + rr_data.get("pet_rent_monthly", 0.0)
                + rr_data.get("utility_income_monthly", 0.0)
            )
            extracted["gross_annual_income"] = monthly_total * 12
            extracted["extraction_notes"].append("Gross annual income was derived from rent roll monthly rent x 12 because T12 income was unavailable.")

  if tax_receipts:
    total_taxes = 0.0
    for receipt in tax_receipts:
        if not hasattr(receipt, "read"):
            continue  # skip invalid inputs (like empty strings from Swagger)

        pdf_bytes = await receipt.read()
        tax_data = parse_tax_receipt_pdf(pdf_bytes)
        total_taxes += tax_data["property_taxes"]
        extracted["extraction_notes"].extend([f"Tax Receipt: {n}" for n in tax_data["notes"]])

    if total_taxes > 0:
        extracted["property_taxes"] = total_taxes

    if extracted["unit_count"] <= 0:
        raise HTTPException(status_code=400, detail="Could not determine unit_count from uploaded files.")

    if extracted["gross_annual_income"] <= 0:
        raise HTTPException(status_code=400, detail="Could not determine gross_annual_income from uploaded files.")

    return run_strict_sop_analysis(extracted)
