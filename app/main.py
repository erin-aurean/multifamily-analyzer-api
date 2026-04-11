from fastapi import FastAPI, Header, HTTPException
import os

app = FastAPI()

API_KEY = os.getenv("API_KEY")

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/health")
def health():
    return {"status": "ok"}

def verify_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.post("/analyze")
def analyze(data: dict, x_api_key: str = Header(None)):
    verify_key(x_api_key)

    price = data.get("price", 0)
    monthly_rent = data.get("monthly_rent", 0)
    expenses = data.get("expenses", 0)

    annual_rent = monthly_rent * 12
    noi = annual_rent - expenses

    loan_amount = price * 0.75
    interest_rate = 0.065
    annual_debt_service = loan_amount * interest_rate

    dcr = noi / annual_debt_service if annual_debt_service else 0
    cash_flow = noi - annual_debt_service

    decision = "GO" if dcr >= 1.25 else "NO-GO"

    return {
        "noi": round(noi, 2),
        "dcr": round(dcr, 2),
        "cash_flow": round(cash_flow, 2),
        "decision": decision
    }
