#!/usr/bin/env python3
import json
import sys
from common import (
    load_playbook,
    format_playbook,
    is_diagnostic_mode,
    save_diagnostic,
    is_first_message,
    mark_session,
)


def main():
    input_data = json.load(sys.stdin)
    session_id = input_data.get("session_id", "unknown")

    if not is_first_message(session_id):
        print(json.dumps({}), flush=True)
        sys.exit(0)

    playbook = load_playbook()
    context = format_playbook(playbook)

    if not context:
        print(json.dumps({}), flush=True)
        sys.exit(0)

    if is_diagnostic_mode():
        save_diagnostic(context, "user_prompt_inject")

    response = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(response), flush=True)

    mark_session(session_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        print(json.dumps({}), flush=True)
        sys.exit(1)
