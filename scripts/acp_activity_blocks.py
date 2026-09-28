#!/usr/bin/env python3
"""Build protocol-level activity blocks from raw ACP JSON-RPC wire JSONL.

Raw wire remains authoritative.  Blocks are deterministic, rebuildable routing
views for live supervision and post-run audit.  Derived files contain model
text and therefore use private 0600 output inside a private directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


SCHEMA_VERSION = "acp_activity_block.v1"
TEXT_UPDATE_KINDS = {
    "agent_thought_chunk": "thinking",
    "agent_message_chunk": "message",
}
TOOL_UPDATE_KINDS = {
    "tool_call",
    "tool_call_update",
    "tool_call_content_chunk",
}


class ActivityBlockError(RuntimeError):
    """A user-facing ACP activity-block contract error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def message_text(update: dict[str, Any]) -> str:
    content = update.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return ""


def record_message(
    record: Any,
    *,
    line_number: int,
) -> tuple[dict[str, Any] | None, str | None, str]:
    if not isinstance(record, dict):
        return None, None, f"line:{line_number}"
    if isinstance(record.get("message"), dict):
        message = record["message"]
        direction = str(record.get("direction") or "") or None
        timestamp = str(
            record.get("timestamp")
            or record.get("t")
            or f"line:{line_number}"
        )
        return message, direction, timestamp
    if "jsonrpc" in record or "method" in record or "id" in record:
        return record, None, f"line:{line_number}"
    return None, str(record.get("direction") or "") or None, str(
        record.get("timestamp") or record.get("t") or f"line:{line_number}"
    )


class ActivityBlockAssembler:
    """Coalesce ACP text deltas using protocol boundaries only."""

    def __init__(self) -> None:
        self.current: dict[str, Any] | None = None
        self.closed_blocks: list[dict[str, Any]] = []
        self.block_sequence = 0
        self.raw_session_update_count = 0
        self.raw_text_chunk_count = 0
        self.raw_text_char_count = 0
        self.prompt_request_ids: set[Any] = set()
        self.boundary_counts: Counter[str] = Counter()
        self.protocol_event_counts: Counter[str] = Counter()

    @staticmethod
    def _message_id(update: dict[str, Any]) -> str | None:
        value = update.get("messageId", update.get("message_id"))
        return str(value) if value not in (None, "") else None

    def _start(
        self,
        *,
        kind: str,
        message_id: str | None,
        timestamp: str,
        raw_sequence: int,
    ) -> None:
        self.block_sequence += 1
        self.current = {
            "schema_version": SCHEMA_VERSION,
            "block_id": f"{kind}-{self.block_sequence:06d}",
            "kind": kind,
            "message_id": message_id,
            "started_at": timestamp,
            "updated_at": timestamp,
            "chunk_count": 0,
            "char_count": 0,
            "raw_event_start": raw_sequence,
            "raw_event_end": raw_sequence,
            "_parts": [],
        }

    def close_current(
        self,
        reason: str,
        *,
        timestamp: str | None = None,
    ) -> dict[str, Any] | None:
        if self.current is None:
            return None
        block = dict(self.current)
        text = "".join(block.pop("_parts"))
        block.update(
            {
                "closed_at": timestamp or block["updated_at"],
                "close_reason": reason,
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        if block.get("message_id") is None:
            block.pop("message_id", None)
        self.closed_blocks.append(block)
        self.boundary_counts[reason] += 1
        self.current = None
        return block

    def observe_update(
        self,
        update: dict[str, Any],
        *,
        timestamp: str,
        raw_sequence: int,
    ) -> None:
        update_kind = str(update.get("sessionUpdate") or "unknown")
        self.raw_session_update_count += 1
        block_kind = TEXT_UPDATE_KINDS.get(update_kind)
        if block_kind is None:
            if update_kind in TOOL_UPDATE_KINDS:
                self.close_current("tool_boundary", timestamp=timestamp)
            return

        message_id = self._message_id(update)
        if self.current is not None:
            current_message_id = self.current.get("message_id")
            if self.current.get("kind") != block_kind:
                self.close_current("stream_kind_changed", timestamp=timestamp)
            elif (
                current_message_id is not None
                and message_id is not None
                and current_message_id != message_id
            ):
                self.close_current("message_id_changed", timestamp=timestamp)

        if self.current is None:
            self._start(
                kind=block_kind,
                message_id=message_id,
                timestamp=timestamp,
                raw_sequence=raw_sequence,
            )
        elif self.current.get("message_id") is None and message_id is not None:
            self.current["message_id"] = message_id

        text = message_text(update)
        self.current["_parts"].append(text)
        self.current["chunk_count"] += 1
        self.current["char_count"] += len(text)
        self.current["updated_at"] = timestamp
        self.current["raw_event_end"] = raw_sequence
        self.raw_text_chunk_count += 1
        self.raw_text_char_count += len(text)

    def observe_message(
        self,
        message: dict[str, Any],
        *,
        direction: str | None,
        timestamp: str,
        raw_sequence: int,
    ) -> None:
        method = str(message.get("method") or "")
        if direction == "out":
            if method == "session/prompt":
                self.protocol_event_counts["prompt_request"] += 1
                self.close_current("prompt_request", timestamp=timestamp)
                if "id" in message:
                    self.prompt_request_ids.add(message.get("id"))
            elif method == "session/cancel":
                self.protocol_event_counts["cancel_request"] += 1
                self.close_current("cancel_requested", timestamp=timestamp)
            elif method == "session/close":
                self.protocol_event_counts["session_close_request"] += 1
                self.close_current("session_close_requested", timestamp=timestamp)
            return

        if method == "session/update":
            update = (message.get("params") or {}).get("update") or {}
            if isinstance(update, dict):
                self.observe_update(
                    update,
                    timestamp=timestamp,
                    raw_sequence=raw_sequence,
                )
            return
        if method == "_cognition.ai/thinking_complete":
            if self.current is not None and self.current.get("kind") == "thinking":
                self.close_current("thinking_complete", timestamp=timestamp)
            return
        if method == "_cognition.ai/agent_stopped":
            self.close_current("agent_stopped", timestamp=timestamp)
            return
        if direction is None and method == "session/prompt":
            self.protocol_event_counts["prompt_request"] += 1
            self.close_current("prompt_request", timestamp=timestamp)
            if "id" in message:
                self.prompt_request_ids.add(message.get("id"))
            return
        if direction is None and method == "session/cancel":
            self.protocol_event_counts["cancel_request"] += 1
            self.close_current("cancel_requested", timestamp=timestamp)
            return

        request_id = message.get("id")
        result = message.get("result")
        prompt_response = request_id in self.prompt_request_ids
        prompt_response = prompt_response or bool(
            isinstance(result, dict)
            and ("stopReason" in result or "usage" in result)
        )
        if prompt_response:
            self.protocol_event_counts["prompt_response"] += 1
            self.prompt_request_ids.discard(request_id)
            self.close_current(
                "prompt_error" if "error" in message else "prompt_response",
                timestamp=timestamp,
            )

    @staticmethod
    def _summary(block: dict[str, Any], *, tail_chars: int = 0) -> dict[str, Any]:
        result = {
            key: block.get(key)
            for key in (
                "schema_version",
                "block_id",
                "kind",
                "message_id",
                "started_at",
                "updated_at",
                "closed_at",
                "close_reason",
                "chunk_count",
                "char_count",
                "text_sha256",
                "raw_event_start",
                "raw_event_end",
            )
            if block.get(key) is not None
        }
        if tail_chars > 0:
            text = str(block.get("text") or "".join(block.get("_parts") or []))
            result["text_tail"] = text[-tail_chars:]
            result["text_tail_chars_returned"] = len(result["text_tail"])
        return result

    def snapshot(self, *, tail_chars: int = 0, recent_limit: int = 5) -> dict[str, Any]:
        recent_blocks = self.closed_blocks[-max(0, recent_limit) :]
        kind_counts = Counter(str(block.get("kind") or "unknown") for block in self.closed_blocks)
        if self.current is not None:
            kind_counts[str(self.current.get("kind") or "unknown")] += 1
        return {
            "schema_version": SCHEMA_VERSION,
            "current_block": (
                self._summary(self.current, tail_chars=tail_chars)
                if self.current is not None
                else None
            ),
            "recent_blocks": [
                self._summary(block, tail_chars=tail_chars) for block in recent_blocks
            ],
            "block_count": len(self.closed_blocks) + (1 if self.current else 0),
            "closed_block_count": len(self.closed_blocks),
            "kind_counts": dict(sorted(kind_counts.items())),
            "raw_session_update_count": self.raw_session_update_count,
            "raw_text_chunk_count": self.raw_text_chunk_count,
            "raw_text_char_count": self.raw_text_char_count,
            "boundary_counts": dict(sorted(self.boundary_counts.items())),
            "protocol_event_counts": dict(sorted(self.protocol_event_counts.items())),
            "block_visibility_boundary": (
                "protocol-level coalescing of host-emitted ACP deltas; "
                "not UI/NLP semantic segmentation"
            ),
        }


def parse_wire(
    source: str | Path,
    *,
    finalize: bool,
    allow_invalid: bool = False,
) -> tuple[ActivityBlockAssembler, dict[str, Any]]:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ActivityBlockError(f"ACP wire JSONL not found: {path}")
    assembler = ActivityBlockAssembler()
    raw_line_count = 0
    invalid_line_count = 0
    ignored_line_count = 0
    direction_counts: Counter[str] = Counter()
    last_timestamp = f"line:0"
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            raw_line_count += 1
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                invalid_line_count += 1
                if not allow_invalid:
                    raise ActivityBlockError(
                        f"invalid JSON at {path}:{line_number}: {exc}"
                    ) from exc
                continue
            message, direction, timestamp = record_message(
                record,
                line_number=line_number,
            )
            last_timestamp = timestamp
            direction_counts[direction or "unspecified"] += 1
            if message is None:
                ignored_line_count += 1
                continue
            assembler.observe_message(
                message,
                direction=direction,
                timestamp=timestamp,
                raw_sequence=line_number,
            )
    if finalize:
        assembler.close_current("source_eof", timestamp=last_timestamp)
    directions = set(direction_counts)
    if {"in", "out"}.issubset(directions):
        source_view = "bidirectional_wire"
        boundary_replay_status = "eligible_for_exact_live_boundary_replay"
    elif (
        assembler.protocol_event_counts.get("prompt_request", 0) > 0
        and assembler.protocol_event_counts.get("prompt_response", 0) > 0
    ):
        source_view = "directionless_full_wire_candidate"
        boundary_replay_status = "eligible_with_directionless_source_caveat"
    elif directions == {"in"}:
        source_view = "incoming_only_wire"
        boundary_replay_status = "partial_without_outbound_control_boundaries"
    else:
        source_view = "direction_unspecified_or_partial"
        boundary_replay_status = "partial_without_proven_outbound_control_boundaries"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "source_path": str(path),
        "source_size_bytes": path.stat().st_size,
        "source_sha256": sha256_file(path),
        "source_mode": oct(stat.S_IMODE(path.stat().st_mode)),
        "raw_line_count": raw_line_count,
        "invalid_line_count": invalid_line_count,
        "ignored_line_count": ignored_line_count,
        "direction_counts": dict(sorted(direction_counts.items())),
        "source_view": source_view,
        "boundary_replay_status": boundary_replay_status,
        "finalized": finalize,
    }
    return assembler, receipt


def ensure_private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = stat.S_IMODE(path.parent.stat().st_mode)
    if mode & 0o077:
        raise ActivityBlockError(
            f"output directory must be private (0700 or stricter): {path.parent} mode={oct(mode)}"
        )


def write_private_blocks(path: Path, blocks: list[dict[str, Any]], *, force: bool) -> None:
    ensure_private_parent(path)
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_TRUNC if force else os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ActivityBlockError(
            f"output exists; pass --force only after preserving the prior receipt: {path}"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for block in blocks:
            handle.write(json.dumps(block, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def build_blocks(
    source: str | Path,
    output: str | Path,
    *,
    force: bool = False,
    allow_invalid: bool = False,
) -> dict[str, Any]:
    requested_destination = Path(output).expanduser()
    if requested_destination.is_symlink():
        raise ActivityBlockError(f"output must not be a symlink: {requested_destination}")
    assembler, receipt = parse_wire(
        source,
        finalize=True,
        allow_invalid=allow_invalid,
    )
    destination = requested_destination.resolve()
    if destination == Path(receipt["source_path"]):
        raise ActivityBlockError("output must differ from the raw source path")
    write_private_blocks(destination, assembler.closed_blocks, force=force)
    snapshot = assembler.snapshot(tail_chars=0, recent_limit=0)
    receipt.update(snapshot)
    receipt.update(
        {
            "output_path": str(destination),
            "output_sha256": sha256_file(destination),
            "output_size_bytes": destination.stat().st_size,
            "output_mode": oct(stat.S_IMODE(destination.stat().st_mode)),
        }
    )
    return receipt


def summary(
    source: str | Path,
    *,
    tail_chars: int = 0,
    recent_limit: int = 5,
    allow_invalid: bool = False,
) -> dict[str, Any]:
    assembler, receipt = parse_wire(
        source,
        finalize=False,
        allow_invalid=allow_invalid,
    )
    receipt.update(
        assembler.snapshot(
            tail_chars=max(0, tail_chars),
            recent_limit=max(0, recent_limit),
        )
    )
    return receipt


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Build deterministic protocol-level blocks from ACP raw wire JSONL."
    )
    subparsers = root.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser(
        "summary",
        help="read a live or finished wire and return aggregate metadata",
    )
    summary_parser.add_argument("source")
    summary_parser.add_argument("--tail-chars", type=int, default=0)
    summary_parser.add_argument("--recent", type=int, default=5)
    summary_parser.add_argument("--allow-invalid", action="store_true")

    build_parser = subparsers.add_parser(
        "build",
        help="write finalized private activity_blocks.jsonl and print a receipt",
    )
    build_parser.add_argument("source")
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--force", action="store_true")
    build_parser.add_argument("--allow-invalid", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "summary":
            result = summary(
                args.source,
                tail_chars=args.tail_chars,
                recent_limit=args.recent,
                allow_invalid=args.allow_invalid,
            )
        else:
            result = build_blocks(
                args.source,
                args.output,
                force=args.force,
                allow_invalid=args.allow_invalid,
            )
    except (ActivityBlockError, OSError, ValueError) as exc:
        print(f"acp_activity_blocks: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
