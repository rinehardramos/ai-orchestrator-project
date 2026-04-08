"""Tail LLM trace JSONLs written by the worker.

The worker writes one JSONL per task to ``/tmp/orchestrator-llm-traces/``
on the host (mounted as ``/tmp/llm-traces`` inside the worker container).
This CLI reads those files directly — no HTTP layer — because the worker
runs on the same physical host as Genesis (DOCKER_HOST=ssh://localhost).

Subcommands::

    python -m src.genesis.llm_logs list                # recent task ids
    python -m src.genesis.llm_logs latest [-f] [-n N]  # tail most recent
    python -m src.genesis.llm_logs tail TASK_ID [-f]   # tail specific task
    python -m src.genesis.llm_logs clean [--task ID | --all]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

TRACE_DIR = Path(os.environ.get("LLM_TRACE_DIR_HOST", "/tmp/orchestrator-llm-traces"))  # nosec B108 — ephemeral by design

# ANSI colors — degrade gracefully when piped.
_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


_EVENT_COLORS = {
    "task_start": "1;36",
    "prompt_in": "33",
    "llm_out": "1;32",
    "tool_call": "1;34",
    "tool_result": "36",
    "error": "1;31",
}


def _fmt_event(record: dict) -> str:
    ts = datetime.fromtimestamp(record.get("ts", 0)).strftime("%H:%M:%S.%f")[:-3]
    event = record.get("event", "?")
    step = record.get("step")
    color = _EVENT_COLORS.get(event, "0")
    head_bits = [_c(color, f"[{ts}] {event}")]
    if step is not None:
        head_bits.append(_c("2", f"step={step}"))
    head = " ".join(head_bits)

    body_lines: list[str] = []
    if event == "task_start":
        body_lines.append(f"  spec={record.get('specialization')}  model={record.get('model_id')}")
        body_lines.append(f"  description: {record.get('description', '')[:300]}")
    elif event == "prompt_in":
        msgs = record.get("messages") or []
        body_lines.append(f"  task_type={record.get('task_type')}  messages={len(msgs)}")
        if msgs:
            last = msgs[-1]
            content = last.get("content", "") if isinstance(last, dict) else str(last)
            body_lines.append(f"  last[{last.get('role') if isinstance(last, dict) else '?'}]: {str(content)[:500]}")
    elif event == "llm_out":
        cost = record.get("cost_usd")
        cum = record.get("cumulative_cost_usd")
        body_lines.append(f"  cost=${cost}  total=${cum}")
        content = record.get("content") or ""
        if content:
            body_lines.append("  content:")
            for line in str(content).splitlines():
                body_lines.append(f"    {line}")
        for tc in record.get("tool_calls") or []:
            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            body_lines.append(f"  tool_call → {fn.get('name')}({fn.get('arguments', '')[:200]})")
    elif event == "tool_call":
        args = record.get("args") or {}
        body_lines.append(f"  {record.get('name')}({json.dumps(args, default=str)[:400]})")
    elif event == "tool_result":
        result = record.get("result") or ""
        body_lines.append(f"  ← {record.get('name')}")
        for line in str(result).splitlines()[:10]:
            body_lines.append(f"    {line}")
    elif event == "error":
        body_lines.append(_c("1;31", f"  {record.get('where')}: {record.get('msg')}"))
    else:
        body_lines.append(f"  {json.dumps({k: v for k, v in record.items() if k not in {'ts', 'event', 'step', 'task_id'}}, default=str)[:500]}")

    return head + ("\n" + "\n".join(body_lines) if body_lines else "")


def _print_record(line: str) -> None:
    line = line.strip()
    if not line:
        return
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        print(line)
        return
    print(_fmt_event(rec))


def _resolve_path(task_id: str) -> Path:
    return TRACE_DIR / f"{task_id}.jsonl"


def _list_traces() -> list[Path]:
    if not TRACE_DIR.exists():
        return []
    return sorted(TRACE_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def cmd_list(args: argparse.Namespace) -> int:
    files = _list_traces()
    if not files:
        print(f"(no traces in {TRACE_DIR})")
        return 0
    for p in files[: args.limit]:
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{mtime}  {st.st_size:>8}B  {p.stem}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    path = _resolve_path(args.task_id) if args.task_id else None
    if args.task_id is None:
        files = _list_traces()
        if not files:
            print(f"(no traces in {TRACE_DIR})", file=sys.stderr)
            return 1
        path = files[0]
        print(_c("2", f"# tailing {path.name}"))
    if not path.exists():
        print(f"trace not found: {path}", file=sys.stderr)
        return 1

    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
        tail = lines[-args.lines :] if args.lines and args.lines > 0 else lines
        for line in tail:
            _print_record(line)
        if not args.follow:
            return 0
        # follow mode
        while True:
            where = fh.tell()
            line = fh.readline()
            if not line:
                time.sleep(0.5)
                fh.seek(where)
                continue
            _print_record(line)


def cmd_clean(args: argparse.Namespace) -> int:
    if args.all:
        if not TRACE_DIR.exists():
            print("(nothing to clean)")
            return 0
        n = 0
        for p in TRACE_DIR.glob("*.jsonl"):
            p.unlink()
            n += 1
        print(f"removed {n} trace(s) from {TRACE_DIR}")
        return 0
    if args.task:
        path = _resolve_path(args.task)
        if path.exists():
            path.unlink()
            print(f"removed {path}")
            return 0
        print(f"not found: {path}", file=sys.stderr)
        return 1
    print("specify --task ID or --all", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_logs", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list recent traces")
    p_list.add_argument("-n", "--limit", type=int, default=20)
    p_list.set_defaults(fn=cmd_list)

    p_tail = sub.add_parser("tail", help="tail a specific task trace")
    p_tail.add_argument("task_id")
    p_tail.add_argument("-n", "--lines", type=int, default=200)
    p_tail.add_argument("-f", "--follow", action="store_true")
    p_tail.set_defaults(fn=cmd_tail)

    p_latest = sub.add_parser("latest", help="tail the most recent trace")
    p_latest.add_argument("-n", "--lines", type=int, default=200)
    p_latest.add_argument("-f", "--follow", action="store_true")
    p_latest.set_defaults(fn=cmd_tail, task_id=None)

    p_clean = sub.add_parser("clean", help="delete trace files")
    p_clean.add_argument("--task", help="delete a single trace by id")
    p_clean.add_argument("--all", action="store_true", help="delete every trace")
    p_clean.set_defaults(fn=cmd_clean)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
