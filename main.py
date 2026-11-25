"""
ECE-052 Instrument Calibration Due-Date and Certificate Tracker
Team E006 - entry point.

Usage:
    python main.py [--data data] [--out output] [--commands data/commands.txt]

Reads instruments.csv (via the LOAD_INSTRUMENTS command) and commands.txt
from the data directory, runs every command in file order, and writes
state_table.csv, due_list.csv, issue_log.csv, cert_log.csv and error_log.csv to the
output directory.
"""
import argparse
import os
import sys

sys.path.insert(0, "src")
from engine import CalibrationTracker  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="ECE-052 calibration tracker")
    ap.add_argument("--data", default="data", help="directory holding instruments.csv / commands.txt")
    ap.add_argument("--commands", default=None, help="path to the command file (default: <data>/commands.txt)")
    ap.add_argument("--out", default="output", help="directory to write the output CSVs to")
    args = ap.parse_args()

    commands_path = args.commands or f"{args.data}/commands.txt"

    os.makedirs(args.out, exist_ok=True)
    tracker = CalibrationTracker()
    tracker.run_command_file(commands_path, data_dir=args.data)
    tracker.write_outputs(args.out)

    print(f"Processed {commands_path}")
    print(f"  instruments loaded : {len(tracker.instruments)}")
    print(f"  certificates seen  : {len(tracker.cert_log)}")
    print(f"  issue requests     : {len(tracker.issue_log)}")
    print(f"  STATUS snapshots   : {len(set(r['status_date'] for r in tracker.state_table_rows)) if tracker.state_table_rows else 0}")
    print(f"  rejected input lines: {len(tracker.error_log)} (see error_log.csv)")
    print(f"Outputs written to {args.out}/")


if __name__ == "__main__":
    main()
