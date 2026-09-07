# CI budget visibility

Current status: UNKNOWN; no real GitHub owner exists yet.
Run npm run budget. CI displays the same snapshot in its run summary.

The foundation provides a transparent MANUAL snapshot, not a working live billing integration.
A maintainer records account-wide allowance/usage and storage from the billing dashboard in
ci-budget.json, with owner, month, source and UTC verified_at. It expires after 24 hours.
Do not insert this repository's runtime sum and call it account-wide usage.
No fictional 2,000-minute allowance is prefilled.

NORMAL <70%; CONSERVE >=70%; CRITICAL >=90%; EXHAUSTED >=100%.
The worst of minutes/storage determines status. Missing, stale or invalid data is UNKNOWN.
The snapshot is informational; only actual GitHub billing controls prevent paid overages.
Required verification is never silently removed.

After choosing repo owner: verify the owner's billing API/permissions, included units and
allowance, then implement retrieval and a pinned issue update in a trusted scheduled workflow.
The standard GITHUB_TOKEN is not assumed to have billing access. Don't expose billing tokens
to PR jobs. API failure must retain an UNKNOWN state. Avoid adding paid reporting services.
This pending integration is tracked in docs/infrastructure/tasks/INF-04.md.

CI uses Linux, bounded job time, PR/push-main triggers and cancellation of obsolete verification.
Deployment serialization has its own group; don't cancel an active migration/deploy when
superseding verification runs. At activation review concurrency semantics for the actual repo.
No automatic large reports are uploaded; archive required assessment evidence separately.
Source: https://docs.github.com/en/billing/concepts/product-billing/github-actions
