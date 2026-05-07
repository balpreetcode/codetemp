# codetemp

A minimal, single-file coding agent built on the Anthropic SDK — read/write files, list directories, run shell. Designed to be a stripped-down stand-in for Claude Code when the official binary is blocked by corporate egress policy.

~250 lines of Python. No frameworks, no plugins.

## Setup

```bash
git clone https://github.com/balpreetcode/codetemp
cd codetemp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in ANTHROPIC_API_KEY
```

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python codetemp.py
```

If `api.anthropic.com` is blocked on your network but you have a reverse proxy reachable elsewhere (e.g. devtunnel):

```bash
export ANTHROPIC_BASE_URL=https://your-tunnel.use.devtunnels.ms
python codetemp.py
```

## Tools the agent has

- `read_file(path)` — read a file
- `write_file(path, content)` — write/overwrite a file (asks for confirmation)
- `list_dir(path)` — list a directory
- `run_bash(command, timeout?)` — run a shell command (asks for confirmation)

Set `CODETEMP_YOLO=1` to skip confirmations.

## REPL commands

- `/reset` — clear conversation history
- `/exit` — quit

## Limits

- No streaming UI (responses arrive as a block).
- No MCP, no slash-commands, no sub-agents.
- Path safety only confines to `CODETEMP_WORKDIR`; bash runs unconstrained inside it.
- Conversation lives in memory only.
