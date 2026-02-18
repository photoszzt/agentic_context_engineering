#!/usr/bin/env python3
import json
import os
from pathlib import Path
from datetime import datetime

try:
    import anthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


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


def generate_keypoint_name(existing_names: set) -> str:
    max_num = 0
    for name in existing_names:
        if name.startswith("kpt_"):
            try:
                num = int(name.split("_")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue

    return f"kpt_{max_num + 1:03d}"


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
    # @implements REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    if not playbook_path.exists():
        return {"version": "1.0", "last_updated": None, "key_points": []}

    try:
        with open(playbook_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "key_points" not in data:
            data["key_points"] = []

        keypoints = []
        existing_names = set()
        migrated_entries = []

        for item in data["key_points"]:
            if isinstance(item, str):
                # Branch 1: Bare string (REQ-SCORE-004, SCN-SCORE-004-01)
                name = generate_keypoint_name(existing_names)
                keypoints.append({"name": name, "text": item, "helpful": 0, "harmful": 0})
                existing_names.add(name)
                migrated_entries.append({"name": name, "from": "bare_string", "original_score": None})
            elif isinstance(item, dict):
                if "helpful" in item and "harmful" in item:
                    # Branch 0: Already migrated (no-op, keep as-is)
                    if "name" not in item:
                        item["name"] = generate_keypoint_name(existing_names)
                    # Drop "score" if it somehow co-exists (defensive, SCN-SCORE-006-02)
                    item.pop("score", None)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                elif "score" in item:
                    # Branch 3: Dict with score (REQ-SCORE-006, SCN-SCORE-006-01)
                    if "name" not in item:
                        item["name"] = generate_keypoint_name(existing_names)
                    original_score = item.pop("score")
                    item["helpful"] = max(original_score, 0)
                    item["harmful"] = max(-original_score, 0)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_with_score", "original_score": original_score})
                else:
                    # Branch 2: Dict without score or counters (REQ-SCORE-005, SCN-SCORE-005-01)
                    if "name" not in item:
                        item["name"] = generate_keypoint_name(existing_names)
                    item["helpful"] = 0
                    item["harmful"] = 0
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_no_score", "original_score": None})

        # @invariant INV-SCORE-001, INV-SCORE-002 (counters >= 0)
        # @invariant INV-SCORE-004 (no score field)
        # @invariant INV-SCORE-005 (round-trip stability: migrated entries re-load as Branch 0 no-op)

        # LOG-SCORE-001: Diagnostic logging for migration
        if migrated_entries and is_diagnostic_mode():
            migration_summary = json.dumps(migrated_entries, indent=2)
            save_diagnostic(
                f"Migrated {len(migrated_entries)} playbook entries:\n{migration_summary}",
                "playbook_migration"
            )

        data["key_points"] = keypoints
        return data

    except Exception:
        return {"version": "1.0", "last_updated": None, "key_points": []}


def save_playbook(playbook: dict):
    playbook["last_updated"] = datetime.now().isoformat()
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(playbook, f, indent=2, ensure_ascii=False)


def format_playbook(playbook: dict) -> str:
    # @implements REQ-SCORE-003, REQ-SCORE-008
    key_points = playbook.get("key_points", [])
    if not key_points:
        return ""

    key_points_text = "\n".join(
        f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
        for kp in key_points
    )

    template = load_template("playbook.txt")
    return template.format(key_points=key_points_text)


def update_playbook_data(playbook: dict, extraction_result: dict) -> dict:
    # @implements REQ-SCORE-001, REQ-SCORE-002, REQ-SCORE-007
    new_key_points = extraction_result.get("new_key_points", [])
    evaluations = extraction_result.get("evaluations", [])

    existing_names = {kp["name"] for kp in playbook["key_points"]}
    existing_texts = {kp["text"] for kp in playbook["key_points"]}

    # REQ-SCORE-001: New key points use helpful/harmful counters
    for text in new_key_points:
        if text and text not in existing_texts:
            name = generate_keypoint_name(existing_names)
            playbook["key_points"].append({"name": name, "text": text, "helpful": 0, "harmful": 0})
            existing_names.add(name)

    # REQ-SCORE-002: Counter increment per rating
    name_to_kp = {kp["name"]: kp for kp in playbook["key_points"]}

    for eval_item in evaluations:
        name = eval_item.get("name", "")
        rating = eval_item.get("rating", "")

        if name in name_to_kp:
            if rating == "helpful":
                name_to_kp[name]["helpful"] += 1
            elif rating == "harmful":
                name_to_kp[name]["harmful"] += 1
            # "neutral" and unrecognized ratings: no change (SCN-SCORE-002-03, SCN-SCORE-002-04)

    # REQ-SCORE-007: Pruning rule -- harmful >= 3 AND harmful > helpful
    # @invariant INV-SCORE-003: Zero-evaluation entries (helpful=0, harmful=0) are never pruned
    pruned_entries = []
    surviving = []
    for kp in playbook["key_points"]:
        harmful = kp.get("harmful", 0)
        helpful = kp.get("helpful", 0)
        if harmful >= 3 and harmful > helpful:
            pruned_entries.append(kp)
        else:
            surviving.append(kp)

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

    playbook["key_points"] = surviving

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

    playbook_dict = (
        {kp["name"]: kp["text"] for kp in playbook["key_points"]}
        if playbook["key_points"]
        else {}
    )

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
