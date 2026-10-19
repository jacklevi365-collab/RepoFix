"""Controller-owned unittest verification, independent from agent messages."""

import json
import shlex

# -I imports the harness's stdlib before adding the untrusted repository path.
HARNESS = r"""
import json
import sys
import unittest
import traceback
from pathlib import Path
sys.path.append('/workspace')
try:
    config=json.loads(sys.argv[1]) if len(sys.argv)>1 else {}
    if config.get('regression'):
        names=config.get('selectors')
        if names:
            suite=unittest.defaultTestLoader.loadTestsFromNames(names)
        else:
            start='/workspace/tests' if Path('/workspace/tests').is_dir() else '/workspace'
            suite=unittest.defaultTestLoader.discover(start)
    else:
        suite=unittest.defaultTestLoader.discover('/verification')
    def flatten(node):
        for item in node:
            if isinstance(item, unittest.TestSuite):
                yield from flatten(item)
            else:
                yield item
    cases = list(flatten(suite))
    ids = [case.id() for case in cases]
    collection_errors = list(unittest.defaultTestLoader.errors)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    report = {
        'test_ids': ids, 'tests_run': result.testsRun,
        'failures': [case.id() for case, _ in result.failures],
        'errors': [case.id() for case, _ in result.errors],
        'skipped': [case.id() for case, _ in result.skipped],
        'expected_failures': [case.id() for case, _ in result.expectedFailures],
        'unexpected_successes': [case.id() for case in result.unexpectedSuccesses],
        'collection_errors': collection_errors, 'successful': result.wasSuccessful(),
    }
except Exception as exc:
    report = {'collection_errors': [traceback.format_exc()]}
print('\nREPOFIX_RESULT=' + json.dumps(report), flush=True)
sys.exit(0 if report.get('successful') else 1)
"""
COMMAND = "python -I -B -X pycache_prefix=/tmp/repofix-cache -c " + shlex.quote(HARNESS)


def run_checks(runner, regression=False, selectors=None):
    config = {"regression": regression, "selectors": selectors}
    result = runner.run(COMMAND + " " + shlex.quote(json.dumps(config)), timeout=60)
    # The bounded process output retains the tail containing the final record.
    for line in reversed(result["output"].splitlines()):
        if line.startswith("REPOFIX_RESULT="):
            try:
                summary = json.loads(line.removeprefix("REPOFIX_RESULT="))
                if isinstance(summary, dict):
                    result["checks"] = summary
            except json.JSONDecodeError:
                pass
            break
    return result


def assess(baseline, candidate):
    """Return explicit failure reasons instead of inferring success from exit 0."""
    for label, result in (("baseline", baseline), ("candidate", candidate)):
        if result["timed_out"]:
            return {"status": "failed", "reason": label + "_timeout"}
        checks = result.get("checks", {})
        if checks.get("collection_errors"):
            return {"status": "failed", "reason": label + "_collection_error"}
        if not checks.get("test_ids") or checks.get("tests_run") != len(checks["test_ids"]):
            return {"status": "failed", "reason": label + "_invalid_suite"}
    original, fixed = baseline["checks"], candidate["checks"]
    if original["successful"] or baseline["exit_code"] == 0:
        return {"status": "failed", "reason": "baseline_not_failing"}
    if sorted(original["test_ids"]) != sorted(fixed["test_ids"]):
        return {"status": "failed", "reason": "test_set_changed"}
    if set(fixed["skipped"]) - set(original["skipped"]):
        return {"status": "failed", "reason": "newly_skipped_tests"}
    if set(fixed["expected_failures"]) - set(original["expected_failures"]):
        return {"status": "failed", "reason": "new_expected_failures"}
    if not fixed["successful"] or candidate["exit_code"] != 0:
        return {"status": "failed", "reason": "candidate_tests_failed"}
    return {"status": "passed", "reason": "independent_tests_passed"}


def regression_readiness(result):
    if result["timed_out"]:
        return "regression_timeout"
    checks = result.get("checks")
    if not checks or checks.get("collection_errors"):
        return "regression_collection_error"
    if checks.get("tests_run") != len(checks.get("test_ids", [])):
        return "regression_invalid_suite"
    return None


def assess_regression(baseline, candidate):
    for label, result in (("baseline", baseline), ("candidate", candidate)):
        reason = regression_readiness(result)
        if reason:
            return {"status": "failed", "reason": label + "_" + reason}
    original, fixed = baseline["checks"], candidate["checks"]
    ids = set(original["test_ids"])
    if not ids:
        return {"status": "not_available", "reason": "no_original_tests"}
    if not ids.issubset(fixed["test_ids"]):
        return {"status": "failed", "reason": "original_tests_missing"}
    if set(fixed["skipped"]) - set(original["skipped"]):
        return {"status": "failed", "reason": "newly_skipped_regressions"}
    if set(fixed["expected_failures"]) - set(original["expected_failures"]):
        return {"status": "failed", "reason": "new_expected_regression_failures"}
    before = set(
        original.get("failures", [])
        + original.get("errors", [])
        + original.get("unexpected_successes", [])
    )
    after = set(
        fixed.get("failures", []) + fixed.get("errors", []) + fixed.get("unexpected_successes", [])
    )
    introduced = sorted(after - before)
    if introduced:
        return {
            "status": "failed",
            "reason": "new_regression_failures",
            "new_failures": introduced,
        }
    return {
        "status": "passed",
        "reason": "no_new_failures",
        "remaining_known_failures": sorted(after),
    }
