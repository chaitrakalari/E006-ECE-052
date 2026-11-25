"""
Test suite for the ECE-052 calibration tracker.
Run with:  pytest -v
Each test is tagged with the business-rule ID(s) it proves (see DESIGN.md).
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine import CalibrationTracker, add_months, parse_date, Instrument  # noqa: E402


def make_tracker(instruments):
    """instruments: list of dicts with the instruments.csv columns."""
    t = CalibrationTracker()
    for row in instruments:
        inst = Instrument(
            instrument_id=row["instrument_id"],
            instrument_type=row.get("instrument_type", "DMM"),
            description=row.get("description", ""),
            serial_no=row.get("serial_no", "SN0"),
            calibration_interval_months=row["calibration_interval_months"],
            criticality=row["criticality"],
            location=row.get("location", ""),
        )
        t.instruments[inst.instrument_id] = inst
        t.applied_certs[inst.instrument_id] = []
    return t


# ---------------------------------------------------------------------------
# BR-01: due-date month arithmetic
# ---------------------------------------------------------------------------

def test_add_months_31_aug_plus_6_lands_on_feb_28_non_leap():
    # 2025-08-31 + 6 months -> Feb 2026 has no 29/30/31 -> clamp to 28
    assert add_months(date(2025, 8, 31), 6) == date(2026, 2, 28)


def test_add_months_31_mar_plus_6_lands_on_sep_30():
    assert add_months(date(2025, 3, 31), 6) == date(2025, 9, 30)


def test_add_months_regular_case():
    assert add_months(date(2024, 1, 15), 3) == date(2024, 4, 15)


def test_add_months_leap_year_29_feb():
    # cal date 31 Aug 2023 + 6 months -> Feb 2024 (leap) has 29 days
    assert add_months(date(2023, 8, 31), 6) == date(2024, 2, 29)


# ---------------------------------------------------------------------------
# BR-02: state machine (IN_CAL / GRACE / OUT_OF_CAL / FAILED)
# ---------------------------------------------------------------------------

def test_in_cal_up_to_and_including_due_date():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    state, *_ = t._compute_state("I1", date(2025, 1, 1))  # exactly due date
    assert state == "IN_CAL"


def test_criticality_a_has_zero_grace_days():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "A"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    state_due, *_ = t._compute_state("I1", date(2025, 1, 1))
    state_next_day, *_ = t._compute_state("I1", date(2025, 1, 2))
    assert state_due == "IN_CAL"
    assert state_next_day == "OUT_OF_CAL"


def test_criticality_b_grace_day_15_vs_16():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    due = date(2025, 1, 1)
    day15, *_ = t._compute_state("I1", due + __import__("datetime").timedelta(days=15))
    day16, *_ = t._compute_state("I1", due + __import__("datetime").timedelta(days=16))
    assert day15 == "GRACE"
    assert day16 == "OUT_OF_CAL"


def test_fail_result_overrides_date_based_state():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "FAIL", "Lab"])
    state, limited, due_date, *_ = t._compute_state("I1", date(2024, 1, 2))  # day after cal, well within interval
    assert state == "FAILED"
    assert due_date is None


def test_fail_then_pass_recovers_to_in_cal():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "FAIL", "Lab"])
    t._upload_cert(2, ["UPLOAD_CERT", "2024-06-01", "C2", "I1", "2024-06-01", "PASS", "Lab"])
    state, *_ = t._compute_state("I1", date(2024, 6, 2))
    assert state == "IN_CAL"


# ---------------------------------------------------------------------------
# BR-03 / BR-04: ISSUE lock and LIMITED accuracy-class restriction
# ---------------------------------------------------------------------------

def test_issue_refused_when_out_of_cal():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 1, "criticality": "A"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    t._issue(2, ["ISSUE", "2024-03-01", "J1", "I1", "B"])
    rec = t.issue_log[-1]
    assert rec.result == "REFUSED" and rec.reason == "OUT_OF_CAL"


def test_issue_in_grace_is_issued_with_grace_flag():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    t._issue(2, ["ISSUE", "2025-01-10", "J1", "I1", "B"])  # 9 days into grace
    rec = t.issue_log[-1]
    assert rec.result == "ISSUED" and rec.flag == "GRACE"


def test_limited_refused_for_class_a_issued_for_class_b():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "LIMITED", "Lab"])
    t._issue(2, ["ISSUE", "2024-02-01", "J1", "I1", "A"])
    t._issue(3, ["ISSUE", "2024-02-01", "J2", "I1", "B"])
    rec_a, rec_b = t.issue_log[-2], t.issue_log[-1]
    assert rec_a.result == "REFUSED" and rec_a.reason == "LIMITED"
    assert rec_b.result == "ISSUED"


# ---------------------------------------------------------------------------
# BR-05: certificate ordering / duplicates
# ---------------------------------------------------------------------------

def test_out_of_order_cert_is_stored_but_does_not_change_state():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-11-01", "C1", "I1", "2024-10-01", "PASS", "Lab"])
    t._upload_cert(2, ["UPLOAD_CERT", "2024-11-05", "C2", "I1", "2024-05-01", "LIMITED", "Lab"])
    assert t.cert_log[-1].outcome == "STORED_OLDER"
    assert len(t.applied_certs["I1"]) == 1
    assert t.applied_certs["I1"][0].cert_no == "C1"


def test_duplicate_cert_number_is_rejected():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])
    t._upload_cert(2, ["UPLOAD_CERT", "2024-02-01", "C1", "I1", "2024-02-01", "PASS", "Lab"])
    assert t.cert_log[-1].outcome == "DUPLICATE"
    assert len(t.applied_certs["I1"]) == 1  # second (duplicate) cert never applied


# ---------------------------------------------------------------------------
# BR-07: interval shortening on two consecutive LIMITED results
# ---------------------------------------------------------------------------

def test_two_consecutive_limited_halves_interval_for_future_certs():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 7, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2025-05-28", "C1", "I1", "2025-05-20", "LIMITED", "Lab"])
    t._upload_cert(2, ["UPLOAD_CERT", "2025-12-20", "C2", "I1", "2025-12-15", "LIMITED", "Lab"])
    # the second LIMITED cert's own due date still uses the pre-halving interval (7)
    assert t.applied_certs["I1"][-1].due_date == date(2026, 7, 15)
    assert t.instruments["I1"].current_interval == 3  # floor(7/2) = 3
    t._upload_cert(3, ["UPLOAD_CERT", "2026-08-17", "C3", "I1", "2026-08-10", "PASS", "Lab"])
    assert t.applied_certs["I1"][-1].due_date == date(2026, 11, 10)


def test_interval_halving_has_a_floor_of_three_months():
    t = make_tracker([{"instrument_id": "I1", "calibration_interval_months": 6, "criticality": "B"}])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "LIMITED", "Lab"])
    t._upload_cert(2, ["UPLOAD_CERT", "2024-02-01", "C2", "I1", "2024-02-01", "LIMITED", "Lab"])
    assert t.instruments["I1"].current_interval == 3
    t._upload_cert(3, ["UPLOAD_CERT", "2024-03-01", "C3", "I1", "2024-03-01", "LIMITED", "Lab"])
    t._upload_cert(4, ["UPLOAD_CERT", "2024-04-01", "C4", "I1", "2024-04-01", "LIMITED", "Lab"])
    assert t.instruments["I1"].current_interval == 3  # max(floor(3/2),3) stays at the floor


# ---------------------------------------------------------------------------
# BR-06: due list (30-day window, sort order, negative days when overdue)
# ---------------------------------------------------------------------------

def test_due_list_includes_overdue_with_negative_days_and_excludes_failed():
    t = make_tracker([
        {"instrument_id": "I1", "calibration_interval_months": 12, "criticality": "B"},  # will be overdue
        {"instrument_id": "I2", "calibration_interval_months": 1, "criticality": "B"},    # FAILED -> excluded
    ])
    t._upload_cert(1, ["UPLOAD_CERT", "2023-01-01", "C1", "I1", "2023-01-01", "PASS", "Lab"])  # due 2024-01-01
    t._upload_cert(2, ["UPLOAD_CERT", "2024-01-01", "C2", "I2", "2024-01-01", "FAIL", "Lab"])
    t._status(["STATUS", "2024-01-20"])
    due_ids = {r["instrument_id"] for r in t.due_list_rows}
    assert "I1" in due_ids and "I2" not in due_ids
    row = next(r for r in t.due_list_rows if r["instrument_id"] == "I1")
    assert row["days_remaining"] == -19


def test_due_list_sorted_by_due_date_then_instrument_id():
    t = make_tracker([
        {"instrument_id": "I2", "calibration_interval_months": 1, "criticality": "B"},
        {"instrument_id": "I1", "calibration_interval_months": 1, "criticality": "B"},
    ])
    t._upload_cert(1, ["UPLOAD_CERT", "2024-01-01", "C1", "I1", "2024-01-01", "PASS", "Lab"])  # due 2024-02-01
    t._upload_cert(2, ["UPLOAD_CERT", "2024-01-01", "C2", "I2", "2024-01-01", "PASS", "Lab"])  # due 2024-02-01 too
    t._status(["STATUS", "2024-01-10"])
    assert [r["instrument_id"] for r in t.due_list_rows] == ["I1", "I2"]  # same due date -> ID order


# ---------------------------------------------------------------------------
# Full-pack smoke test: run the whole sample data pack end to end
# ---------------------------------------------------------------------------

def test_full_sample_pack_runs_and_matches_planted_scenarios(tmp_path):
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    t = CalibrationTracker()
    t.run_command_file(os.path.join(base, "commands.txt"), data_dir=base)

    # 76 certificate lines total, one is a duplicate
    outcomes = [r.outcome for r in t.cert_log]
    assert outcomes.count("DUPLICATE") == 1
    assert len(t.cert_log) == 76

    # 40 ISSUE commands processed
    assert len(t.issue_log) == 40

    # INS-028: cal 2025-08-31, 6-month interval -> due 2026-02-28 (Feb clamp)
    cert_028 = [c for c in t.cert_log if c.instrument_id == "INS-028" and c.outcome == "APPLIED"][-1]
    from engine import add_months as am
    assert am(date(2025, 8, 31), 6) == date(2026, 2, 28)

    # INS-008 interval shortened from 7 to 3 after two consecutive LIMITED
    assert t.instruments["INS-008"].current_interval == 3

    # job 28 (class A) refused as LIMITED, job 29 (class B) issued, for INS-008
    j28 = next(r for r in t.issue_log if r.job_id == "JOB-0028")
    j29 = next(r for r in t.issue_log if r.job_id == "JOB-0029")
    assert j28.result == "REFUSED" and j28.reason == "LIMITED"
    assert j29.result == "ISSUED"
