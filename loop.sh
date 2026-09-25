#!/usr/bin/env bash
set -euo pipefail

ROUNDS=12

for ((i=1; i<=ROUNDS; i++)); do
  echo "=== Round $i of $ROUNDS ==="
  pibox --with web,browser --mode json \
    "/skill:implement-autonomous Take exactly one next available open issue from https://github.com/jvanlier/recall/issues and implement it. If you need the recall-cards repo, clone it from https://github.com/jvanlier/recall-cards" | python3 -c '
import sys, json

newline_count = 0

def emit(text, color=""):
    global newline_count
    out = []
    for char in text:
        if char == "\n":
            newline_count += 1
            if newline_count <= 1:
                out.append("\n")
        else:
            newline_count = 0
            out.append(char)
    if out:
        s = "".join(out)
        sys.stdout.write(f"{color}{s}\033[0m" if color else s)
        sys.stdout.flush()

for line in sys.stdin:
    try:
        ev = json.loads(line)
        t = ev.get("type")
        
        if t == "tool_execution_start":
            tool = ev.get("toolName", "tool")
            args = ev.get("args") or ev.get("input") or {}
            
            summary = ""
            if isinstance(args, dict):
                if "command" in args:
                    cmd = args["command"].replace("\n", " ")
                    summary = cmd[:80] + "..." if len(cmd) > 80 else cmd
                elif "path" in args or "file_path" in args:
                    summary = args.get("path") or args.get("file_path")
                elif "query" in args:
                    summary = args.get("query")
                elif args:
                    raw = json.dumps(args)
                    summary = raw[:70] + "..." if len(raw) > 70 else raw
            
            detail = f": {summary}" if summary else ""
            emit(f"\n⚡ [{tool}{detail}]\n", "\033[36m")
            
        elif t == "tool_execution_end":
            if ev.get("isError"):
                tool = ev.get("toolName", "tool")
                emit(f"❌ [{tool} failed]\n", "\033[31m")
            
        elif t == "message_update":
            ame = ev.get("assistantMessageEvent", {})
            kind = ame.get("type")
            delta = ame.get("delta", "")
            
            if kind == "text_delta":
                emit(delta)
            elif kind == "thinking_delta":
                emit(delta, "\033[90m")
    except Exception:
        pass
'
  break # testing !
done

