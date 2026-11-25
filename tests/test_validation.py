"""
Validation / robustness tests (BR-08 .. BR-11).
A bad input line must be rejected with a clear code in error_log and must
never crash the run or change state.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine import CalibrationTracker  # noqa: E402

HEADER = "instrument_id,instrument_type,description,serial_no,calibration_interval_months,criticality,location\n"


def run(instrument_rows, command_lines):
    """Write temp data files, run the engine, return the tracker."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "instruments.csv"), "w", newline="") as f:
        f.write(HEADER + "".join(r + "\n" for r in instrument_rows))
    with open(os.path.join(d, "commands.txt"), "w") as f:
        f.write("LOAD_INSTRUMENTS|instruments.csv\n" + "".join(c + "\n" for c in command_lines))
    t = CalibrationTracker()
    t.run_command_file(os.path.join(d, "commands.txt"), data_dir=d)
    return t


GOOD = "I1,DMM,d,SN1,12,B,Lab"


def codes(t):
    return [e.code for e in t.error_log]


# ---- BR-08: instrument master ------------------------------------------------

def test_br08_bad_interval_rejected():
    t = run([GOOD, "I2,DMM,d,SN2,abc,B,Lab", "I3,DMM,d,SN3,0,B,Lab"], [])
    assert list(t.instruments) == ["I1"]
    assert codes(t) == ["BAD_INTERVAL", "BAD_INTERVAL"]


def test_br08_bad_criticality_rejected():
    t = run([GOOD, "I2,DMM,d,SN2,12,C,Lab"], [])
    assert list(t.instruments) == ["I1"]
    assert codes(t) == ["BAD_CRITICALITY"]


def test_br08_duplicate_instrument_id_rejected_first_one_kept():
    t = run([GOOD, "I1,LCR,other,SN9,6,A,Lab2"], [])
    assert t.instruments["I1"].calibration_interval_months == 12
    assert codes(t) == ["DUPLICATE_INSTRUMENT"]


def test_br08_missing_id_rejected():
    t = run([",DMM,d,SN2,12,B,Lab"], [])
    assert t.instruments == {}
    assert codes(t) == ["MISSING_ID"]


# ---- BR-09: UPLOAD_CERT --------------------------------------------------------

def test_br09_unknown_instrument_rejected_and_not_stored():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|NOPE|2024-01-01|PASS|lab"])
    assert codes(t) == ["UNKNOWN_INSTRUMENT"]
    assert t.cert_log == [] and t.seen_cert_numbers == set()


def test_br09_bad_result_rejected():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|MAYBE|lab"])
    assert codes(t) == ["BAD_RESULT"]
    assert t.applied_certs["I1"] == []


def test_br09_bad_date_rejected():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|I1|2024-02-30|PASS|lab",
                     "UPLOAD_CERT|2024-01-02|C2|I1|not-a-date|PASS|lab"])
    assert codes(t) == ["BAD_DATE", "BAD_DATE"]


def test_br09_wrong_field_count_rejected():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|PASS"])
    assert codes(t) == ["BAD_FIELD_COUNT"]


def test_br09_empty_cert_number_rejected():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02||I1|2024-01-01|PASS|lab"])
    assert codes(t) == ["MISSING_CERT_NO"]


def test_br09_rejected_cert_number_can_be_reused_after_fix():
    # a rejected line must not "burn" the cert number
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|MAYBE|lab",
                     "UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|PASS|lab"])
    assert [c.outcome for c in t.cert_log] == ["APPLIED"]


def test_br09_lowercase_result_is_normalised():
    t = run([GOOD], ["UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|pass|lab"])
    assert t.error_log == [] and t.applied_certs["I1"][0].result == "PASS"


# ---- BR-10: ISSUE ---------------------------------------------------------------

def test_br10_unknown_instrument_rejected():
    t = run([GOOD], ["ISSUE|2024-01-01|J1|NOPE|A"])
    assert codes(t) == ["UNKNOWN_INSTRUMENT"] and t.issue_log == []


def test_br10_bad_required_class_rejected():
    t = run([GOOD], ["ISSUE|2024-01-01|J1|I1|C"])
    assert codes(t) == ["BAD_CLASS"] and t.issue_log == []


def test_br10_bad_date_and_field_count_rejected():
    t = run([GOOD], ["ISSUE|31-01-2024|J1|I1|A", "ISSUE|2024-01-01|J1|I1"])
    assert codes(t) == ["BAD_DATE", "BAD_FIELD_COUNT"]


# ---- BR-11: command-file robustness ---------------------------------------------

def test_br11_unknown_command_logged_and_run_continues():
    t = run([GOOD], ["FLY_AWAY|1", "UPLOAD_CERT|2024-01-02|C1|I1|2024-01-01|PASS|lab"])
    assert codes(t) == ["UNKNOWN_COMMAND"]
    assert len(t.applied_certs["I1"]) == 1  # later line still processed


def test_br11_bad_status_date_logged_no_rows_added():
    t = run([GOOD], ["STATUS|2024-13-01", "STATUS"])
    assert codes(t) == ["BAD_DATE", "BAD_FIELD_COUNT"]
    assert t.state_table_rows == []


def test_br11_missing_command_file_does_not_crash():
    t = CalibrationTracker()
    t.run_command_file("/no/such/file.txt")
    assert codes(t) == ["FILE_NOT_FOUND"]


def test_br11_error_line_numbers_match_physical_lines():
    # line 1 is LOAD_INSTRUMENTS, so the first command below is physical line 2
    t = run([GOOD], ["# comment", "ISSUE|2024-01-01|J1|NOPE|A"])
    assert t.error_log[0].line_no == 3


def test_br11_error_log_csv_written():
    t = run([GOOD], ["ISSUE|2024-01-01|J1|NOPE|A"])
    d = tempfile.mkdtemp()
    t.write_outputs(d)
    text = open(os.path.join(d, "error_log.csv")).read()
    assert "UNKNOWN_INSTRUMENT" in text and text.startswith("line_no,command,code,message")
