"""Unit tests for scripts/run_pipeline.py. No cloud access: steps are replaced by a fake that returns exit codes.

Run:  uv run --extra dev pytest tests/test_run_pipeline.py -q
"""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_pipeline as rp  # noqa: E402


class Fake:
    """Returns scripted exit codes per step and records what was run."""

    def __init__(self, codes=None):
        self.codes, self.calls, self.sleeps = codes or {}, [], []

    def run_step(self, step):
        self.calls.append(step)
        script = self.codes.get(step, [0])
        return script[min(self.calls.count(step) - 1, len(script) - 1)]

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def test_steps_are_selected_in_pipeline_order():
    assert rp.select_steps() == rp.STEPS
    assert rp.select_steps(start="features") == ["features", "marts", "verify", "analysis"]
    assert rp.select_steps(skip=["upload", "analysis"]) == ["clean", "quality", "features", "marts", "verify"]
    assert rp.select_steps(only=["marts", "clean"]) == ["clean", "marts"]  # order is fixed, not the order typed
    with pytest.raises(ValueError):
        rp.select_steps(only=["clean", "nonsense"])


def test_a_clean_run_goes_through_every_step_in_order():
    fake = Fake()
    code, results = rp.run_pipeline(rp.STEPS, fake.run_step, sleep=fake.sleep)
    assert code == 0 and fake.calls == rp.STEPS and all(r.status == "ok" for r in results)


def test_the_quality_gate_stops_the_run_and_is_never_retried():
    fake = Fake({"quality": [2]})
    code, results = rp.run_pipeline(rp.STEPS, fake.run_step, retries=3, sleep=fake.sleep)
    assert code == 2
    assert fake.calls == ["upload", "clean", "quality"]  # features and marts never ran
    assert [r.status for r in results] == ["ok", "ok", "blocked", "not run", "not run", "not run", "not run"]
    assert fake.sleeps == []  # bad data is not fixed by trying again


def test_a_crash_is_retried_with_a_growing_pause_then_succeeds():
    fake = Fake({"clean": [1, 1, 0]})
    code, results = rp.run_pipeline(["clean", "quality"], fake.run_step, retries=2, sleep=fake.sleep)
    assert code == 0 and fake.calls == ["clean", "clean", "clean", "quality"]
    assert fake.sleeps == [5, 15] and results[0].attempts == 3


def test_a_step_that_keeps_crashing_stops_the_run():
    fake = Fake({"marts": [1]})
    code, results = rp.run_pipeline(["features", "marts", "verify"], fake.run_step, retries=2, sleep=fake.sleep)
    assert code == 1 and fake.calls.count("marts") == 3
    assert [r.status for r in results] == ["ok", "failed", "not run"]


def test_alerts_are_logged_at_error_level(caplog):
    with caplog.at_level("ERROR"):
        rp.run_pipeline(["quality"], Fake({"quality": [2]}).run_step)
        rp.run_pipeline(["clean"], Fake({"clean": [1]}).run_step, retries=0)
    messages = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("critical data quality failure" in m for m in messages) and any("failed after 1 attempts" in m for m in messages)


def test_the_step_runner_runs_scripts_as_processes_and_handles_a_failed_upload():
    seen = []
    runner = lambda cmd, cwd: seen.append((cmd, cwd)) or subprocess.CompletedProcess(cmd, 2)  # noqa: E731
    run_step = rp.make_step_runner(upload=lambda: None, python="py", runner=runner)
    assert run_step("quality") == 2 and seen[0][0] == ["py", str(rp.SCRIPTS / "quality_checks.py")] and seen[0][1] == rp.ROOT
    assert run_step("verify") == 2 and seen[1][0][1].endswith("quality_checks.py")  # verify re-runs the same checks
    assert run_step("upload") == 0

    def broken():
        raise ConnectionError("no network")

    assert rp.make_step_runner(upload=broken, runner=runner)("upload") == 1


def test_every_step_has_a_description_and_a_script():
    assert set(rp.STEP_DESCRIPTION) == set(rp.STEPS)
    for step, script in rp.STEP_SCRIPT.items():
        assert (rp.SCRIPTS / script).exists(), f"{step} points at a missing script {script}"


def test_the_run_log_is_appended(tmp_path):
    results = [rp.StepResult("clean", "ok", 1, 3.21, 0), rp.StepResult("quality", "blocked", 1, 1.0, 2), rp.StepResult("marts", "not run")]
    path = rp.write_run_log(results, "abc123", tmp_path)
    rp.write_run_log(results[:1], "def456", tmp_path)
    rows = list(csv.DictReader(open(path)))
    assert len(rows) == 4 and rows[1]["status"] == "blocked" and rows[1]["exit_code"] == "2" and rows[2]["exit_code"] == ""
    assert rows[3]["run_id"] == "def456"


def test_the_plan_lists_every_selected_step():
    text = rp.plan_text(["clean", "marts"])
    assert "data_cleaning.py" in text and "build_marts.py" in text and "upload" not in text
