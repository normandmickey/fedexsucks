# FedExSucks Active Notes

Task FS1 goals:
- keep this project separate from Odd$mith
- prove one real FedEx API call before building the full app
- start with a standalone script, then grow into Django if the API path is solid

## FS1 result
- Credential model confirmed: `FEDEX_API_KEY` + `FEDEX_SECRET_KEY`
- Target lane confirmed: real-package lookup, not sandbox-only validation
- Proof script: `scripts/test_fedex_tracking.py`
- Real FedEx tracking lookup works
- FS1 is effectively complete

## FS2 result
- Django project scaffolded in place under `projects/fedexsucks`
- App: `tracker`
- Initial models:
  - `Package`
  - `PackageEvent`
- Admin registration exists for both models
- Root URL returns a minimal app page
- Initial migration generated: `tracker/migrations/0001_initial.py`

## FS3 result
- Reusable FedEx client logic moved into `tracker/fedex.py`
- Standalone proof script now reuses app FedEx logic instead of duplicating it
- Added management command: `python manage.py refresh_package --tracking-number YOUR_TRACKING_NUMBER`
- Refresh command now:
  - calls the live FedEx API
  - updates the `Package` current-state fields
  - stores raw payload on the package
  - persists `PackageEvent` rows from scan events
- Homepage now renders persisted packages and recent events

## Local run steps for FS3
1. Make sure `.env` contains FedEx credentials
2. Install minimum packages:
   - `./.venv/bin/pip install django requests`
3. Apply migrations if not already done:
   - `./.venv/bin/python manage.py migrate`
4. Refresh a package:
   - `./.venv/bin/python manage.py refresh_package --tracking-number YOUR_TRACKING_NUMBER --nickname "Optional label"`
5. Run dev server:
   - `./.venv/bin/python manage.py runserver 0.0.0.0:8000`
6. Visit the homepage or admin to inspect persisted package/event data

## FS4 direction pivot
- Product shape changed: this should be a private recent-shipments dashboard, not a manual add-package tracker.
- Goal now is to show shipments sent in the previous 7 days without one-by-one package creation.
- FedEx docs strongly suggest a possible lane through Track API reference/account-based retrieval, but not a simple guaranteed "list all recent shipments" endpoint.
- If account-wide recent shipment retrieval is not directly available, likely fallback lanes are:
  - a shipment creation feed/history source from the shipping workflow
  - webhook/visibility subscription flow
  - or tracking-by-reference with enough reference/account/date inputs

## FS5 decision
- Do not build FedExSucks around a presumed FedEx endpoint that lists all account shipments from the last 7 days.
- Chosen strategy: treat FedEx as the status/details API for shipments we already know about, not the primary discovery source for all recent shipments.
- Best future ingestion lane: a source of known shipment identities from the real shipping workflow, ideally either:
  - FedEx visibility/webhook subscription if available for the account/use case, or
  - shipment-creation/history data from the workflow that creates labels.
- Secondary fallback only if needed: reference/account/date tracking, but only if the shipping workflow has dependable reference data and the extra lookup inputs are already known.

## FS7 result
- Added API-only reference lookup lane for `CUSTOMER_REFERENCE`.
- New FedEx helper path in `tracker/fedex.py` uses `/track/v1/referencenumbers` with shipper account number.
- New proof script: `scripts/test_fedex_reference.py`
- Required env for this test path:
  - `FEDEX_ACCOUNT_NUMBER`
  - `FEDEX_CUSTOMER_REFERENCE`
- This is a proof lane for known references only; it does not restore the earlier "all recent shipments" assumption.

## Local run steps for FS7
- `./.venv/bin/python scripts/test_fedex_reference.py --reference YOUR_REFERENCE --account-number YOUR_ACCOUNT_NUMBER`
- Add `--raw` to inspect the full FedEx payload if the shape is odd.

## Likely next task after FS7
- FS8: if the reference lookup works, map reference-returned results into the app as a first-class lookup flow
