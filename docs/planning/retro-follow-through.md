# Retrospective actions carried into later sprints

This evidence index distinguishes a planning commitment from an implemented process change
and a participant-reported outcome. Meeting times are Singapore time; timestamps are offsets
within each recording.

## Source records

| Source | Location / recording identity |
| --- | --- |
| Sprint 2 retrospective | [Confluence 4Ls record](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/SPGT3/pages/12353539) |
| Sprint 3 planning | 6 October 2026, 22:06; recording folder `2026-10-06 22.06.06 Ryan LEE Bing En's Zoom Meeting`, audio `audio1138179182.m4a`, duration 18:57 |
| Sprint 3 retrospective | 18 October 2026, 21:32:16; duration 19:01; recording package `Sprint 3 Retro.zip` |
| Sprint 4 backlog grooming | 18 October 2026, 22:05:20; duration 19:52; next pre-planning discussed for Tuesday, 20 October |

The local recording-derived notes and automatic transcripts are under
`output/sprint-3-meetings/00-planning`, `02-retro` and `03-grooming`. The summaries below were
cross-checked against those transcripts, not independently transcribed from audio. Automatic
transcription contains errors, especially in names. Recordings are organised under the sprint documentation in the submission. The excerpts below preserve the useful evidence without requiring
the generated `output/` directory in the source archive.

## 1. Sprint 2 to Sprint 3: daily updates and blocker escalation

**Retro action.** Sprint 2 asked each person to check and report their own stand-up status instead
of waiting to be asked. The action belongs to the whole team and is marked ongoing in Confluence.

**Next planning.** Sprint 3 planning, 18:21–18:45, restated the working agreement: raise problems
to the Scrum Master, who informs the PO; continue the existing buddy system; maintain daily
updates. At 18:31–18:36 the transcript says, “Remember your buddy system again … and to keep
track of that.” The final daily-update reminder is rendered imprecisely as “daily sprints” by
the automatic transcript; the meeting notes interpret it as daily stand-ups.

**Review of the outcome.** Sprint 3 retrospective, 08:53–09:53, explicitly refers back to the
Sprint 2 self-check approach and says it did not work well during travel and school commitments.
Buddy accountability was proposed. At 15:36–16:13 the incoming Scrum Master committed to
individual check-ins to surface blockers.

**Conclusion:** the action was carried into the next planning and evaluated at the next retro.
It was not fully achieved; the team adjusted its approach for Sprint 4. There is no verified
Sprint 4 attendance result in these records.

## 2. Sprint 3 to Sprint 4 preparation: clarify AC before allocation

**Retro action.** Sprint 3 retrospective, 10:41–11:49, identified overlapping or insufficiently
specific AC as a source of unnecessary work. At 14:34–15:00, the team agreed to clarify ticket
boundaries together, using buddy checks, before the next sprint.

**Next sprint preparation.** Sprint 4 grooming later that evening left stories unassigned and
unestimated until pre-planning. At 19:10–19:31 the incoming PO asked everyone to read the tickets
over the next one or two days and “negotiate the acceptance criteria” before Tuesday's assignment
and story-point estimation. Earlier discussion left specific questions for clarification, including
notification preferences versus recipient routing and safety-review transitions.

**Conclusion:** the retro action became an explicit preparation step before Sprint 4 allocation
and estimation. This is evidence from grooming, not final planning minutes or proof that every
story received a completed buddy review.

## 3. Sprint 3 to Sprint 4 delivery: standardise shared workflows

**Retro action.** Sprint 3 retrospective, 12:24–13:23 and 15:00–15:14, called for consistent
development/QA/DevOps prompts and clearer mapping between UAT video segments and AC.

**Implementation.** On 20 October, [commit ae2c18f](https://github.com/Ryan-Lee-2000/ConnectSphere/commit/ae2c18f302de4a19da47d0fc5c5f95df6b593d4f)
introduced the shared build, QA, DevOps and PR-review skills, linked the QA/DevOps master
templates, and documented the workflow in `AGENTS.md` and `docs/development/workflow.md`.
[Commit dbc0166](https://github.com/Ryan-Lee-2000/ConnectSphere/commit/dbc0166b27f785b6bfb5c31419cc935ab4bff264)
aligned the QA skill's video-upload instructions with the shared QA template.
[Commit 3b4e7a2](https://github.com/Ryan-Lee-2000/ConnectSphere/commit/3b4e7a2307d54dc71e059a553f948b680bfbad73)
standardised test-case identifiers and AC comments in the testing guide and skills.

**Conclusion:** these dated repository changes implement the type of standardisation requested
in the retro. The connection is supported by matching content and timing; the commits do not
explicitly cite the retrospective. They establish a shared workflow, not universal compliance
or a measured improvement in test quality. No final Sprint 4 planning record was available to
establish a separate planning decision for this action.

## 4. Sprint 2 to Sprint 3 review: UAT evidence and responsive PR reviews

**Retro actions.** Sprint 2 requested local/UAT happy-path evidence, explicit AC walkthroughs
and more initiative reviewing teammates' PRs.

**Next retrospective.** Sprint 3 retrospective revisited these actions at 00:00–00:46. At
06:46–07:03 participants positively described UAT video evidence and more responsive, detailed
PR reviews. At 10:07–10:30 they reported that Playwright MCP helped with manual-flow verification.
At 13:05–13:23 they requested a further improvement: identify which video portions cover each AC.

**Conclusion:** the next retro reports adoption and identifies the next refinement. This is
participant-reported progress, not a measured time saving or proof of every story's coverage.
The Sprint 3 planning recording does not explicitly establish these actions as planning decisions.

## Evidence boundaries

The Sprint 2 QA run-link and test-comment actions are recalled in the Sprint 3 retrospective,
but it does not verify their completion across all stories. Do not mark them universally closed.
These records do not establish closure of the later Sprint 4 follow-ups. A ceremony template requiring a retro recap is a working agreement, not
evidence that a particular meeting completed the recap.
