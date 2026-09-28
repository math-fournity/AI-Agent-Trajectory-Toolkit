#!/usr/bin/env python3
"""oc_traj.py — opencode ACP trajectory 层次化分析工具。

两层遍历设计（与 zcode_traj.py 同范式）：
  第一层 scan/tail/search — 低成本概览与定位
  第二层 read             — 按字符位置精确下钻

数据源（按扩展名自动识别）：
  thoughts.jsonl   ACP实时流，每行一个chunk {"t":秒,"mid":消息id,"text":文本} 【最完整，主源】
  *.md / *.txt     已拼接纯文本

用法：
  oc_traj.py scan   <file>                     分段大纲：段号|行号|字符数|首句
  oc_traj.py tail   <file> [chars=6000]        末尾N字符（看前一轮"最后的思考"）
  oc_traj.py head   <file> [chars=2000]        开头N字符
  oc_traj.py read   <file> <start> [chars]     从字符位置start读N字符
  oc_traj.py search <file> <pattern>           正则定位（输出命中点±100字符）
"""
import json
import re
import sys


def load(path):
    """加载数据源为统一 (text, meta) 。"""
    if path.endswith(".jsonl"):
        chunks = []
        t0 = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    chunks.append(f"[解析错误: {e}]")
                    continue
                if t0 is None:
                    t0 = rec.get("t")
                chunks.append(rec.get("text", ""))
        text = "".join(chunks)
        meta = {"source": "thoughts.jsonl(ACP实时流)", "chunks": len(chunks),
                "first_t": t0}
    else:
        text = open(path, encoding="utf-8").read()
        meta = {"source": "plain text", "chars": len(text)}
    return text, meta


def line_of(text, idx):
    return text.count("\n", 0, idx) + 1


def cmd_scan(text, meta):
    total = len(text)
    marks = [m.start() for m in re.finditer(
        r"\n(?=(Wait|Hold on|Actually|Hmm|Let me|Now|So|OK|But|However|Anyway|Alright|Therefore|Thus))",
        text)]
    segs, start = [], 0
    HARD = 2500
    for p in marks:
        if p - start >= HARD:
            segs.append((start, p))
            start = p
    if start < total:
        segs.append((start, total))
    merged = []
    for s, e in segs:
        if merged and e - merged[-1][0] < 400:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    print(f"[meta] {meta}")
    print(f"[scan] 总字符 {total}, 分段 {len(merged)}")
    print(f"{'段':>5} {'行号范围':>12} {'字符数':>7}  首句")
    for i, (s, e) in enumerate(merged):
        first = re.sub(r"\s+", " ", text[s:s + 90]).strip()
        print(f"  #{i:03d} L{line_of(text,s):>5}-L{line_of(text,e):<5} {e-s:>7}  {first}")


def cmd_tail(text, n):
    n = min(n, len(text))
    body = text[-n:]
    print(f"--- 尾部 {len(body)} 字符（全文{len(text)}，起始 L{line_of(text, len(text)-len(body))} / 字符位 {len(text)-len(body)}）---")
    print(body)


def cmd_read(text, start, n):
    start = max(0, int(start))
    n = min(int(n), len(text) - start)
    print(f"--- 字符位 {start} 起 {n} 字符（L{line_of(text,start)}）---")
    print(text[start:start + n])


def cmd_search(text, pattern):
    hits = list(re.finditer(pattern, text))
    print(f"命中 {len(hits)} 处:")
    for m in hits[:30]:
        s = max(0, m.start() - 100)
        ctx = re.sub(r"\s+", " ", text[s:m.end() + 100])
        print(f"  @字符{m.start()} L{line_of(text,m.start())}: …{ctx}…")


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("scan", "tail", "head", "read", "search"):
        print(__doc__)
        sys.exit(1)
    cmd, path = a[0], a[1]
    text, meta = load(path)
    if cmd == "scan":
        cmd_scan(text, meta)
    elif cmd == "tail":
        cmd_tail(text, int(a[2]) if len(a) > 2 else 6000)
    elif cmd == "head":
        print(text[:int(a[2]) if len(a) > 2 else 2000])
    elif cmd == "read":
        cmd_read(text, a[2], int(a[3]) if len(a) > 3 else 3000)
    elif cmd == "search":
        cmd_search(text, a[2])


if __name__ == "__main__":
    main()
