# Third-Party Auto claim dashboard API

## Endpoint

```http
GET /fraud/dashboard/{claim_number}
```

The endpoint requires the same bearer-token authentication as the existing
claim APIs. It is read-only and does not change the selector-table GET,
upsert, or transfer endpoints.

## Database configuration

The dashboard reads from three databases on the SQL Server configured by
`DB_SERVER`, using the existing driver and authentication settings.

```env
DATATEXT_DB_NAME=CLMDS_DataModelingAndTextMining
FRAUD_DB_NAME=CLMAA_FraudModel
VENDOR_DB_NAME=CLM_VendorData
```

`DATATEXT_DB_NAME` falls back to the existing `DB_NAME`. The Fraud and Vendor
database names have the Power BI source names as defaults.

## Response

```json
{
  "claim_number": "85-00370154",
  "indicators": {
    "assigned": "Y",
    "dcw": "Y",
    "cts": "Y",
    "smart_features": "Y",
    "watchlist": "Y",
    "carpe": "Y",
    "ies_bills": "Y",
    "iso_match": "N"
  },
  "edw": [],
  "cts": [],
  "smart_features": [],
  "watchlist": [],
  "carpe": [],
  "ies_bills": [],
  "alert_reasons": [],
  "game_summary": []
}
```

Every source can return multiple rows. IES flags are nested under the
corresponding bill in a `Flags` array; the Power BI-style concatenated values
are also returned as `Flag Short Names` and `Flag Type Codes`.

All dates use the existing API `YYYY-MM-DD` serialization.

## Query behavior

The service sends fixed parameterized queries to the three databases in
parallel. Results are kept in separate response sections instead of joining
all one-to-many sources into a row-multiplying result set.
