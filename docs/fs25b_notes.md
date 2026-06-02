# FS25b Notes — FedEx website/API parity gap

Known-good website lookup example:
- URL pattern: `https://www.fedex.com/wtrk/track/?action=altref&trackingnumber=ny1294&shipdate=2026-5-1&account_number=216297091&dest_cntry=US&dest_postal=20294`
- Visible inputs from website lane:
  - reference value: `NY1294`
  - ship date: `2026-5-1`
  - account number: `216297091`
  - destination country: `US`
  - destination postal code: `20294`

Current API request shape in `tracker/fedex.py`:
- endpoint: `/track/v1/referencenumbers`
- body:
  - `referencesInformation.type = CUSTOMER_REFERENCE`
  - `referencesInformation.value = NY1294`
  - `referencesInformation.accountNumber = 216297091`
  - `referencesInformation.carrierCode = FDXE`
  - `referencesInformation.shipDateBegin = 2026-05-01`
  - `referencesInformation.shipDateEnd = 2026-05-01`
  - `referencesInformation.destinationCountryCode = US`
  - `referencesInformation.destinationPostalCode = 20294`
  - `includeDetailedScans = true`

Observed result:
- Website path works for Norm
- API path still returns `TRACKING.REFERENCENUMBER.NOTFOUND`

Likely explanations still open:
1. FedEx website alt-ref flow is not actually backed by the same API lane/logic as `/track/v1/referencenumbers`
2. Website path may apply hidden normalization or alternate fallback matching not exposed in the public API contract
3. One visible field still differs in a subtle way despite matching at first glance (format, account/reference interpretation, or postal/date semantics)
4. The effective website reference type may not map cleanly to `CUSTOMER_REFERENCE` in the API

Next useful comparisons:
- inspect whether the working website lane reveals any additional query/body params beyond the visible URL values
- test whether alternative reference type values exist/are accepted by FedEx for this reference class
- test whether dropping or varying carrier assumptions changes anything if the API allows it
