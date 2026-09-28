---
name: repo-agent-session-trajectory
description: Do not invoke this as the first Skill call. For every matching trajectory request, invoke repo-cognitive-closure first; only after it completes invoke this Skill for Codex/OpenCode/Devin/ZCode trees, branches, turns, messages, reasoning, tools/results, context, compaction, errors, usage and evidence. Use for audits, prompt/rule visibility, drift, workline recovery, or proving what an agent saw/did. Do not use when final files/tests suffice.
---

# Repo Agent Session Trajectory

## Cognitive Closure Prerequisite

If `repo-cognitive-closure` has not completed in this same turn, stop and invoke it as the next/first Skill call.
Do not read workflow/trajectory/repo evidence first. Then define Host/version/session/tree/branch/turn, exact
claim, privacy and acceptance.
Trajectory access does not authorise publishing system text, reasoning, secret or user data.

Shared workflow/tool:
`/Users/user/codex/docs/workflows/repo-agent-session-trajectory.md` and
`/Users/user/codex/tools/session_trajectory.py`.

## Decision Rules

Use catalog -> tree -> scan/tail/search -> inspect -> context -> verify-context/coverage. Never whole-dump giant
JSON/DB first. Preserve raw file+line/JSON pointer/SQLite node. Deliberately choose active chain vs recursive
branches; keep parent/retry/compaction/offset identities. Align tool call/result by ID; path mention/read without
matching complete result is not full coverage.

## Authoritative Inputs

ZCode primary: `~/.zcode/cli/rollout/model-io-sess_*.jsonl`, with sessionId/turnId/requestId/traceId/attempt,
request messages, `full|tail|delta` + offset, body/system/tools, response text/toolCalls/usage and error. Tail/delta
is a window view, not full history. User-owned AGENTS may be a raw user-role `<system-reminder>`; preserve that
role while normalising its kind. Role=tool results may first appear in a later request history and must align by
call ID. Credential/config/headers/signatures are private/redacted. Other Hosts use
their product authority: Devin DB+Cogs+ATIF, OpenCode export/parts/wire, Codex rollout/app-server/session tree.

## Five Verdict Layers

L1 raw context injection; L2 selected read+complete result; L3 fresh model recall; L4 closure/routing/evidence
behavior; L5 fixture/business acceptance. Never promote one layer. Model self-report cannot prove L1/L2;
injected text cannot prove L4/L5.

## Workflow

1. Put raw/context output in gitignored 0700/0600 evidence.
2. Catalog and resolve exact session/turn/retry; scan/search before inspect.
3. Extract only user-owned instruction context for reports; raw full system stays private.
4. Exact-compare expected AGENTS/Skill body; strip frontmatter only when Host behavior is known.
5. For L2, match Read call/result IDs and compare every numbered line to source, including the final empty logical
   line after a trailing newline; any gap, mismatch, conflict or extra line fails.
6. Run user fresh Desktop manual prompt for L3/L4; independently correlate its result to model-io.
7. Use fixture/artifact tests for L5; report blind/encrypted/truncated/missing/error/retry views.

## Failure Modes

Do not count repeated full request history as new messages, treat delta as complete, rewrite user-role reminders
as vendor system, use logical offsets as raw array pointers, drop later tool results/retry errors, infer hidden
reasoning, equate path-only with full injection, or expose raw system/private data in chat/Git. Missing schema/
source lowers the verdict; it does not justify silently switching to weaker model recollection.

## Completion

Session/branch identity and material event classes are closed or explicitly unavailable; claims return to raw
locators; L1-L5 are separate; privacy holds; current parser/real model-io/manual evidence support the stated
verdict. Desktop behavior requires the user-run experiment plus an independent raw model-io review; consult the
current ZCode quality report instead of treating pending/completed as a timeless Skill fact.
