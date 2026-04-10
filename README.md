# Multifamily Deal Analyzer API

This API underwrites multifamily deals and can now ingest raw source files.

## Endpoints

- `GET /health`
- `POST /v1/analyze-multifamily`
- `POST /v1/analyze-deal-package`
- `POST /v1/analyze-raw-files`

## New raw file ingestion flow

`/v1/analyze-raw-files` accepts multipart form-data and is built for the real way multifamily deals show up:

- broker text or asking price
- T12 spreadsheet (`.xls` or `.xlsx`)
- rent roll spreadsheet (`.xls` or `.xlsx`)
- one or more tax receipt PDFs

The endpoint parses the files, builds a normalized deal package, and then runs underwriting.

## Example cURL

```bash
curl -X POST "http://localhost:8000/v1/analyze-raw-files" \
  -H "x-api-key: YOUR_KEY_IF_SET" \
  -F "property_name=Sample Asset" \
  -F "asking_price=2200000" \
  -F "broker_text=$2,200,000 purchase price\nLoan terms: $1.64M balance, 3.68% interest, 30-year amortization, maturity 2031" \
  -F "t12_file=@/path/to/t12.xls" \
  -F "rent_roll_file=@/path/to/rent_roll.xlsx" \
  -F "tax_receipt_files=@/path/to/tax_1.pdf" \
  -F "tax_receipt_files=@/path/to/tax_2.pdf"
```

## Raw file response shape

The response includes:

- `extracted_package`: parsed broker, rent roll, T12, and tax receipt data
- `extraction_notes`: what the parser successfully extracted
- `warnings`: what was missing or inferred
- `analysis`: underwriting output if enough data was available to run the deal

## Notes

- `.xls` files are converted internally before parsing.
- Tax receipts are parsed from PDF text.
- If no asking price is supplied and none is found in broker text, the endpoint will still return extraction notes and warnings, but analysis will be omitted.
