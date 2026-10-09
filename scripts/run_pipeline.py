#!/usr/bin/env python3
"""run_pipeline.py

Run the whole pipeline in dependency order, with a quality gate, retries and a run log.

    upload    copy the raw files to Cloud Storage (only files that changed are uploaded)
    clean     data_cleaning.py: clean, mask and load the staging tables
    quality   quality_checks.py on staging. A CRITICAL failure stops the run here, so the marts are never refreshed
              from bad data
    features  feature_engineering.py: age band, income band, days past due, risk category
    marts     build_marts.py: fact table and the metric tables
    verify    quality_checks.py again, now including the personal-data scan of the marts
    analysis  analysis.py: charts and findings

Run from the project root (needs Application Default Credentials; unset GOOGLE_APPLICATION_CREDENTIALS first):
    uv run python scripts/run_pipeline.py --dry-run            # show the plan, run nothing
    uv run python scripts/run_pipeline.py                      # everything
    uv run python scripts/run_pipeline.py --from features      # resume after a fix
    uv run python scripts/run_pipeline.py --skip upload --skip analysis

Failure handling:
    * A step that crashes (exit code 1, for example a network error) is retried with a growing pause.
    * A critical data quality failure (exit code 2) is NOT retried: retrying cannot fix bad data. The run stops and an
      ALERT line is logged. In Cloud Run the ERROR level makes Cloud Monitoring email the data engineer.
    * Every step is recorded in logs/pipeline_runs.csv (run id, step, status, attempts, seconds).
    * Every step is safe to run again: loads replace whole tables and uploads skip identical files.

Exit codes: 0 success, 1 a step failed, 2 the data quality gate blocked the run.
"""
from __future__ import annotations

import argparse
import csv
import logging
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from utils.bq_client import upload_raw_files
from utils.config import load_config
from utils.logging_setup import setup_logging

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LOG = logging.getLogger("run_pipeline")

STEPS = ["upload", "clean", "quality", "features", "marts", "verify", "analysis"]
STEP_SCRIPT = {"clean": "data_cleaning.py", "quality": "quality_checks.py", "features": "feature_engineering.py",
               "marts": "build_marts.py", "verify": "quality_checks.py", "analysis": "analysis.py"}
STEP_DESCRIPTION = {
    "upload": "copy raw files to Cloud Storage (skips unchanged files)",
    "clean": "clean, mask and load the staging tables",
    "quality": "data quality gate on staging (critical failure stops the run)",
    "features": "build age band, income band, days past due and risk category",
    "marts": "build the fact table and the metric tables",
    "verify": "data quality checks again, including the personal-data scan of the marts",
    "analysis": "charts and findings",
}
GATE_EXIT_CODE = 2
BACKOFF_SECONDS = (5, 15, 45)


@dataclass
class StepResult:
    step: str
    status: str  # ok, failed, blocked, not run
    attempts: int = 0
    seconds: float = 0.0
    exit_code: int | None = None


def select_steps(only: list[str] | None = None, skip: list[str] | None = None, start: str | None = None) -> list[str]:
    """The steps to run, always in pipeline order."""
    for name in [*(only or []), *(skip or []), *([start] if start else [])]:
        if name not in STEPS:
            raise ValueError(f"Unknown step '{name}'. Steps are: {', '.join(STEPS)}")
    steps = list(only) if only else STEPS[STEPS.index(start):] if start else list(STEPS)
    return [s for s in STEPS if s in steps and s not in (skip or [])]


def execute_step(step: str, run_step, retries: int, sleep=time.sleep) -> StepResult:
    """Run one step. Crashes are retried with a growing pause. The quality gate exit code is never retried."""
    started = time.monotonic()
    attempts, code = 0, 1
    while True:
        attempts += 1
        code = run_step(step)
        if code == 0:
            return StepResult(step, "ok", attempts, time.monotonic() - started, 0)
        if code == GATE_EXIT_CODE:
            return StepResult(step, "blocked", attempts, time.monotonic() - started, code)
        if attempts > retries:
            return StepResult(step, "failed", attempts, time.monotonic() - started, code)
        pause = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        LOG.warning("Step '%s' failed (exit code %s), attempt %s of %s. Trying again in %ss.", step, code, attempts, retries + 1, pause)
        sleep(pause)


def run_pipeline(steps: list[str], run_step, retries: int = 2, sleep=time.sleep) -> tuple[int, list[StepResult]]:
    """Run the steps in order and stop at the first one that does not succeed."""
    results: list[StepResult] = []
    for i, step in enumerate(steps):
        LOG.info("=== Step %s of %s: %s (%s)", i + 1, len(steps), step, STEP_DESCRIPTION[step])
        result = execute_step(step, run_step, retries, sleep)
        results.append(result)
        LOG.info("Step '%s' finished: %s in %.1fs (%s attempt%s)", step, result.status, result.seconds, result.attempts, "" if result.attempts == 1 else "s")
        if result.status != "ok":
            results += [StepResult(s, "not run") for s in steps[i + 1:]]
            if result.status == "blocked":
                LOG.error("ALERT critical data quality failure at step '%s'. The run was stopped so the marts are not refreshed from bad data.", step)
                return 2, results
            LOG.error("ALERT pipeline step '%s' failed after %s attempts (exit code %s). Later steps were not run.", step, result.attempts, result.exit_code)
            return 1, results
    return 0, results


def write_run_log(results: list[StepResult], run_id: str, log_dir: Path) -> Path:
    """Append one row per step to logs/pipeline_runs.csv."""
    path = Path(log_dir) / "pipeline_runs.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(["run_id", "logged_at_utc", "step", "status", "attempts", "seconds", "exit_code"])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in results:
            writer.writerow([run_id, now, r.step, r.status, r.attempts, round(r.seconds, 1), "" if r.exit_code is None else r.exit_code])
    return path


def plan_text(steps: list[str]) -> str:
    lines = ["Pipeline plan:"]
    for i, s in enumerate(steps, 1):
        command = f"scripts/{STEP_SCRIPT[s]}" if s in STEP_SCRIPT else "upload to Cloud Storage"
        lines.append(f"  {i}. {s:<9} {command:<30} {STEP_DESCRIPTION[s]}")
    return "\n".join(lines)


def make_step_runner(upload, python: str = sys.executable, runner=subprocess.run):
    """Build the function that runs one step and returns an exit code. Steps are separate processes, so each
    script keeps its own command line, log file and exit code."""
    def run_step(step: str) -> int:
        if step == "upload":
            try:
                upload()
                return 0
            except Exception:  # noqa: BLE001 - any upload problem is a failed step, logged with its traceback
                LOG.exception("Upload failed")
                return 1
        return runner([python, str(SCRIPTS / STEP_SCRIPT[step])], cwd=ROOT).returncode
    return run_step


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    ap.add_argument("--from", dest="start", choices=STEPS, help="start at this step (resume after a fix)")
    ap.add_argument("--only", action="append", choices=STEPS, help="run only this step (repeatable)")
    ap.add_argument("--skip", action="append", choices=STEPS, help="skip this step (repeatable)")
    ap.add_argument("--retries", type=int, default=2, help="extra attempts for a step that crashes (default 2)")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--ingest-date", default=date.today().isoformat(), help="date used in the Cloud Storage folder name")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    setup_logging("run_pipeline", args.log_dir)
    steps = select_steps(args.only, args.skip, args.start)
    print(plan_text(steps))
    if args.dry_run:
        return 0

    cfg = load_config(args.config)

    def upload() -> None:
        from google.cloud import storage

        bucket = storage.Client(project=cfg["gcp"]["project_id"]).bucket(cfg["gcp"]["raw_bucket"])
        upload_raw_files(bucket, args.raw_dir, f"raw/ingest_date={args.ingest_date}")

    run_id = uuid.uuid4().hex[:8]
    LOG.info("Pipeline run %s started", run_id)
    code, results = run_pipeline(steps, make_step_runner(upload), retries=args.retries)
    write_run_log(results, run_id, args.log_dir)
    print(f"\nRun {run_id}\n" + "\n".join(f"  {r.step:<9} {r.status:<8} {r.seconds:6.1f}s  attempts={r.attempts}" for r in results))
    print({0: "\nPipeline finished.", 1: "\nPipeline FAILED. See the ALERT line above.", 2: "\nBLOCKED by the data quality gate. Fix the data, then resume with --from quality."}[code])
    return code


if __name__ == "__main__":
    sys.exit(main())