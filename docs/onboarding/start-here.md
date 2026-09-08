# Start here: joining ConnectSphere

The aim of onboarding is to understand the project, run it independently and know how to
contribute. Installation time is infrastructure effort, not a product-story estimate.

## 1. Understand what exists

ConnectSphere's documented scope covers event requests, approvals, venue and equipment
bookings, attendee registration, changes and notifications. The current repository provides
the foundation for that work; those product features have not been implemented.

The [shared demo](https://connectsphere-mmay.onrender.com) shows the foundation's connectivity
screen. It is not a preview of the finished product.

Read these in order:

1. [README](../../README.md): what is included and how to run it.
2. [Requirements](../requirements.md): current scope summary and authoritative-source order.
   This is not the complete customer brief; review the course brief and Week 4 instructions too.
3. [Architecture](../architecture.md): how the parts connect and where business logic belongs.
   Use the [C4 diagrams](../architecture/c4.md) for the shared walkthrough.
4. [Workflow](../development/workflow.md) and [AGENTS.md](../../AGENTS.md): how humans and agents contribute.

The application flow is React → Flask → PostgreSQL for business operations. Supabase handles
authentication; Flask validates identity and future stories must enforce business permissions.
A successful login alone does not grant access to another organisation's records.

## 2. Prepare your machine before the team session

Accept the GitHub collaborator invitation and check that you can open the
[repository](https://github.com/Ryan-Lee-2000/ConnectSphere). Follow the README prerequisites,
then clone your own copy:

```sh
git clone https://github.com/Ryan-Lee-2000/ConnectSphere.git
cd ConnectSphere
```

Follow the [onboarding checklist](checklist.md) for setup, verification, browser checks and
restart checks. Windows uses PowerShell and macOS uses Terminal. WSL is optional as a shell;
Docker still needs a supported backend. The README explains how to preserve an existing Node 22
installation while using Node 24 here.

Use your own local database and generated configuration. You do not need access to the hosted
Render/Supabase accounts or their secrets to develop locally. Do not copy another person's .env.
If setup fails, record the failing step and a sanitised error; do not reset someone else's stack.

## 3. Walk through the repository together

Suggested walkthrough, after installations finish:

| Topic | What to demonstrate |
| --- | --- |
| Product context | Explain the customer workflow and identify requirements that need clarification |
| Frontend | Find frontend/src/App.tsx and its request to the health endpoint |
| API and database | Follow backend/app/__init__.py to the database health query and identity check |
| Schema changes | Locate backend/migrations; explain why merged migrations are never rewritten |
| Verification | Explain quick checks, separate PostgreSQL checks and browser/Auth checks |
| Delivery | Trace a task branch through PR, human review, CI and deployment; distinguish each status |

This walkthrough does not need a dummy feature or one practice PR per person. Use the first
team-approved story to exercise contribution and review once the team has refined it.

## 4. Report readiness

Send the following result to the person coordinating onboarding, without secrets:

```text
Name:
OS / processor / Docker backend:
Git commit:
Repository access: pass / blocked
Setup and second setup: pass / fail / not run
Quick verification: pass / fail / not run
Browser/Auth check: pass / fail / not run
Stop and restart: pass / fail / not run
First setup elapsed time:
Blocker and sanitised error, if any:
Requirement or workflow questions:
```

Record actual verification evidence using the checklist. Setup is complete when the checks pass
on that person's machine. Understanding is demonstrated when they can explain the application
flow, where their changes belong, and how a change reaches the shared demo.

## Decisions reserved for the team

- Confirm the complete requirements baseline and unresolved customer questions.
- Select and refine the smallest useful reference story, then agree its estimate.
- Assign work, reviewers and primary/backup migration maintainers.
- Agree the Definition of Done and shared API/schema contracts for related stories.

These are discussion items, not decisions made by this guide. No product task is assigned by onboarding.
