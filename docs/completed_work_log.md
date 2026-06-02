# FedExSucks Completed Work Log

Keep this as the historical ledger.
Open work belongs in `projects/fedexsucks/docs/active_work_queue.md`.

---

## Completed

### FS1 — Bootstrap FedExSucks and prove one FedEx API call
- Result: separate project created under `projects/fedexsucks`; real FedEx auth + direct tracking-number lookup proved

### FS2 — Scaffold the Django app
- Result: Django project/app created with `Package` and `PackageEvent` models, admin registration, initial migration, and root page

### FS3 — Reuse FedEx client logic and persist package/event data
- Result: shared FedEx client moved into app code, refresh command added, package state and scan events persist locally

### FS4 — Verify recent-shipment retrieval path
- Result: confirmed FedEx does not obviously expose a simple account-wide recent-shipment list lane for this use case

### FS5 — Choose ingestion strategy
- Result: decided not to rely on an assumed account-wide shipment list endpoint; treat FedEx tracking as a status/details API and use reference/account/date as the current practical lookup lane

### FS7 — Add proof-of-concept reference lookup lane
- Result: added `/track/v1/referencenumbers` helper path and standalone reference lookup script

### FS8 — First-pass app reference lookup flow
- Result: added saved references, homepage lookup flow, candidate/result rendering, and local package persistence for returned tracking numbers

### FS9 — Fix reference payload contract
- Commit: `381f2fb`
- Result: updated request shape to match FedEx docs, including `type`, `accountNumber`, and `shipDateEnd`

### FS10 — Polish reference lookup results UI
- Commit: `f413237`
- Result: clearer result summary, saved-reference context, and more obvious link into stored package flow

### FS11 — Add package detail page
- Commit: `8a11d5a`
- Result: added dedicated `/packages/<tracking_number>/` page and linked homepage/lookup results into it

### FS12 — Simplify homepage package list
- Commit: `b01a1e4`
- Result: homepage trimmed toward a compact queue with tracking, status, latest event, and details link

### FS13 — Make homepage feel like a queue
- Commit: `6b74edf`
- Result: converted key homepage sections to queue/table-style views and simplified labels

### FS14 — Force saved references through the reference lookup path
- Commit: `07d879c`
- Result: saved-reference lookups no longer try the direct tracking-number path first; bogus `NY1294` row was cleaned up

### FS15 — Ignore errored FedEx reference echoes
- Commit: `b9e8fb5`
- Result: errored reference rows that echo the reference string as a tracking-like value are no longer stored as packages

### FS16 — Separate real hits from unresolved rows
- Commit: `b7f87cd`
- Result: lookup results now distinguish real tracking-number hits from unresolved/error FedEx rows and summarize them separately
