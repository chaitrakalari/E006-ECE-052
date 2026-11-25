"""
ECE-052 - Instrument Calibration Due-Date and Certificate Tracker
Team E006 (Chaitra Kalari, Chandana D M)

Core engine: loads instruments, processes UPLOAD_CERT / ISSUE / STATUS
commands in file order, and produces the four output tables.

Business rules implemented here (see DESIGN.md for the full register):
  BR-01  Due date = latest cal date + interval months (same day-of-month;
         clamp to the last day of the month if that day does not exist).
  BR-02  States: IN_CAL (<= due date) -> GRACE (criticality B only, due+1
         .. due+15) -> OUT_OF_CAL. FAILED whenever the latest applied
         certificate's result is FAIL (overrides everything else).
  BR-03  Issue lock: OUT_OF_CAL / FAILED instruments are refused for ISSUE.
         GRACE instruments may be issued, but the issue log line carries a
         GRACE flag.
  BR-04  LIMITED result: instrument stays IN_CAL (or GRACE/OUT_OF_CAL per
         the normal date rules) but is tagged `limited`; it may only be
         issued to jobs whose required accuracy class is B.
  BR-05  Certificate ordering: the latest cal date wins. A certificate
         dated on/before the current latest applied cal date is stored but
         does not change state (STORED_OLDER). A duplicate cert number
         (seen anywhere before) is rejected (DUPLICATE) and not stored.
  BR-06  Due list: instruments (excluding FAILED, which has no due date)
         whose due date falls on or before STATUS date + 30 days, sorted
         by due date then instrument ID, with days_remaining (can be
         negative if already overdue).
  BR-07  Interval shortening: when two *consecutive applied* certificates
         for an instrument are both LIMITED, the interval is halved
         (floor, minimum 3 months) for certificates applied after that
         point. The due date of the second LIMITED certificate itself is
         still computed with the interval in effect *before* the halving.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(s: str) -> date:
    y, m, d = s.strip().split("-")
    return date(int(y), int(m), int(d))


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    return (next_month_first - timedelta(days=1)).day


def add_months(d: date, months: int) -> date:
    """BR-01: same day-of-month, else the last day of the resulting month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _last_day_of_month(year, month))
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Instrument:
    instrument_id: str
    instrument_type: str
    description: str
    serial_no: str
    calibration_interval_months: int  # original/starting interval (BR csv)
    criticality: str  # "A" or "B"
    location: str

    current_interval: int = field(init=False)

    def __post_init__(self):
        self.current_interval = self.calibration_interval_months


@dataclass
class AppliedCert:
    cert_no: str
    cal_date: date
    result: str              # PASS / LIMITED / FAIL
    interval_used: int       # interval in effect when this cert was applied
    due_date: date
    upload_line: int


@dataclass
class IssueRecord:
    line_no: int
    date: date
    job_id: str
    instrument_id: str
    required_class: str
    result: str     # ISSUED / REFUSED
    reason: str     # NONE / OUT_OF_CAL / FAILED / LIMITED
    flag: str        # NONE / GRACE


@dataclass
class CertRecord:
    line_no: int
    cert_no: str
    instrument_id: str
    cal_date: date
    result: str
    outcome: str  # APPLIED / STORED_OLDER / DUPLICATE


GRACE_DAYS_B = 15
GRACE_DAYS_A = 0
MIN_INTERVAL_MONTHS = 3


class CalibrationTracker:
    def __init__(self):
        self.instruments: dict[str, Instrument] = {}
        self.applied_certs: dict[str, list[AppliedCert]] = {}
        self.seen_cert_numbers: set[str] = set()
        self.issue_log: list[IssueRecord] = []
        self.cert_log: list[CertRecord] = []
        self.state_table_rows: list[dict] = []
        self.due_list_rows: list[dict] = []

    # -- loading ------------------------------------------------------------

    def load_instruments(self, path: str) -> None:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                inst = Instrument(
                    instrument_id=row["instrument_id"].strip(),
                    instrument_type=row["instrument_type"].strip(),
                    description=row["description"].strip(),
                    serial_no=row["serial_no"].strip(),
                    calibration_interval_months=int(row["calibration_interval_months"]),
                    criticality=row["criticality"].strip(),
                    location=row["location"].strip(),
                )
                self.instruments[inst.instrument_id] = inst
                self.applied_certs[inst.instrument_id] = []

    # -- commands -------------------------------------------------------------

    def run_command_file(self, path: str, data_dir: str = ".") -> None:
        with open(path, encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                line = raw.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split("|")
                cmd = parts[0]
                if cmd == "LOAD_INSTRUMENTS":
                    self.load_instruments(f"{data_dir}/{parts[1]}")
                elif cmd == "UPLOAD_CERT":
                    self._upload_cert(line_no, parts)
                elif cmd == "ISSUE":
                    self._issue(line_no, parts)
                elif cmd == "STATUS":
                    self._status(parts)
                elif cmd == "PRINT_ISSUE_LOG":
                    pass  # issue_log.csv is always produced; nothing extra to do
                else:
                    raise ValueError(f"Unknown command at line {line_no}: {cmd}")

    # -- BR-05 / BR-07: certificate upload ----------------------------------

    def _upload_cert(self, line_no: int, parts: list[str]) -> None:
        _, upload_date_s, cert_no, instrument_id, cal_date_s, result, lab = parts
        cal_date = parse_date(cal_date_s)

        if cert_no in self.seen_cert_numbers:
            self.cert_log.append(CertRecord(line_no, cert_no, instrument_id, cal_date, result, "DUPLICATE"))
            return
        self.seen_cert_numbers.add(cert_no)

        inst = self.instruments[instrument_id]
        certs = self.applied_certs[instrument_id]
        latest = certs[-1] if certs else None

        if latest is not None and cal_date <= latest.cal_date:
            self.cert_log.append(CertRecord(line_no, cert_no, instrument_id, cal_date, result, "STORED_OLDER"))
            return

        # APPLIED: becomes the new latest certificate
        interval_used = inst.current_interval
        due_date = add_months(cal_date, interval_used)
        applied = AppliedCert(cert_no, cal_date, result, interval_used, due_date, line_no)
        certs.append(applied)
        self.cert_log.append(CertRecord(line_no, cert_no, instrument_id, cal_date, result, "APPLIED"))

        # BR-07: two consecutive applied LIMITED results -> halve interval
        if len(certs) >= 2 and certs[-1].result == "LIMITED" and certs[-2].result == "LIMITED":
            inst.current_interval = max(inst.current_interval // 2, MIN_INTERVAL_MONTHS)

    # -- state computation (BR-02) -------------------------------------------

    def _compute_state(self, instrument_id: str, on_date: date):
        """Returns (state, limited, due_date_or_None, latest_cert_or_None, interval_months)."""
        inst = self.instruments[instrument_id]
        certs = self.applied_certs[instrument_id]
        if not certs:
            # No certificate ever recorded for this instrument.
            return "OUT_OF_CAL", False, None, None, inst.current_interval

        latest = certs[-1]
        limited = latest.result == "LIMITED"

        if latest.result == "FAIL":
            return "FAILED", limited, None, latest, latest.interval_used

        due_date = latest.due_date
        if on_date <= due_date:
            state = "IN_CAL"
        elif inst.criticality == "A":
            grace_end = due_date + timedelta(days=GRACE_DAYS_A)
            state = "OUT_OF_CAL" if on_date > grace_end else "GRACE"
        else:  # criticality B
            grace_end = due_date + timedelta(days=GRACE_DAYS_B)
            state = "GRACE" if on_date <= grace_end else "OUT_OF_CAL"

        return state, limited, due_date, latest, latest.interval_used

    # -- BR-03 / BR-04: ISSUE -------------------------------------------------

    def _issue(self, line_no: int, parts: list[str]) -> None:
        _, date_s, job_id, instrument_id, required_class = parts
        on_date = parse_date(date_s)
        state, limited, _due, _latest, _interval = self._compute_state(instrument_id, on_date)

        if state in ("OUT_OF_CAL", "FAILED"):
            result, reason, flag = "REFUSED", state, "NONE"
        elif limited and required_class == "A":
            result, reason, flag = "REFUSED", "LIMITED", "NONE"
        else:
            result, reason = "ISSUED", "NONE"
            flag = "GRACE" if state == "GRACE" else "NONE"

        self.issue_log.append(
            IssueRecord(line_no, on_date, job_id, instrument_id, required_class, result, reason, flag)
        )

    # -- STATUS: state table row per instrument + due list (BR-06) ----------

    def _status(self, parts: list[str]) -> None:
        status_date = parse_date(parts[1])
        rows_this_status = []
        for instrument_id in sorted(self.instruments.keys()):
            state, limited, due_date, latest, interval_months = self._compute_state(instrument_id, status_date)
            row = {
                "status_date": status_date,
                "instrument_id": instrument_id,
                "state": state,
                "limited": "true" if limited else "false",
                "latest_cert_no": latest.cert_no if latest else "",
                "latest_cal_date": latest.cal_date if latest else "",
                "due_date": due_date if due_date else "NONE",
                "interval_months": interval_months,
            }
            self.state_table_rows.append(row)
            if state != "FAILED" and due_date is not None:
                if due_date <= status_date + timedelta(days=30):
                    rows_this_status.append((due_date, instrument_id, state))

        rows_this_status.sort(key=lambda r: (r[0], r[1]))
        for due_date, instrument_id, state in rows_this_status:
            self.due_list_rows.append({
                "status_date": status_date,
                "instrument_id": instrument_id,
                "due_date": due_date,
                "days_remaining": (due_date - status_date).days,
                "state": state,
            })

    # -- output writers -------------------------------------------------------

    def write_outputs(self, out_dir: str) -> None:
        self._write_csv(
            f"{out_dir}/state_table.csv",
            ["status_date", "instrument_id", "state", "limited", "latest_cert_no",
             "latest_cal_date", "due_date", "interval_months"],
            self.state_table_rows,
        )
        self._write_csv(
            f"{out_dir}/due_list.csv",
            ["status_date", "instrument_id", "due_date", "days_remaining", "state"],
            self.due_list_rows,
        )
        self._write_csv(
            f"{out_dir}/issue_log.csv",
            ["line_no", "date", "job_id", "instrument_id", "required_class", "result", "reason", "flag"],
            [vars(r) for r in self.issue_log],
        )
        self._write_csv(
            f"{out_dir}/cert_log.csv",
            ["line_no", "cert_no", "instrument_id", "cal_date", "result", "outcome"],
            [vars(r) for r in self.cert_log],
        )

    @staticmethod
    def _write_csv(path: str, header: list[str], rows: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in header})
