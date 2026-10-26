"""Realistic example values for the Swagger/OpenAPI docs (documentation only)."""

ACCOUNT_ID = "8f14e45f-ceea-4f6a-9c1a-2b5d3e7a9c01"
OTHER_ACCOUNT_ID = "c9f0f895-fb98-4b9f-8c9b-5a1d2e3f4a02"
TRANSACTION_ID = "45c48cce-2e2d-4fbd-9a7b-6c1e2d3f4b03"
TRANSFER_ID = "d3d94468-02a4-4e8e-8b1f-7a2b3c4d5e04"
TIMESTAMP = "2026-10-26T09:30:00.123456Z"

TRANSACTION = {
    "id": TRANSACTION_ID,
    "account_id": ACCOUNT_ID,
    "type": "credit",
    "amount": "100.00",
    "description": "Salary",
    "reference_id": "deposit-001",
    "balance_after": "150.00",
    "transfer_id": None,
    "created_at": TIMESTAMP,
}

TRANSFER = {
    "id": TRANSFER_ID,
    "from_account_id": ACCOUNT_ID,
    "to_account_id": OTHER_ACCOUNT_ID,
    "amount": "30.00",
    "reference_id": "rent-2026-10",
    "description": "October rent",
    "created_at": TIMESTAMP,
}
