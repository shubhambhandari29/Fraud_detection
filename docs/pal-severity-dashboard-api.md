# PAL Severity claim dashboard API

```http
GET /pal_severity/dashboard/{claim_number}
```

Use the complete `DERIVE_CLM_FTR_NBR` claim-feature value shown in the Power BI
claim slicer. The endpoint requires the existing bearer token.

The response has `edw` rows from
`CLMDS_DataModelingAndTextMining.dbo.tblPALSeverity_EDW_OpenClaims`, `carpe`
rows from `CLM_VendorData.dbo.tblCarpeDataWeeklyAlerts`, and a `Y`/`N`
`carpe_available` indicator. The Carpe join matches `ClientID` to the full
claim-feature value. Both arrays retain all matching rows.

```json
{
  "claim_number": "85-00837106-02",
  "carpe_available": "Y",
  "edw": [],
  "carpe": []
}
```

The report's Vendor source is on `prpre2-clms-azsql01.database.windows.net`.
Set `VENDOR_DB_SERVER` to that host when `DB_SERVER` points to a different
server. It defaults to `DB_SERVER`. `VENDOR_DB_NAME` defaults to
`CLM_VendorData`. Dates returned as SQL date/datetime values use `YYYY-MM-DD`.
