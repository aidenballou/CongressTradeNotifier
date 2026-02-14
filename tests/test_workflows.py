from pathlib import Path


def test_daily_runner_cron_is_every_15_minutes():
    workflow = Path(".github/workflows/daily-run-main.yml").read_text()
    assert 'cron: "*/15 * * * *"' in workflow


def test_scheduler_watchdog_workflow_exists_and_checks_45_minute_staleness():
    workflow_path = Path(".github/workflows/scheduler-watchdog.yml")
    assert workflow_path.exists()

    workflow = workflow_path.read_text()
    assert 'cron: "7 * * * *"' in workflow
    assert "Daily Main Runner appears stale" in workflow
    assert "age_minutes > 45" in workflow
