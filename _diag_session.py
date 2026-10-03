import json
import os
import sys
from datetime import datetime

import httpx

BASE = os.getenv("OPENCODE_URL", "http://127.0.0.1:4097")
SESSION = sys.argv[1] if len(sys.argv) > 1 else "ses_efe3406e7ffehoys1GCA3P6t0h"
OUT = sys.argv[2] if len(sys.argv) > 2 else None


def wall(ms):
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%H:%M:%S")


def delta(a, b):
    if not a or not b:
        return "-"
    return f"{(a - b) / 1000:.0f}s"


def main():
    resp = httpx.get(f"{BASE}/session/{SESSION}/message", params={"directory": os.getcwd()}, timeout=60)
    payload = resp.json()
    first = (payload[0].get("info", {}) or {}).get("time", {}).get("created")
    lines = [f"SESSION {SESSION} first message at {wall(first)}", ""]
    tool_total = 0.0
    for index, message in enumerate(payload):
        info = message.get("info", {}) or {}
        time_info = info.get("time", {}) or {}
        created = time_info.get("created")
        completed = time_info.get("completed")
        lines.append(
            f"=== [{index}] role={info.get('role')} created={wall(created)}({delta(created, first)}) "
            f"completed={wall(completed)}({delta(completed, first)}) dur={delta(completed, created)}"
        )
        for part in message.get("parts", []) or []:
            kind = part.get("type")
            if kind == "text":
                text = (part.get("text") or "").strip()
                if text:
                    lines.append("--- TEXT ---")
                    lines.append(text)
            elif kind == "tool":
                state = part.get("state", {}) or {}
                stime = state.get("time", {}) or {}
                end = stime.get("end")
                dur = (end - stime.get("start")) / 1000 if end else None
                if dur:
                    tool_total += dur
                lines.append(
                    f"--- TOOL {part.get('tool')} status={state.get('status')} "
                    f"dur={dur if dur is not None else 'STILL RUNNING'}({delta(stime.get('start'), first)}->{delta(end, first)})"
                )
    lines.insert(2, f"TOTAL TOOL WALL TIME: {tool_total:.0f}s")
    body = "\n".join(lines)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as handle:
            handle.write(body)
        print(f"wrote {OUT} ({len(body)} chars), tool wall total {tool_total:.0f}s")
    else:
        print(body)


if __name__ == "__main__":
    main()