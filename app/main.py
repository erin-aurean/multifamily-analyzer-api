from fastapi import FastAPI, Header, HTTPException
from math import pow

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


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(
    data: dict,
    x_api_key: str = Header(...)
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    assumptions_used = []
    red_flags = []

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
        "red_flags": red_flags
    }
