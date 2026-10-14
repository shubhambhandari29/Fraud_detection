# ABI Litigation claim dashboard API

## Endpoint

```http
GET /abi_litigation/dashboard/{claim_number}
```

The endpoint is authenticated and read-only. `claim_number` is the complete
claim-feature identifier stored in `DERIVE_CLM_FTR_NBR`, not the normalized
base claim number used by the landing page.

## Data sources

Both sections are read from `DATATEXT_DB_NAME`, which defaults to
`CLMDS_DataModelingAndTextMining`:

- `dbo.tblALLitigation_EDW_OpenClaims` supplies the Litigation facts displayed
  by the Power BI summary report.
- `dbo.tblALLitigation_GAME_REASONS` supplies generated narrative sections.
  `game_summary` follows the newer report with `LITIGATION = 1`, excluding
  results containing `Error : 400`. `game_summary_legacy` follows the older
  report with `LITIGATION = 0` and a cleaned `Claim Summary` field.

The API follows the newer `Litigation_GAME_Summary_Model_1` project. GAME text
is split into the same six `## Heading: value` sections used by that report.

## Response

```json
{
  "claim_number": "85-00837106-02",
  "edw": [],
  "game_summary": [],
  "game_summary_legacy": []
}
```

Both sections are arrays. Multiple EDW rows and multiple GAME runs are
returned independently instead of being collapsed or multiplied by a join.
Dates use the application's existing `YYYY-MM-DD` response format.

The Law Firm Profiling project has its own
`GET /abi_litigation/law_firm/dashboard/{law_firm_name}` endpoint.
