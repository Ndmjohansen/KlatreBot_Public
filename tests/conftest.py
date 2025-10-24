import pytest

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Add a clear, visible summary at the end of pytest runs so passing tests
    are not silently empty. This prints counts and a short list of test nodeids
    grouped by outcome (passed/failed/skipped/xfailed/xpassed).
    """
    tr = terminalreporter
    def _nodes_for(kind):
        return [getattr(x, "nodeid", str(x)) for x in tr.stats.get(kind, [])]

    passed = _nodes_for("passed")
    failed = _nodes_for("failed")
    skipped = _nodes_for("skipped")
    xfailed = _nodes_for("xfailed")
    xpassed = _nodes_for("xpassed")

    total = sum(len(lst) for lst in (passed, failed, skipped, xfailed, xpassed))
    tr.section("KlatreBot test summary", sep="-")
    tr.line(f"Total tests collected: {total}")
    tr.line(f"Passed: {len(passed)}")
    tr.line(f"Failed: {len(failed)}")
    tr.line(f"Skipped: {len(skipped)}")
    if xfailed:
        tr.line(f"XFailed (expected fail): {len(xfailed)}")
    if xpassed:
        tr.line(f"XPassed (unexpected pass): {len(xpassed)}")

    if passed:
        tr.section("Passed tests (short list)", sep=".")
        for p in passed:
            tr.line(f" - {p}")

    if failed:
        tr.section("Failed tests (details)", sep=".")
        for f in failed:
            tr.line(f" - {f}")
        tr.line("")  # spacing

    if skipped:
        tr.section("Skipped tests", sep=".")
        for s in skipped:
            # skipped entries are Report objects; try to show reason if available
            rep = next((r for r in tr.stats.get("skipped", []) if getattr(r, "nodeid", None) == s), None)
            tr.line(f" - {s}")

    tr.line("")
