# Automated test traceability and demonstration

This convention keeps Jira/QA test cases, executable code and CI evidence connected. It applies to
new or revised stories without requiring a change from the repository's existing pytest and Vitest
frameworks.

## Identify and find a test case

Use `TC-SPL-<Jira number>-<two-digit sequence>`, for example `TC-SPL-70-03`.

- Record the ID, acceptance-criteria reference, scenario and expected result in the story document.
- In Python, put the exact ID immediately above the test and include its normalised form in the
  function name, for example `test_tc_spl_70_03_...`.
- In TypeScript, begin the Vitest title with `[TC-SPL-70-03]`.
- Reuse an ID on multiple executable tests when they are distinct partitions of the same documented
  case. Do not combine unrelated outcomes merely to reduce the displayed case count.

Find every document and executable test for a case from the repository root:

```sh
rg -n "TC-SPL-70-03" docs backend/tests frontend/src
```

The result should lead directly to the documented expected result and the executable assertions.

## Write reviewable tests

Before accepting a test, answer all of these from the code and acceptance criteria:

1. Which acceptance criterion does it cover?
2. What incorrect implementation would make it fail?
3. Can its setup, action and expected result be explained plainly?
4. Is the expected result justified by the requirement rather than copied from the implementation?
5. Is it deterministic, self-validating and non-vacuous?

Keep tests fast, isolated, repeatable and timely. Use fresh fixtures, explicit actions and specific
assertions. Coverage helps reveal untested paths, but a percentage does not establish test quality.

## Run tests and present evidence

During development, run the smallest relevant test file or ID first. Each task document should list
its exact focused commands. Then run the repository gate:

```sh
npm run verify
```

Run `npm run integration` when the change has PostgreSQL-specific migration, constraint, RLS or
concurrency behaviour, using the empty disposable database described in the README. Run applicable
browser checks or a documented manual walkthrough for behaviour that component/API tests cannot
establish.

The pull-request CI check reruns the maintained automated suite in a clean environment. It is the
authoritative shared result, but it does not replace reviewing the assertions or demonstrating the
test locally. Record focused checks, the full gate, integration/browser checks and anything not run
separately in the PR.


## Record UI evidence (Windows and macOS)

With the local app, database and real Auth fixtures already running, use Node 24:

```sh
npm run e2e:record -- e2e/exact-venue-timing.spec.ts
npm run e2e:report
```

On PowerShell, use `npm.cmd` if script execution policy blocks `npm`. The optional
`E2E_BASE_URL` selects another local app port; the default is http://127.0.0.1:5173.
This command runs actual browser assertions and the existing local venue cleanup.
It does not start the app, seed fixtures or enable product feature flags.

SPL-129 additionally requires its isolated exact-timing environment and the existing
`SPL129_EVENT_ID` and `SPL129_VENUE_NAME` fixture variables. Missing fixtures skip the
story: a skipped test is not acceptance evidence. See [SPL-129](SPL-129.md).

The opt-in configuration keeps successful and failed videos, traces and end-of-test
screenshots under `artifacts/e2e-evidence/results`; the self-contained HTML report is
under `artifacts/e2e-evidence/report`. Story screenshots are attached to the test report.
Open a test in the report to inspect its named steps, assertions, images, video and trace.
Videos capture browser activity, not spoken narration. Codegen records test code and
is not needed to record an existing test.

Copy the entire evidence directory to a dated evidence folder before another run:
Playwright replaces output on rerun. Share the complete report folder, not index.html
alone. Record story/TC IDs, covered AC, build commit plus any uncommitted changes,
fixture/environment, execution date and actual result alongside it. Use only local
fake accounts: traces can contain Auth tokens, request bodies and local credentials;
review artifacts before sharing, and never commit them. Generated evidence is ignored.

Use meaningful browser journeys for visible outcomes, with `test.step` labels and
assertions. A walkthrough is evidence only for what it checks; it does not replace
API/unit evidence or imply every AC has passed. Ordinary test and CI settings remain
unchanged. SPL-129's recorded TC-12 journey shows configuration and search; the rest
of its 12-case coverage remains mapped in the story's task and development notes.
