#!/usr/bin/env python3
"""Read and audit Devin CLI session trajectories without printing private content.

The authoritative live source is ``sessions.db``.  This tool follows
``sessions.main_chain_id`` through ``message_nodes.parent_node_id`` and also
walks the complete message forest, so branches and compaction ancestry are not
silently flattened.  Raw exports are opt-in and are written mode 0600 inside a
mode 0700 directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB = Path(
    os.environ.get(
        "DEVIN_SESSIONS_DB",
        "~/.local/share/devin/cli/sessions.db",
    )
).expanduser()


class TrajectoryError(RuntimeError):
    """A user-facing trajectory contract error."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_or_raw(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    return value


def open_db(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise TrajectoryError(f"sessions database not found: {resolved}")
    uri = f"file:{resolved}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise TrajectoryError(f"session not found: {session_id}")
    session = {key: json_safe(row[key]) for key in row.keys()}
    for key in ("cogs_json", "workspace_dirs", "metadata"):
        session[key] = json_or_raw(session.get(key))
    return session


def parse_node(row: sqlite3.Row) -> dict[str, Any]:
    message = json_or_raw(row["chat_message"])
    metadata = json_or_raw(row["metadata"])
    role = message.get("role") if isinstance(message, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return {
        "row_id": row["row_id"],
        "session_id": row["session_id"],
        "node_id": row["node_id"],
        "parent_node_id": row["parent_node_id"],
        "created_at": row["created_at"],
        "role": role,
        "content_bytes": len(content.encode("utf-8")) if isinstance(content, str) else 0,
        "chat_message": message,
        "metadata": metadata,
    }


def get_nodes(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT row_id, session_id, node_id, parent_node_id, chat_message, "
        "created_at, metadata FROM message_nodes WHERE session_id = ? "
        "ORDER BY node_id",
        (session_id,),
    ).fetchall()
    return [parse_node(row) for row in rows]


def active_chain(
    session: dict[str, Any], nodes: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    by_id = {node["node_id"]: node for node in nodes}
    tip = session.get("main_chain_id")
    if tip is None:
        if not nodes:
            return [], ["session has no main_chain_id and no message nodes"]
        tip = max(by_id)
        warnings.append("main_chain_id is null; inferred the maximum node_id")
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    current = tip
    while current is not None:
        if current in seen:
            warnings.append(f"cycle detected at node_id={current}")
            break
        seen.add(current)
        node = by_id.get(current)
        if node is None:
            warnings.append(f"active-chain node missing: node_id={current}")
            break
        chain.append(node)
        current = node["parent_node_id"]
    chain.reverse()
    return chain, warnings


def forest_details(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {node["node_id"]: node for node in nodes}
    children: dict[int | None, list[int]] = defaultdict(list)
    orphans: list[int] = []
    for node in nodes:
        parent = node["parent_node_id"]
        if parent is not None and parent not in by_id:
            orphans.append(node["node_id"])
        children[parent].append(node["node_id"])
    for values in children.values():
        values.sort()
    roots = sorted(
        node["node_id"]
        for node in nodes
        if node["parent_node_id"] is None or node["parent_node_id"] not in by_id
    )
    branch_points = {
        str(parent): values
        for parent, values in children.items()
        if parent is not None and len(values) > 1
    }
    return {
        "roots": roots,
        "orphans": sorted(orphans),
        "children": children,
        "branch_points": branch_points,
    }


def walk_forest(nodes: list[dict[str, Any]], active_ids: set[int]) -> list[dict[str, Any]]:
    by_id = {node["node_id"]: node for node in nodes}
    details = forest_details(nodes)
    children = details["children"]
    output: list[dict[str, Any]] = []
    visited: set[int] = set()

    def visit(node_id: int, depth: int) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = by_id[node_id]
        output.append(
            {
                "node_id": node_id,
                "parent_node_id": node["parent_node_id"],
                "depth": depth,
                "active": node_id in active_ids,
                "role": node["role"],
                "content_bytes": node["content_bytes"],
                "created_at": node["created_at"],
                "child_count": len(children.get(node_id, [])),
            }
        )
        for child in children.get(node_id, []):
            visit(child, depth + 1)

    for root in details["roots"]:
        visit(root, 0)
    for node_id in sorted(by_id):
        if node_id not in visited:
            visit(node_id, 0)
    return output


def compact_prior_ids(value: Any) -> list[int]:
    found: list[int] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key == "compact/prior_node_ids" and isinstance(child, list):
                    found.extend(x for x in child if isinstance(x, int))
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def summarize(
    session: dict[str, Any], nodes: list[dict[str, Any]], chain: list[dict[str, Any]], warnings: list[str]
) -> dict[str, Any]:
    details = forest_details(nodes)
    roles = Counter(str(node["role"] or "unknown") for node in nodes)
    compact_refs: list[dict[str, Any]] = []
    for node in nodes:
        ids = compact_prior_ids(node.get("metadata"))
        ids.extend(compact_prior_ids(node.get("chat_message")))
        if ids:
            compact_refs.append({"node_id": node["node_id"], "prior_node_ids": sorted(set(ids))})
    lock_path = DEFAULT_DB.parent / "session_locks" / f"{session['id']}.lock"
    return {
        "schema_version": "devin-trajectory-audit/v1",
        "session": {
            key: session.get(key)
            for key in (
                "id",
                "working_directory",
                "backend_type",
                "model",
                "agent_mode",
                "created_at",
                "last_activity_at",
                "title",
                "main_chain_id",
                "hidden",
            )
        },
        "node_count": len(nodes),
        "active_chain_count": len(chain),
        "roles": dict(sorted(roles.items())),
        "roots": details["roots"],
        "orphans": details["orphans"],
        "branch_points": details["branch_points"],
        "compaction_references": compact_refs,
        "lock_path": str(lock_path),
        "lock_exists": lock_path.exists(),
        "warnings": warnings,
    }


def message_content(node: dict[str, Any]) -> str | None:
    message = node.get("chat_message")
    if not isinstance(message, dict):
        return None
    value = message.get("content")
    return value if isinstance(value, str) else None


def secure_write(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def write_json(path: Path, value: Any) -> None:
    secure_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    payload = "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values)
    secure_write(path, payload.encode("utf-8"))


def prepare_output_dir(path: Path, force: bool) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        raise TrajectoryError(f"output path is not a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(resolved, 0o700)
    if any(resolved.iterdir()) and not force:
        raise TrajectoryError(f"output directory is not empty; pass --force to replace named exports: {resolved}")
    return resolved


def export_session(
    session: dict[str, Any],
    nodes: list[dict[str, Any]],
    chain: list[dict[str, Any]],
    warnings: list[str],
    output_dir: Path,
    force: bool,
) -> dict[str, Any]:
    destination = prepare_output_dir(output_dir, force)
    system_messages: list[dict[str, Any]] = []
    raw_parts: list[str] = []
    offset = 0
    boundaries: list[dict[str, Any]] = []
    for node in chain:
        if node.get("role") != "system":
            continue
        content = message_content(node)
        if content is None:
            continue
        encoded = content.encode("utf-8")
        if raw_parts:
            offset += 1  # the literal newline separator below
        start = offset
        end = start + len(encoded)
        boundaries.append(
            {
                "node_id": node["node_id"],
                "start_byte": start,
                "end_byte": end,
                "bytes": len(encoded),
                "sha256": sha256_bytes(encoded),
            }
        )
        offset = end
        raw_parts.append(content)
        system_messages.append(node)
    raw_context = "\n".join(raw_parts).encode("utf-8")
    summary = summarize(session, nodes, chain, warnings)
    summary["system_context"] = {
        "message_count": len(system_messages),
        "join_separator": "\\n",
        "bytes": len(raw_context),
        "sha256": sha256_bytes(raw_context),
        "boundaries": boundaries,
    }
    write_json(destination / "trajectory-summary.json", summary)
    write_json(destination / "session.json", session)
    write_json(destination / "context-cogs.json", session.get("cogs_json"))
    write_jsonl(destination / "nodes.jsonl", nodes)
    write_jsonl(destination / "active-main-chain.jsonl", chain)
    write_jsonl(destination / "active-system-messages.jsonl", system_messages)
    secure_write(destination / "active-system-context.raw.txt", raw_context)
    return {
        "output_dir": str(destination),
        "files": sorted(path.name for path in destination.iterdir()),
        "node_count": len(nodes),
        "active_chain_count": len(chain),
        "system_message_count": len(system_messages),
        "system_context_bytes": len(raw_context),
        "system_context_sha256": sha256_bytes(raw_context),
        "warnings": warnings,
    }


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    return text[end + 5 :]


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n")


def audit_injection(chain: list[dict[str, Any]], sources: list[Path]) -> dict[str, Any]:
    context = "\n".join(
        content
        for node in chain
        if node.get("role") == "system"
        for content in [message_content(node)]
        if content is not None
    )
    normalized_context = normalized(context)
    results: list[dict[str, Any]] = []
    for source in sources:
        resolved = source.expanduser().resolve()
        if not resolved.is_file():
            results.append({"path": str(resolved), "mode": "source-missing"})
            continue
        raw = resolved.read_text(encoding="utf-8", errors="strict")
        body = strip_frontmatter(raw)
        candidates = [raw]
        if body != raw:
            candidates.append(body)
        full = any(normalized(candidate) in normalized_context for candidate in candidates if candidate)
        path_seen = str(resolved) in context
        prefix_seen = any(
            len(normalized(candidate)) >= 256
            and normalized(candidate)[:256] in normalized_context
            for candidate in candidates
        )
        basename_seen = resolved.name in context
        if full:
            mode = "full"
        elif prefix_seen:
            mode = "truncated-or-prefix"
        elif path_seen:
            mode = "path-only"
        elif basename_seen:
            mode = "mismatch-or-name-only"
        else:
            mode = "missing"
        results.append(
            {
                "path": str(resolved),
                "source_bytes": len(raw.encode("utf-8")),
                "source_sha256": sha256_bytes(raw.encode("utf-8")),
                "body_bytes": len(body.encode("utf-8")),
                "body_sha256": sha256_bytes(body.encode("utf-8")),
                "mode": mode,
            }
        )
    return {
        "schema_version": "devin-injection-audit/v1",
        "system_context_bytes": len(context.encode("utf-8")),
        "system_context_sha256": sha256_bytes(context.encode("utf-8")),
        "sources": results,
        "counts": dict(sorted(Counter(item["mode"] for item in results).items())),
    }


def audit_reads(chain: list[dict[str, Any]], expected: list[Path]) -> dict[str, Any]:
    def ranges(values: set[int]) -> list[list[int]]:
        if not values:
            return []
        ordered = sorted(values)
        output: list[list[int]] = []
        start = previous = ordered[0]
        for value in ordered[1:]:
            if value == previous + 1:
                previous = value
                continue
            output.append([start, previous])
            start = previous = value
        output.append([start, previous])
        return output

    tool_nodes: list[tuple[int, str]] = []
    tool_results: list[tuple[int, str]] = []
    all_message_text: list[str] = []
    for node in chain:
        message = node.get("chat_message")
        if not isinstance(message, dict):
            continue
        all_message_text.append(json.dumps(message, ensure_ascii=False, sort_keys=True))
        calls = message.get("tool_calls")
        if calls:
            tool_nodes.append((node["node_id"], json.dumps(calls, ensure_ascii=False, sort_keys=True)))
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            tool_results.append((node["node_id"], message["content"]))
    joined = "\n".join(all_message_text)
    results = []
    for path in expected:
        resolved = path.expanduser().resolve()
        exact = str(resolved)
        nodes = [node_id for node_id, payload in tool_nodes if exact in payload]
        result_records: list[dict[str, Any]] = []
        for node_id, content in tool_results:
            opening = re.search(
                r'<file-view\s+path="(?P<path>[^"]+)"\s+'
                r'start_line="(?P<start>\d+)"\s+end_line="(?P<end>\d+)"\s+'
                r'total_lines="(?P<total>\d+)">',
                content,
            )
            if not opening or opening.group("path") != exact:
                continue
            start = int(opening.group("start"))
            end = int(opening.group("end"))
            total = int(opening.group("total"))
            body = content[opening.end() :]
            body = body.split("</file-view>", 1)[0]
            numbered_lines: list[tuple[int, str]] = []
            parse_failed = False
            for raw_line in body.splitlines():
                if not raw_line.strip():
                    continue
                match = re.match(r"^\s*(\d+)\|(.*)$", raw_line)
                if not match:
                    parse_failed = True
                    continue
                numbered_lines.append((int(match.group(1)), match.group(2)))
            source_text = resolved.read_text(encoding="utf-8") if resolved.is_file() else None
            source_lines = source_text.splitlines() if source_text is not None else []
            visible_numbers = [number for number, _ in numbered_lines]
            reconstructed = "\n".join(text for _, text in numbered_lines)
            expected_visible_lines = [
                source_lines[number - 1]
                for number in visible_numbers
                if 1 <= number <= len(source_lines)
            ]
            expected_visible = "\n".join(expected_visible_lines)
            exact_line_numbers = {
                number
                for number, text in numbered_lines
                if 1 <= number <= len(source_lines) and source_lines[number - 1] == text
            }
            mismatch_line_numbers = sorted(
                number
                for number, text in numbered_lines
                if not (1 <= number <= len(source_lines) and source_lines[number - 1] == text)
            )
            claimed_numbers = set(range(start, end + 1))
            visible_set = set(visible_numbers)
            metadata_span_exact = (
                visible_numbers == list(range(start, end + 1))
                and len(visible_numbers) == len(visible_set)
            )
            content_exact = (
                source_text is not None
                and not parse_failed
                and metadata_span_exact
                and exact_line_numbers == claimed_numbers
            )
            full_span = start == 1 and end == total and (
                source_text is None or total == len(source_lines)
            )
            result_records.append(
                {
                    "node_id": node_id,
                    "start_line": start,
                    "end_line": end,
                    "total_lines": total,
                    "source_line_count": len(source_lines) if source_text is not None else None,
                    "visible_start_line": min(visible_numbers) if visible_numbers else None,
                    "visible_end_line": max(visible_numbers) if visible_numbers else None,
                    "visible_line_count": len(visible_numbers),
                    "metadata_span_exact": metadata_span_exact,
                    "full_span": full_span,
                    "content_exact": content_exact,
                    "exact_visible_line_count": len(exact_line_numbers),
                    "exact_line_ranges": ranges(exact_line_numbers),
                    "mismatch_line_numbers": mismatch_line_numbers,
                    "missing_from_claim_ranges": ranges(claimed_numbers - visible_set),
                    "reconstructed_sha256": sha256_bytes(reconstructed.encode("utf-8")),
                    "expected_visible_sha256": (
                        sha256_bytes(expected_visible.encode("utf-8")) if source_text is not None else None
                    ),
                    "parse_failed": parse_failed,
                    "_exact_line_numbers": sorted(exact_line_numbers),
                }
            )
        source_line_count = (
            len(resolved.read_text(encoding="utf-8").splitlines()) if resolved.is_file() else 0
        )
        combined_exact_lines = {
            number
            for record in result_records
            for number in record.pop("_exact_line_numbers")
        }
        combined_full_exact = (
            source_line_count > 0
            and combined_exact_lines == set(range(1, source_line_count + 1))
        )
        missing_combined_lines = set(range(1, source_line_count + 1)) - combined_exact_lines
        if combined_full_exact:
            coverage = "full-exact"
        elif any(record["full_span"] for record in result_records):
            coverage = "full-span-not-exact"
        elif result_records:
            coverage = "partial-result"
        elif nodes:
            coverage = "tool-call-without-matched-result"
        else:
            coverage = "not-read"
        results.append(
            {
                "path": exact,
                "exists": resolved.exists(),
                "mentioned_in_active_chain": exact in joined,
                "tool_call_nodes": nodes,
                "tool_call_count": len(nodes),
                "matched_tool_results": result_records,
                "combined_exact_line_ranges": ranges(combined_exact_lines),
                "combined_missing_line_ranges": ranges(missing_combined_lines),
                "combined_full_exact": combined_full_exact,
                "coverage": coverage,
            }
        )
    return {
        "schema_version": "devin-selected-read-audit/v1",
        "expected_count": len(results),
        "tool_covered_count": sum(bool(item["tool_call_count"]) for item in results),
        "full_exact_count": sum(item["coverage"] == "full-exact" for item in results),
        "mentioned_count": sum(bool(item["mentioned_in_active_chain"]) for item in results),
        "results": results,
        "boundary": "full-exact requires the union of actually visible numbered tool-result lines to match every current source line. file-view end_line/total_lines metadata and model EOF claims are not trusted when visible line numbers contain gaps.",
    }


def compare_recall(expected: Path, observed: Path) -> dict[str, Any]:
    left_bytes = expected.expanduser().resolve().read_bytes()
    right_bytes = observed.expanduser().resolve().read_bytes()
    left = normalized(left_bytes.decode("utf-8", errors="strict"))
    right = normalized(right_bytes.decode("utf-8", errors="strict"))
    left_lines = [line for line in left.split("\n") if line.strip()]
    right_counter = Counter(line for line in right.split("\n") if line.strip())
    matched = 0
    missing_line_numbers: list[int] = []
    for index, line in enumerate(left_lines, start=1):
        if right_counter[line] > 0:
            right_counter[line] -= 1
            matched += 1
        else:
            missing_line_numbers.append(index)
    return {
        "schema_version": "devin-context-recall-compare/v1",
        "expected": {
            "path": str(expected.expanduser().resolve()),
            "bytes": len(left_bytes),
            "sha256": sha256_bytes(left_bytes),
            "nonblank_lines": len(left_lines),
        },
        "observed": {
            "path": str(observed.expanduser().resolve()),
            "bytes": len(right_bytes),
            "sha256": sha256_bytes(right_bytes),
        },
        "byte_exact": left_bytes == right_bytes,
        "normalized_exact": left == right,
        "expected_block_in_observed": bool(left) and left in right,
        "observed_block_in_expected": bool(right) and right in left,
        "exact_nonblank_line_coverage": (
            matched / len(left_lines) if left_lines else 1.0
        ),
        "missing_expected_nonblank_line_numbers": missing_line_numbers,
        "boundary": "Line coverage detects verbatim recall only; it does not grade paraphrase or comprehension.",
    }


def emit(value: Any, output: Path | None = None) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        secure_write(output.expanduser().resolve(), payload.encode("utf-8"))
        sys.stdout.write(json.dumps({"output": str(output.expanduser().resolve())}) + "\n")


def command_sessions(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    try:
        clauses: list[str] = []
        values: list[Any] = []
        if args.cwd:
            clauses.append("working_directory = ?")
            values.append(str(Path(args.cwd).expanduser().resolve()))
        if not args.include_hidden:
            clauses.append("hidden = 0")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(args.limit)
        rows = conn.execute(
            "SELECT id, working_directory, model, agent_mode, created_at, last_activity_at, "
            "title, main_chain_id, hidden FROM sessions"
            + where
            + " ORDER BY created_at DESC LIMIT ?",
            values,
        ).fetchall()
        emit([{key: json_safe(row[key]) for key in row.keys()} for row in rows])
    finally:
        conn.close()


def load_session_bundle(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    conn = open_db(args.db)
    try:
        session = get_session(conn, args.session_id)
        nodes = get_nodes(conn, args.session_id)
    finally:
        conn.close()
    chain, warnings = active_chain(session, nodes)
    return session, nodes, chain, warnings


def command_summary(args: argparse.Namespace) -> None:
    session, nodes, chain, warnings = load_session_bundle(args)
    emit(summarize(session, nodes, chain, warnings), args.output)


def command_tree(args: argparse.Namespace) -> None:
    _, nodes, chain, _ = load_session_bundle(args)
    rows = walk_forest(nodes, {node["node_id"] for node in chain})
    if args.json:
        emit(rows, args.output)
        return
    lines = ["node parent depth active role content_bytes children"]
    for row in rows:
        lines.append(
            f"{row['node_id']} {row['parent_node_id']} {row['depth']} "
            f"{str(row['active']).lower()} {row['role']} {row['content_bytes']} {row['child_count']}"
        )
    payload = "\n".join(lines) + "\n"
    if args.output:
        secure_write(args.output.expanduser().resolve(), payload.encode("utf-8"))
    else:
        sys.stdout.write(payload)


def command_export(args: argparse.Namespace) -> None:
    session, nodes, chain, warnings = load_session_bundle(args)
    emit(export_session(session, nodes, chain, warnings, args.output_dir, args.force))


def command_injection(args: argparse.Namespace) -> None:
    _, _, chain, warnings = load_session_bundle(args)
    result = audit_injection(chain, args.sources)
    result["warnings"] = warnings
    emit(result, args.output)


def command_reads(args: argparse.Namespace) -> None:
    _, _, chain, warnings = load_session_bundle(args)
    result = audit_reads(chain, args.expected)
    result["warnings"] = warnings
    emit(result, args.output)


def command_compare(args: argparse.Namespace) -> None:
    emit(compare_recall(args.expected, args.observed), args.output)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--db", type=Path, default=DEFAULT_DB, help="read-only sessions.db path")
    commands = root.add_subparsers(dest="command", required=True)

    sessions = commands.add_parser("sessions", help="list recent sessions without message content")
    sessions.add_argument("--limit", type=int, default=20)
    sessions.add_argument("--cwd")
    sessions.add_argument("--include-hidden", action="store_true")
    sessions.set_defaults(handler=command_sessions)

    for name, help_text, handler in (
        ("summary", "summarize forest, active chain, branches and compaction", command_summary),
        ("tree", "recursively walk every branch without printing content", command_tree),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("session_id")
        sub.add_argument("--output", type=Path)
        if name == "tree":
            sub.add_argument("--json", action="store_true")
        sub.set_defaults(handler=handler)

    export = commands.add_parser("export", help="securely export raw forest, active chain and system context")
    export.add_argument("session_id")
    export.add_argument("output_dir", type=Path)
    export.add_argument("--force", action="store_true")
    export.set_defaults(handler=command_export)

    injection = commands.add_parser("audit-injection", help="classify source files in active system messages")
    injection.add_argument("session_id")
    injection.add_argument("sources", nargs="+", type=Path)
    injection.add_argument("--output", type=Path)
    injection.set_defaults(handler=command_injection)

    reads = commands.add_parser("audit-reads", help="locate exact expected paths in active-chain tool calls")
    reads.add_argument("session_id")
    reads.add_argument("expected", nargs="+", type=Path)
    reads.add_argument("--output", type=Path)
    reads.set_defaults(handler=command_reads)

    compare = commands.add_parser("compare-recall", help="compare raw context with a separately captured recall")
    compare.add_argument("expected", type=Path)
    compare.add_argument("observed", type=Path)
    compare.add_argument("--output", type=Path)
    compare.set_defaults(handler=command_compare)
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "limit", 1) < 1:
        raise TrajectoryError("--limit must be positive")
    args.handler(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TrajectoryError, sqlite3.Error, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
