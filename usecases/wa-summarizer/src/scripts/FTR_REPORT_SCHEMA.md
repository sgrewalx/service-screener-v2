# Deterministic FTR Report Schema Notes

Source inspected: `ftr-summary-output-2026-08-03/ftr_results.original.json`

The deterministic FTR report generator treats the JSON as the source of truth and uses these units:

- **FTR requirement rows / summary outcomes**: entries in `framework.ftr.categories`. The source summary reports `compliantCount`, `notCompliantCount`, and `notAvailableCount`; these reconcile to the number of category rows.
- **Category groups**: distinct `categoryName` values across the requirement rows.
- **Evaluated check instances**: objects in `framework.ftr.categories[].checks[]`.
- **Check-level non-compliant finding instances**: evaluated check objects where `status == "not_compliant"`. The detailed appendix has exactly one entry for each of these.
- **Resource-level non-compliant references**: strings in `resources[]` on each non-compliant check. These are listed inside appendix entries and counted separately from appendix entries.
- **Severity totals**: counts of check-level non-compliant finding instances grouped by source-provided `criticality`.

For the preserved 2026-08-03 source JSON:

- FTR requirement rows: 56
- Source summary outcomes: 12 compliant, 18 Need Attention, 26 Not available
- Distinct category groups: 14
- Evaluated check instances: 144
- Check-level non-compliant finding instances: 31
- Resource-level non-compliant references on those findings: 53
- Severity totals for check-level findings: 22 High (`H`), 5 Medium (`M`), 4 Low (`L`)

Optional fields such as `extendedDescription`, `criticality`, `waRelatedPillar`, and `service` are present only on the 31 non-compliant checks in the inspected JSON. Missing fields are rendered as `Not provided in source data`.
