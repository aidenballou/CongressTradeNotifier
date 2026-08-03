from pathlib import Path


def test_daily_runner_cron_is_every_15_minutes():
    workflow = Path(".github/workflows/daily-run-main.yml").read_text()
    assert 'cron: "11,26,41,56 * * * *"' in workflow
    assert "catches up" in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert 'python-version: "3.13"' in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "actions/cache/restore@v6" in workflow
    assert "actions/cache/save@v6" in workflow


def test_scheduler_watchdog_workflow_exists_and_checks_staleness():
    workflow_path = Path(".github/workflows/scheduler-watchdog.yml")
    assert workflow_path.exists()

    workflow = workflow_path.read_text()
    assert 'cron: "17 * * * *"' in workflow
    assert "Daily Main Runner appears stale" in workflow
    assert 'WARNING_MINUTES: "45"' in workflow
    assert 'FAILURE_MINUTES: "90"' in workflow
