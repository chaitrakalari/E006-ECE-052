# Decision Log — ECE-052 (Team E006)

1. Chose Python 3.10+ over Java — faster to iterate on date arithmetic and easier to unit-test in the time we had.
2. State is computed on demand from the latest applied certificate (`_compute_state`), never stored on the instrument — matches the brief's explicit ask to explain this in the viva.
3. Modelled "applied vs. stored-older" certificates as two separate code paths (`_upload_cert`) rather than one, so BR-05 and BR-07 (which only look at *applied* certs) can't accidentally see an out-of-order cert.
4. `due_date` for an applied certificate is computed and frozen at the moment it's applied, using whatever `current_interval` the instrument has *then* — so BR-07's halving only affects certificates applied afterwards, never retroactively. Verified against the README's INS-008 walkthrough (7-month interval, due dates before and after the halving).
5. BR-07 (interval halving) is triggered every time the current and previous *applied* certs are both LIMITED — not just once per instrument — so three or more LIMITED results in a row would halve more than once. The brief and sample data only cover exactly two, so we documented this instead of guessing; see test `test_interval_halving_has_a_floor_of_three_months`.
6. An instrument with zero certificates ever uploaded is treated as OUT_OF_CAL with `due_date = NONE` (not in the brief or sample data, but every instrument must get a state table row).
7. DUPLICATE check (cert number already seen) happens before the STORED_OLDER check, and a duplicate is not stored at all — only logged with outcome DUPLICATE. Confirmed against the sample pack's planted duplicate (CC-2025-0063).
8. Same-day command ordering within commands.txt follows strict file order (uploads/issues/status interleave exactly as written) — the sample-pack README confirms this is simply "file order", so no extra sorting was added.
9. Grace window is `due_date + 1` through `due_date + 15` inclusive for criticality B; implemented as `on_date <= due_date + 15 days` since due_date+0 is already IN_CAL. Verified against the README's day-15-vs-day-16 example (INS-002 vs INS-011).
10. Line numbers in cert_log.csv / issue_log.csv are the physical line number in commands.txt, including comment/blank lines, so they line up with the planted-scenario references in the sample pack's README.
11. Wrote one pytest per business rule (not just end-to-end tests) so a failing rule points straight at its ID instead of a vague diff — this is also our viva script.
12. Did not implement either stretch goal (reminder list at 30/15/0 days; annual calibration budget) given the time left before the deadline — core rules, edge cases and tests came first.
