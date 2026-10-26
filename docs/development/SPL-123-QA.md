# SPL-123 QA design and execution record

Date: 26 October 2026 (Singapore). QA snapshot: current main `27d8669` plus the uncommitted SPL-123 patch. Original feature checkout remains on `f585243`; the isolated QA branch is `qa/SPL-123-20261026`. No product commit was created.

## External report setup

Live Jira/Confluence access is pending: Atlassian is installed but exposes no actions in this chat. Jira status, current card comparison, master-template copy, report Web link and evidence upload are not verified. This local record is not a substitute for the Confluence master or a claim of publication.

## Saved acceptance criteria (verbatim)

- AC1. Notified when the event becomes Confirmed
- AC2. Notified when a Confirmed event returns to Planning after a significant change (as defined
  by SPL-109)
- AC3. Notified when the event is cancelled, with the reason
- AC4. Notified when each change request item is decided
- AC5. A refused or failed action sends no notice, and retrying an action does not create a
  duplicate notice

The task records approved decisions, including no self-notifications, responsible organiser versus request submitter, and separate item/Planning facts. Dependencies SPL-109 and SPL-112 are present on main; live Jira status remains unverified.

## Case design (before execution)

| Case | AC | Kind | Automated test |
| --- | --- | --- | --- |
| QA-SPL-123-001 | AC1 | BB | `test_qa_spl_123_001_confirmation_is_persisted_and_reloadable` |
| QA-SPL-123-002 | AC1 AC5 | BB | `test_qa_spl_123_002_unready_confirmation_has_no_notice` |
| QA-SPL-123-003 | AC1 AC5 | BB | `test_qa_spl_123_003_only_assigned_coordinator_can_trigger_confirmation` |
| QA-SPL-123-004 | AC1 | WB | `test_qa_spl_123_004_new_confirmation_uses_new_history_identity` |
| QA-SPL-123-005 | AC1 | WB | `test_qa_spl_123_005_dual_role_actor_gets_no_self_confirmation` |
| QA-SPL-123-006 | AC2 | BB | `test_qa_spl_123_006_direct_significant_edit_notifies_return_to_planning` |
| QA-SPL-123-007 | AC2 AC4 | BB | `test_qa_spl_123_007_two_significant_items_send_one_planning_notice` |
| QA-SPL-123-008 | AC2 | BB | `test_qa_spl_123_008_edit_while_planning_sends_no_return_notice` |
| QA-SPL-123-009 | AC2 AC5 | BB | `test_qa_spl_123_009_noop_and_preview_do_not_notify` |
| QA-SPL-123-010 | AC2 | WB | `test_qa_spl_123_010_self_significant_change_is_silent` |
| QA-SPL-123-011 | AC3 | BB | `test_qa_spl_123_011_cancellation_includes_trimmed_reason` |
| QA-SPL-123-012 | AC3 | BB | `test_qa_spl_123_012_cancellation_notifies_without_arrangements` |
| QA-SPL-123-013 | AC3 AC5 | BB | `test_qa_spl_123_013_invalid_cancellation_reason_writes_nothing` |
| QA-SPL-123-014 | AC3 AC5 | BB | `test_qa_spl_123_014_terminal_event_refuses_cancellation_without_notice` |
| QA-SPL-123-015 | AC3 | WB | `test_qa_spl_123_015_self_cancellation_is_silent` |
| QA-SPL-123-016 | AC4 | BB | `test_qa_spl_123_016_ordinary_accepted_item_names_field_and_outcome` |
| QA-SPL-123-017 | AC4 | BB | `test_qa_spl_123_017_decline_has_reason_without_proposed_values` |
| QA-SPL-123-018 | AC4 | BB | `test_qa_spl_123_018_partial_then_mixed_final_decisions_notify_each_item` |
| QA-SPL-123-019 | AC4 | WB | `test_qa_spl_123_019_item_recipient_comes_from_stored_submitter` |
| QA-SPL-123-020 | AC4 | WB | `test_qa_spl_123_020_self_decision_is_silent` |
| QA-SPL-123-021 | AC5 | WB | `test_qa_spl_123_021_confirmation_failure_rolls_back_notice_and_transition` |
| QA-SPL-123-022 | AC5 | WB | `test_qa_spl_123_022_cancellation_failure_rolls_back_notice_and_action` |
| QA-SPL-123-023 | AC5 | WB | `test_qa_spl_123_023_significant_change_failure_rolls_back` |
| QA-SPL-123-024 | AC5 | WB | `test_qa_spl_123_024_later_item_failure_rolls_back_entire_batch` |
| QA-SPL-123-025 | AC5 | BB | `test_qa_spl_123_025_retries_do_not_duplicate` |
| QA-SPL-123-026 | AC1 AC3 AC4 | BB | `test_qa_spl_123_026_foreign_inbox_cannot_read_notices` |
| QA-SPL-123-027 | AC5 | WB | `test_qa_spl_123_027_database_dedupe_constraint` |
| QA-SPL-123-028 | AC4 AC5 | BB | `test_qa_spl_123_028_reassignment_after_preview_refuses_decisions` |
| QA-SPL-123-029 | AC4 AC5 | BB | `test_qa_spl_123_029_stale_preview_sends_no_notice` |
| QA-SPL-123-030 | AC5 | BB | `test_qa_spl_123_030_client_cannot_choose_notice_recipient` |

BB/WB counts: BB 19, WB 11. Cases 001–005 cover AC1; 006–010 AC2; 011–015 AC3; 016–020 AC4; 021–025 AC5. Parameterized values are partitions of the same case, not additional case IDs. PostgreSQL cases 070–074 and recorded UAT 200 supplement these.

## Exact-wording and risk review

| Risk | Added case coverage |
| --- | --- |
| Exactly once after retry, distinct reconfirmation, or a multi-item save | 004, 007, 025, 027; PostgreSQL 070–073 |
| Failed action after writes, rather than validation failure alone | 021–024; PostgreSQL 074 |
| Read after reload and foreign inbox isolation | 001, 026 |
| Reassignment or stale state between preview and save | 028, 029 |
| Recipient or role spoofing and multi-role self-action | 003, 005, 010, 015, 019, 020, 030 |
| Each item versus one event transition | 007, 018 |
## Run history (append-only)

| Run | Scope | Passed | Failed | Skipped / unavailable | Evidence |
| --- | --- | --- | --- | --- | --- |
| P1 | Initial doctor in sandbox | — | npm DNS resolution blocked | Prerequisites not established by that attempt | Tool output |
| RE-TEST P1 | Doctor with required network/Docker access | Passed | 0 | 0 | Node 24, pnpm 10.15.1, Docker 29.7.2 |
| B1 | Current-main full verify on 27d8669 | Backend 2723; frontend 541; lint/format/typecheck/build | 0 | 167 PostgreSQL-dependent skips | main checkout artifacts/spl-123-qa/baseline-verify-run1.log |

## Failure and change log (append-only)

| Row | Class | Original result / cause | Change or retest |
| --- | --- | --- | --- |
| F1 | B, authoring lint | Initial new-test draft had 33 E501 line-length diagnostics before formatting; no test had run | New file formatted; Ruff check and format check passed |
| O1 | Environment | Playwright MCP profile is already in use; no tabs could be inspected | Existing browser left untouched; repository Playwright runner will use its own context |
| O2 | Environment | Attempt to add ignore entries under the worktree git metadata was denied | No product file affected; dependency symlinks remain local and uncommitted |

## Resources created

- `/tmp/connectsphere-spl123-main-20261026`: detached main baseline.
- `/tmp/connectsphere-spl123-feature-20261026`: current-main QA branch plus feature snapshot.
- Docker `connectsphere-spl123-qa-20261026`, PostgreSQL 17 Alpine at loopback port 55439; no shared data mounted.
- Shared development API/frontend/Supabase are left running without reset or restart.

## 26 October execution additions (append-only)

| Run | Scope | Passed | Failed | Skipped / unavailable | Evidence |
| --- | --- | --- | --- | --- | --- |
| B2 | Main standard PostgreSQL on 27d8669 | 154 | 0 | 0 | baseline-integration-run1.log |
| B3 | Main additional PostgreSQL files omitted by standard runner | 13 | 0 | 0 | baseline-additional-postgres-run1.xml |
| F2 | Feature focused backend | 41 | 0 | 0 | focused-run1.xml |
| F3 | Feature focused PostgreSQL | 5 | 0 | 0 | postgres-focused-run1.xml |
| F4 | Feature notification component | 5 | 0 | 0 | frontend-focused-run1.log |
| F5 | Feature full verify, base 27d8669 plus uncommitted snapshot | Backend 2764; frontend 546; lint/format/typecheck/build | 0 | 172 PostgreSQL-dependent skips, separately executed | feature-verify-run1.log |
| F6 | Feature added-statement/branch coverage | 17/17 statements; 2/2 branch exits; 41 tests | 0 | Frontend added product code: none | added-coverage-run1.json |
| E1 | Main and feature isolated UI fixture preparation | 0 browser tests executed | Missing auth.users fixture mapping table | Browser suites could not start | browser-run1.log in both worktrees |
| RE-TEST E1 | Add only synthetic local identity references to auth.users in the two disposable UI databases | Fixture preparation passed; whole browser suites running | Results pending at this entry | Real Supabase Auth verification unchanged | browser-run2.log |
| F7 | Feature standard PostgreSQL | 158 | 1: QA-SPL-122-071 | 0 | feature-integration-run1.log |
| U1 | Recorded UAT 200 | Confirmation action completed | 1: new login helper missed asynchronous organiser role selector | Later ACs not executed | uat-run1.log and uat-run1-results |

| Row | Class | Original result / cause | Proposed rectification |
| --- | --- | --- | --- |
| E2 | Environment setup | Initial baseline API lacked PYTHONPATH; isolated Vite config could not resolve vite; second launch used root rather than frontend Vite path | Corrected isolated launch/config only; both API/frontend pairs healthy on 5123/5183 and 5124/5184; original logs retained |
| E3 | Environment fixture | Both browser fixture setups failed because the disposable application databases lacked auth.users identity references | Added a minimal fixture table containing only synthetic local Auth IDs/emails; no Auth bypass, shared DB reset or credentials changed |
| F2 | C, stale expectation from SPL-122 | QA-SPL-122-071 fails on organiser:1 in addition to the two Technical Support recipients; main passed the same case. SPL-123 AC3 requires this organiser notice | User approval requested to require all three exact counts; existing test is unchanged while approval is pending |
| F3 | B, new UAT helper | QA-SPL-123-200 run 1 failed at organiser login because isVisible returned before role selector mounted | Helper now waits for selector or existing workspace before inspecting it. New recording uses new fixtures and output paths; run 1 retained |

Fixture additions: qa.coordinator.b@example.test and safety.officer@example.test were missing from local Auth and were added as synthetic fixtures; existing Auth users/credentials were untouched. Application fixture records are restricted to the two owned disposable UI databases. Four initial UAT events and four separate run-2 events avoid resetting run-1 data.

Live Atlassian remains blocked: installed/enabled plugin but no Jira/Confluence actions exposed. No live card/status/template/page/link has been read or changed. This local file is a staging record, not the mandated Confluence report.

## Further measured evidence, 26 October (append-only)

- RE-TEST of F3 / UAT run 2: PASS, case 200 completed all action/inbox checks in 29.2 seconds after the login-helper wait was corrected. No product code changed. Eight extracted video frames show AC1–AC5, the refusal, reassigned-event refusal and foreign-account notice isolation. All captions are visible; only synthetic fixture data is shown, with no credentials exposed in those frames.
- Exact-wording follow-up: run 2's foreign coordinator inbox contained unrelated assignment notices from the whole browser run. Its SPL-123 isolation assertion passed, but the skill specifically asks for an empty inbox. Added a dedicated synthetic organiser, qa.spl123.other@example.test, in a different organisation, and expanded the new case 200 assertion to require the real empty-state text and zero list items. Run 3 uses four new events; no previous run data or evidence was reset or overwritten.
- Mutation check: all 7 mutations were killed by assertion failures with zero setup errors. M1 disables all hooks (16 failures); M2 confirmation (4); M3 return to Planning (3); M4 cancellation (4); M5 item decisions (6); M6 self-action suppression (4); M7 stored submitter recipient (1). Mutations live only in independent application copies under ignored artifacts/mutants; product source was never changed. mutation-summary-run1.json maps every failure to its executable test.
- Additional feature PostgreSQL suite: 13 passed in 17.70 seconds, zero failures/skips (feature-additional-postgres-run1.xml). Together with standard integration run 1: 171 passed, 1 failed, zero skipped.
- Budget command completed: Actions usage UNKNOWN (snapshot is September, current date October); no CI, paid service or billing change was invoked.

| Row | Class | Original result / established cause | Action |
| --- | --- | --- | --- |
| F4 | Pre-existing on main, SPL-135 test setup | QA-SPL-135-UAT-021 fails before its browser actions on both 27d8669 baseline and the feature snapshot: beforeAll hard-codes .venv/Scripts/python.exe, which does not exist on macOS | Existing test unchanged. Recommend a separate SPL-135 portability correction using the platform-appropriate Python executable; approval would be required to edit that existing test |
| O3 | Evidence tooling | First contact-sheet extraction command failed because bundled Playwright FFmpeg does not include fps/tile filters | Retained extraction error log; individual seek-to-frame extraction passed and the eight actual video frames were inspected |

The recorded video's AC5 failed-storage-action rollback is Partly shown: stale refusal and deduplication are visible; an injected storage failure and atomic rollback are verified by backend 021–024 and PostgreSQL 074, not simulated in the real UI. AC1–AC4 are fully shown. Reassignment is a prepared fixture plus denied old-coordinator UI; preview-to-save reassignment race is automated case 028.

## Final local evidence snapshot — 26 October 2026, 10:02 SGT (append-only)

QA is INCOMPLETE, not a pass: live Jira/Confluence setup and publication are unavailable, and one existing PostgreSQL assertion still awaits explicit approval. No SPL-123 product defect was found by the executed cases. No commit, push, PR, deployment or Jira transition was performed.

| Final run | Passed | Failed | Skipped / could not run |
| --- | --- | --- | --- |
| Main full verify, 27d8669 | 2723 backend; 541 frontend; lint/format/typecheck/build | 0 | 167 PostgreSQL-dependent skips, then all 167 passed separately |
| Main PostgreSQL, standard plus omitted files | 167 | 0 | 0 |
| Main existing whole browser suite | 49 | 1: pre-existing SPL-135 Windows Python path | 14 fixture-dependent skips |
| Feature full verify on 27d8669 plus SPL-123 and new tests | 2764 backend; 546 frontend; lint/format/typecheck/build | 0 | 172 PostgreSQL-dependent skips, separately executed |
| Feature PostgreSQL, standard plus omitted files | 171 | 1: QA-SPL-122-071 stale recipient assertion | 0 |
| Feature existing whole browser suite | 49 | 1: same pre-existing SPL-135 Windows Python path | 14 fixture-dependent skips |
| Recorded UAT 200 run 1 | 0 | 1: new login-helper timing expectation | Remaining steps unexecuted |
| RE-TEST UAT 200 run 2 | 1 | 0 | Storage-failure rollback measured by API/PG, not the video |
| Expanded UAT 200 run 3 | 1 in 25.7 seconds | 0 | Storage-failure rollback measured by API/PG, not the video |
| Original f585243 checkout focused backend + PostgreSQL after copying QA files | 46 | 0 | 0 |
| Original checkout notification component after copying QA files | 5 | 0 | 0 |
| Original checkout final Ruff check and format check for new Python tests and integration runner | Passed | 0 | Full suites were measured on the main-level QA snapshot above |

Both existing browser runs collected the same 64 cases before the new SPL-123 manual spec was added; the new spec was then executed separately as UAT 200. Default exclusions for SPL-110 and SPL-119 recorded walkthroughs were retained. No existing browser test was changed, newly skipped, or replaced by a skip. Both runs report zero flaky tests. These results do not claim that unavailable fixture-specific stories passed.

Skipped existing browser cases (14): SPL-137, SPL-129, SPL-104, SPL-109, SPL-112, SPL-121, SPL-122, SPL-141, SPL-138, SPL-130, and four SPL-107 partitions; each is already conditional on its own isolated fixtures. No selected SPL-123 acceptance case was skipped in its focused runs.

Coverage: 17/17 added executable statements and 2/2 added branch exits (100% each), measured by coverage.py on the five changed backend modules with the 41 focused executions. This is added-code coverage, not 100% of those pre-existing modules. Frontend percentage was not measured; no frontend product source was changed, and five component cases plus the real UI recording passed.

| Row | Class | Original result / cause | Retest |
| --- | --- | --- | --- |
| F5 | B, QA handoff formatting | Initial integration-runner insertion in the original checkout had excess indentation on its two new lines; Ruff format check failed | RE-TEST F5: PASS after indenting only those two new lines consistently. Ruff check and format check passed; no existing test assertion changed |
| O4 | Test maintainability | Existing equipment walkthroughs locate cards through CSS classes such as .equipment-availability__card | Recommend semantic article/region locators scoped by the equipment heading when those tests are next maintained; existing tests left unchanged |

## Supplementary case traceability

| Case | AC | Kind | Automated test |
| --- | --- | --- | --- |
| QA-SPL-123-070 | AC1 AC5 | WB | `test_qa_spl_123_070_concurrent_confirmation_notifies_once` |
| QA-SPL-123-071 | AC3 AC5 | WB | `test_qa_spl_123_071_concurrent_cancellation_notifies_once` |
| QA-SPL-123-072 | AC4 AC5 | WB | `test_qa_spl_123_072_concurrent_item_decisions_notifies_once` |
| QA-SPL-123-073 | AC2 AC5 | WB | `test_qa_spl_123_073_concurrent_significant_saves_notify_once` |
| QA-SPL-123-074 | AC5 | WB | `test_qa_spl_123_074_notice_failure_rolls_back_postgres_transaction` |
| QA-SPL-123-101 | AC1 | BB | `[QA-SPL-123-101] renders a confirmation notice addressed by the inbox API` |
| QA-SPL-123-102 | AC2 | BB | `[QA-SPL-123-102] explains that a significant change requires confirmation again` |
| QA-SPL-123-103 | AC3 | BB | `[QA-SPL-123-103] displays the organiser cancellation reason` |
| QA-SPL-123-104 | AC4 | BB | `[QA-SPL-123-104] displays an item outcome and decline reason` |
| QA-SPL-123-105 | AC1 AC2 AC3 AC4 AC5 | BB | `[QA-SPL-123-105] follows the protected organiser event link without generating an action request` |
| QA-SPL-123-200 | AC1 AC2 AC3 AC4 AC5 | BB recorded real UI | `[QA-SPL-123-200] organiser sees lifecycle and item notices; refused retries and access stay protected` |

Core per-AC design counts (excluding extra cross-cutting/PG/UI partitions): AC1 3 BB/2 WB; AC2 4 BB/1 WB; AC3 4 BB/1 WB; AC4 3 BB/2 WB; AC5 1 BB/4 WB. Across all distinct case IDs: 25 BB and 16 WB, 41 cases; parameterized backend executions are not additional IDs. The frontend cases are 101–105, PostgreSQL cases 070–074 and manual recorded case 200.

## Recorded UAT run 3

Repository Playwright with real local Supabase Auth, not Playwright MCP. Fixture case IDs/names: `artifacts/spl-123-qa/uat-fixtures-run3.json`. Written order is the named steps in e2e/spl123-uat-evidence.spec.ts: confirm → significant change → cancel → decide each item → stale retry → reassigned access and foreign empty inbox. No UI response was mocked.

Video: `/tmp/connectsphere-spl123-feature-20261026/artifacts/spl-123-qa/uat-run3-results/spl123-uat-evidence--QA-SP-73acd-s-and-access-stay-protected/video.webm`.

| AC / access behavior | ACs shown | Extracted video timestamp | Additional evidence |
| --- | --- | --- | --- |
| AC1 confirmation notice and durable reload | Fully | 00:03.24 | Backend 001–005; PostgreSQL 070; frontend 101 |
| AC2 significant return-to-Planning notice | Fully | 00:06.84 | Backend 006–010; PostgreSQL 073; frontend 102 |
| AC3 cancelled notice with reason | Fully | 00:11.14 | Backend 011–015; PostgreSQL 071; frontend 103 |
| AC4 separate accepted/declined item notices | Fully | 00:14.48 | Backend 016–020; PostgreSQL 072; frontend 104 |
| AC5 refused stale retry and exactly one notice | Partly | 00:17.95 refusal; 00:20.49 inbox | Failed-storage rollback: backend 021–024 and PostgreSQL 074; retry 025, dedupe 027 |
| Former coordinator denied a reassigned event | Fully for prepared reassignment state | 00:22.79 | Preview-to-save reassignment: backend 028 |
| Other organisation account's empty inbox | Fully | 00:24.82 | Foreign inbox API 026; protected-link component 105 |

All eight final video frames were extracted and visually inspected: every caption appears; they show only synthetic fixture data, no credentials. Main video holds all steps; video-1.webm is a supplementary short second-tab recording. Earlier failed and passed videos, logs and frames remain intact.

Confluence publication cannot proceed: the live master and destination page cannot be accessed, so no genuine QA-SPL-123 page/link exists in this session. Once Atlassian actions are available, first read the card/master, compare the saved ACs, create/link the report exactly once, transfer the complete append-only history, attach this final video in Recorded UAT, and re-read the page/link. Any changed AC, merge or source revision requires a fresh measurement of affected evidence. Do not call QA complete or start devops before these steps and the existing-test decision are resolved.

## Handoff and running local resources

- Original feature branch remains based on f585243. Its seven-file tracked feature patch is byte-for-byte unchanged from the patch saved before QA. Only five new QA files and a two-line integration-runner addition were handed back; this does not merge main into the original checkout.
- Full verification and regression evidence is for current-main 27d8669 plus that feature snapshot on qa/SPL-123-20261026. Main's notifications.py also contains its separately merged changes; they were not copied over the original developer's source.
- The original checkout's new 41 backend executions, 5 real PostgreSQL cases and 5 component cases were separately rechecked and passed. No later product-source change or merge occurred.
- Owned APIs remain on 5123 (baseline), 5124 (feature); owned frontends on 5183/5184; the shared developer API/frontend/Supabase remain untouched and running on their existing ports.
- Owned PostgreSQL container connectsphere-spl123-qa-20261026 remains on 55439 with baseline/feature UI databases plus two integration entry databases. Per-case race databases created by tests were dropped by their own fixtures; no shared DB was reset.
- Two QA worktrees remain under /tmp/connectsphere-spl123-{main,feature}-20261026, with ignored environment files and local dependency symlinks. Logs, videos, XML, coverage and mutation evidence remain in each artifacts/spl-123-qa directory.
- Three new synthetic local Auth fixtures remain: qa.coordinator.b@example.test, safety.officer@example.test and qa.spl123.other@example.test. The last belongs to a separate organisation in the owned feature UI DB. There are twelve UAT events across three retained runs, their venue fixtures, and ordinary E2E fixtures in the owned UI DBs. Existing Auth users and development data were not reset.
- No product migration was added or merged migration edited. No hosted deployment/migration ran. Actions budget is UNKNOWN; no CI was triggered.

Next independent action: await the specific existing-test approval, then update only QA-SPL-122-071 and re-run its file plus cancellation/notice concurrency tests (and the complete PostgreSQL gate on a new empty entry database). Next external action: expose working Atlassian Jira/Confluence tools. The QA skill requires the master report and evidence upload; local evidence does not substitute for them.

### Final read-back, 26 October 2026 10:02 SGT

Both owned UI databases report Alembic head `s4_safety_reviews`. The original checkout's final `git diff --check` passed. All original failure/run rows remain present; later outcomes are append-only. Case traceability includes every ID 001–030, 070–074, 101–105 and 200. Eight run-3 video frames and all captions were visually verified, including the actual empty inbox. Atlassian tool discovery was checked again and still exposes zero Jira/Confluence actions. Ticket status, live AC comparison, master/report creation, Web link, video attachment and page read-back could not run. The requested existing-test approval has not yet arrived; QA-SPL-122-071 is unchanged. The independent local work is preserved for continuation.

## Approved targeted PostgreSQL assertion update — 26 October 2026 (append-only)

User explicitly approved updating only QA-SPL-122-071. In backend/tests/test_qa_spl122_postgres.py, the recipient count map changed from technical:1 / technical-2:1 to technical:1 / technical-2:1 / organiser:1. Both Technical Support counts, the three race iterations, the one-200/one-409 check, and the Technical Support message assertion remain intact. This corrects the stale expectation for SPL-123 AC3; no product code changed. The same narrow change was applied to the original checkout and current-main QA snapshot. No commit was made.

RE-TEST of failure F2 / run F7 is now in progress against a newly created, verified-empty disposable entry database. All earlier failure rows and run counts remain unchanged.

### Targeted approval follow-up — 26 October 2026, 10:22 SGT

- RE-TEST F2 (focused on original feature checkout f585243 plus uncommitted feature/QA files): 14 passed, zero failures/skips, in 14.17 seconds. Scope: entire test_qa_spl122_postgres.py, test_event_cancellation_postgres.py and test_qa_spl123_postgres.py. Evidence: original-cancellation-retest-run1.xml/.log in the isolated feature artifacts directory.
- Additional PostgreSQL retest on current-main QA snapshot: 13 passed, zero failures/skips, in 14.41 seconds. Scope: test_qa_spl102_postgres.py, test_qa_spl103_postgres.py, test_qa_spl106_postgres.py and test_qa_spl109_postgres.py. Evidence: feature-additional-postgres-run2.xml/.log.
- Changed-file Ruff check, Ruff format check and git diff --check: PASS. Only the approved recipient-count mapping changed in the existing PostgreSQL test; product code, concurrency setup, status assertions and message checks are unchanged. The main baseline worktree has not been modified.
- Complete integration gate is still running at this entry; its original failed run remains recorded as 158 passed / 1 failed. The fresh entry database is spl123_retest_20261026_022134 in the already-owned PostgreSQL container. No shared database, service or hosted resource changed.

## Completed approved retest — 26 October 2026, 10:24 SGT (append-only)

RE-TEST of failure F2 / integration run F7: PASS. Standard npm run integration run 2 finished with **159 passed, 0 failed, 0 skipped**, 9 existing Alembic deprecation warnings, in 140.98 seconds. The additional PostgreSQL run 2 passed all **13**, giving **172/172 PostgreSQL checks passed** on the current-main QA snapshot. The original failure remains recorded unchanged as 158 passed / 1 failed; the newly approved assertion is the sole rectification. Evidence: artifacts/spl-123-qa/feature-integration-run2.log and feature-additional-postgres-run2.xml/.log in /tmp/connectsphere-spl123-feature-20261026.

The original feature checkout's focused cancellation/notice tests also passed **14/14**. Ruff check, Ruff format check and git diff --check passed for the approved change. Approval is resolved; no additional test edit is pending from this request. Both copies of test_qa_spl122_postgres.py contain the same narrow mapping update. No existing concurrency, status or message check was removed or relaxed; exactly one notice is now required for each of the three expected recipients. No product source or migration changed, and no commit, push, PR or deployment occurred.

Full verify, browser, mutation, coverage and recorded UAT were not repeated after this assertion-only correction; their prior dated measurements remain as recorded. Product source has not changed, so the already-inspected UAT run 3 and its video remain the current feature evidence. The pre-existing SPL-135 macOS browser setup failure and the 14 existing fixture-specific browser skips remain unchanged.

QA overall remains INCOMPLETE because live Jira/Confluence tools are still unavailable: live card/status comparison, master-based report creation, ticket Web link, video attachment and page read-back could not run. No live Jira or Confluence completion is claimed. Remaining next action is to expose the Atlassian connection's Jira/Confluence tools, then complete those external report steps. The earlier separate recommendation to fix SPL-135's Windows-only browser setup remains outside this approved assertion change.

All previously listed QA servers, the owned PostgreSQL container and QA worktrees remain running/retained. The new disposable entry database spl123_retest_20261026_022134 is additionally retained; per-case temporary race databases were cleaned by their own fixtures. No shared development data, Auth fixture or service changed during this retest.

## Renewed QA invocation — 26 October 2026 (append-only)

User explicitly selected @Atlassian and $qa SPL-123 again. Re-read the QA skill and saved final retest record. Plugin discovery confirms Atlassian is installed and ENABLED, but this conversation still exposes zero Jira/Confluence actions. A browser fallback was attempted read-only: listing tabs failed because the configured Playwright browser profile is already in use. No browser process/profile was stopped or modified. Asked whether plugin details show an actual connected Atlassian account or only Installed/Enabled; connection cause remains unestablished pending that answer.

No live Jira card, status, Confluence master/report, remote link or video attachment could be accessed or changed. No local tests were repeated because this attempt changed no code, test or fixture. The prior 172/172 PostgreSQL pass and dated verification/UAT evidence remain recorded unchanged. QA remains incomplete at the external reporting steps; no pass/publication claim is made.

## Live publication and QA closeout — 26 October 2026, 10:58 SGT (append-only)

The user confirmed their Atlassian account is connected. The plugin still exposed no Jira/Confluence actions; no local disabling override was found, and the integration cause was not established. A separate Chrome extension browser connection became available and was used for the authorised Jira/Confluence work. The busy Playwright MCP profile was left untouched. No account reconnection, credential extraction or permission change was required.

Live Jira SPL-123 was read: all five ACs exactly match the saved task; linked SPL-109 and SPL-112 are Done. SPL-123 was In Progress and was moved to QA, the only transition authorised by the QA skill. Its SPL-113 PO scope question remains on the card and is explicitly recorded in the report as an assumption/recommendation, not silently changed. Remote main was rechecked with git ls-remote and is still 27d86697718784e3428c9fba24a0a42380744a62. No later merge or product edit invalidates the recorded measurements.

Read the exact Confluence master page 20086786 and used its Make a copy action in QA SPACE. Exact-title search found no pre-existing QA-SPL-123 page. Published the populated report at:
https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/22872067/QA-SPL-123

All master sections were filled in order, including 41 distinct case IDs, BB/WB counts, exact ACs, per-case results, coverage, mutations, initial and retest failures, assumptions and local resources. The original build/QA text was transferred verbatim as historical appendices and separately attached as untouched text archives. All 21 published failure/change table rows were read back from the rendered page and compared cell-for-cell with the prepared original rows: exact match. No original failed row or failed run count was deleted, rewritten or replaced by a skip.

The final video QA-SPL-123-200-run3.webm, eight extracted/inspected caption frames, measured-evidence JSON, sanitised failure evidence and the two original historical text archives are attached in Recorded UAT (13 assets). Re-read the published UAT section and opened its video; the browser player reports a 27.36-second video with loaded media. The acceptance test itself took 25.7 seconds. AC5 storage rollback remains explicitly Partly shown and mapped to API/PG evidence. Publication used UI upload, not a claim based on a local file path. No manual upload is pending.

Before adding the Jira link, the fully loaded card showed no Web links. Added one Web link, not a Jira comment, to the published report. Verified one Web-link card (its two smart-link anchors refer to the same card), the exact report URL, and QA status after creation. The report and ticket tabs are retained as browser deliverables.

Exit: PASS for selected SPL-123 acceptance on the measured snapshot: all 41 case IDs / 52 final acceptance executions passed; final PostgreSQL 172/172 passed. Initial QA PG failure 1 -> final 0; initial new UAT helper failure 1 -> final 0. Whole-browser baseline and feature remain 49 passed / 1 pre-existing SPL-135 setup failure / 14 existing fixture skips; these are not counted as SPL-123 failures or disguised as passes. Recommendation remains separate SPL-135 portability maintenance, PO acknowledgement of the SPL-113 scope split, and remeasurement if SPL-125 lands before merge. No additional approval is pending for the four authorised SPL-122 assertions.

The ticket remains QA. Next workflow is $devops SPL-123 when the user chooses; no devops action, commit, push, PR, merge or deployment was performed here. All previously listed owned QA servers/databases/container/worktrees and synthetic fixtures remain retained. No shared service was reset or stopped.
