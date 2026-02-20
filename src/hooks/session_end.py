#!/usr/bin/env python3
# Module: session_end -- Phase 1 ACE session-end hook.
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
    clear_session,
    load_settings,
)


async def main():
    input_data = json.load(sys.stdin)

    transcript_path = input_data.get("transcript_path")
    messages = load_transcript(transcript_path)

    if not messages:
        sys.exit(0)

    settings = load_settings()
    update_on_exit = settings.get("playbook_update_on_exit", False)
    update_on_clear = settings.get("playbook_update_on_clear", False)

    reason = input_data.get("reason", "")

    # Skip playbook update for /exit command when setting is disabled
    if not update_on_exit and reason == "prompt_input_exit":
        sys.exit(0)

    # Skip playbook update for /clear command when setting is disabled
    if not update_on_clear and reason == "clear":
        sys.exit(0)

    playbook = load_playbook()

    # Step 5: Extract cited IDs from transcript
    cited_ids = extract_cited_ids(messages)

    # Step 6: Reflector LLM call
    reflector_output = await run_reflector(messages, playbook, cited_ids)

    # Step 7: Counter update BEFORE curator (curator sees up-to-date harm/help ratios)
    apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))

    # Step 8: Curator LLM call (works from reflector output, not transcript)
    curator_output = await run_curator(reflector_output, playbook)

    # Step 9: Apply structured operations
    playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

    # Step 10: Semantic deduplication
    playbook = run_deduplication(playbook)

    # Step 11: Prune harmful entries
    playbook = prune_harmful(playbook)

    save_playbook(playbook)
    clear_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
