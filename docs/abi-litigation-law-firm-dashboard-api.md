# ABI Litigation Law Firm Profiling API

```http
GET /abi_litigation/law_firm/dashboard/{law_firm_name}
```

The endpoint requires the existing bearer token and an exact law firm name
from `PLNTF_ATTY_LAW_FIRM_NM`. The UI must URL-encode the name.

It reads `vw_plaintiff_lawfirm_data_v2` for claim and matter rows and
`vw_lawfirm_profile_v2` for the report's note chunks. Both views are in
`DATATEXT_DB_NAME` (`CLMDS_DataModelingAndTextMining` by default).

The response includes the source `claim_info` rows, `notes`, KPI values,
and chart-ready counts for resolution, settlement bands, line of business,
jurisdiction, and annual settlement/trial rates. Matter counts use distinct
`MATTER_HCS_SYS_ID` values. Source date/datetime values use `YYYY-MM-DD`.

The PBIP's visuals reference several `v2` measures absent from its semantic
model. The KPI calculations here follow the explicit non-`v2` measure
definitions present in `Claim_Matter_Info.tmdl`; compare against Power BI
before treating them as exact matches for the `v2` cards.
