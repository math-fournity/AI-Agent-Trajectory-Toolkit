#!/usr/bin/env python3
"""zcode_traj.py — ZCode model-io JSONL 层次化遍历工具。

两层遍历设计：
  1. scan   — 高层次遍历，输出每条记录的紧凑概览（不展开 messages），带 idx 定位参数
  2. inspect — 用 idx 深层次定位某条记录，展开消息结构 / reasoning / toolCalls / error 细节

用法：
  zcode_traj.py scan   <jsonl> [--json] [--turn <turnId>]
  zcode_traj.py inspect <jsonl> <idx> [--reasoning] [--tool-input] [--msg <N>] [--truncate <N>]

详见 /Users/user/skills-devin/zcode-trajectory.md
"""
import json
import sys
import argparse
from pathlib import Path


# ── 通用工具 ──────────────────────────────────────────────────────────────────

def _head(s, n=60):
    if s is None:
        return ""
    s = str(s).replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


def _tool_names(tool_calls):
    """从 response.toolCalls 或 assistant.toolCalls 提取工具名列表。"""
    if not tool_calls:
        return []
    return [tc.get("name", "?") for tc in tool_calls if isinstance(tc, dict)]


def _iter_records(path):
    """流式逐行读取 jsonl，yield (idx, record)。不缓存——单行可能几 MB。"""
    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield idx, json.loads(line)
            except json.JSONDecodeError as e:
                yield idx, {"_parse_error": str(e)}


def _get_msg_list(rec):
    """取逻辑消息列表：优先 request.messages，其次 request.body.messages。"""
    req = rec.get("request", {})
    msgs = req.get("messages")
    if msgs is not None:
        return msgs
    body = req.get("body", {})
    return body.get("messages", [])


def _part_summary(p):
    """单个 content part 的紧凑摘要。"""
    if not isinstance(p, dict):
        return str(type(p).__name__)
    t = p.get("type", "?")
    if t == "text":
        return f"text({_head(p.get('text', ''), 40)})"
    if t == "reasoning":
        return f"reasoning({len(p.get('text', ''))})"
    if t == "thinking":
        return f"thinking({len(p.get('thinking', ''))})"
    if t == "tool_use":
        return f"tool_use({p.get('name', '?')})"
    if t == "tool_result":
        return "tool_result"
    if t == "redacted_thinking":
        return "redacted_thinking"
    return t


def _msg_summary(msg, indent="  "):
    """单条消息的结构摘要（不展开全文）。"""
    role = msg.get("role", "?")
    c = msg.get("content")
    if isinstance(c, str):
        cdesc = f"str({len(c)})"
    elif isinstance(c, list):
        cdesc = "[" + ",".join(_part_summary(p) for p in c) + "]"
    elif c is None:
        cdesc = "None"
    else:
        cdesc = str(type(c).__name__)
    extras = []
    if msg.get("toolCalls"):
        extras.append(f"toolCalls=[{','.join(_tool_names(msg['toolCalls']))}]")
    if msg.get("toolCallId"):
        extras.append(f"toolCallId={msg['toolCallId'][:16]}")
    if msg.get("toolName"):
        extras.append(f"toolName={msg['toolName']}")
    if msg.get("isError"):
        extras.append("isError=True")
    if msg.get("cacheControl"):
        extras.append("cache=ephemeral")
    extra_str = (" " + " ".join(extras)) if extras else ""
    return f"{indent}role={role} content={cdesc}{extra_str}"


# ── scan 子命令 ───────────────────────────────────────────────────────────────

def cmd_scan(args):
    path = args.jsonl
    if not Path(path).is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1

    turn_filter = getattr(args, "_turn_filter", None) or args.turn
    rows = []
    for idx, rec in _iter_records(path):
        if turn_filter and not str(rec.get("turnId", "")).startswith(turn_filter):
            continue
        if "_parse_error" in rec:
            row = {"idx": idx, "error": "parse_error", "detail": rec["_parse_error"]}
            rows.append(row)
            if args.json:
                print(json.dumps(row, ensure_ascii=False))
            else:
                print(f"{idx:>4}  PARSE_ERROR  {rec['_parse_error'][:80]}")
            continue

        req = rec.get("request", {})
        resp = rec.get("response", {})
        err = rec.get("error")
        model = rec.get("model", {})

        row = {
            "idx": idx,
            "turnId": rec.get("turnId", ""),
            "querySource": rec.get("querySource", ""),
            "role": model.get("role", ""),
            "messagesKind": req.get("messagesKind", ""),
            "messageOffset": req.get("messageOffset", 0),
            "messageCount": req.get("messageCount", 0),
            "attempt": rec.get("attempt", 0),
            "finishReason": resp.get("finishReason"),
            "errorName": err.get("name") if err else None,
            "errorMessage": err.get("message") if err else None,
            "durationMs": rec.get("durationMs", 0),
            "toolCalls": _tool_names(resp.get("toolCalls")),
            "textHead": _head(resp.get("text"), 80),
            "requestId": rec.get("requestId", ""),
        }
        rows.append(row)

        if args.json:
            print(json.dumps(row, ensure_ascii=False))
        else:
            # 人类可读表格
            turn_short = row["turnId"].replace("turn_", "")[:8]
            qs = {"session_title": "title", "main_turn": "main"}.get(row["querySource"], row["querySource"][:5])
            kind = row["messagesKind"][:5]
            finish = (row["finishReason"] or "-")[:10]
            errn = (row["errorName"] or "-")[:18]
            tools = ",".join(row["toolCalls"])[:30]
            print(f"{idx:>4}  {turn_short}  {qs:<5}  {row['role']:<4}  {kind:<5}  {row['messageOffset']:>4}  {row['messageCount']:>4}  a{row['attempt']}  {finish:<10}  {errn:<18}  {row['durationMs']:>6}ms  {tools:<30}  {row['textHead']}")

    if not args.json and rows:
        print(f"\n共 {len(rows)} 条记录", file=sys.stderr)
    return 0


# ── inspect 子命令 ────────────────────────────────────────────────────────────

def _print_section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _print_text(label, text, truncate):
    if text is None:
        print(f"  {label}: <None>")
        return
    text = str(text)
    if truncate and len(text) > truncate:
        print(f"  {label} ({len(text)} chars, truncated {truncate}):")
        print(text[:truncate] + f"\n  …[+{len(text) - truncate} chars]")
    else:
        print(f"  {label} ({len(text)} chars):")
        print(text)


def cmd_inspect(args):
    path = args.jsonl
    if not Path(path).is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1

    target = args.idx
    rec = None
    for idx, r in _iter_records(path):
        if idx == target:
            rec = r
            break
    if rec is None:
        print(f"未找到 idx={target}（文件可能没有这么多行）", file=sys.stderr)
        return 1
    if "_parse_error" in rec:
        print(f"idx={target} 解析失败: {rec['_parse_error']}", file=sys.stderr)
        return 1

    truncate = args.truncate if args.truncate is not None else 500
    req = rec.get("request", {})
    resp = rec.get("response", {})
    err = rec.get("error")
    model = rec.get("model", {})

    # ── 顶层元数据 ──
    _print_section("顶层元数据")
    print(f"  idx:           {target}")
    print(f"  sessionId:     {rec.get('sessionId', '')}")
    print(f"  turnId:        {rec.get('turnId', '')}")
    print(f"  requestId:     {rec.get('requestId', '')}")
    print(f"  traceId:       {rec.get('traceId', '')}")
    print(f"  querySource:   {rec.get('querySource', '')}")
    print(f"  attempt:       {rec.get('attempt', '')}")
    print(f"  startedAt:     {rec.get('startedAt', '')}")
    print(f"  completedAt:   {rec.get('completedAt', '')}")
    print(f"  durationMs:    {rec.get('durationMs', '')}")
    print(f"  model:         {json.dumps(model, ensure_ascii=False)}")

    # ── request 概要 ──
    _print_section("request 概要")
    print(f"  messagesKind:    {req.get('messagesKind', '')}")
    print(f"  messageOffset:   {req.get('messageOffset', '')}")
    print(f"  messageCount:    {req.get('messageCount', '')}")
    print(f"  maxOutputTokens: {req.get('maxOutputTokens', '')}")
    body = req.get("body", {})
    print(f"  body.keys:       {list(body.keys())}")
    if body.get("bodySource"):
        print(f"  bodySource:      {body.get('bodySource')}")
        print(f"  bodyMessagesKind:    {req.get('bodyMessagesKind', '')}")
        print(f"  bodyMessageOffset:   {req.get('bodyMessageOffset', '')}")
        print(f"  bodyMessageCount:    {req.get('bodyMessageCount', '')}")
    print(f"  thinking:        {body.get('thinking')}")
    print(f"  output_config:   {body.get('output_config')}")
    print(f"  tool_choice:     {body.get('tool_choice')}")
    print(f"  stream:          {body.get('stream')}")
    print(f"  max_tokens:      {body.get('max_tokens')}")
    print(f"  toolNames:       {req.get('toolNames', [])}")
    print(f"  providerOptions.endpoints: {req.get('providerOptions', {}).get('endpoints', {})}")

    # ── error ──
    if err:
        _print_section("ERROR")
        print(f"  name:    {err.get('name', '')}")
        print(f"  message: {err.get('message', '')}")
        stack = err.get("stack", "")
        if truncate and len(stack) > truncate:
            print(f"  stack ({len(stack)} chars, truncated {truncate}):")
            print(stack[:truncate] + f"\n  …[+{len(stack) - truncate} chars]")
        else:
            print(f"  stack:")
            print(stack)

    # ── response ──
    _print_section("response")
    print(f"  finishReason: {resp.get('finishReason')}")
    print(f"  modelId:      {resp.get('modelId')}")
    print(f"  responseId:   {resp.get('responseId')}")
    u = resp.get("usage", {})
    if u:
        print(f"  usage:        input={u.get('inputTokens')} output={u.get('outputTokens')} total={u.get('totalTokens')} cacheRead={u.get('cacheReadTokens')} cacheWrite={u.get('cacheWriteTokens')}")
    else:
        print(f"  usage:        <empty>")
    tcs = resp.get("toolCalls", [])
    if tcs:
        _print_section("response.toolCalls")
        for i, tc in enumerate(tcs):
            inp = tc.get("input", {})
            if args.tool_input:
                print(f"  [{i}] {tc.get('name', '?')}  id={tc.get('id', '?')}")
                print(f"      input:")
                print(json.dumps(inp, indent=8, ensure_ascii=False))
            else:
                inp_s = json.dumps(inp, ensure_ascii=False)
                print(f"  [{i}] {tc.get('name', '?')}  id={tc.get('id', '?')}  input={_head(inp_s, 120)}")
    _print_text("response.text", resp.get("text"), truncate)

    # ── messages 结构摘要 ──
    msgs = _get_msg_list(rec)
    _print_section(f"messages 结构 ({len(msgs)} 条)")
    msg_filter = args.msg
    for i, m in enumerate(msgs):
        marker = " <== --msg" if (msg_filter is not None and i == msg_filter) else ""
        print(f"  [{i}]" + _msg_summary(m).lstrip() + marker)

    # ── 深入展开指定消息 ──
    if msg_filter is not None:
        if msg_filter < 0 or msg_filter >= len(msgs):
            print(f"\n  --msg {msg_filter} 超出范围（0..{len(msgs) - 1}）", file=sys.stderr)
        else:
            _print_section(f"message[{msg_filter}] 完整内容")
            m = msgs[msg_filter]
            print(f"  role: {m.get('role')}")
            c = m.get("content")
            if isinstance(c, str):
                _print_text("content (str)", c, truncate if not args.reasoning else None)
            elif isinstance(c, list):
                for j, p in enumerate(c):
                    if not isinstance(p, dict):
                        print(f"  part[{j}]: {p}")
                        continue
                    t = p.get("type")
                    if t == "reasoning":
                        if args.reasoning:
                            _print_text(f"part[{j}] reasoning", p.get("text", ""), None)
                        else:
                            _print_text(f"part[{j}] reasoning", p.get("text", ""), truncate)
                        sig = p.get("providerOptions", {}).get("anthropic", {}).get("signature")
                        if sig:
                            print(f"    signature: {sig}")
                    elif t == "text":
                        _print_text(f"part[{j}] text", p.get("text", ""), truncate)
                    elif t == "tool_use":
                        print(f"  part[{j}] tool_use: name={p.get('name')} id={p.get('id')}")
                        if args.tool_input:
                            print(f"    input:")
                            print(json.dumps(p.get("input", {}), indent=8, ensure_ascii=False))
                        else:
                            print(f"    input: {_head(json.dumps(p.get('input', {}), ensure_ascii=False), 120)}")
                    elif t == "tool_result":
                        _print_text(f"part[{j}] tool_result", p.get("content", ""), truncate)
                    else:
                        print(f"  part[{j}] {t}: {json.dumps(p, ensure_ascii=False)[:truncate]}")
            # toolCalls on assistant msg
            if m.get("toolCalls"):
                print(f"  toolCalls ({len(m['toolCalls'])}):")
                for j, tc in enumerate(m["toolCalls"]):
                    if args.tool_input:
                        print(f"    [{j}] {tc.get('name')} id={tc.get('id')}")
                        print(f"        input: {json.dumps(tc.get('input', {}), indent=10, ensure_ascii=False)}")
                    else:
                        print(f"    [{j}] {tc.get('name')} id={tc.get('id')} input={_head(json.dumps(tc.get('input', {}), ensure_ascii=False), 100)}")
            # tool result content
            if m.get("role") == "tool":
                _print_text("tool content", m.get("content"), truncate)

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ZCode model-io JSONL 层次化遍历工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 第一层：高层次遍历，看工作脉络
  zcode_traj.py scan ~/.zcode/cli/rollout/model-io-sess_xxx.jsonl

  # JSONL 输出（供程序消费）
  zcode_traj.py scan <file> --json

  # 第二层：定位到 idx=71 的记录细节
  zcode_traj.py inspect <file> 71

  # 展开第 5 条消息的 reasoning 全文
  zcode_traj.py inspect <file> 71 --msg 5 --reasoning

  # 展开工具调用输入全文
  zcode_traj.py inspect <file> 71 --tool-input
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="高层次遍历：每条记录的紧凑概览，带 idx 定位参数")
    p_scan.add_argument("jsonl", help="model-io-sess_*.jsonl 路径")
    p_scan.add_argument("--json", action="store_true", help="输出 JSONL 而非表格")
    p_scan.add_argument("--turn", default=None, help="过滤 turnId（前缀匹配）")

    p_inspect = sub.add_parser("inspect", help="深层次定位：展开某条记录的消息/reasoning/tool/error 细节")
    p_inspect.add_argument("jsonl", help="model-io-sess_*.jsonl 路径")
    p_inspect.add_argument("idx", type=int, help="scan 输出的行号 idx（0-based）")
    p_inspect.add_argument("--reasoning", action="store_true", help="展开 reasoning 全文（不截断）")
    p_inspect.add_argument("--tool-input", action="store_true", help="展开 toolCalls input 全文")
    p_inspect.add_argument("--msg", type=int, default=None, help="深入展开第 N 条消息的完整 content")
    p_inspect.add_argument("--truncate", type=int, default=500, help="文本截断长度（默认 500）")

    args = parser.parse_args()

    if args.command == "scan":
        if args.turn:
            # turn 过滤在 scan 内部处理
            args._turn_filter = args.turn
        return cmd_scan(args)
    elif args.command == "inspect":
        return cmd_inspect(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
