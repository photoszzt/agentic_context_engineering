#!/usr/bin/env python3
# Module: precompact -- Phase 1 ACE precompact hook.
#
# Spec: docs/hooks/spec.md
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
)


async def main():
    """Run the precompact pipeline.

    @implements REQ-PRECOMPACT-001, REQ-PRECOMPACT-002, REQ-PRECOMPACT-003,
                REQ-PRECOMPACT-004, REQ-PRECOMPACT-005, REQ-PRECOMPACT-006,
                REQ-PRECOMPACT-007, REQ-PRECOMPACT-009
    @invariant INV-PRECOMPACT-001 (counter update precedes curator)
    @invariant INV-PRECOMPACT-002 (pipeline function parity with session_end.py)
    @invariant INV-PRECOMPACT-003 (no old pipeline functions)
    """
    input_data = json.load(sys.stdin)

    transcript_path = input_data.get("transcript_path")
    messages = load_transcript(transcript_path)

    # REQ-PRECOMPACT-009: Empty transcript early exit
    if not messages:
        sys.exit(0)

    playbook = load_playbook()

    # Step 1: Extract cited IDs from transcript
    cited_ids = extract_cited_ids(messages)

    # Step 2: Reflector LLM call
    reflector_output = await run_reflector(messages, playbook, cited_ids)

    # Step 3: Counter update BEFORE curator (curator sees up-to-date harm/help ratios)
    # INV-PRECOMPACT-001: apply_bullet_tags always called before run_curator
    apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))

    # Step 4: Curator LLM call (works from reflector output, not transcript)
    curator_output = await run_curator(reflector_output, playbook)

    # Step 5: Apply structured operations
    playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

    # Step 6: Semantic deduplication
    playbook = run_deduplication(playbook)

    # Step 7: Prune harmful entries
    playbook = prune_harmful(playbook)

    save_playbook(playbook)

    # REQ-PRECOMPACT-007: clear_session called after save_playbook
    clear_session()


# REQ-PRECOMPACT-008: Top-level try/except with asyncio.run
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
