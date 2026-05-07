#!/usr/bin/env python3
"""codetemp: minimal coding agent built on the Anthropic SDK.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    # Optional: route through a proxy (e.g. devtunnel) when api.anthropic.com is blocked.
    export ANTHROPIC_BASE_URL=https://your-tunnel.use.devtunnels.ms
    python codetemp.py
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from anthropic import Anthropic

MODEL = os.environ.get("CODETEMP_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 8192
WORKDIR = Path(os.environ.get("CODETEMP_WORKDIR", os.getcwd())).resolve()

SYSTEM_PROMPT = f"""You are codetemp, a terminal coding assistant.

You operate inside a working directory and have tools to read files, write files,
list directories, and run shell commands. When the user asks for changes, make
them with the tools — don't just describe what you would do.

Working directory: {WORKDIR}

Keep responses short. When you finish a task, give a one-line summary."""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the working directory. Returns its contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the working directory."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List entries in a directory (non-recursive).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Defaults to '.'"},
            },
        },
    },
    {
        "name": "run_bash",
        "description": "Run a bash command inside the working directory. Returns stdout, stderr, exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds. Default 60."},
            },
            "required": ["command"],
        },
    },
]


def _safe_path(rel: str) -> Path:
    p = (WORKDIR / rel).resolve()
    if WORKDIR not in p.parents and p != WORKDIR:
        raise ValueError(f"path escapes working directory: {rel}")
    return p


def tool_read_file(path: str) -> str:
    p = _safe_path(path)
    return p.read_text(errors="replace")


def tool_write_file(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} bytes to {path}"


def tool_list_dir(path: str = ".") -> str:
    p = _safe_path(path)
    entries = []
    for entry in sorted(p.iterdir()):
        kind = "d" if entry.is_dir() else "f"
        entries.append(f"{kind} {entry.name}")
    return "\n".join(entries) or "(empty)"


def tool_run_bash(command: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return f"timeout after {timeout}s\nstdout:\n{e.stdout or ''}\nstderr:\n{e.stderr or ''}"
    return (
        f"exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def dispatch_tool(name: str, args: dict) -> str:
    try:
        if name == "read_file":
            return tool_read_file(**args)
        if name == "write_file":
            return tool_write_file(**args)
        if name == "list_dir":
            return tool_list_dir(**args)
        if name == "run_bash":
            return tool_run_bash(**args)
        return f"unknown tool: {name}"
    except Exception as exc:
        return f"error: {exc}"


def confirm_destructive(name: str, args: dict) -> bool:
    """Ask before write_file or run_bash unless CODETEMP_YOLO=1."""
    if os.environ.get("CODETEMP_YOLO") == "1":
        return True
    if name == "write_file":
        preview = (args.get("content") or "")[:200]
        print(f"\n  write_file -> {args.get('path')} ({len(args.get('content') or '')} bytes)")
        print(f"  preview: {preview!r}")
    elif name == "run_bash":
        print(f"\n  run_bash: {args.get('command')}")
    else:
        return True
    answer = input("  proceed? [y/N] ").strip().lower()
    return answer == "y"


def run_agent_turn(client: Anthropic, messages: list) -> list:
    """Run one user-turn through the agent loop. Returns updated messages."""
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        text_chunks = [b.text for b in response.content if b.type == "text"]
        if text_chunks:
            print("\n" + "\n".join(text_chunks).strip())

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return messages

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            args = block.input or {}
            if not confirm_destructive(block.name, args):
                output = "user denied this tool call"
            else:
                print(f"\n[tool] {block.name}({json.dumps(args)[:120]})")
                output = dispatch_tool(block.name, args)
                print(f"[tool result] {output[:200]}{'...' if len(output) > 200 else ''}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: set ANTHROPIC_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = Anthropic()
    base = os.environ.get("ANTHROPIC_BASE_URL", "(default)")
    print(f"codetemp ready — model={MODEL} workdir={WORKDIR} base_url={base}")
    print("type your request, or /exit to quit. /reset clears history.\n")

    messages: list = []
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/reset":
            messages = []
            print("(history cleared)")
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            messages = run_agent_turn(client, messages)
        except KeyboardInterrupt:
            print("\n(interrupted)")
            messages.pop()


if __name__ == "__main__":
    main()
