# FS26c Notes — Make destination postal code optional

Goal:
- test the older working FedEx sample assumption that `destinationPostalCode` may be optional for reference lookup

Changes made:
- `tracker/fedex.py`
  - `request_tracking_by_reference(...)` now omits `destinationPostalCode` from the JSON body when it is blank/None
  - `fetch_reference_tracking_results(...)` now accepts `destination_postal_code: str | None = None`
- `tracker/services.py`
  - reference lookup validation no longer requires destination postal code
- `tracker/templates/tracker/home.html`
  - destination postal code label now says `(optional)`

Re-test:
- reference: `NY1294`
- account: `216297091`
- ship date begin/end: `2026-05-01`
- destination country: `US`
- destination postal code: omitted
- result: still `TRACKING.REFERENCENUMBER.NOTFOUND`

Takeaway:
- requiring postal code was too strict in the app
- removing postal code did not fix the website/API parity gap for the known example
- this keeps the product closer to a previously working sample and removes an unnecessary local constraint, but the deeper parity issue remains
