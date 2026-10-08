# Deployment runbook (optional, not performed)

The project runs from a laptop with `scripts/run_pipeline.py`. This page describes how it would run unattended in Google Cloud, and what has to change. Nothing here has been deployed.

## What would run

A Cloud Run job executes `run_pipeline.py` once a day. Cloud Scheduler starts the job. A log-based alert emails the data engineer when the job logs an `ERROR` (a critical data quality failure or a crashed step).

```
Cloud Scheduler (daily) -> Cloud Run job -> run_pipeline.py -> BigQuery, Cloud Storage, Secret Manager
                                                  |
                                           ERROR log line -> Cloud Monitoring alert -> email
```

## Changes needed before deploying

1. **Read the raw files from Cloud Storage.** The cleaning step reads `data/raw`. In the job, the first step should download the newest `raw/ingest_date=.../` folder into a temporary directory and point `--raw-dir` at it. The upload step is then run by whoever delivers new files, not by the job.
2. **Container image.** Cloud Run runs a container. This project does not include a Dockerfile and this page gives no build commands on purpose: building and pushing images from a home connection has been costly in mobile data. If you decide to deploy, build the image remotely in Cloud Build, check the size of what will be uploaded first, and ask for that step when you are ready.
3. **No credentials in the image.** The job uses a service account, not a key file. No `.env` file and no key file is ever needed.

## One-time setup (these commands do not involve images)

Replace the project id if yours differs.

```bash
PROJECT=abc-credit-portfolio-rg
REGION=us-central1
SA_NAME=abc-pipeline
SA=$SA_NAME@$PROJECT.iam.gserviceaccount.com

# 1. A service account for the job
gcloud iam service-accounts create $SA_NAME --display-name="ABC pipeline runner" --project=$PROJECT

# 2. Give it only what it needs
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.dataEditor"
gcloud storage buckets add-iam-policy-binding gs://abc-credit-portfolio-rg-raw --member="serviceAccount:$SA" --role="roles/storage.objectUser"
gcloud secrets add-iam-policy-binding masking-key --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --project=$PROJECT
```

The secret binding is on the one secret only, not on the project.

## After the Cloud Run job exists

Call the job `abc-pipeline`. This starts it every day at 06:00 East Africa Time (03:00 UTC):

```bash
gcloud scheduler jobs create http abc-pipeline-daily \
  --location=$REGION --schedule="0 3 * * *" --time-zone="UTC" \
  --uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/abc-pipeline:run" \
  --http-method=POST --oauth-service-account-email=$SA
```

The scheduler's service account also needs permission to run the job (the `roles/run.invoker` role on the job).

## Alerts

In the Cloud console, under Logging, create a log-based alert:

- **Filter:** `resource.type="cloud_run_job" AND severity>=ERROR`
- **Notification channel:** email to the data engineer
- **Escalation:** the critical path in `pipeline_design/architecture.md` (unresolved after 4 hours goes to the engineering lead)

## Budget alert

In the console, under Billing, then Budgets and alerts, set a budget of a few dollars with alerts at 50% and 100%. Do this before running anything on a schedule.

## Cost

At this size the project is expected to stay inside the free tiers (Cloud Run jobs, the first Cloud Scheduler jobs on a billing account, and BigQuery's monthly free query allowance). Prices change, so check the pricing pages at deployment time. Container images stored in Artifact Registry and builds in Cloud Build are billed separately.

## Checking it works

1. Run the job once by hand from the console and open its logs.
2. Confirm a new row per check in `abc_staging.dq_results`.
3. Break something on purpose in a test copy (for example, remove an expected snapshot) and confirm the alert email arrives.
