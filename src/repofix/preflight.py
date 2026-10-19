"""Validate reproducibility before any paid model request."""
from .evaluation import run_checks, regression_readiness
from .workspace import snapshot


def baseline_reason(result):
    if result['timed_out']:
        return 'baseline_timeout'
    checks = result.get('checks', {})
    if checks.get('collection_errors'):
        return 'baseline_collection_error'
    ids = checks.get('test_ids', [])
    if not ids or checks.get('tests_run') != len(ids):
        return 'baseline_invalid_suite'
    if checks['successful'] or result['exit_code'] == 0:
        return 'baseline_not_failing'
    return None


def prepare_baseline(source, verification, folder, runner_factory, regression_tests=None):
    snapshot(source, folder)
    result = run_checks(runner_factory(folder, verification=verification))
    reason = baseline_reason(result)
    report={'ready': reason is None,'reason': reason or 'reproducible_failure','baseline_result':result}
    if reason is None:
        regression=run_checks(runner_factory(folder),regression=True,selectors=regression_tests)
        report['regression_baseline_result']=regression
        failure=regression_readiness(regression)
        if failure:
            report.update(ready=False,reason=failure)
    return report
