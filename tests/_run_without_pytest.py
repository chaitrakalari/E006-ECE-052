"""
Sandbox-only helper: this container has no internet access, so pytest can't
be pip-installed here. This script runs the exact same test_*.py functions
with a tiny stdlib harness so we can verify the suite before submission.
On a normal machine, just run `pytest -v` instead - test_engine.py needs no
changes.
"""
import sys
import traceback
import test_engine as mod

tests = [name for name in dir(mod) if name.startswith("test_")]
passed, failed = 0, []
for name in tests:
    fn = getattr(mod, name)
    try:
        fn(None) if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount] else fn()
        passed += 1
        print(f"PASS  {name}")
    except Exception:
        failed.append(name)
        print(f"FAIL  {name}")
        traceback.print_exc()

print(f"\n{passed} passed, {len(failed)} failed out of {len(tests)}")
sys.exit(1 if failed else 0)
