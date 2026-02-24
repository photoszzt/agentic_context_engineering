#!/usr/bin/env python3
# Module: subagent_stop -- ACE SubagentStop hook.
#
# Spec: docs/reflector/spec.md, docs/dedup/spec.md, docs/curator/spec.md
import json
import sys
import asyncio
from common import (
    load_playbook,
    save_playbook,
    load_transcript,
    extract_cited_ids,
    run_reflector,
    apply_bullet_tags,
    run_curator,
    apply_structured_operations,
    run_deduplication,
    prune_harmful,
    load_settings,
)


async def main():
    input_data = json.load(sys.stdin)

    transcript_path = input_data.get("transcript_path")
    messages = load_transcript(transcript_path)

    if not messages:
        sys.exit(0)

    settings = load_settings()
    if not settings.get("playbook_update_on_subagent_stop", True):
        sys.exit(0)

    playbook = load_playbook()

    cited_ids = extract_cited_ids(messages)

    reflector_output = await run_reflector(messages, playbook, cited_ids)

    apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))

    curator_output = await run_curator(reflector_output, playbook)

    playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

    playbook = run_deduplication(playbook)

    playbook = prune_harmful(playbook)

    save_playbook(playbook)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
