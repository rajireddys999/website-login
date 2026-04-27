"""
Slack → Claude Code bridge.

Listens for messages in Slack (Socket Mode — no public URL needed) and runs
them as Claude Code prompts in this project directory.

Usage:
  1. Copy .env.slack.example to .env.slack and fill in the tokens.
  2. pip install slack-bolt python-dotenv
  3. python slack_bridge.py

Trigger modes:
  • @mention the bot in any channel it is invited to
  • Send it a direct message (DM)

Recovery:
  • On error the bot asks "retry?" — reply `retry` to re-run the same prompt.
"""

import os
import subprocess
import threading
import re
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env.slack")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]   # xoxb-...
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]    # xapp-...

ALLOWED_USERS: set[str] = set(
    u.strip() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()
)

PROJECT_DIR = str(Path(__file__).parent.resolve())

# Call the .exe directly — avoids cmd.exe shell interpretation of < > & | in prompts
CLAUDE_CMD = os.environ.get(
    "CLAUDE_CMD",
    r"C:\Users\rajir\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
)

MAX_OUTPUT = 2800

# ── Per-channel last-prompt store (for retry) ─────────────────────────────────
# key: channel id  →  value: last prompt string
_last_prompt: dict[str, str] = {}
_last_prompt_lock = threading.Lock()

def save_last_prompt(channel: str, prompt: str):
    with _last_prompt_lock:
        _last_prompt[channel] = prompt

def get_last_prompt(channel: str) -> str | None:
    with _last_prompt_lock:
        return _last_prompt.get(channel)

# ── Helpers ───────────────────────────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN)

_bot_id: str | None = None

def bot_id() -> str:
    global _bot_id
    if _bot_id is None:
        _bot_id = app.client.auth_test()["user_id"]
    return _bot_id


def is_allowed(user_id: str) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def run_claude(prompt: str) -> tuple[str, bool]:
    """
    Run claude and stream output live to the terminal.
    Returns (output_text, success).
    """
    SEP = "─" * 60
    try:
        print(f"\n{SEP}")
        print(f"  PROMPT: {prompt[:120]}{'…' if len(prompt) > 120 else ''}")
        print(SEP)

        process = subprocess.Popen(
            [CLAUDE_CMD,
             "--print",
             "--dangerously-skip-permissions",
             "--output-format", "text",
             prompt],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        lines = []
        for line in process.stdout:
            print(line, end="", flush=True)
            lines.append(line)

        process.wait()
        print(f"{SEP}\n")

        output = "".join(lines).strip() or "(no output)"
        success = process.returncode == 0
        return output, success

    except FileNotFoundError:
        msg = f":x: `claude` CLI not found at `{CLAUDE_CMD}`."
        print(msg)
        return msg, False
    except Exception as exc:
        msg = f":x: Unexpected error: {exc}"
        print(msg)
        return msg, False


def format_output(output: str) -> str:
    truncated = len(output) > MAX_OUTPUT
    if truncated:
        output = output[:MAX_OUTPUT]
    text = f"```\n{output}\n```"
    if truncated:
        text += "\n_…(output truncated)_"
    return text


def dispatch(prompt: str, channel: str, say, user_id: str):
    """Validate, acknowledge, run, reply — with retry on error."""
    if not is_allowed(user_id):
        say(":no_entry: You are not in the allowed users list.")
        return

    # ── Retry shortcut ────────────────────────────────────────────
    if prompt.lower().strip() in ("retry", "yes", "y", "re-run"):
        last = get_last_prompt(channel)
        if not last:
            say(":shrug: No previous prompt to retry.")
            return
        say(f":repeat: Retrying last prompt:\n> {last[:120]}{'…' if len(last) > 120 else ''}")
        prompt = last
    elif not prompt:
        say("Hi! Send me a task and I'll run it through Claude Code. :robot_face:\n_Reply `retry` to re-run the last task._")
        return

    # Save prompt before running (so retry works even mid-run)
    save_last_prompt(channel, prompt)

    short = prompt[:80] + ("…" if len(prompt) > 80 else "")
    say(f":hourglass_flowing_sand: Running: `{short}`")

    def _worker():
        output, success = run_claude(prompt)

        if success:
            say(format_output(output))
        else:
            # Error — post error + offer retry
            say(
                f"{format_output(output)}\n\n"
                f":warning: Something went wrong. Reply `retry` to try the same task again."
            )

    threading.Thread(target=_worker, daemon=True).start()


# ── Event handlers ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    raw     = event.get("text", "")
    uid     = event.get("user", "")
    channel = event.get("channel", "")
    prompt  = re.sub(r"<@[A-Z0-9]+>", "", raw).strip()
    dispatch(prompt, channel, say, uid)


@app.event("message")
def handle_message(event, say):
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return
    prompt  = event.get("text", "").strip()
    uid     = event.get("user", "")
    channel = event.get("channel", "")
    dispatch(prompt, channel, say, uid)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[slack_bridge] Project dir  : {PROJECT_DIR}")
    print(f"[slack_bridge] Claude CMD   : {CLAUDE_CMD}")
    print(f"[slack_bridge] Allowed users: {ALLOWED_USERS or 'everyone'}")
    print("[slack_bridge] Connecting to Slack via Socket Mode…\n")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
