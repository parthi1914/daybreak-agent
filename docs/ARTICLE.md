# Weekend Agent Challenge: DayBreak — Your Autonomous Morning-Brief Agent

**Tag:** #agents

*The best productivity tool is the one you never have to open. DayBreak is an AI agent that wakes before I do, gathers my day from real data, and leaves a single scannable brief in my inbox — with follow-up drafts already written for anything that's gone quiet.*

![DayBreak architecture: EventBridge Scheduler wakes a Bedrock tool-use agent on Lambda, which reads tasks, weather, and stale threads, then delivers a brief by SES and stores it in DynamoDB.](architecture/architecture.png)
*Figure 1 — DayBreak architecture. The schedule is the only trigger; everything else happens while I'm asleep.*

![DayBreak AWS architecture diagram showing EventBridge Scheduler, Lambda, Bedrock Nova, DynamoDB, Gmail SMTP, and the React dashboard.](architecture/daybreak-architecture.svg)
*Figure 2 — current AWS architecture for the deployed demo, including Gmail delivery and the React dashboard.*

![DayBreak data flow diagram showing schedule trigger, tool gathering, Bedrock reasoning, Gmail email, DynamoDB storage, and dashboard display.](architecture/daybreak-data-flow.svg)
*Figure 3 — basic data flow from autonomous schedule trigger to ready-to-read result.*

## Vision & What the Agent Does

Last weekend's challenge was about apps you open, paste into, and get something back from. This one flips it: build something that does the work on its own. That reframing is the whole point of DayBreak. There's no app to launch and no button to press. **Amazon EventBridge Scheduler fires the agent at 6 AM** in my timezone, and by the time I'm awake the result is waiting.

When it wakes, the agent gathers my day: today's weather for my location, my open tasks (with overdue and due-today surfaced first), any conversation threads that have gone quiet past a staleness threshold, and — optionally — a few news headlines. It then reasons over all of it with Amazon Bedrock and composes a **structured brief**: a one-line greeting, the weather in plain terms, my top priorities with *why each matters today*, my schedule, and short, paste-ready follow-up drafts for the stale threads. It reports back by emailing me a clean HTML brief and storing the record in DynamoDB. A React dashboard shows brief history and search, while settings and test-run controls are protected behind an admin token so the public showcase link stays safe.

The problem it solves is the ten scattered minutes every morning spent reconstructing "what actually matters today" from four different places. DayBreak does that reconstruction overnight so the day starts already triaged.

## How You Built It

The core decision was to make this a genuine **agent, not a script**. Instead of hard-coding "fetch weather, then tasks, then write," I gave Bedrock Nova a set of tools and a goal and let it run a tool-use loop: it decides which tools to call, reads the results I feed back, and repeats until it has enough, then composes the brief. That means a morning with no stale threads simply doesn't produce a nudges section — the agent adapts to the data instead of forcing a fixed template.

Key decisions and the challenges behind them:

- **Structured output.** Free-form model prose is hard to render consistently and impossible to store cleanly. I force a final JSON turn against a fixed schema, so one payload drives the email, the stored record, and the viewer. A defensive parser tolerates fences and stray prose, with a minimal-brief fallback if parsing ever fails.
- **Idempotency.** Scheduled invocations are at-least-once, and a retry or double-fire should never send two briefs for the same morning. I used AWS Lambda Powertools idempotency keyed on the date, backed by a DynamoDB store, so a repeat run replays the first result instead of re-sending.
- **Degrade, don't fail.** Each tool is defensive: a dead weather API or an unseeded task table drops that section rather than failing the run. Only a genuine compose/deliver failure raises — which is exactly what I *want* to alarm on.
- **Retune without redeploy.** Recipient, feeds, tone, and the stale threshold live in SSM Parameter Store, so I can adjust the agent from the console without touching code.

I validated the whole pipeline offline first — a local harness runs the tool loop, parsing, and rendering with Bedrock and AWS mocked — then deployed and invoked once manually before trusting the schedule.

## AWS Services Used / Architecture Overview

- **Amazon EventBridge Scheduler** — the timezone-aware cron trigger. *This is the "always-on" part.*
- **AWS Lambda** (Python 3.12, arm64) — the agent runtime and orchestration.
- **Amazon Bedrock (Nova Lite, Converse API with tool use)** — the reasoning core.
- **Amazon DynamoDB** — tasks, briefs (with TTL), and the idempotency store.
- **AWS Systems Manager Parameter Store** — runtime configuration.
- **Amazon SES** — delivers the brief.
- **Amazon SQS + CloudWatch + SNS + AWS X-Ray** — a dead-letter queue for missed runs, alarms on errors and DLQ depth routed to email, a dashboard, and traces.

All of it is one AWS SAM template with least-privilege IAM scoped per action (Bedrock invoke limited to Nova, DynamoDB limited to the three tables, SES limited to the sender identity). The trigger flow is simply: **Scheduler → Lambda → (tool loop over DynamoDB + external APIs + Bedrock) → SES + DynamoDB**, with the DLQ and alarms watching the edges.

*Figure 4 — the EventBridge schedule showing its next run time (screenshot to capture in the console).*
*Figure 5 — the brief as it lands in my inbox at 6 AM (screenshot to capture from email).*

## What You Learned

The biggest shift was designing for an agent that runs **when I'm not watching**. That changes what "done" means: it's not enough for the happy path to work once when I click invoke. I had to think about what happens when a data source is down, when the schedule fires twice, and how I'd even *know* something failed at 6 AM. That pushed idempotency, dead-lettering, and alarms from "nice to have" to "the actual product."

I also got hands-on with Bedrock's **Converse tool-use loop** for the first time — letting the model drive which tools run, rather than orchestrating every call myself, is a cleaner mental model than I expected, and forcing a final structured-JSON turn turned out to be the trick that made model output safe to build a UI and a database record on.

## Link to App or Repo

- **Live dashboard** (brief history and latest brief): *paste the `ViewerUrl` stack output here.*
- **Source code:** *paste your public GitHub repo link here.*

*Word count: ~780 (excludes captions and code). Built and deployed over one weekend on the AWS Free Tier.*
