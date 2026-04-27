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

# Optional: comma-separated Slack user IDs allowed to send commands.
# Leave empty to allow anyone who can reach the bot.
# Example:  ALLOWED_USERS=U012AB3CD,U987XY6ZW
ALLOWED_USERS: set[str] = set(
    u.strip() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()
)

PROJECT_DIR = str(Path(__file__).parent.resolve())

# Claude CLI path — resolved at startup so subprocess inherits it correctly
CLAUDE_CMD = os.environ.get(
    "CLAUDE_CMD",
    r"C:\Users\rajir\AppData\Roaming\npm\claude.cmd"
)

# Maximum characters to send back to Slack (hard limit is ~4000 per block)
MAX_OUTPUT = 2800

# ── Helpers ───────────────────────────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN)

def _bot_user_id() -> str:
    return app.client.auth_test()["user_id"]

_bot_id: str | None = None

def bot_id() -> str:
    global _bot_id
    if _bot_id is None:
        _bot_id = _bot_user_id()
    return _bot_id


def is_allowed(user_id: str) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def run_claude(prompt: str) -> str:
    """Run `claude -p <prompt>` in the project directory and return output."""
    try:
        # On Windows, .cmd files must be invoked via cmd.exe
        result = subprocess.run(
            ["cmd", "/c", CLAUDE_CMD,
             "--print",
             "--dangerously-skip-permissions",
             "--output-format", "text",
             prompt],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or "").strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        return output or "(no output)"

    except subprocess.TimeoutExpired:
        return ":warning: Timed out after 5 minutes."
    except FileNotFoundError:
        return f":x: `claude` CLI not found at `{CLAUDE_CMD}`."
    except Exception as exc:
        return f":x: Unexpected error: {exc}"


def format_output(output: str) -> str:
    truncated = len(output) > MAX_OUTPUT
    if truncated:
        output = output[:MAX_OUTPUT]
    text = f"```\n{output}\n```"
    if truncated:
        text += "\n_…(output truncated)_"
    return text


def dispatch(prompt: str, say, user_id: str):
    """Called from event handlers. Validates, acknowledges, runs, replies."""
    if not prompt:
        say("Hi! Send me a task and I'll run it through Claude Code in the project. :robot_face:")
        return

    if not is_allowed(user_id):
        say(":no_entry: You are not in the allowed users list.")
        return

    # Acknowledge immediately (Slack requires a response within 3 s)
    short = prompt[:80] + ("…" if len(prompt) > 80 else "")
    say(f":hourglass_flowing_sand: Running: `{short}`")

    def _worker():
        output = run_claude(prompt)
        say(format_output(output))

    threading.Thread(target=_worker, daemon=True).start()


# ── Event handlers ────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    """Someone @-mentioned the bot in a channel."""
    raw  = event.get("text", "")
    uid  = event.get("user", "")
    # Strip the mention token so it isn't part of the prompt
    prompt = re.sub(r"<@[A-Z0-9]+>", "", raw).strip()
    dispatch(prompt, say, uid)


@app.event("message")
def handle_message(event, say):
    """Direct message sent to the bot."""
    if event.get("channel_type") != "im":
        return                          # ignore channel messages (handled by app_mention)
    if event.get("bot_id") or event.get("subtype"):
        return                          # ignore bot messages and edits/deletes
    prompt = event.get("text", "").strip()
    uid    = event.get("user", "")
    dispatch(prompt, say, uid)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[slack_bridge] Project dir : {PROJECT_DIR}")
    print(f"[slack_bridge] Allowed users: {ALLOWED_USERS or 'everyone'}")
    print("[slack_bridge] Connecting to Slack via Socket Mode…\n")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
