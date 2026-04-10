curl -X POST "http://localhost:8000/v1/analyze-raw-files" \
  -F "property_name=Sample Asset" \
  -F "asking_price=2200000" \
  -F "broker_text=$2,200,000 purchase price\nLoan terms: $1.64M balance, 3.68% interest, 30-year amortization, maturity 2031" \
  -F "t12_file=@/path/to/t12.xls" \
  -F "rent_roll_file=@/path/to/rent_roll.xlsx" \
  -F "tax_receipt_files=@/path/to/tax_1.pdf" \
  -F "tax_receipt_files=@/path/to/tax_2.pdf"
