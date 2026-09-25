"""Render Pi's JSON event stream for loop.sh."""

import json
import re
import sys

at_line_start = True


def emit(text, color=""):
    global at_line_start
    text = re.sub(r"\n+", "\n", text)
    if at_line_start:
        text = text.lstrip("\n")
    if not text:
        return
    at_line_start = text.endswith("\n")
    # Docker's interactive mode can disable the terminal's newline translation.
    if sys.stdout.isatty():
        text = text.replace("\n", "\r\n")
    sys.stdout.write(f"{color}{text}\033[0m" if color else text)
    sys.stdout.flush()


for line in sys.stdin:
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue

    event_type = ev.get("type")
    if event_type == "tool_execution_start":
        tool = ev.get("toolName", "tool")
        args = ev.get("args") or ev.get("input") or {}
        summary = ""
        if isinstance(args, dict) and args:
            summary = next(
                (args[key] for key in ("command", "path", "file_path", "query") if args.get(key)),
                json.dumps(args),
            )
            summary = str(summary).replace("\n", " ")
            summary = summary[:80] + "..." if len(summary) > 80 else summary
        detail = f": {summary}" if summary else ""
        emit(f"\n⚡ [{tool}{detail}]\n", "\033[36m")

    elif event_type == "tool_execution_end" and ev.get("isError"):
        tool = ev.get("toolName", "tool")
        emit(f"\n❌ [{tool} failed]\n", "\033[31m")
        result = ev.get("result") or {}
        details = "\n".join(block["text"] for block in result.get("content", []) if block.get("type") == "text")
        if not details and result:
            details = json.dumps(result)
        if details:
            emit(f"{details}\n", "\033[31m")

    elif event_type == "message_update":
        update = ev.get("assistantMessageEvent", {})
        kind = update.get("type")
        delta = update.get("delta", "")
        if kind == "text_delta":
            emit(delta)
        elif kind == "thinking_delta":
            emit(delta, "\033[90m")
