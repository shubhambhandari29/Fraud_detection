# Combined claims landing page

`GET /landing/` uses the same authenticated session cookie as the existing model APIs.
It returns a JSON array with one object per normalized claim number. There are no
required query parameters. Every table is filtered only by `Selected = 1`;
addressed claims remain included. Results are ordered by claim number.

```json
[
  {
    "claim_number": "85-00837106",
    "fraud": [{"Predictions": "High", "Action": "Status — Feedback"}],
    "litigation": [
      {"Predictions": "High", "Action": "Action A — Details A"},
      {"Predictions": "Low", "Action": null}
    ],
    "severity": [],
    "subrogation": [{"Predictions": "High", "Action": "Assigned"}]
  }
]
```

Each model array preserves every selected source row, including identical entries.
Predictions and actions from the same source row stay in the same object. No IDs or
feature numbers appear in the response. An empty array means no selected record
exists for that model; a null field means a record exists but that field is empty.
If there are no selected records anywhere, the endpoint returns `[]`.

| Model | Claim column | Prediction column | Action components |
| --- | --- | --- | --- |
| fraud | CLM_NBR | ML_PREDICTIONS | Status, Feedback |
| litigation | DERIVE_CLM_FTR_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| severity | CLM_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| subrogation | CLM_NBR_U | PREDICTIONS | Status |

Litigation's final feature suffix is removed: `85-00837106-02` becomes
`85-00837106`. Already normalized claim numbers are retained. Claim numbers are
trimmed and kept as strings to preserve leading zeros.

Prediction labels after the colon are trimmed and matched case-insensitively:
`1: High` and `1 : High` both become `High`; Low variants become `Low`.
Missing or unrecognized predictions become null. Nonempty action components are
joined with ` — `; a single component is returned alone, and two empty components
produce null. Blank strings and textual `NULL` are treated as empty action values.

The SQL in `services/landing/claims_service.py` reads all four selector tables in
one parameterized statement. CTEs normalize the rows, and per-model `OUTER APPLY`
expressions with `FOR JSON PATH, INCLUDE_NULL_VALUES` collect the matching rows
without multiplying features across models. No intermediate tables or database
schema changes are required. The service parses the SQL JSON arrays and validates
the response; blocking database work runs in FastAPI's thread pool.

The local regression tests exercise the normalization CTE with equivalent SQLite
functions and verify the HTTP contract with mocked SQL JSON results. The SQL Server
`OUTER APPLY` / `FOR JSON` execution and performance require a configured live
database to verify.
