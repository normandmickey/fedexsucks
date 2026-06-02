# FS26b Notes — Reference type probing against known-good website example

Test case:
- reference value: `NY1294`
- account number: `216297091`
- ship date begin/end: `2026-05-01`
- destination country: `US`
- destination postal code: `20294`
- carrier code: `FDXE`

Goal:
- test whether a different FedEx `referencesInformation.type` value explains the website/API parity gap

Results:
- `CUSTOMER_REFERENCE` -> accepted by API, but result row still returned `TRACKING.REFERENCENUMBER.NOTFOUND`
- `PURCHASE_ORDER` -> accepted by API, but result row still returned `TRACKING.REFERENCENUMBER.NOTFOUND`
- `DEPARTMENT` -> accepted by API, but result row still returned `TRACKING.REFERENCENUMBER.NOTFOUND`
- `CUSTOMER` -> API 400 `TRACKING.REFERENCETYPE.INVALID`
- `REFERENCE` -> API 400 `TRACKING.REFERENCETYPE.INVALID`
- `INVOICE_NUMBER` -> API 400 `TRACKING.REFERENCETYPE.INVALID`
- `BOL` -> API 400 `TRACKING.REFERENCETYPE.INVALID`
- `RMA_ASSOCIATION` -> API 400 `TRACKING.REFERENCETYPE.INVALID`

Takeaway:
- the parity gap is not solved just by swapping to another obvious reference type
- FedEx does accept a small subset of type values, but the accepted alternatives tested here still do not reproduce the website success
- this points more strongly toward a hidden website normalization/fallback path or a backend lane that differs from the public `/track/v1/referencenumbers` contract

Possible next probes:
1. inspect whether the website alt-ref flow uses different semantics for destination postal/date than the API docs imply
2. inspect whether another FedEx endpoint or non-public internal lane underlies the website flow
3. keep product work moving by improving operator UX while treating website/API parity as a tracked research lane
