# ECE-052 — Instrument Calibration Due-Date and Certificate Tracker

Team E006 · Chaitra Kalari (1AT24UE011) · Chandana D M (1AT24UE012) · Section ECM A

A command-file-driven engine that tracks calibration status of test-lab instruments
(multimeters, LCR meters, power supplies), locks out-of-calibration instruments
from being issued to test jobs, and reports due dates, grace periods and the
30-day due list. No UI — everything runs from `commands.txt`.

See `DESIGN.md` for the glossary, class diagram, state diagram and full
business-rule register (BR-01 … BR-07), and `decision_log.md` for the
choices we made along the way.

## Requirements

Python 3.10+, standard library only (no pip installs needed to run the engine).

## How to run

```bash
python main.py --data data --out output
```

This reads `data/instruments.csv` and `data/commands.txt`, runs every
command in file order, and writes four files to `output/`:

- `state_table.csv` — one row per instrument per STATUS date
- `due_list.csv` — one row per due instrument per STATUS date (30-day window)
- `issue_log.csv` — one row per ISSUE command
- `cert_log.csv` — one row per UPLOAD_CERT command

To run against a different data pack (e.g. the hidden evaluation set):

```bash
python main.py --data path/to/other/pack --out output
```

## How to run the tests

```bash
pytest -v tests/
```

19 tests, one (or more) per business rule, plus a full-pack smoke test that
re-runs the whole sample data and checks every planted edge case named in
the sample pack's own README (31-Aug/Feb clamp, STATUS-on-due-date,
criticality-A zero grace, out-of-order upload, interval halving, grace
day-15-vs-16, FAIL/recovery, duplicate cert).

> Note: this sandbox had no internet access to `pip install pytest`, so the
> suite was also verified here with a tiny stdlib runner
> (`tests/_run_without_pytest.py`) — all 19 pass. `pytest -v` will work
> normally wherever pytest is installed; the test file itself needs no
> changes.

## Command format (`commands.txt`)

One command per line, `COMMAND|arg1|arg2|...`. Lines starting with `#` and
blank lines are ignored but still counted for line numbers.

| Command | Arguments |
|---|---|
| `LOAD_INSTRUMENTS` | file |
| `UPLOAD_CERT` | upload_date \| cert_no \| instrument_id \| cal_date \| result \| lab |
| `ISSUE` | date \| job_id \| instrument_id \| required_class |
| `STATUS` | YYYY-MM-DD |
| `PRINT_ISSUE_LOG` | (none — issue_log.csv is always written) |

## Project layout

```
main.py                 CLI entry point
src/engine.py            All business logic (CalibrationTracker)
tests/test_engine.py     Unit tests, one per business rule + smoke test
data/                     Sample data pack (instruments.csv, commands.txt)
output/                   Generated CSVs (gitignored — regenerate with main.py)
DESIGN.md                 Glossary, diagrams, business-rule register
decision_log.md           One-line decisions with reasoning
```
