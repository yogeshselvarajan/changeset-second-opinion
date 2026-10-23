# Cloud native reference architecture (design note)

Status: design and an unvalidated-in-AWS template. Nothing here has been deployed. Written 2026-10-20 for the maintainers. The user-facing comparison is `site/src/content/docs/self-host/deployment-options.mdx`. The single host in `infra/cloudformation/cso-single-host.yaml` stays the supported default and does not change.

Template: `cso-cloud-native.yaml` (CloudFormation, because the project's existing infra is CloudFormation). It passes `cfn-lint` 1.52.1 with no findings. It has not been run through `aws cloudformation validate-template`, change sets or a deployment, so resource behavior (VPC origin, capacity provider scale from zero, Cloud Map records) is unproven.

## Goals and limits

- A small community can run it with no host to patch, a managed edge and a service-based deploy.
- Invariants hold: no OpenStreetMap writes, nothing hidden, the Decider model server binds `127.0.0.1` only, no secrets in code, logs or the web bundle.
- SQLite stays the database. One writer, always.
- It is not cheaper than the single host at small scale. It buys operations, not savings.

## Diagram

```
                          Internet
                             |
                     CloudFront (TLS, one distribution)
                    /        |                 \
   /docs/*, app shell     /api/*, /healthz,     (viewer request function:
   S3 site bucket          /readyz, manifest     docs index files, app shell)
   (OAC, private)               |
                       VPC origin (private path)
                                |
                  internal ALB  (SG: CloudFront prefix list, port 80)
                                |  health check GET /healthz
                                v
        +---------------- Fargate task (ARM, 1 task, old ends first) ----------------+
        | restore (init)  -> migrate (init) -> replicate (Litestream) -> api + worker   |
        |   shared task storage /data/cso.db  <--- 15 s replication --->  S3 backup     |
        +-------------------------------+----------------------------------------------+
                  |                      |                         |
        task role: Bedrock          GET only: api.openstreetmap.org   Cloud Map
        InvokeModel (Haiku 4.5)     maproulette.org                   decider.<stage>.cso.internal:8099
                                                                         |
                          SG: 8099 from the API task SG only             v
        +---- ECS service on EC2 GPU capacity (desired 0, scheduled or started on demand) ----+
        | proxy container :8099 (bearer token) --> decider container 127.0.0.1:8098 (GPU)    |
        +-----------------------------------------------------------------------------------+
           ASG min 0 / max 1 (g6.xlarge), ECS capacity provider with managed scaling

   Secrets Manager: OSM client secret, Decider token    CloudWatch Logs /cso/<stage>/*, alarms -> SNS
```

## Services and why

| Concern | Choice | Reason and alternatives |
| --- | --- | --- |
| API and worker | ECS on Fargate, ARM, one task, `MinimumHealthyPercent 0`, `MaximumPercent 100` | One SQLite writer. A deploy ends the old task first (about a minute of downtime). App Runner is closed to new customers (verified in its docs); ECS Express Mode is the stated successor but adds an ALB per group and gives no control of the single-writer deployment settings, so plain ECS is used. |
| Database durability | Task ephemeral storage plus Litestream restore and replicate to a versioned S3 bucket | Service-managed ECS EBS volumes are deleted when a service task ends (verified in the ECS guide). EFS is unsafe for SQLite WAL (SQLite docs). The restore init container uses `-if-db-not-exists -if-replica-exists`. |
| Web app and docs | S3 (private, OAC) behind CloudFront | Replaces the static part of Caddy. A CloudFront Function rewrites folder paths and routes client routes to `/_shell.html`. |
| API path | CloudFront behavior with caching disabled to an internal ALB through a VPC origin | The ALB is not reachable from the internet. The prefix list `com.amazonaws.global.cloudfront.origin-facing` is on the ALB security group (verified as supported). |
| Edge limits | Not in the template yet | Caddy's 10 requests per second per client and the 64 KB body limits need AWS WAF (web ACL about 5 per month plus a rate rule) or an application setting. See code changes. |
| Secrets | Secrets Manager, injected by the task definition | Two secrets at 0.40 each. SSM Parameter Store SecureString is the cheaper alternative if you want to avoid the fee. |
| Bedrock | Task role, `bedrock:InvokeModel` on the Haiku 4.5 profile and foundation model ARNs only | Same two ARNs as the single host. No key anywhere. |
| Decider | ECS on EC2 GPU, ASG min 0, capacity provider with managed scaling, desired count 0 | Fargate has no GPU. Scheduled actions (optional cron parameters) or `aws ecs update-service --desired-count 1` start it. |
| Logs | CloudWatch Logs, 14 days, `/cso/<stage>/app` and `/decider` | Ingest is 0.50 per GB. |
| Alarms | Task not running, no healthy target, 5xx count | One SNS topic to `AlertEmail`. |

Alternatives costed on the docs page: hosted Decider (needs client code), CPU Decider on Fargate, SageMaker asynchronous inference (`ml.g6.xlarge` 1.1267 per hour, scales to zero, needs a `/invocations` and `/ping` adapter and a client change to the asynchronous call style), and a Lambda container (experimental, unmeasured).

## IAM roles

| Role | Trusted by | Permissions |
| --- | --- | --- |
| `ExecutionRole` | `ecs-tasks.amazonaws.com` (source account condition) | `AmazonECSTaskExecutionRolePolicy`, `secretsmanager:GetSecretValue` on the two secrets |
| `ApiTaskRole` | `ecs-tasks.amazonaws.com` (source account condition) | `bedrock:InvokeModel` on two ARNs; the backup bucket (list, get, put, delete objects) |
| `DeciderInstanceRole` | `ec2.amazonaws.com` | `AmazonEC2ContainerServiceforEC2Role`, `AmazonSSMManagedInstanceCore` |

Nothing has `s3:*`, `bedrock:*` or write access to anything outside its own bucket. No OpenStreetMap credential beyond the `read_prefs` sign-in app exists.

## Networking

- One VPC with an internet gateway and at least two subnets in two Availability Zones (parameters).
- ALB: `internal`, security group allows port 80 from the CloudFront prefix list only. HTTP between CloudFront and the ALB stays on the AWS private path of the VPC origin.
- API task: port 8000 from the ALB security group only. Outbound open (OpenStreetMap, MapRoulette, the token endpoint, Bedrock, S3). Default `AssignPublicIp ENABLED` avoids a NAT gateway (0.045 per hour plus 0.045 per GB, about 33 per month). Set `DISABLED` with NAT or VPC endpoints if policy needs it.
- Decider: port 8099 from the API security group only, behind a proxy container. The model server stays on `127.0.0.1:8098` inside the task (an `awsvpc` task shares one network namespace across containers, the same trick compose uses).

## Cost (US East N. Virginia, 730 hours, checked 2026-10-20)

Assumptions: small is 30 analyses and 10 drafts per day with the Decider awake 60 hours; medium is 200 and 100 per day, 220 hours; busy is 1,000 and 300 per day, 730 hours. A draft is 2,500 input and 300 output tokens at 1.10 and 5.50 US dollars per million (Haiku 4.5, US profile).

| Line | Small | Medium | Busy |
| --- | --- | --- | --- |
| Fargate task (ARM: 0.5 vCPU 2 GiB, 1 vCPU 2 GiB, 2 vCPU 4 GiB) | 17.02 | 28.84 | 57.67 |
| Internal ALB (16.43 plus 1, 1 and 3 capacity units) | 22.27 | 22.27 | 33.95 |
| Task public IPv4 | 3.65 | 3.65 | 3.65 |
| CloudFront and site S3 (assumed) | 1.00 | 1.00 | 5.00 |
| Edge firewall (assumed) | 6.50 | 7.00 | 10.00 |
| Secrets Manager (2), private DNS zone | 1.30 | 1.30 | 1.30 |
| Logs and alarms (assumed volume) | 3.00 | 4.00 | 8.00 |
| ECR (8 GB) and Litestream S3 | 1.30 | 1.30 | 1.30 |
| **Fixed subtotal** | **56.04** | **69.36** | **120.87** |
| GPU Decider (`g6.xlarge` 0.8048 per hour, plus 100 GiB gp3 while awake) | 48.95 | 179.47 | 595.50 |
| Bedrock drafts | 1.32 | 13.20 | 39.60 |
| **Total with scale-to-zero GPU** | **106.31** | **262.03** | **755.97** |
| Total with hosted Decider (price unknown, 0 assumed) | 57.36 | 82.56 | 160.47 |
| Total with CPU Decider on Fargate (8 vCPU, 16 GiB x86, 0.395 per hour) | 81.06 | 169.45 | 448.79 |
| Total with SageMaker asynchronous (1.1267 per hour) | 124.96 | 330.46 | 982.97 |
| Total with Lambda container (experimental, price from memory) | 58.86 | 92.56 | 210.47 |

Single host for comparison, same assumptions: GPU 66, 207, 644; CPU (`c7i.2xlarge`) 39, 108, 317.

Later database add-ons: RDS PostgreSQL `db.t4g.micro` plus 20 GB 13.98; `db.t4g.small` plus 50 GB 29.11; `db.t4g.medium` Multi-AZ 94.17 for the instance (storage not priced); Aurora Serverless v2 at 0.5 capacity units about 44.80. Aurora auto-pause to zero is documented, but the polling worker would keep it awake.

Verified from the AWS Price List API: EC2 (`g6.xlarge`, `g5.xlarge`, `c7i.2xlarge`), Fargate (x86 and ARM, vCPU, memory, storage), ALB, NAT, public IPv4, EBS gp3 and snapshots, S3, EFS, ECR, Secrets Manager, CloudWatch alarms and logs, RDS, Aurora, SageMaker async `ml.g6.xlarge`, Bedrock Haiku 4.5, Route 53 zone. Not verified: Lambda price, CloudFront free tier, WAF rate rule fee, Cloud Map, ALB capacity units for real traffic, the hosted Decider (price, limits, schema), cold start times.

## Operating it

1. Build and push the images (`backend` for arm64, `decider` for amd64, a proxy image, see below). Deploy the stack with your parameter values. Look up the prefix list id first: `aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing`.
2. If you set `OsmClientId`, put the real secret in the `OsmClientSecret` secret, then replace the service tasks.
3. Build the web app with the public origin and the docs site, upload `web/dist` and `site/dist` to the site bucket with long `Cache-Control` on hashed files, then create a CloudFront invalidation for the shell.
4. Wake the Decider before a work session: `aws ecs update-service --cluster cso-<stage> --service cso-<stage>-decider --desired-count 1`, or set the cron parameters.

## Code changes needed (not done)

Shared contracts change only through the integration owner.

### Database

The code is closer to Postgres than the docs imply, but unproven.

- Present: `psycopg[binary,pool]` is a dependency; `persistence/db.py` accepts any async URL (use `postgresql+psycopg://`); JSON columns use JSONB on Postgres; `persistence/repos/jobs_repo.py` claims with `FOR UPDATE SKIP LOCKED`; `test_postgres_ddl_renders_offline` proves the DDL.
- Missing: the live Postgres migration test is skipped without `testcontainers` and Docker, and the Postgres CI job was cut from the plan. Run the whole suite on Postgres 17 first, especially `outcomes_repo` (its version bump relies on first-write locking) and the reaper.
- Add: pool settings (`pool_pre_ping`, size); a way to supply the URL from a secret (the whole URL, or parts plus IAM auth); a revoke of `UPDATE` and `DELETE` on the immutable tables for the app role (the guard comment already asks for it); a `cso db copy` command that moves a SQLite file into Postgres in table order, with row counts checked; the matching section in `backup-upgrade-migrate` (RDS snapshots replace Litestream).
- Only after that: more than one API task, and a separate worker task (`CSO_JOBS_WORKER_ENABLED=false` plus `cso worker`).

### Hosted Decider mode

The client (`adapters/decider/client.py`) posts `/v1/systemone` and calls `GET /health` before each request. It has no auth.

- Settings: a mode (`local`, `hosted`), `CSO_DECIDER_API_KEY` as `SecretStr`, and `https` allowed in `CSO_DECIDER_URL`.
- Client: add `Authorization: Bearer`; map the request and response to `POST /v1/decide` once its schema is documented (not known to us); make the pre-call health check optional; keep strict validation so a bad answer is never a default.
- Readiness probe: use the hosted service's own health route, or skip it and report `unknown`.
- Docs and privacy: add the host to the outbound table, and say that evidence text is sent to a third party. Evidence is public OpenStreetMap data, but reviewers should be told.
- Same key support serves the proxy in the template (`CSO_DECIDER_TOKEN`), which the current client ignores.

### A Decider on another host

- Invariant 7 says the Decider binds `127.0.0.1` only. The template keeps that (model server on loopback, proxy in the same task) but a maintainer decision is needed that an authenticated proxy on the task address is acceptable. Write the proxy image (about 30 lines of nginx or Caddy config) and its test.
- Scale to zero: a Decider that is asleep has to read as "waiting", not "unavailable". Today `DeciderUnavailable` leads to the Rules only lane. Add a retry-later state with backoff in the job, and optionally let the API call `ecs:UpdateService` (one added statement on the task role) when a job is queued and the Decider is down. `jobs_repo.py` and `worker.py` have uncommitted edits from another agent, so re-read them before you design this.

### Health checks

- ALB and container checks use `/healthz` (exists, no dependencies). Keep `/readyz` (needs the database at head and, in live mode, the Decider) for dashboards only; the template alarms do not use it.
- Add a startup grace: the task needs about 30 seconds after Litestream restore and migration.

### Graceful shutdown

- The embedded worker's shutdown (`jobs/runtime.py`) waits 10 seconds, then cancels. Job leases are 300 seconds, so an interrupted job waits up to five minutes. On SIGTERM, release leases at once (`release_for_retry`) before cancelling.
- ECS sends SIGTERM and waits `StopTimeout` (60 seconds for the API in the template; check the Fargate maximum before raising it). Confirm uvicorn drains in-flight requests inside that time and that the connection pool closes so the WAL is checkpointed.
- Container order is restore, migrate, replicate, api. ECS ends them in reverse, so Litestream makes a final sync after the API ends. Test a kill during a write.

### Client address and edge limits

- `CSO_TRUST_PROXY` takes the rightmost `X-Forwarded-For` hop. Behind CloudFront and an ALB that hop is not the visitor. Add a setting that reads `CloudFront-Viewer-Address` (the template forwards it) or a hop count, or the per-address limits and the login lockout share one bucket.
- Move Caddy's request rate limits and body-size limits to AWS WAF, or enforce them in the app, and add them to the template.
- Response headers and the two content security policies are in CloudFront response headers policies already. Keep them in sync with `infra/caddy/Caddyfile`.

### Smaller items

- `/metrics` is loopback only, so nothing can scrape it in Fargate. Send the counters as CloudWatch embedded metric format lines, or drop the endpoint in this layout.
- The backend image default command binds `127.0.0.1`; the template overrides it with `--host 0.0.0.0`. Build and test an arm64 image (wheels for every dependency).
- The written pages the build produces (for example `/about`) need to be listed in the CloudFront Function (`written = []`).
- A budget alert resource and a Bedrock spend alarm, matching the single host template.
- Decide where the ECS-optimized GPU AMI parameter name is confirmed (`/aws/service/ecs/optimized-ami/amazon-linux-2023/gpu/recommended/image_id` in the template was not re-checked).

## Safe SQLite rules (summary)

One writer task, ever. Not on EFS or any network file system. Do not rely on service-managed EBS volumes for durability. Restore from S3 on every start, replicate while running, and accept up to about 15 seconds of loss on a hard failure. Do not set `MaximumPercent` above 100.
