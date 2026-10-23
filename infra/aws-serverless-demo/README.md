# Serverless replay demo on AWS (spike, not deployed)

Target: the public replay demo at `osm.changesetreview.online` (15 seeded cases, `CSO_MODE=replay`, no Decider, no
Bedrock, no sign-in), for 5 to 10 parallel visitors and 100 to 300 visits a day, at the lowest cost.

Files here (nothing else in the repo changed):

| File | Purpose |
| --- | --- |
| `template.yaml` | One CloudFormation stack: S3, CloudFront, Lambda container, alarms, budget |
| `Dockerfile`, `Dockerfile.dockerignore` | Arm64 capable API image with the Lambda Web Adapter and the seeded database |
| `deploy.sh` | Builds and pushes the image, deploys the stack, uploads the web files, clears the cache |

## Verdict

**Good fit for the replay demo: yes. For the full product: no.**

- The replay API is a read-only service over 15 fixed cases. It needs no state between requests, no background worker
  and no writes, which is exactly what Lambda is good at. Idle cost is zero, and the expected load stays inside the
  always-free tiers. Estimated bill: well under 1 US dollar a month (table below), against about 17 for the EC2 option.
- The full product is not a fit: it needs sign-in with sessions that persist, a job worker that keeps running after a
  response, the Decider server (a model on a GPU or a large CPU box) and a writable database. Lambda freezes the
  process after each response, has no shared disk and limits one call to 15 minutes. That stays on the EC2 template.
- The cost is a cold start: 4 to 6 seconds on the first request after an idle period (measured locally, see below).
  After that, requests take well under 200 ms. For a demo this is acceptable; the first page shell and all static
  files come from CloudFront and never wait for Lambda.

### The Lambda Web Adapter is still needed for this Python app

The new **Lambda Web Functions** (docs: `lambda/latest/dg/web-functions.html`) run a plain HTTP server with no adapter,
but today only for **Node.js** (`nodejs24.x`), deployed as a zip, with a fixed 2 GB environment. Python, containers and
other languages are not supported there. The adapter's own README says the same: use Web Functions for new Node.js apps,
and keep the adapter for other runtimes and container images. So the assumption "the adapter is no longer needed"
holds for Node.js and does not hold for this FastAPI backend. (Regions for Web Functions: see the launch
announcement; not checked, since it does not apply.)

### Three hosting options compared

| | Lambda + Web Adapter (built here) | Lambda MicroVMs | EC2 t4g.small (existing template) |
| --- | --- | --- | --- |
| Python, stock FastAPI container | Yes, container image plus one extension line; app code unchanged | Yes, container on Amazon Linux 2023, but needs lifecycle hooks and a snapshot-safe start | Yes, unchanged |
| Public anonymous access | Yes, function URL behind CloudFront with origin access control | **No**: every request needs a token header (`X-aws-proxy-auth`, valid 60 minutes at most); one endpoint per VM, no load balancing | Yes |
| Scale to zero | Yes | Suspend when idle (state kept, storage billed); you create and end VMs through the API | No, runs all month |
| Concurrency model | One request per instance, instances added automatically, cap with reserved concurrency | You start each VM yourself; up to 8 hours life | One host |
| Pricing | Requests + GB-seconds, free tier 1M requests and 400,000 GB-seconds a month | Per second for vCPU and memory while running (about 0.0000277 per vCPU-second and 0.0000037 per GB-second, Arm, us-east-1) plus snapshot storage; smallest size 0.25 vCPU, 0.5 GB is about 23 USD a month if always running | About 17 USD a month |
| Fit | Replay demo | Built for isolated sandboxes (AI code execution, notebooks, CI). Needs a Lambda in front to start VMs and mint tokens, so it adds a layer instead of removing one. Not a fit | Full product; simplest, flat cost |

Sources: Lambda developer guide pages for MicroVMs (`lambda-microvms-guide`, `microvms-networking`, `microvms-images`),
the Lambda pricing page, and the adapter README (checked 2026-10-20). Region list for MicroVMs not verified.

## Architecture

```
 visitor
   |  https://osm.changesetreview.online   (DNS at Hostinger: CNAME to the CloudFront name)
   v
 CloudFront  (ACM certificate in us-east-1, HTTP/2 and 3, response headers policy = Caddyfile headers)
   |-- /api/*, /healthz, /readyz, /site.webmanifest   GET, HEAD, OPTIONS only, 30 s shared cache
   |        |  signed with origin access control (SigV4)
   |        v
   |     Lambda function URL (AuthType AWS_IAM, only this distribution may call it)
   |        v
   |     Lambda, x86_64, 1024 MB, reserved concurrency 5, container image:
   |        Lambda Web Adapter --> uvicorn cso.main:app on 127.0.0.1:8080 --> SQLite copy in /tmp
   |
   |-- /docs*   viewer-request function (redirect, folder index)  --> S3, docs headers policy
   '-- default  viewer-request function (folder index, app shell)  --> S3, app headers policy
                                                 (private bucket, origin access control)
 Alarms: Lambda errors and throttles, CloudFront requests per hour, monthly budget  --> SNS email
```

How it mirrors `infra/caddy/Caddyfile`: same security headers, the tight policy for the app and the looser one only for
`/docs*`, `/docs` redirects to `/docs/`, folder paths answer with `index.html`, written pages (`/about`, `/privacy`) are
served, and every other path without a file extension gets `_shell.html` (client routes). API methods other than GET,
HEAD and OPTIONS are refused by CloudFront with 403 before Lambda is called, so the demo is read only at the edge.

Known differences from Caddy:

- A missing static file answers with the built `404.html` (and `docs/404.html` under `/docs/`) and status 404, through a
  Lambda@Edge function on the two static behaviours only (see "Update: keep warm and styled 404" below).
- No per-address rate limit at the edge (Caddy has 10 a second). The cap on parallel instances and the alarms replace it.
- `PAGES` in the CloudFront function lists the written page folders (`ls web/dist`: `about`, `privacy`). Add new ones.

## Update: keep warm, styled 404 and demo wording

What changed in `template.yaml` and the web files (the stack updates in place, no downtime, no new domain or certificate):

### 1. Keep warm

A first call after a quiet period took 4.8 s once and about 21 s once (a cold start: container start, then about
250 MB of Python libraries). An EventBridge rule (`KeepWarmRule`) now invokes the function **every 5 minutes** with an
API Gateway HTTP API (v2) shaped event for `GET /healthz`.

- Parameters: `KeepWarmEnabled` (`true` or `false`, default `true`) and `KeepWarmMinutes` (2 to 60, default 5).
  `KeepWarmEnabled=false` removes the rule and its permission.
- Why this event shape: the adapter README (v1.1.0) lists API Gateway REST and HTTP API, Function URL and ALB events,
  says it "supports non-http event triggers", and names `AWS_LWA_PASS_THROUGH_PATH` (default `/events`). It documents
  no warm-up feature and does not say what happens to other events. Checked locally with the Lambda Runtime Interface
  Emulator on the deployed image: the v2 event returned `statusCode 200`, body `{"status":"ok"}`; a bare scheduler
  style event was posted to `/events`, answered 404 by the app (the invocation still succeeded, so it also warms, but
  it logs a 404 every time, so it was not used).
- Cost: 30 days at every 5 minutes is 8,640 calls. At about 60 to 100 ms and 1 GB that is 520 to 860 GB-seconds a
  month, against the free 400,000 GB-seconds and 1,000,000 requests: about 0.2 percent of each. EventBridge rules that
  run on a schedule are free. Log lines: about 5 MB a month. Added cost: 0 (worst reading without any free tier:
  8,640 x 0.0000002 + 860 x 0.0000133 = about 0.013 US dollars).
- Limits, honestly: it keeps **one** instance warm. Two visitors at the same moment can still start a second one.
  Lambda also replaces instances every few hours on its own, so an occasional cold start remains. Not measured on
  Lambda: the rate of cold starts after the change.
- Memory or SnapStart instead? SnapStart for container images exists (Python 3.12 and later on the Lambda base images,
  checked in the docs), but it needs published versions and an alias, so the function URL, the CloudFront origin and the
  permissions would change; our image uses a plain Python base image, not the Lambda one, so it would need to implement the
  restore API or a label and the adapter's `AWS_LWA_SNAPSTART_*` hooks; the 10 second restore limit shares time with
  the readiness check; it cannot be tried in the local emulator. That is not something to change on a live stack
  without a test, so it is **not** used. More memory is a one parameter change (`MemorySizeMb`): 1769 MB is one full
  vCPU, which shortens the Python start-up that is CPU bound (about 2.8 s at full CPU, 2 to 4 s at 1 CPU in the
  emulator), and costs nothing within the free tier (at 300 visits a day it adds about 10,000 GB-seconds). The timer
  removes most cold starts, memory only shortens the rest, so the timer comes first. If cold starts still show in the
  logs after a week, deploy again with `MemorySizeMb=1769` (add it to `--parameter-overrides`).

### 2. Styled 404

Static paths now answer a missing file with the built `404.html` and status 404 (`docs/404.html` for `/docs/...`),
as `infra/caddy/Caddyfile` does. The API keeps its own JSON problem answers.

- Rejected: CloudFront custom error responses. They apply to the whole distribution, so they would also replace the
  API's JSON 404 (a missing case) and 403 (the API has GET routes that answer 403, such as `/api/v1/settings` for a
  non admin), and they allow one page for the whole site (no separate docs page). A CloudFront Function cannot do it:
  a viewer function cannot read or replace the response body, and a request function cannot know whether the file exists.
- Chosen: `EdgeErrorPagesFunction`, a small Lambda@Edge function (Node.js 24, 128 MB) on the **origin response** of the
  default and `/docs*` behaviours only. When S3 answers 403 or 404 it fetches `/404.html` (or `/docs/404.html`)
  from the distribution itself, keeps it for 60 seconds in memory and returns it with status 404. If the page cannot be
  fetched it returns the original answer, so it can only improve things. API behaviours have no association.
- Extensionless unknown paths still get the app shell with 200 (client routes), exactly as Caddy does. The 404 page
  appears for missing files and for unknown pages under `/docs/`.
- Cost: it runs only when S3 reports a missing file and CloudFront has no cached answer. Lambda@Edge has no free tier:
  about 0.60 US dollars per million requests, so a day of crawler noise of 10,000 misses is under 0.01.
- Changing the function code later: give `EdgeErrorPagesV1` a new logical id (`EdgeErrorPagesV2`) in both places it is
  used, because CloudFormation does not publish a new version on its own. Deleting the stack removes the function
  replicas, which AWS can take some hours to finish.
- `/docs` still redirects to `/docs/` (301, the viewer function, unchanged).

### 3. Wording and title

The banner and the About page say, on the hosted demo host only: "This hosted demo is view only. Signing in,
analyzing, drafting and recording outcomes are available when you run your own copy: see the self host guide." The
link goes to `/docs/self-host/docker-compose/`. A copy that someone runs on their own host does not show the sentence.
The home page title now reads "Changeset Second Opinion: flagged OpenStreetMap edits" and the docs home title
"Documentation | Changeset Second Opinion" (before: the name twice).

### How to deploy the update

Order matters little but this is the safe one. `deploy.sh` does both in the right order (stack first, then web files,
then a CloudFront invalidation):

```
CERT_ARN=arn:aws:acm:us-east-1:<account-id>:certificate/<certificate-id> \
ALERT_EMAIL=<your mail> bash infra/aws-serverless-demo/deploy.sh
```

1. The script builds and pushes the API image (unchanged code, new tag) and runs `cloudformation deploy`. The stack
   adds the rule, the Lambda@Edge function and its role, and updates the distribution (a few minutes to propagate;
   the site keeps serving during that time).
2. It then uploads `web/dist` and invalidates `/*`, which publishes the new wording and titles and the 404 pages the
   edge function reads.
3. Check: `curl -si https://osm.changesetreview.online/nothing.png | head -1` shows 404 and the styled page body;
   `curl -si https://osm.changesetreview.online/docs/nothing/` shows the docs page; `curl -si
   https://osm.changesetreview.online/api/v1/cases/none` still shows `application/problem+json`; and the function's
   CloudWatch metrics show an invocation every 5 minutes.

Not verifiable before the live deploy: that CloudFront accepts the Lambda@Edge association with this template (cfn-lint
is clean), the exact behaviour of the viewer-request rewrite together with the origin response, and the real effect on
cold starts.

## Steps for you

Region for everything: **us-east-1**. Use a profile with rights for CloudFormation, ECR, S3, Lambda, IAM, CloudFront,
ACM, SNS, Budgets.

1. **Certificate.** Run:
   `aws acm request-certificate --region us-east-1 --domain-name osm.changesetreview.online --validation-method DNS`
   (add `--subject-alternative-names changesetreview.online` if you want the apex redirect). Note the returned ARN.
2. **Validation record at Hostinger.** Run
   `aws acm describe-certificate --region us-east-1 --certificate-arn <arn> --query 'Certificate.DomainValidationOptions[].ResourceRecord'`.
   In Hostinger, DNS zone for `changesetreview.online`, add a `CNAME` for each record shown. Hostinger adds the zone
   name itself, so enter the name without `.changesetreview.online` at the end (for example `_abc123.osm`) and the
   value exactly as shown. Wait until the certificate status is `ISSUED` (usually minutes).
3. **Deploy.**
   `CERT_ARN=<arn> ALERT_EMAIL=<your mail> bash infra/aws-serverless-demo/deploy.sh`
   (optional `APEX=changesetreview.online`, `BUDGET_USD=5`, `STACK=cso-demo`). It builds the x86_64 image
   (natively on a PC, so no emulation is needed), pushes it to a new ECR repository, deploys the stack,
   uploads `web/dist` with cache headers and clears the CloudFront cache. First deploy takes about 10 minutes, mostly
   CloudFront.
4. **Confirm the mail.** SNS sends one subscription mail; click the link, or the alarms stay silent.
5. **Point the name at CloudFront.** In Hostinger add `CNAME osm` pointing to the `DistributionDomain` the script prints
   (`dxxxx.cloudfront.net`). Remove any older `A` or `AAAA` record for `osm` first (the EC2 address). Lower the TTL to
   300 seconds before the switch so rollback is quick.
6. **Apex (optional).** A bare domain cannot hold a `CNAME`. Use a Hostinger redirect (domain forwarding to
   `https://osm.changesetreview.online`) or an `ALIAS`/`ANAME` record if the plan offers one (not verified). With
   `APEX` set, CloudFront answers the redirect itself once the record points at it.
7. **Check.**
   `curl -s https://osm.changesetreview.online/api/v1/cases | head -c 300`, then open the site, `/docs/` and `/about`.

## What was tested here, and what was not

Tested locally with Docker (amd64 image, Lambda Runtime Interface Emulator, Windows laptop, noisy):

- Image builds; `cso db upgrade` and `cso seed` run at build time; the database ships read only at `/app/data/cso.db`
  and `/tmp` receives a copy per instance.
- Through the emulator with function URL style events: `/healthz` 200, `/readyz` 200, `/api/v1/me` 200 (anonymous
  viewer), `/api/v1/cases` 200 with **15 cases**, case detail, evidence and runs 200, `/api/v1/decisions` 200,
  `/api/v1/config` 200, `/openapi.json` 200 (104 KB), `/site.webmanifest` 200. The adapter translated every event.
- Container memory after a dozen calls: about 90 MiB. Image size: 534 MB on disk as Docker Desktop shows it
  (126 MB compressed content). The existing backend image built earlier for arm64 (`cso-test-backend:arm64`) shows
  557 MB, so this image is about the same size: the dependencies are the same. Lambda allows 10 GB.
- Start-up of the app (emulator `INIT REPORT`, this laptop, not Lambda): about 2.8 s with full CPU; 8 to 12 s when
  limited to 0.3 CPU (what 512 MB would give); 2 to 4 s at 1 CPU, 4 to 12 s at 0.58 CPU (1024 MB, noisy, first runs
  after a resume were slow). Warm requests: median 99 ms, p95 197 ms at 0.3 CPU including the emulator hop (tens of
  ms at full CPU). **Real Lambda numbers are unmeasured.**
- `AWS_LWA_ASYNC_INIT=true` is set because init over about 10 s would otherwise hit Lambda's init limit; with it the
  adapter returns at 9.8 s and the first request waits for the app (verified in the emulator at 0.3 CPU).
- `hadolint` clean on the Dockerfile. `cfn-lint` clean on the template. `bash -n` on `deploy.sh`.
- Checkov (the security scan of the Dockerfile validator) did not finish on this laptop, so it was not run. It would
  likely flag the missing `HEALTHCHECK`, which Lambda ignores (the adapter does the readiness check on `/healthz`).

Not run (no deploy, no spend, by instruction):

- Any AWS call that creates something: the stack, ECR push, ACM request, CloudFront behaviour of the viewer function,
  OAC signing, the budget and alarm mails. The CloudFront function logic was read, not executed.
- The arm64 image was not rebuilt in this session: the emulation layer (binfmt) was gone after the laptop resumed
  (`exec format error`), and registering it needs a privileged container, which was left alone. Build it with
  `docker buildx build --platform linux/arm64` on a machine with emulation or an arm64 runner.
- The web build step of `deploy.sh` (it reuses the `web` stage of `infra/compose/web.Dockerfile`, which the EC2 work
  also edits; re-read that file before the first run).
- Real cold starts on Lambda, image pull time from ECR, CloudFront cache hit rates.

## Cost (US East, Arm, prices from the AWS pricing pages read on 2026-10-20)

Assumptions: one visit loads about 40 static files (about 1.5 MB) and makes 8 API calls; 300 visits a day is 9,000 a
month; 30 s cache removes about a third of the API calls; average API call 60 ms at 1 GB; 200 cold starts a month at 8 s;
no WAF; DNS at Hostinger; CloudWatch logs well under the 5 GB free ingestion.

| Item | 300 visits a day | 10x spike (3,000 a day) | Notes |
| --- | --- | --- | --- |
| CloudFront requests and transfer | 0 (about 0.4M requests, 14 GB) | 0 (about 4M requests, 140 GB) | Always free: 1 TB, 10M requests, 2M function calls |
| Lambda requests | 0 (about 50k) | 0 (about 500k) | Free: 1M a month. Beyond: 0.20 per million |
| Lambda GB-seconds | 0 (about 6k) | 0 (about 60k) | Free: 400,000. Beyond: 0.0000133334 per GB-s |
| S3 storage and requests | about 0.01 | about 0.02 | Tens of MB, deploy uploads |
| ECR | about 0.04 | about 0.04 | 3 images of 126 MB at 0.10 per GB-month |
| CloudWatch logs, 3 alarms | 0 | 0 | First 10 alarms free |
| ACM, SNS email, 2 budgets | 0 | 0 | Free |
| **Total** | **about 0.05 to 0.15** | **about 0.1 to 0.3** | |
| Without any free tier (worst reading) | about 0.5 | about 3 | CloudFront at about 1 per million requests |

Comparison: EC2 t4g.small about 12.3 for the instance + 1.6 for 20 GB gp3 + 3.7 for the public IPv4 address = about
17.5 a month, flat. A flood is the real risk on the serverless side: CloudFront has no spend cap, and Lambda at the cap
of 5 parallel 1 GB instances running all day would cost about 5.8 US dollars a day. The cap, the alarms and the budget
mail exist to catch that early. I could not verify the exact CloudFront price per million requests for your account
(listed as about 1 per million in the US) or the AWS Price List API; the figures above use the published docs.

### Why no WAF by default

AWS WAF has a fixed fee: 5 per web ACL a month, 1 per rule a month (a rate-based rule is one rule) and 0.60 per million
requests, so a minimal one costs about 6 to 7 a month. That is more than everything else here. Cheaper protections
used instead: the reserved concurrency cap (limits Lambda cost and load), CloudFront in front (absorbs floods of
cacheable requests, API answers cached 30 s), GET-only API at the edge, a request alarm and a budget alarm.
Option not built: CloudFront flat-rate plans include WAF and IP rate limiting (the Free plan costs 0). The plan docs
list custom response header policies, custom cache policies and custom origin request policies only from the Business
tier up, so the CSP policy here would not fit the Free plan without moving the headers into a CloudFront function.
Not verified whether a Lambda function URL origin works under a flat-rate plan.

## Risks

- **Abuse and cost cap.** See above. Reserved concurrency needs an account quota above 100 plus the number you
  reserve (the account used for the checks here shows 1000). A new account with a lower quota cannot reserve any; then
  raise the quota in Service Quotas first.
- **Cold starts.** 4 to 6 s expected at 1024 MB, now reduced by the 5 minute keep warm call (one instance). Provisioned
  concurrency would remove it but costs a fixed amount; SnapStart now also works with container images on Python 3.12
  and later, but needs the adapter's SnapStart hooks and extra care with uniqueness; not used here (see the update
  section for the comparison).
- **No sign-in.** CloudFront refuses POST on the API (and a POST through origin access control needs a payload hash
  header that the browser app does not send). The sign-in page still shows; sign-in cannot work. No OSM OAuth settings
  are set, so the OpenStreetMap routes answer 404. No path writes to OpenStreetMap and the Decider is not present.
- **SQLite read only.** Each instance has its own `/tmp` copy; nothing written there survives or is shared. Any write
  at request time would be lost, so the edge blocks them. Data changes need a new image.
- **In-memory rate limits** (`api/security.py`) are per instance and reset at each cold start. They only guard POST
  routes, which never reach the app here.
- **Logs.** Lambda logs go to CloudWatch for 14 days. The app logs request lines without addresses or cookies.
- **Single region, single copy of the database** inside the image; a bad image is fixed by redeploying the previous one.

## Backend changes (listed, not made)

None is required: the image runs the backend as it is, using settings only. These are optional improvements, by file:

1. `backend/src/cso/persistence/db.py`: skip `PRAGMA journal_mode=WAL` and `synchronous` when the URL is read only
   (`mode=ro` or `immutable=1`). Then the image can open `/app/data/cso.db` directly and the copy to `/tmp` and the
   `install` in the entrypoint go away. Saves a few ms and one failure mode (the copy has to be writable).
2. `backend/src/cso/settings.py` and `api/security.py`: a `CSO_DEMO_READONLY` setting that makes every non-GET route
   answer a clear `problem+json` (405) from the app itself, so the app is safe even if the edge rule is removed.
3. `backend/src/cso/main.py` and the modules that import `strands`, `boto3` and `psycopg` at import time
   (`agent/`, `adapters/bedrock/`, `adapters/decider/`, `jobs/`): import them inside the functions that use them.
   Start-up drops by roughly a second at full CPU, and with `backend/pyproject.toml` split into a `demo` extra
   (integration owner only) the image would lose about 90 MB (botocore 31 MB, psycopg 20 MB, strands 9 MB, more).
4. `web/src/routes/login.page.tsx`: hide the invite and OpenStreetMap sign-in forms when `/api/v1/me` reports no
   sign-in (`osm_signin` false) in a read only demo, so visitors are not offered something that cannot work.
5. `backend/openapi/v1.json`: no change.

## Rollback and teardown

- **Back to EC2.** In Hostinger change the `osm` record back to the EC2 address (with the short TTL set earlier). The
  serverless stack can stay unused; it costs about nothing.
- **Previous API version.** `aws lambda update-function-code --function-name cso-demo-api --image-uri <older ECR digest>`
  (ECR keeps the last 3 images), or redeploy the stack with the old `ImageUri`.
- **Previous web files.** The bucket is versioned (old versions kept 30 days): restore objects with
  `aws s3api list-object-versions` and copy the earlier version back, or run `deploy.sh` from the older commit.
- **Remove everything.**
  1. `aws s3 rm s3://<bucket> --recursive` and delete old versions (or `aws s3api delete-objects` for each version), as
     the bucket has to be empty before the stack can delete it.
  2. `aws cloudformation delete-stack --region us-east-1 --stack-name cso-demo` and wait.
  3. `aws ecr delete-repository --region us-east-1 --repository-name cso-lwa-api --force`.
  4. `aws acm delete-certificate --region us-east-1 --certificate-arn <arn>` and delete the validation `CNAME` and the
     `osm` `CNAME` at Hostinger.
  5. CloudWatch log group `/aws/lambda/cso-demo-api` is deleted with the stack.
