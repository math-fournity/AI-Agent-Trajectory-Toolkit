#!/usr/bin/env python3
"""Validate that the cross-host capability index covers current repository assets."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "CAPABILITY_INDEX.md"
EXCLUDED_ROOT_DOCS = {
    "AGENTS.md",
    "CAPABILITY_INDEX.md",
    "EVOLUTION.md",
    "MEMORY.md",
    "README.md",
    "feature-list.md",
    "rulings.md",
}
REQUIRED_EXTERNAL_PATHS = [
    Path("/Users/user/codex/tools/agent_session_broker.py"),
    Path("/Users/user/codex/tools/session_trajectory.py"),
    Path("/Users/user/devin/router/run_router.py"),
    Path("/Users/user/glm5.2-math-worktree-aistudio/corpus_governance/broker.py"),
    Path("/Users/user/AI-Math-Competition-Problem-Solving-System/scripts/test_acp_signals.py"),
    Path("/Users/user/.config/opencode/skills/opencode-acp-protocol/SKILL.md"),
    Path("/Users/user/.config/opencode/skills/opencode-subscription-bridge/SKILL.md"),
    Path("/Users/user/work-with-pi/bin/opencode-subscriptions.mjs"),
    Path("/Users/user/work-with-pi/lib/subscription-bridge.mjs"),
    Path("/Users/user/zcode/tests/manual/ZCode治理安装验收提示词.md"),
]


def main() -> int:
    violations: list[str] = []
    text = INDEX.read_text(encoding="utf-8")
    ids = re.findall(r"`(CAP-[A-Z0-9-]+)`", text)
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    # IDs are intentionally repeated when a detailed inventory points back to a fast-route entry.
    definitions = re.findall(r"^\| `(CAP-[A-Z0-9-]+)` \|", text, flags=re.MULTILINE)
    duplicate_definitions = sorted({item for item in definitions if definitions.count(item) > 1})
    if duplicate_definitions:
        violations.append(f"duplicate capability definitions: {duplicate_definitions}")
    if len(set(definitions)) < 10:
        violations.append(f"too few capability definitions: {len(set(definitions))}")

    root_assets = sorted(
        path.name
        for path in ROOT.glob("*.md")
        if path.name not in EXCLUDED_ROOT_DOCS
    )
    script_assets = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "scripts").glob("*.py")
        if path.name != "validate_capability_index.py"
    )
    for asset in root_assets + script_assets:
        if f"`{asset}`" not in text:
            violations.append(f"asset missing from index inventory: {asset}")
    for path in REQUIRED_EXTERNAL_PATHS:
        if not path.exists():
            violations.append(f"required external path missing: {path}")
        if str(path) not in text and str(path.parent) not in text:
            violations.append(f"required external path not routed: {path}")
    required_markers = [
        "Codex, OpenCode, Devin CLI, and ZCode",
        "routing registry, not a bundle",
        "Current direct Devin external bodies: 14",
        "CAP-ACP-ACTIVITY-BLOCKS",
        "CAP-OPENCODE-SUBSCRIPTION-BRIDGE",
        "opencode-subscription-bridge.md",
        "scripts/acp_activity_blocks.py",
        "raw remains authoritative",
        "DO_NOT_LOAD",
        "RUNTIME_OBSERVED",
        "One-shot ZCode Desktop verification",
    ]
    for marker in required_markers:
        if marker not in text:
            violations.append(f"missing contract marker: {marker}")
    if duplicate_ids and not duplicate_definitions:
        # Repeated cross-references are expected; expose the count without failing.
        repeated_reference_count = len(duplicate_ids)
    else:
        repeated_reference_count = 0
    result = {
        "status": "PASS" if not violations else "FAIL",
        "capability_definitions": len(set(definitions)),
        "root_assets": len(root_assets),
        "script_assets": len(script_assets),
        "repeated_reference_ids": repeated_reference_count,
        "violations": violations,
    }
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
