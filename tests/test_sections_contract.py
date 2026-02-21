# Spec: docs/sections/spec.md
# Contract: docs/sections/contract.md
# Testing: docs/sections/testing.md
"""
Contract (black-box) tests for the sections module.

These tests exercise the public API as documented in contract.md.
They do NOT reference internal branches, implementation details, or design.md.
They verify only behaviors promised by the data contracts.
"""

import asyncio
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import src.hooks.common as _common_module

from src.hooks.common import (
    SECTION_SLUGS,
    extract_keypoints,
    format_playbook,
    generate_keypoint_name,
    load_playbook,
    save_playbook,
    update_playbook_data,
)


def _setup_extract_keypoints_mocks(monkeypatch):
    """Set up all mocks needed to call extract_keypoints() without a real LLM.

    Returns the mock_client so callers can inspect calls to messages.create().
    """
    # Set env vars so extract_keypoints proceeds past guards
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AGENTIC_CONTEXT_MODEL", "claude-test")

    # Ensure ANTHROPIC_AVAILABLE is True
    monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", True)

    # Mock load_template to return a template with {playbook} and {trajectories}
    monkeypatch.setattr(
        _common_module,
        "load_template",
        lambda name: "Trajectories: {trajectories}\nPlaybook: {playbook}",
    )

    # Build mock Anthropic client
    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = '{"new_key_points": [], "evaluations": []}'
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_cls = MagicMock(return_value=mock_client)

    # Create a fake anthropic module with Anthropic class
    fake_anthropic = ModuleType("anthropic")
    setattr(fake_anthropic, "Anthropic", mock_anthropic_cls)
    monkeypatch.setattr(_common_module, "anthropic", fake_anthropic, raising=False)

    return mock_client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Set CLAUDE_PROJECT_DIR to a temp directory with .claude/ structure."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def playbook_path(project_dir):
    """Return the path to playbook.json inside the temp project dir."""
    return project_dir / ".claude" / "playbook.json"


@pytest.fixture
def mock_template(monkeypatch):
    """Monkeypatch load_template to return a known template string."""
    template_content = "HEADER\n{key_points}\nFOOTER"

    def _load_template(name):
        return template_content

    monkeypatch.setattr("src.hooks.common.load_template", _load_template)
    return template_content


def _write_playbook_file(playbook_path, data):
    """Helper to write a playbook.json file."""
    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _make_sections_playbook(sections_dict=None):
    """Helper to construct a sections-based playbook dict.

    If sections_dict is None, returns empty playbook.
    Otherwise merges provided sections into default empty sections.
    """
    sections = {name: [] for name in SECTION_SLUGS}
    if sections_dict:
        sections.update(sections_dict)
    return {"version": "1.0", "last_updated": None, "sections": sections}


# ===========================================================================
# REQ-SECT-001: Sections-Based Playbook Schema
# ===========================================================================


# @tests-contract REQ-SECT-001
def test_contract_playbook_sections_schema(project_dir, playbook_path):
    """Contract: save_playbook writes sections-based JSON with all canonical sections."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
        ],
    })
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    # Per contract.md: sections key present, key_points absent
    assert "sections" in saved
    assert "key_points" not in saved
    assert "version" in saved
    assert "last_updated" in saved
    assert saved["last_updated"] is not None

    # All 5 canonical sections present
    for section_name in SECTION_SLUGS:
        assert section_name in saved["sections"]

    # Entry conforms to PlaybookEntry schema
    entry = saved["sections"]["PATTERNS & APPROACHES"][0]
    assert isinstance(entry["name"], str)
    assert isinstance(entry["text"], str)
    assert isinstance(entry["helpful"], int)
    assert isinstance(entry["harmful"], int)
    assert entry["helpful"] >= 0
    assert entry["harmful"] >= 0


# @tests-contract REQ-SECT-001
def test_contract_empty_playbook_returns_default(project_dir):
    """Contract: Missing file -> default empty playbook with all sections."""
    playbook = load_playbook()
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    assert "sections" in playbook
    assert "key_points" not in playbook
    for section_name in SECTION_SLUGS:
        assert section_name in playbook["sections"]
        assert isinstance(playbook["sections"][section_name], list)
        assert playbook["sections"][section_name] == []


# @tests-contract REQ-SECT-001
def test_contract_save_requires_sections():
    """Contract: save_playbook raises AssertionError without sections key."""
    with pytest.raises(AssertionError):
        save_playbook({"version": "1.0", "last_updated": None})


# @tests-contract REQ-SECT-001
def test_contract_save_strips_stale_key_points(project_dir, playbook_path):
    """Contract: save_playbook guarantees no key_points key in written file,
    even when the input dict contains one."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "test", "helpful": 0, "harmful": 0},
        ],
    })
    # Simulate a buggy caller that passes both sections and key_points
    playbook["key_points"] = [{"name": "stale", "text": "leftover", "helpful": 0, "harmful": 0}]
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "key_points" not in saved
    assert "sections" in saved


# ===========================================================================
# REQ-SECT-002: Section-Prefixed Key Point IDs
# ===========================================================================


# @tests-contract REQ-SECT-002
def test_contract_generate_keypoint_name():
    """Contract: generate_keypoint_name returns {slug}-{NNN:03d} format."""
    # Per contract.md: scans for {slug}-NNN, returns next available
    result = generate_keypoint_name([], "pat")
    assert result == "pat-001"

    entries = [
        {"name": "pat-001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "pat-003", "text": "b", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "pat")
    assert result == "pat-004"

    # Legacy kpt_NNN entries ignored
    entries = [
        {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "oth-002", "text": "b", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "oth")
    assert result == "oth-003"


# ===========================================================================
# REQ-SECT-003: Formatted Output with Section Headers
# ===========================================================================


# @tests-contract REQ-SECT-003
def test_contract_format_playbook_sections(project_dir, mock_template):
    """Contract: format_playbook outputs section headers in canonical order."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
        ],
        "USER PREFERENCES": [
            {"name": "pref-001", "text": "prefer pathlib", "helpful": 2, "harmful": 0},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy point", "helpful": 0, "harmful": 0},
        ],
    })
    result = format_playbook(playbook)

    # Per contract.md: sections in canonical order, empty omitted
    assert "## PATTERNS & APPROACHES" in result
    assert "## USER PREFERENCES" in result
    assert "## OTHERS" in result
    assert "## MISTAKES TO AVOID" not in result
    assert "## PROJECT CONTEXT" not in result

    # Per contract.md: entry format
    assert "[pat-001] helpful=5 harmful=1 :: use type hints" in result
    assert "[pref-001] helpful=2 harmful=0 :: prefer pathlib" in result
    assert "[kpt_001] helpful=0 harmful=0 :: legacy point" in result

    # Canonical ordering preserved
    pat_pos = result.index("## PATTERNS & APPROACHES")
    pref_pos = result.index("## USER PREFERENCES")
    oth_pos = result.index("## OTHERS")
    assert pat_pos < pref_pos < oth_pos

    # Template wrapper
    assert "HEADER" in result
    assert "FOOTER" in result


# @tests-contract REQ-SECT-003
def test_contract_format_empty_returns_empty(project_dir, mock_template):
    """Contract: All sections empty -> returns empty string."""
    playbook = _make_sections_playbook()
    result = format_playbook(playbook)
    assert result == ""


# ===========================================================================
# REQ-SECT-004: LLM Categorization of New Key Points
# ===========================================================================


# @tests-contract REQ-SECT-004
def test_contract_reflection_template_sections():
    """Contract: reflection.txt lists all canonical section names and JSON format."""
    template_path = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src" / "prompts" / "reflection.txt")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Per contract.md: template lists all section names
    for section_name in SECTION_SLUGS:
        assert section_name in content, f"Section '{section_name}' missing from template"

    # JSON format shows text and section fields
    assert '"text"' in content
    assert '"section"' in content


# ===========================================================================
# REQ-SECT-005: Backward Compatible Handling of new_key_points
# ===========================================================================


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_section_assignment(project_dir):
    """Contract: Dict with valid section is placed in the correct section."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [
            {"text": "avoid globals", "section": "MISTAKES TO AVOID"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # Per contract.md: entry placed in specified section
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 1
    kp = result["sections"]["MISTAKES TO AVOID"][0]
    assert kp["text"] == "avoid globals"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_backward_compat(project_dir):
    """Contract: Plain string is treated as OTHERS."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": ["use structured logging"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # Per contract.md: plain string -> OTHERS
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["text"] == "use structured logging"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_unknown_section_to_others(project_dir):
    """Contract: Unknown section name falls back to OTHERS."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [
            {"text": "some tip", "section": "NONEXISTENT"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["text"] == "some tip"


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_case_insensitive(project_dir):
    """Contract: Section matching is case-insensitive."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [
            {"text": "a tip", "section": "patterns & approaches"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_missing_section_to_others(project_dir):
    """Contract: Missing/None/empty section falls back to OTHERS."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [
            {"text": "no section key"},
            {"text": "null section", "section": None},
            {"text": "empty section", "section": ""},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 3


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_empty_text_skipped(project_dir):
    """Contract: Empty text is not added."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [{"text": "", "section": "OTHERS"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests-contract REQ-SECT-005
def test_contract_new_keypoint_duplicate_skipped(project_dir):
    """Contract: Duplicate text across any section is skipped."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "existing tip", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "new_key_points": [
            {"text": "existing tip", "section": "OTHERS"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# ===========================================================================
# REQ-SECT-006: Migration from Flat Format to Sections
# ===========================================================================


# @tests-contract REQ-SECT-006
def test_contract_flat_migration(project_dir, playbook_path):
    """Contract: Flat key_points array migrated to sections with entries in OTHERS."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-15T10:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()

    # Per contract.md: returns sections-based dict
    assert "sections" in playbook
    assert "key_points" not in playbook

    # All entries in OTHERS
    assert len(playbook["sections"]["OTHERS"]) == 2
    names = [kp["name"] for kp in playbook["sections"]["OTHERS"]]
    assert "kpt_001" in names
    assert "kpt_002" in names

    # Other sections empty
    for section_name in SECTION_SLUGS:
        if section_name != "OTHERS":
            assert playbook["sections"][section_name] == []


# @tests-contract REQ-SECT-006
def test_contract_flat_migration_with_legacy_formats(project_dir, playbook_path):
    """Contract: Flat playbook with all legacy formats migrated correctly."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "no score"},
            {"name": "kpt_003", "text": "has score", "score": -3},
            {"name": "kpt_004", "text": "canonical", "helpful": 2, "harmful": 1},
        ],
    })
    playbook = load_playbook()

    assert "sections" in playbook
    assert "key_points" not in playbook
    others = playbook["sections"]["OTHERS"]
    assert len(others) == 4

    # All conform to PlaybookEntry schema
    for entry in others:
        assert isinstance(entry["name"], str)
        assert isinstance(entry["text"], str)
        assert isinstance(entry["helpful"], int)
        assert isinstance(entry["harmful"], int)
        assert entry["helpful"] >= 0
        assert entry["harmful"] >= 0
        assert "score" not in entry


# ===========================================================================
# REQ-SECT-007: Dual-Key File Handling
# ===========================================================================


# @tests-contract REQ-SECT-007
def test_contract_dual_key_handling(project_dir, playbook_path):
    """Contract: Dual-key file: sections takes precedence, key_points ignored."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["PATTERNS & APPROACHES"] = [
        {"name": "pat-001", "text": "from sections", "helpful": 1, "harmful": 0},
    ]
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
        "key_points": [
            {"name": "kpt_001", "text": "from key_points", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()

    # Per contract.md: sections used, key_points ignored
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["text"] == "from sections"


# ===========================================================================
# REQ-SECT-008: Evaluations and Pruning Across Sections
# ===========================================================================


# @tests-contract REQ-SECT-008
def test_contract_evaluations_across_sections(project_dir):
    """Contract: Evaluations find key points regardless of which section they are in."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "new_key_points": [],
        "evaluations": [
            {"name": "pat-001", "rating": "helpful"},
            {"name": "kpt_001", "rating": "harmful"},
        ],
    }
    result = update_playbook_data(playbook, extraction)

    # Per contract.md: counters updated regardless of section
    assert result["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 4
    assert result["sections"]["OTHERS"][0]["harmful"] == 1


# @tests-contract REQ-SECT-008
def test_contract_pruning_across_sections(project_dir):
    """Contract: Pruning removes entries from their respective sections."""
    playbook = _make_sections_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 1, "harmful": 4},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "good tip", "helpful": 5, "harmful": 0},
        ],
    })
    extraction = {"new_key_points": [], "evaluations": []}
    result = update_playbook_data(playbook, extraction)

    # Per contract.md: harmful >= 3 AND harmful > helpful -> pruned
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0
    assert len(result["sections"]["OTHERS"]) == 1


# ===========================================================================
# REQ-SECT-009: Flat Key Point Extraction for LLM Prompt
# ===========================================================================


# @tests-contract REQ-SECT-009
def test_contract_extract_keypoints_flat_dict(monkeypatch):
    """Contract: extract_keypoints builds flat {name: text} dict from all sections.

    Calls the actual extract_keypoints() function with a mocked Anthropic client
    to verify the playbook dict-building behavior documented in contract.md.
    """
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })

    mock_client = _setup_extract_keypoints_mocks(monkeypatch)

    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Per contract.md: the function should call the LLM API
    mock_client.messages.create.assert_called_once()

    # Verify the prompt contains the flat {name: text} dict
    call_kwargs = mock_client.messages.create.call_args
    prompt_content = call_kwargs.kwargs["messages"][0]["content"]
    expected_dict = {"pat-001": "use types", "kpt_001": "legacy tip"}
    assert json.dumps(expected_dict, indent=2, ensure_ascii=False) in prompt_content

    # Per contract.md: returns extraction result
    assert result == {"new_key_points": [], "evaluations": []}


# @tests-contract REQ-SECT-009
def test_contract_extract_keypoints_empty_sections(monkeypatch):
    """Contract: Empty sections -> empty playbook dict sent to LLM."""
    playbook = _make_sections_playbook()

    mock_client = _setup_extract_keypoints_mocks(monkeypatch)

    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Per contract.md: the function should still call the LLM API even with empty playbook
    mock_client.messages.create.assert_called_once()

    # Verify empty dict was sent in the prompt
    call_kwargs = mock_client.messages.create.call_args
    prompt_content = call_kwargs.kwargs["messages"][0]["content"]
    assert json.dumps({}, indent=2, ensure_ascii=False) in prompt_content

    # Per contract.md: returns extraction result
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# REQ-SECT-010: Canonical Section-to-Slug Mapping
# ===========================================================================


# @tests-contract REQ-SECT-010
def test_contract_section_slugs_constant():
    """Contract: SECTION_SLUGS has the documented canonical entries."""
    # Per contract.md: exact mapping
    assert SECTION_SLUGS["PATTERNS & APPROACHES"] == "pat"
    assert SECTION_SLUGS["MISTAKES TO AVOID"] == "mis"
    assert SECTION_SLUGS["USER PREFERENCES"] == "pref"
    assert SECTION_SLUGS["PROJECT CONTEXT"] == "ctx"
    assert SECTION_SLUGS["OTHERS"] == "oth"
    assert len(SECTION_SLUGS) == 5

    # Iteration order is canonical
    names = list(SECTION_SLUGS.keys())
    assert names == [
        "PATTERNS & APPROACHES",
        "MISTAKES TO AVOID",
        "USER PREFERENCES",
        "PROJECT CONTEXT",
        "OTHERS",
    ]


# ===========================================================================
# Deliverable Tests: Full Lifecycle
# ===========================================================================


# @tests-contract REQ-SECT-001, REQ-SECT-003, REQ-SECT-005, REQ-SECT-006, REQ-SECT-008
def test_contract_full_lifecycle_migration_and_update(
    project_dir, playbook_path, mock_template
):
    """Deliverable test: Flat file -> load -> update with sections -> save -> load -> format."""
    # Step 1: Write flat-format playbook
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    })

    # Step 2: Load (migration)
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook

    # Step 3: Update with section-aware new key points
    extraction = {
        "new_key_points": [
            {"text": "always test edge cases", "section": "PATTERNS & APPROACHES"},
            {"text": "never use eval()", "section": "MISTAKES TO AVOID"},
            "uncategorized tip",
        ],
        "evaluations": [
            {"name": "kpt_001", "rating": "helpful"},
        ],
    }
    playbook = update_playbook_data(playbook, extraction)

    # Verify section assignment
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert len(playbook["sections"]["MISTAKES TO AVOID"]) == 1
    # kpt_001, kpt_002, and uncategorized tip in OTHERS
    assert len(playbook["sections"]["OTHERS"]) == 3

    # Step 4: Save
    save_playbook(playbook)

    # Step 5: Load again (round-trip)
    playbook2 = load_playbook()
    assert "sections" in playbook2
    assert "key_points" not in playbook2
    assert len(playbook2["sections"]["PATTERNS & APPROACHES"]) == 1
    assert len(playbook2["sections"]["MISTAKES TO AVOID"]) == 1

    # Step 6: Format
    formatted = format_playbook(playbook2)
    assert "## PATTERNS & APPROACHES" in formatted
    assert "## MISTAKES TO AVOID" in formatted
    assert "## OTHERS" in formatted
    assert "HEADER" in formatted
    assert "FOOTER" in formatted
    assert "[pat-001]" in formatted
    assert "[mis-001]" in formatted


# @tests-contract REQ-SECT-001, REQ-SECT-006, REQ-SECT-008
def test_contract_full_lifecycle_pruning_across_sections(
    project_dir, playbook_path, mock_template
):
    """Deliverable test: Entries in different sections, pruning removes from correct one."""
    # Start with sections-based playbook
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "good pattern", "helpful": 5, "harmful": 0},
        ],
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "borderline", "helpful": 0, "harmful": 2},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy", "helpful": 0, "harmful": 0},
        ],
    })

    # Push mis-001 over pruning threshold
    extraction = {
        "new_key_points": [],
        "evaluations": [
            {"name": "mis-001", "rating": "harmful"},  # harmful: 2 -> 3
            {"name": "pat-001", "rating": "helpful"},    # helpful: 5 -> 6
        ],
    }
    playbook = update_playbook_data(playbook, extraction)

    # mis-001 pruned (harmful=3 > helpful=0), others retained
    assert len(playbook["sections"]["MISTAKES TO AVOID"]) == 0
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert len(playbook["sections"]["OTHERS"]) == 1

    # Save and reload
    save_playbook(playbook)
    playbook2 = load_playbook()
    assert len(playbook2["sections"]["MISTAKES TO AVOID"]) == 0
    assert len(playbook2["sections"]["PATTERNS & APPROACHES"]) == 1

    # Format: MISTAKES TO AVOID should not appear (empty)
    formatted = format_playbook(playbook2)
    assert "## PATTERNS & APPROACHES" in formatted
    assert "## MISTAKES TO AVOID" not in formatted


# @tests-contract REQ-SECT-005, REQ-SECT-008
def test_contract_full_lifecycle_new_keypoints_to_sections(
    project_dir, playbook_path, mock_template
):
    """Deliverable test: Add new key points to multiple sections, verify round-trip."""
    playbook = _make_sections_playbook()

    # Add entries to different sections
    extraction = {
        "new_key_points": [
            {"text": "use type hints", "section": "PATTERNS & APPROACHES"},
            {"text": "avoid bare except", "section": "MISTAKES TO AVOID"},
            {"text": "prefers vim", "section": "USER PREFERENCES"},
            {"text": "uses Django", "section": "PROJECT CONTEXT"},
            "uncategorized",
        ],
        "evaluations": [],
    }
    playbook = update_playbook_data(playbook, extraction)

    # Each section got one entry
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert len(playbook["sections"]["MISTAKES TO AVOID"]) == 1
    assert len(playbook["sections"]["USER PREFERENCES"]) == 1
    assert len(playbook["sections"]["PROJECT CONTEXT"]) == 1
    assert len(playbook["sections"]["OTHERS"]) == 1

    # Verify slug-based naming
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["name"] == "pat-001"
    assert playbook["sections"]["MISTAKES TO AVOID"][0]["name"] == "mis-001"
    assert playbook["sections"]["USER PREFERENCES"][0]["name"] == "pref-001"
    assert playbook["sections"]["PROJECT CONTEXT"][0]["name"] == "ctx-001"
    assert playbook["sections"]["OTHERS"][0]["name"] == "oth-001"

    # Save and reload
    save_playbook(playbook)
    playbook2 = load_playbook()

    # Format: all non-empty sections appear
    formatted = format_playbook(playbook2)
    assert "## PATTERNS & APPROACHES" in formatted
    assert "## MISTAKES TO AVOID" in formatted
    assert "## USER PREFERENCES" in formatted
    assert "## PROJECT CONTEXT" in formatted
    assert "## OTHERS" in formatted
