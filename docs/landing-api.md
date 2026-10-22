# Combined claims landing page

`GET /landing/` uses the existing authenticated session cookie. It has no
required query parameters. The four selector tables are filtered only by
`Selected = 1`; addressed rows are still included. An empty result is `{}`.

The response is a JSON object keyed by normalized claim number. If a claim has
multiple rows in any model, its keys gain one-based suffixes (`_1`, `_2`, etc.).
A claim with only one combined row has no suffix. Every value is a flat object
with all 35 fields defined by `FlatLandingClaim`; the original field name is
prefixed with `Fraud_`, `Litigation_`, `Severity_`, or `Subrogation_`.

```json
{
  "85-00837106_1": {
    "Fraud_Predictions": "High",
    "Fraud_Action": "Review — Refer to analyst",
    "Litigation_Predictions": "High",
    "Litigation_Action": "Review — Attorney involved",
    "Litigation_Feature": "01",
    "Severity_Predictions": "Low",
    "Severity_Action": null,
    "Subrogation_Predictions": "High",
    "Subrogation_Action": "Assigned"
  },
  "85-00837106_2": {
    "Fraud_Predictions": "Low",
    "Fraud_Action": null,
    "Litigation_Predictions": "Low",
    "Litigation_Action": "Monitor",
    "Litigation_Feature": "02",
    "Severity_Predictions": "Low",
    "Severity_Action": null,
    "Subrogation_Predictions": "Low",
    "Subrogation_Action": null
  }
}
```

The example omits the other filter fields for readability; the actual response
always includes every field. Missing non-prediction values are JSON `null`, not
the string `"null"`. Every prediction is `"High"` or `"Low"`: a missing model,
blank prediction, unrecognized prediction, or explicit low value becomes
`"Low"`. Only a normalized high value becomes `"High"`.

Rows from different models are paired by ordinal position, not by a database
relationship. A claim with two litigation rows and three subrogation rows has
three flat entries, not six. Model fields without a row at a given position
are null except that model's prediction, which is `"Low"`. Identical source
rows are preserved. Each model's rows are ordered by feature (where present),
high prediction first, action, and remaining field values so numbered entries
are stable for unchanged data. The `Action` field remains the combined display text;
`Action_Raw` carries the original litigation/severity Action column. The
litigation feature is included as `Litigation_Feature`.

| Model | Claim column | Prediction column | Action components |
| --- | --- | --- | --- |
| fraud | CLM_NBR | SIU_REFERRAL (`1` = High, `0` = Low) | Status, Feedback |
| litigation | DERIVE_CLM_FTR_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| severity | CLM_NBR | PREDICTIONS | Action, ACTION_DETAILS |
| subrogation | CLM_NBR_U | PREDICTIONS | Status |

Fraud prediction uses the numeric `SIU_REFERRAL` value; `ML_PREDICTIONS` is not
used by this endpoint. The other models continue to normalize their text
prediction labels after the colon.

Litigation's final two-character feature suffix is split before grouping:
`85-00837106-02` becomes normalized claim `85-00837106` and feature `02`.
Claim and feature values remain strings to preserve leading zeros.

The service uses one parameterized `UNION ALL` query. SQL Server execution and
performance require a configured live database to verify; local tests use
equivalent SQLite functions for normalization and mock the API database call.
