from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze")
def analyze():
    return {
        "decision": "GO",
        "noi": 120000,
        "dcr": 1.32,
        "cash_flow": 25000,
        "message": "Sample deal analysis output"
    }
