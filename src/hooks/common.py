#!/usr/bin/env python3
# Module: common -- shared utilities for playbook lifecycle hooks.
#
# Spec: docs/sections/spec.md
# Contract: docs/sections/contract.md
import json
import os
import re
from pathlib import Path
from datetime import datetime

try:
    import anthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# @implements REQ-SECT-010
# Single source of truth for canonical section names, slugs, and ordering.
# Iteration order = canonical section order (Python 3.7+ dict insertion order).
SECTION_SLUGS = {
    "PATTERNS & APPROACHES": "pat",
    "MISTAKES TO AVOID": "mis",
    "USER PREFERENCES": "pref",
    "PROJECT CONTEXT": "ctx",
    "OTHERS": "oth",
}


def get_project_dir() -> Path:
    project_dir = os.getenv("CLAUDE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir)
    return Path.home()


def get_user_claude_dir() -> Path:
    home = Path.home()
    return home / ".claude"


def is_diagnostic_mode() -> bool:
    flag_file = get_project_dir() / ".claude" / "diagnostic_mode"
    return flag_file.exists()


def save_diagnostic(content: str, name: str):
    diagnostic_dir = get_project_dir() / ".claude" / "diagnostic"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = diagnostic_dir / f"{timestamp}_{name}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def is_first_message(session_id: str) -> bool:
    session_file = get_project_dir() / ".claude" / "last_session.txt"

    if session_file.exists():
        last_session_id = session_file.read_text().strip()
        return session_id != last_session_id

    return True


def mark_session(session_id: str):
    session_file = get_project_dir() / ".claude" / "last_session.txt"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(session_id)


def clear_session():
    session_file = get_project_dir() / ".claude" / "last_session.txt"
    if session_file.exists():
        session_file.unlink()


def generate_keypoint_name(section_entries: list[dict], slug: str) -> str:
    """Generate the next key point name for a section.

    Scans section_entries for names matching {slug}-NNN pattern,
    finds the highest NNN, returns {slug}-{max+1:03d}.

    Legacy kpt_NNN names in section_entries are ignored.

    @implements REQ-SECT-002
    @invariant INV-SECT-005 (slug prefix consistency)
    """
    pattern = re.compile(rf"^{re.escape(slug)}-(\d+)$")
    max_num = 0
    for entry in section_entries:
        match = pattern.match(entry.get("name", ""))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"{slug}-{max_num + 1:03d}"


def _generate_legacy_keypoint_name(existing_names: set) -> str:
    """Generate a legacy kpt_NNN name for migration of bare strings.

    Used only during flat-to-sections migration in load_playbook().
    Preserves the legacy naming pattern for migrated entries (contract.md).
    """
    max_num = 0
    for name in existing_names:
        if name.startswith("kpt_"):
            try:
                num = int(name.split("_")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue
    return f"kpt_{max_num + 1:03d}"


def _default_playbook() -> dict:
    """Return a default empty sections-based playbook.

    @implements REQ-SECT-001
    """
    return {
        "version": "1.0",
        "last_updated": None,
        "sections": {name: [] for name in SECTION_SLUGS},
    }


def _resolve_section(section_name: str) -> str:
    """Resolve a section name via case-insensitive exact match.

    Strips leading/trailing whitespace before matching.
    Returns the canonical section name if matched, or "OTHERS" as fallback.

    @implements REQ-SECT-005
    @invariant INV-SECT-002 (section names from canonical set)
    """
    if not section_name or not section_name.strip():
        return "OTHERS"
    stripped = section_name.strip()
    for canonical in SECTION_SLUGS:
        if canonical.upper() == stripped.upper():
            return canonical
    return "OTHERS"


def load_settings() -> dict:
    settings_path = get_user_claude_dir() / "settings.json"

    if not settings_path.exists():
        return {"playbook_update_on_exit": False, "playbook_update_on_clear": False}

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return {"playbook_update_on_exit": False, "playbook_update_on_clear": False}


def load_playbook() -> dict:
    """Load playbook from disk, migrating flat format to sections if needed.

    @implements REQ-SECT-006, REQ-SECT-007, REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006
    @invariant INV-SECT-001 (sections key always present)
    @invariant INV-SECT-004 (legacy IDs preserved during migration)
    @invariant INV-SECT-006 (migration round-trip stability)
    @invariant INV-SECT-007 (no key_points key in output)
    """
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    if not playbook_path.exists():
        return _default_playbook()

    try:
        with open(playbook_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # REQ-SECT-007: Dual-key handling -- sections takes precedence
        if "sections" in data and "key_points" in data:
            data.pop("key_points")
            # LOG-SECT-003: Dual-key warning diagnostic
            if is_diagnostic_mode():
                save_diagnostic(
                    "Dual-key playbook.json detected: both 'sections' and 'key_points' present. "
                    "Using 'sections', ignoring 'key_points'.",
                    "sections_dual_key_warning"
                )

        if "sections" in data:
            # Already migrated: ensure all 5 canonical sections exist
            for section_name in SECTION_SLUGS:
                if section_name not in data["sections"]:
                    data["sections"][section_name] = []
            # @invariant INV-SECT-007: no key_points key in output
            data.pop("key_points", None)
            return data

        if "key_points" not in data:
            return _default_playbook()

        # REQ-SECT-006: Flat format migration to sections
        # Apply scoring migration to each entry (same branches as scoring module)
        keypoints = []
        existing_names = set()
        migrated_entries = []

        for item in data["key_points"]:
            if isinstance(item, str):
                # Branch 1: Bare string (REQ-SCORE-004, SCN-SCORE-004-01)
                # Uses legacy kpt_NNN naming during migration (contract.md)
                name = _generate_legacy_keypoint_name(existing_names)
                keypoints.append({"name": name, "text": item, "helpful": 0, "harmful": 0})
                existing_names.add(name)
                migrated_entries.append({"name": name, "from": "bare_string", "original_score": None})
            elif isinstance(item, dict):
                if "helpful" in item and "harmful" in item:
                    # Branch 0: Already migrated (no-op, keep as-is)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    # Drop "score" if it somehow co-exists (defensive, SCN-SCORE-006-02)
                    item.pop("score", None)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                elif "score" in item:
                    # Branch 3: Dict with score (REQ-SCORE-006, SCN-SCORE-006-01)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    original_score = item.pop("score")
                    item["helpful"] = max(original_score, 0)
                    item["harmful"] = max(-original_score, 0)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_with_score", "original_score": original_score})
                else:
                    # Branch 2: Dict without score or counters (REQ-SCORE-005, SCN-SCORE-005-01)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    item["helpful"] = 0
                    item["harmful"] = 0
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_no_score", "original_score": None})

        # @invariant INV-SCORE-001, INV-SCORE-002 (counters >= 0)
        # @invariant INV-SCORE-004 (no score field)
        # @invariant INV-SCORE-005 (round-trip stability: migrated entries re-load as Branch 0 no-op)

        # LOG-SCORE-001: Diagnostic logging for scoring migration
        if migrated_entries and is_diagnostic_mode():
            migration_summary = json.dumps(migrated_entries, indent=2)
            save_diagnostic(
                f"Migrated {len(migrated_entries)} playbook entries:\n{migration_summary}",
                "playbook_migration"
            )

        # Place ALL migrated entries into OTHERS section
        # @invariant INV-SECT-004: Legacy IDs preserved (no renaming)
        sections = {name: [] for name in SECTION_SLUGS}
        sections["OTHERS"] = keypoints

        # LOG-SECT-001: Sections migration diagnostic
        if keypoints and is_diagnostic_mode():
            save_diagnostic(
                f"Migrated {len(keypoints)} entries from flat key_points to OTHERS section",
                "sections_migration"
            )

        data["sections"] = sections
        data.pop("key_points", None)
        # @invariant INV-SECT-007: no key_points key in output
        return data

    except Exception:
        return _default_playbook()


def save_playbook(playbook: dict):
    """Save playbook to disk.

    @implements INV-SECT-001 (assertion that sections key is present)
    @invariant INV-SECT-001 (sections key always present after write)
    @invariant INV-SECT-007 (no key_points key in output)
    """
    assert "sections" in playbook, (
        "Playbook must have 'sections' key. "
        "Got keys: " + str(list(playbook.keys()))
    )
    playbook.pop("key_points", None)  # INV-SECT-007: strip legacy key if present
    playbook["last_updated"] = datetime.now().isoformat()
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(playbook, f, indent=2, ensure_ascii=False)


def format_playbook(playbook: dict) -> str:
    """Format playbook with section headers for prompt injection.

    @implements REQ-SECT-003
    """
    sections = playbook.get("sections", {})

    section_blocks = []
    for section_name in SECTION_SLUGS:  # Canonical order
        entries = sections.get(section_name, [])
        if not entries:
            continue  # Omit empty sections (SCN-SECT-003-02)

        lines = [f"## {section_name}"]
        for kp in entries:
            lines.append(
                f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
            )
        section_blocks.append("\n".join(lines))

    if not section_blocks:
        return ""

    key_points_text = "\n\n".join(section_blocks)

    template = load_template("playbook.txt")
    return template.format(key_points=key_points_text)


def update_playbook_data(playbook: dict, extraction_result: dict) -> dict:
    """Apply new key points, evaluations, and pruning across all sections.

    Signature is UNCHANGED from the scoring module -- callers must not break.

    @implements REQ-SECT-005, REQ-SECT-008
    @invariant INV-SECT-002 (section names from canonical set)
    @invariant INV-SECT-003 (counter non-negativity)
    @invariant INV-SECT-005 (section-slug ID prefix consistency)
    """
    new_key_points = extraction_result.get("new_key_points", [])
    evaluations = extraction_result.get("evaluations", [])

    # Collect all existing texts across all sections for dedup
    existing_texts = set()
    for entries in playbook["sections"].values():
        for kp in entries:
            existing_texts.add(kp["text"])

    # REQ-SECT-005: New key point insertion with section resolution
    for item in new_key_points:
        # Backward compat: plain string -> {"text": str, "section": "OTHERS"}
        # (SCN-SECT-004-03)
        if isinstance(item, str):
            text = item
            section_name = "OTHERS"
        elif isinstance(item, dict):
            text = item.get("text", "")
            raw_section = item.get("section", "") or ""
            section_name = _resolve_section(raw_section)
            # LOG-SECT-002: Unknown section fallback diagnostic
            # Only emitted for non-empty strings that don't match canonical names
            # (SCN-SECT-004-05: missing/None/empty do NOT trigger this)
            if section_name == "OTHERS" and raw_section and raw_section.strip():
                # Check if the resolved "OTHERS" was due to unknown name vs. explicit "OTHERS"
                stripped_upper = raw_section.strip().upper()
                if stripped_upper != "OTHERS":
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Unknown section '{raw_section}' for key point: \"{text[:80]}\". "
                            f"Assigned to OTHERS.",
                            "sections_unknown_section"
                        )
        else:
            continue  # Skip invalid entry types

        if not text or text in existing_texts:
            continue

        slug = SECTION_SLUGS[section_name]
        target_entries = playbook["sections"][section_name]
        name = generate_keypoint_name(target_entries, slug)
        target_entries.append({"name": name, "text": text, "helpful": 0, "harmful": 0})
        existing_texts.add(text)

    # REQ-SECT-008: Evaluations across ALL sections
    # Build name-to-keypoint lookup across ALL sections
    name_to_kp = {}
    for entries in playbook["sections"].values():
        for kp in entries:
            name_to_kp[kp["name"]] = kp

    for eval_item in evaluations:
        name = eval_item.get("name", "")
        rating = eval_item.get("rating", "")

        if name in name_to_kp:
            if rating == "helpful":
                name_to_kp[name]["helpful"] += 1
            elif rating == "harmful":
                name_to_kp[name]["harmful"] += 1
            # "neutral" and unrecognized ratings: no change (SCN-SCORE-002-03, SCN-SCORE-002-04)

    # REQ-SECT-008: Pruning across ALL sections
    # @invariant INV-SCORE-003: Zero-evaluation entries (helpful=0, harmful=0) are never pruned
    pruned_entries = []
    for section_name in playbook["sections"]:
        surviving = []
        for kp in playbook["sections"][section_name]:
            harmful = kp.get("harmful", 0)
            helpful = kp.get("helpful", 0)
            if harmful >= 3 and harmful > helpful:
                pruned_entries.append(kp)
            else:
                surviving.append(kp)
        playbook["sections"][section_name] = surviving

    # LOG-SCORE-002: Diagnostic logging for pruning
    if pruned_entries and is_diagnostic_mode():
        prune_details = []
        for kp in pruned_entries:
            prune_details.append(
                f"  - {kp['name']}: \"{kp['text'][:80]}\" "
                f"(helpful={kp['helpful']}, harmful={kp['harmful']}) "
                f"reason: harmful >= 3 AND harmful > helpful"
            )
        save_diagnostic(
            f"Pruned {len(pruned_entries)} key points:\n" + "\n".join(prune_details),
            "playbook_pruning"
        )

    return playbook


def load_transcript(transcript_path: str) -> list[dict]:
    if not transcript_path or not Path(transcript_path).exists():
        return []

    conversations = []

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            entry = json.loads(line)

            if entry.get("type") not in ["user", "assistant"]:
                continue
            if entry.get("isMeta") or entry.get("isVisibleInTranscriptOnly"):
                continue

            message = entry.get("message", {})
            role = message.get("role")
            content = message.get("content", "")

            if not role or not content:
                continue

            if isinstance(content, str) and (
                "<command-name>" in content or "<local-command-stdout>" in content
            ):
                continue

            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if text_parts:
                    conversations.append(
                        {"role": role, "content": "\n".join(text_parts)}
                    )
            else:
                conversations.append({"role": role, "content": content})

    return conversations


def load_template(template_name: str) -> str:
    template_path = get_user_claude_dir() / "prompts" / template_name
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


async def extract_keypoints(
    messages: list[dict], playbook: dict, diagnostic_name: str = "reflection"
) -> dict:
    """Extract key points from reasoning trajectories via LLM.

    @implements REQ-SECT-009
    """
    if not ANTHROPIC_AVAILABLE:
        return {"new_key_points": [], "evaluations": []}

    settings = load_settings()

    model = (
        os.getenv("AGENTIC_CONTEXT_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or "claude-sonnet-4-5-20250929"
    )
    if not model:
        return {"new_key_points": [], "evaluations": []}

    api_key = (
        os.getenv("AGENTIC_CONTEXT_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key:
        return {"new_key_points": [], "evaluations": []}

    base_url = os.getenv("AGENTIC_CONTEXT_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

    template = load_template("reflection.txt")

    # @implements REQ-SECT-009: Build flat {name: text} dict from ALL sections
    playbook_dict = {}
    for entries in playbook.get("sections", {}).values():
        for kp in entries:
            playbook_dict[kp["name"]] = kp["text"]

    prompt = template.format(
        trajectories=json.dumps(messages, indent=2, ensure_ascii=False),
        playbook=json.dumps(playbook_dict, indent=2, ensure_ascii=False),
    )

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**client_kwargs)

    response = client.messages.create(
        model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}]
    )

    response_text_parts = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            response_text_parts.append(block.text)

    response_text = "".join(response_text_parts)

    if is_diagnostic_mode():
        save_diagnostic(
            f"# PROMPT\n{prompt}\n\n{'=' * 80}\n\n# RESPONSE\n{response_text}\n",
            diagnostic_name,
        )

    if not response_text:
        return {"new_key_points": [], "evaluations": []}

    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        json_text = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        json_text = response_text[start:end].strip()
    else:
        json_text = response_text.strip()

    try:
        result = json.loads(json_text)
    except json.JSONDecodeError:
        return {"new_key_points": [], "evaluations": []}

    return {
        "new_key_points": result.get("new_key_points", []),
        "evaluations": result.get("evaluations", []),
    }
