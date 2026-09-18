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
      {"Feature": "01", "Predictions": "High", "Action": "Action A — Details A"},
      {"Feature": "02", "Predictions": "Low", "Action": null}
    ],
    "severity": [],
    "subrogation": [{"Predictions": "High", "Action": "Assigned"}]
  }
]
```

Each model array preserves every selected source row, including identical entries.
Predictions and actions from the same source row stay in the same object. Litigation
entries also contain the two-character `Feature` suffix from
`DERIVE_CLM_FTR_NBR`; no database IDs appear. An empty array means no selected record
exists for that model; a null field means a record exists but that field is empty.
If there are no selected records anywhere, the endpoint returns `[]`.

| Model | Claim column | Prediction column | Action components |
| --- | --- | --- | --- |
| fraud | CLM_NBR | ML_PREDICTIONS | Status, Feedback |
| litigation | DERIVE_CLM_FTR_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| severity | CLM_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| subrogation | CLM_NBR_U | PREDICTIONS | Status |

Litigation's final two-character feature suffix is split before grouping:
`85-00837106-02` becomes claim number `85-00837106` and feature `02`. Already
normalized claim numbers are retained. Claim and feature values remain strings to
preserve leading zeros.

Prediction labels after the colon are trimmed and matched case-insensitively:
`1: High` and `1 : High` both become `High`; Low variants become `Low`.
Missing or unrecognized predictions become null. Nonempty action components are
joined with ` — `; a single component is returned alone, and two empty components
produce null. Blank strings and textual `NULL` are treated as empty action values.

The SQL in `services/landing/claims_service.py` reads all four selector tables in
one parameterized `UNION ALL` statement. CTEs normalize the rows and are referenced
once to fetch a flat result, ordered by claim number, model, prediction, and action.
Python groups the rows by claim and model in one pass, preserving every source row.
This avoids running four correlated SQL JSON subqueries per claim. No intermediate
tables or database schema changes are required. Database access, grouping, and
response validation run in FastAPI's thread pool.

The service logs connection, execute, fetch, connection-close, grouping/validation,
and total service times, plus row and claim counts. Timings are logged at INFO for
normal requests and WARNING when total service time reaches five seconds. Execute
and fetch timings both may include SQL execution work. Total service time excludes
HTTP response serialization, compression, network transfer, and browser rendering.

The local regression tests exercise the normalization CTE with equivalent SQLite
functions and verify grouping and the HTTP contract with flat SQL results. SQL
Server execution and performance require a configured live database to verify.
