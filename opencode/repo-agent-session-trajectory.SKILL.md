---
name: repo-agent-session-trajectory
description: Do not invoke this as the first Skill call. For every matching trajectory request, invoke repo-cognitive-closure first; only after it completes invoke this Skill to recursively analyse Codex, OpenCode, Devin, or ZCode session trees, branches, turns, messages, reasoning, tools/results, context, compaction, errors, usage, and evidence. Use for live/finished audits, ACP raw-block reconciliation, prompt/rule visibility, drift diagnosis, workline recovery, or proving what an agent saw/did. Do not use when final files/tests suffice.
---

# Repo Agent Session Trajectory

## Cognitive Closure Prerequisite

**Mandatory direct-invocation gate:** if `repo-cognitive-closure` has not already been fully executed in this
same turn, stop here and call `skill(repo-cognitive-closure)` as the next/first Skill tool call. Do not read the
canonical workflow, trajectory, repo files, or product docs first; return to this Skill only after closure.

Then define the claim to prove, target Host/version/session/tree/branch/turn, privacy boundary, required source
views and acceptance. Reading trajectory does not authorise publishing system instructions, private reasoning,
secrets or user data.

Canonical workflow:
`/Users/user/codex/docs/workflows/repo-agent-session-trajectory.md`. Fully read it before substantive
analysis. Shared tool: `/Users/user/codex/tools/session_trajectory.py`.

This Skill is the OpenCode runtime adapter for `CAP-TRAJ-MULTIHOST`, not its lifecycle registry. Before reusing,
designing, repairing, or behavior-testing the reader, resolve that exact ID in
`/Users/user/skills-devin/CAPABILITY_INDEX.md`; for OpenCode native export also resolve
`CAP-TRAJ-OPENCODE` and load `/Users/user/opencode/docs/ai/OpenCode-ACP与Trajectory适配.md`. A live Host
shape that causes a parser false negative must become a tested shared fixture and then be written back to the
Capability/product evidence; do not leave it only as a business-report caveat.

For live ACP raw text deltas, first select `CAP-ACP-ACTIVITY-BLOCKS` from
`/Users/user/skills-devin/CAPABILITY_INDEX.md` and run
`/Users/user/skills-devin/scripts/acp_activity_blocks.py`. Do not write an inline chunk parser. Blocks are
derived navigation evidence; retain raw locators and use native DB/export as a sibling post-run view.

## Use And Do Not Use

Use to reconstruct work across branches/compaction, inspect reasoning/tool/result/error/usage, verify user-owned
AGENTS/Skill/Plugin context, diagnose goal drift, compare system injection with selected reads, or review a live
agent via native export/DB/wire evidence. Do not load trajectory when code, files, tests and runtime state already
close the question. Do not demand hidden/encrypted reasoning or expose vendor/private prompts in ordinary output.

## Decision Rules

Move from low cost to decisive detail:

1. `catalog`: enumerate artifact identity, size and time;
2. `tree`: group Session tree, branches, turns and event counts recursively;
3. `scan`/`tail`/`search`: locate the material region with stable locators;
4. `inspect`: expand exactly one event;
5. `context`: extract system/user/assistant text with provenance to a private 0600 artifact;
6. `verify-context`/`coverage`: compare expected source and tool evidence.

Do not begin with a whole-file dump or one-off inline parser. Normalised events route back to a raw line/JSON
pointer/SQLite node. The normalised schema is never stronger evidence than the source record.

## Authoritative Inputs

- OpenCode: current 1.18.30 official export/session message+part schema, child/fork relationships and ACP wire.
  Historical 1.18.21 raw export stores the controller task in a user text part and native read input/output as
  `state.input.filePath` plus XML-like wrapper lines with `N: ` visible-source prefixes. Raw private export is
  required for exact L1/L2; sanitized export is a sibling structure/count view. Requalify this shape whenever the
  installed version changes; do not relabel the historical run as current evidence.
- Devin: live `~/.local/share/devin/cli/sessions.db` message forest and `main_chain_id`; canonical
  `devin_traj.py export` `session-db-full/` is an off-machine source, active chain by default and `--recursive`
  for the full forest. Thinking may be a string or an object containing a `thinking` body. ATIF export/transcript,
  ACP raw and summaries/logs are sibling views.
- Codex: `~/.codex/sessions/**/rollout-*.jsonl`, app-server thread/turn/item views and session tree/fork/spawn
  state. Encrypted reasoning is opaque or summary, never reconstructed by inference.
- ZCode: `~/.zcode/cli/rollout/model-io-sess_*.jsonl`, turn/request/attempt and `full/tail/delta` offsets, plus
  safe DB metadata only. User-owned AGENTS may be a raw user-role `<system-reminder>` and tool results may first
  appear in a later request history. Desktop tests use a manual prompt/result protocol.

Keep OpenCode product schemas in `~/opencode`; the shared tool owns only the common event/evidence contract.

## Five Independent Verdict Layers

- L1 context injection: raw request/system evidence contains the complete expected body;
- L2 selected read coverage: read call and matching result prove the complete selected file/range;
- L3 model recall: a fresh model can reproduce/export what it saw;
- L4 cognition execution: trajectory shows correct closure/routing/evidence/conflict behavior;
- L5 behavior verdict: artifacts/tests/runtime meet acceptance.

Model self-report cannot prove L1/L2. Full injected text cannot prove L4/L5. Give every layer its own status,
evidence locator, time/version and unknowns.

## Execution Workflow

1. Baseline any persistent output and choose a private gitignored evidence directory.
2. Catalog all plausible views and resolve exact Session/tree/branch identity before reading content.
3. Choose active chain vs recursive branch mode deliberately; preserve duplicate, retry, parent and compaction
   edges. For a Devin offline bundle, pass the directory directly to the shared reader; do not reconstruct an
   ad-hoc JSONL or query an unrelated local global DB.
4. Scan/tail/search, then inspect only material reasoning/message/tool/error/usage records.
5. When the source is ACP wire, distinguish transport chunk count from protocol activity blocks. Exact live
   boundary claims require bidirectional prompt/cancel evidence; incoming-only sources remain partial.
6. Align tool call/result by ID; a mentioned path without matching result is not a completed read. For numbered
   Read output, accept only Host-declared deterministic prefixes, compare every visible line to source, and
   distinguish physical content-line coverage (L2a) from strict terminal-newline representation (L2b). Gaps,
   conflicts, mismatches or unsupported terminators fail the corresponding layer.
7. Extract user-owned system/task context privately and compare the exact source body; classify `full`,
   `truncated`, `path-only`, or `missing`. Preserve raw role provenance when normalising a user reminder as
   instruction context.
8. If L3/L4 is required, run a separate fresh prompt without the expected answer, save the model result, then
   independently compare it with raw trajectory.
9. Validate L5 through business artifacts/tests/runtime rather than model self-evaluation.
10. Report blind views such as missing post-exit transcript, encrypted reasoning, stale DB, truncated export or
    unresolved branch identity.
11. Write back stable schema/product facts only to their proper authorities.

## Failure Modes

- Linearising a forest/session tree or counting repeated full context as new messages: rebuild the identity graph.
- Treating missing transcript during a live Session as no trajectory: use native export/DB/wire.
- Copying a Devin `session-db-full/` bundle that the shared reader cannot replay and calling it off-machine
  complete: require directory-source tree/scan/context replay with exact Session identity.
- Treating tail/delta as complete ZCode history: reconstruct with offsets and prior full records.
- Rewriting ZCode user-role reminders as vendor system, using logical offset as a raw JSON pointer, or dropping
  later tool results/retry errors: preserve raw provenance and call/result identities.
- Treating path-only rule discovery as full injection: fail L1.
- Treating read invocation without output/EOF as full coverage: fail or mark partial L2.
- Reasoning encrypted/redacted/missing: mark unavailable; never infer hidden chain of thought.
- Giant line/terminal truncation: stream records and use private `context --output`.
- ACP chunk flow is treated as semantic blocks, or DB/export is treated as its live upstream: rebuild with the
  canonical activity-block script, preserve raw, and report direction/boundary completeness plus sibling-view
  differences.
- Secret/signature/header leakage: redact reports, keep raw mode 0600, never commit.

## Outputs

Outputs may include a compact tree/timeline, raw locator map, private context artifact, expected-file comparison,
tool/path coverage and L1-L5 verdict table. Raw system/reasoning/tool content remains private unless the user
explicitly asks for an appropriately bounded artifact.

## Completion Criteria

Completion requires target identity and branch coverage closed, material claims traceable to raw records, every
necessary event class available or explicitly unavailable, privacy preserved, and no verdict layer promoted
beyond its evidence. Four parser fixtures plus current available-Host smoke are required for tool changes; a
Host-shape bug requires a fixture derived from that real shape and Capability/product write-back after tests pass.
For OpenCode 1.18.30, historical 1.18.29/1.18.21 L1/L2 success remains historical until a current native export/runtime
probe establishes the relevant current shape. ZCode behavioral acceptance requires the user-run Desktop package
plus an independent raw model-io audit.

## Repository Impact

Shared trajectory schema/tool/method changes belong in `~/codex`; cross-host capability bodies/scripts/index
belong in `/Users/user/skills-devin`; OpenCode schema and adapter facts belong in `~/opencode` before this
runtime; business conclusions remain in the business repo. Do not commit raw Session data or change Host
configuration merely to simplify an analysis.
