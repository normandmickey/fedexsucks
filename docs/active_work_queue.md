# FedExSucks Active Work Queue

Keep this tight and forward-looking.
Use this file for open work only.
Move completed items to `projects/fedexsucks/docs/completed_work_log.md`.

Status values:
- `todo`
- `in_progress`
- `parked`

---

## Working Rules
- One active task at a time
- Define success before coding
- Retest before commit
- Commit after each small win
- Split follow-up polish into separate tasks
- Use this file instead of rebuilding the whole plan in chat

---

## Track A — Reference Lookup Truthfulness

### Task FS24 — Separate real package hits from unresolved FedEx rows
- Status: `done`
- Goal: make the reference lookup UI and persistence distinguish real trackable packages from errored or unresolved FedEx result rows
- Success check: errored reference rows are not stored as packages or presented as valid tracking hits
- Outcome: saved references now force the reference lookup path; errored FedEx reference echoes are not stored as packages; lookup results are split into trackable packages vs unresolved rows

### Task FS25 — Make reference lookup copy and summaries plainer
- Status: `todo`
- Goal: reduce confusing wording around result rows, saved packages, and unresolved rows
- Current issue: the app is more truthful now, but some labels still feel too technical or awkward for day-to-day use
- Success check: lookup summary language is obvious without needing FedEx API context

### Task FS25b — Compare working FedEx website lookup shape vs API request
- Status: `done`
- Goal: identify the parity gap between a known-good FedEx website reference lookup and the request we send to `/track/v1/referencenumbers`
- Current issue: the website lookup works for `NY1294`, but the API request with the same visible values still returns `TRACKING.REFERENCENUMBER.NOTFOUND`
- Success check: the likely mismatch is narrowed to one concrete factor or a short list of concrete factors (field mapping, hidden normalization, or different backend lane)
- Outcome: website-visible inputs were matched in the API request, but the API still returned not found; parity gap is now narrowed to hidden normalization, different backend lookup lane, or a still-hidden field/interpretation mismatch

### Task FS26 — Confirm multi-package reference/date-range behavior with real examples
- Status: `todo`
- Goal: verify whether real references can return multiple shipments in a date range and make sure all valid hits are saved cleanly
- Current issue: the UI assumes multi-hit behavior, but this needs real-world confirmation beyond single-row/error-ish examples
- Success check: one confirmed multi-hit example returns and saves all real tracking numbers without creating junk rows

### Task FS26c — Relax postal-code requirement for reference lookups
- Status: `done`
- Goal: match the older working FedEx sample more closely by allowing reference lookups without destination postal code
- Current issue: app had been forcing destination postal code even though older working sample omitted it
- Success check: postal code becomes optional in app/API flow and the known example is re-tested without it
- Outcome: postal code is now optional in the FedExSucks form and API request; the known `NY1294` example still returned `TRACKING.REFERENCENUMBER.NOTFOUND` without postal code, so postal requirement was too strict but not the parity fix

---

## Track B — Queue and Detail UX

### Task FS27 — Keep homepage queue compact and operator-friendly
- Status: `todo`
- Goal: keep the homepage focused on tracking number, status, latest event, and details link
- Current issue: the queue is much better now, but still may need a small cleanup pass after more real usage
- Success check: homepage reads like a work queue, not a debug screen

### Task FS28 — Clean up package detail page
- Status: `todo`
- Goal: make the detail page easier to scan while preserving the deeper payload context when needed
- Current issue: the detail page still feels a little raw and data-dumpy
- Success check: package summary is easy to scan and deeper sections feel secondary

---

## Track C — Persistence and Data Quality

### Task FS29 — Review package save/update rules
- Status: `todo`
- Goal: confirm exactly when a returned result should create or update a Package row
- Current issue: direct tracking hits, reference hits, and unresolved rows now behave better, but the save/update rules should be explicitly hardened
- Success check: only real trackable packages persist, and repeat lookups update cleanly without confusion

### Task FS30 — Add lightweight diagnostics for unresolved FedEx rows
- Status: `todo`
- Goal: preserve enough raw-response visibility to debug weird FedEx behavior without polluting the package queue
- Current issue: unresolved rows are visible in the UI, but operator debugging may still be clunky for edge cases
- Success check: odd FedEx responses are inspectable quickly when a lookup behaves strangely

---

## Track D — Workflow Simplification

### Task FS31 — Tighten the main operator workflow
- Status: `todo`
- Goal: optimize for the real flow: choose reference, choose date range, list packages, click details
- Current issue: the app has the right pieces now, but the workflow still carries some exploratory scaffolding from earlier iterations
- Success check: the happy path feels obvious and uncluttered
