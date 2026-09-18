# Claim-specific selector APIs

Each authenticated endpoint returns all columns from matching selector-table rows.
The response is always a JSON array. Multiple matching rows are preserved, one
matching row still returns a one-item array, and no match returns `[]`.

| Model | Endpoint example | Database lookup |
| --- | --- | --- |
| Fraud | `GET /claims/get/85-00837106` | `CLM_NBR = '85-00837106'` |
| Litigation | `GET /abi_litigation/get/85-00837106-02` | `DERIVE_CLM_FTR_NBR = '85-00837106-02'` |
| Severity | `GET /pal_severity/get/85-00560726` | `CLM_NBR = '85-00560726'` |
| Subrogation | `GET /auto_subrogation/get/85-00837106` | `CLM_NBR_U = '85-00837106'` |

The Litigation value is the normalized landing-page `claim_number`, a hyphen, and
that recommendation's `Feature`. The endpoint performs an exact lookup of this
complete value. Severity uses the claim number alone and can therefore return
multiple feature rows. Filter values are parameterized, column names are fixed by
the service, and date/datetime response values use the existing `YYYY-MM-DD`
serialization.
