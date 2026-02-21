# Spec: docs/sections/spec.md
# Testing: docs/sections/testing.md
"""
White-box tests for the sections module (src/hooks/common.py).

Covers all REQ-SECT-001 through REQ-SECT-010, all 18 SCN-SECT-* scenarios,
all 7 INV-SECT-* invariants, and LOG-SECT-001/002/003 instrumentation tests.
"""

import asyncio
import json
import os
import sys
import glob as glob_module
from unittest.mock import MagicMock, patch
from types import ModuleType

import pytest

# Ensure the project root is on sys.path so we can import from src.hooks.common
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import src.hooks.common as _common_module

from src.hooks.common import (
    SECTION_SLUGS,
    _default_playbook,
    _generate_legacy_keypoint_name,
    _resolve_section,
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
    """Set CLAUDE_PROJECT_DIR to a temp directory and create .claude/ structure."""
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


@pytest.fixture
def enable_diagnostic(project_dir):
    """Enable diagnostic mode by creating the flag file."""
    flag_file = project_dir / ".claude" / "diagnostic_mode"
    flag_file.touch()
    return project_dir


@pytest.fixture
def diagnostic_dir(project_dir):
    """Return the path to the diagnostic output directory."""
    d = project_dir / ".claude" / "diagnostic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_playbook(playbook_path, data):
    """Helper to write a playbook.json file."""
    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _make_playbook(sections_dict=None):
    """Helper to construct a sections-based playbook dict.

    If sections_dict is None, returns default empty playbook.
    If sections_dict is a dict, uses it directly as sections.
    """
    if sections_dict is None:
        return _default_playbook()
    sections = {name: [] for name in SECTION_SLUGS}
    sections.update(sections_dict)
    return {"version": "1.0", "last_updated": None, "sections": sections}


def _make_extraction(new_key_points=None, evaluations=None):
    """Helper to construct an extraction_result dict."""
    return {
        "new_key_points": new_key_points or [],
        "evaluations": evaluations or [],
    }


# ===========================================================================
# REQ-SECT-001: Sections-Based Playbook Schema
# ===========================================================================


# @tests REQ-SECT-001
def test_save_playbook_sections_schema(project_dir, playbook_path):
    """After save_playbook, file has sections key with canonical sections,
    no key_points key, and version/last_updated fields."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy point", "helpful": 0, "harmful": 0},
        ],
    })
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert "sections" in saved
    assert "key_points" not in saved
    assert "version" in saved
    assert "last_updated" in saved
    assert saved["last_updated"] is not None

    # All 5 canonical sections present
    for section_name in SECTION_SLUGS:
        assert section_name in saved["sections"]

    # Entry schema check
    entry = saved["sections"]["PATTERNS & APPROACHES"][0]
    assert entry["name"] == "pat-001"
    assert entry["text"] == "use type hints"
    assert entry["helpful"] == 5
    assert entry["harmful"] == 1


# @tests REQ-SECT-001
def test_default_playbook_has_all_sections():
    """_default_playbook returns a dict with all 5 canonical sections."""
    pb = _default_playbook()
    assert "sections" in pb
    assert pb["version"] == "1.0"
    assert pb["last_updated"] is None
    for section_name in SECTION_SLUGS:
        assert section_name in pb["sections"]
        assert pb["sections"][section_name] == []


# @tests REQ-SECT-001
def test_load_missing_file_returns_default(project_dir):
    """load_playbook returns default empty playbook when file missing."""
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    for section_name in SECTION_SLUGS:
        assert section_name in playbook["sections"]
        assert playbook["sections"][section_name] == []


# @tests REQ-SECT-001
def test_load_corrupt_json_returns_default(project_dir, playbook_path):
    """load_playbook returns default empty playbook when JSON is corrupt."""
    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    playbook_path.write_text("NOT VALID JSON {{{")
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    for section_name in SECTION_SLUGS:
        assert playbook["sections"][section_name] == []


# ===========================================================================
# REQ-SECT-002: Section-Prefixed Key Point IDs
# ===========================================================================


# @tests REQ-SECT-002
def test_generate_keypoint_name_basic():
    """generate_keypoint_name returns {slug}-001 for empty section."""
    result = generate_keypoint_name([], "pat")
    assert result == "pat-001"


# @tests REQ-SECT-002
def test_generate_keypoint_name_existing():
    """generate_keypoint_name returns max+1 for existing entries."""
    entries = [
        {"name": "pat-001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "pat-003", "text": "b", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "pat")
    assert result == "pat-004"


# @tests REQ-SECT-002
def test_generate_keypoint_name_legacy_ignored():
    """generate_keypoint_name ignores kpt_NNN entries when scanning."""
    entries = [
        {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "kpt_005", "text": "b", "helpful": 0, "harmful": 0},
        {"name": "oth-002", "text": "c", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "oth")
    assert result == "oth-003"


# @tests SCN-SECT-002-01
def test_scn_generate_first_id_empty_section():
    """SCN-SECT-002-01: Empty section, slug 'pat' -> 'pat-001'."""
    result = generate_keypoint_name([], "pat")
    assert result == "pat-001"


# @tests SCN-SECT-002-02
def test_scn_generate_next_id_after_existing():
    """SCN-SECT-002-02: Section with pat-001, pat-003 -> pat-004."""
    entries = [
        {"name": "pat-001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "pat-003", "text": "b", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "pat")
    assert result == "pat-004"


# @tests SCN-SECT-002-03
def test_scn_legacy_kpt_ids_ignored_in_counter():
    """SCN-SECT-002-03: OTHERS with kpt_001, kpt_005, oth-002 -> oth-003."""
    entries = [
        {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "kpt_005", "text": "b", "helpful": 0, "harmful": 0},
        {"name": "oth-002", "text": "c", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "oth")
    assert result == "oth-003"


# @tests REQ-SECT-002
def test_generate_keypoint_name_no_name_key():
    """Entries without 'name' key are safely skipped (defensive)."""
    entries = [
        {"text": "a", "helpful": 0, "harmful": 0},
    ]
    result = generate_keypoint_name(entries, "pat")
    assert result == "pat-001"


# ===========================================================================
# REQ-SECT-003: Formatted Output with Section Headers
# ===========================================================================


# @tests REQ-SECT-003
def test_format_playbook_section_headers(project_dir, mock_template):
    """format_playbook outputs section headers in canonical order."""
    playbook = _make_playbook({
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

    assert "## PATTERNS & APPROACHES" in result
    assert "## USER PREFERENCES" in result
    assert "## OTHERS" in result
    assert "## MISTAKES TO AVOID" not in result
    assert "## PROJECT CONTEXT" not in result

    # Verify ordering: PATTERNS before USER PREFERENCES before OTHERS
    pat_pos = result.index("## PATTERNS & APPROACHES")
    pref_pos = result.index("## USER PREFERENCES")
    oth_pos = result.index("## OTHERS")
    assert pat_pos < pref_pos < oth_pos

    # Template wrapper
    assert result.startswith("HEADER\n")
    assert result.endswith("\nFOOTER")


# @tests REQ-SECT-003
def test_format_empty_sections_omitted(project_dir, mock_template):
    """Empty sections are omitted from format output."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "only here", "helpful": 0, "harmful": 0},
        ],
    })
    result = format_playbook(playbook)
    assert "## OTHERS" in result
    assert "## PATTERNS & APPROACHES" not in result
    assert "## MISTAKES TO AVOID" not in result
    assert "## USER PREFERENCES" not in result
    assert "## PROJECT CONTEXT" not in result


# @tests REQ-SECT-003
def test_format_all_empty_returns_empty(project_dir, mock_template):
    """All sections empty -> returns empty string."""
    playbook = _make_playbook()
    result = format_playbook(playbook)
    assert result == ""


# @tests REQ-SECT-003
def test_format_entry_format_preserved(project_dir, mock_template):
    """Entry format is [name] helpful=X harmful=Y :: text."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
        ],
    })
    result = format_playbook(playbook)
    assert "[pat-001] helpful=5 harmful=1 :: use type hints" in result


# @tests SCN-SECT-003-01
def test_scn_format_multiple_sections(project_dir, mock_template):
    """SCN-SECT-003-01: Format playbook with multiple sections."""
    playbook = _make_playbook({
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

    # Must have the exact spec output format
    assert "[pat-001] helpful=5 harmful=1 :: use type hints" in result
    assert "[pref-001] helpful=2 harmful=0 :: prefer pathlib" in result
    assert "[kpt_001] helpful=0 harmful=0 :: legacy point" in result

    # Empty sections omitted
    assert "## MISTAKES TO AVOID" not in result
    assert "## PROJECT CONTEXT" not in result


# @tests SCN-SECT-003-02
def test_scn_format_empty_playbook_returns_empty(project_dir, mock_template):
    """SCN-SECT-003-02: All sections empty -> returns empty string."""
    playbook = _make_playbook()
    result = format_playbook(playbook)
    assert result == ""


# @tests SCN-SECT-003-03
def test_scn_format_overhead_within_20_percent(project_dir, mock_template):
    """SCN-SECT-003-03: Sections output overhead within 20% of flat equivalent."""
    # 20 entries across 5 sections (4 each)
    all_entries = {}
    flat_lines = []
    idx = 0
    for section_name, slug in SECTION_SLUGS.items():
        entries = []
        for i in range(1, 5):
            name = f"{slug}-{i:03d}"
            text = f"entry for {section_name} number {i}"
            entry = {"name": name, "text": text, "helpful": i, "harmful": 0}
            entries.append(entry)
            flat_lines.append(
                f"[{name}] helpful={i} harmful=0 :: {text}"
            )
            idx += 1
        all_entries[section_name] = entries

    playbook = _make_playbook(all_entries)
    result = format_playbook(playbook)

    # Extract just the key_points portion (between HEADER and FOOTER)
    key_points_text = result.replace("HEADER\n", "").replace("\nFOOTER", "")

    flat_equivalent = "\n".join(flat_lines)
    overhead = (len(key_points_text) - len(flat_equivalent)) / len(flat_equivalent)
    assert overhead <= 0.20, f"Overhead is {overhead:.2%}, exceeds 20%"


# ===========================================================================
# REQ-SECT-004: LLM Categorization of New Key Points
# ===========================================================================


# @tests REQ-SECT-004
def test_reflection_template_lists_sections():
    """reflection.txt lists all canonical section names and JSON format."""
    template_path = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src" / "prompts" / "reflection.txt")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # All canonical section names must be listed
    for section_name in SECTION_SLUGS:
        assert section_name in content, f"Section '{section_name}' not found in template"

    # JSON output format shows dict with text and section
    assert '"text"' in content
    assert '"section"' in content


# ===========================================================================
# REQ-SECT-005: Backward Compatible Handling of new_key_points
# ===========================================================================


# @tests REQ-SECT-005
def test_update_dict_with_valid_section(project_dir):
    """Dict entry with valid section is placed in the correct section."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "avoid globals", "section": "MISTAKES TO AVOID"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 1
    kp = result["sections"]["MISTAKES TO AVOID"][0]
    assert kp["text"] == "avoid globals"
    assert kp["name"].startswith("mis-")
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# @tests REQ-SECT-005
def test_update_dict_with_unknown_section(project_dir):
    """Dict entry with unknown section falls back to OTHERS."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "some tip", "section": "RANDOM STUFF"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["text"] == "some tip"
    assert kp["name"].startswith("oth-")


# @tests REQ-SECT-005
def test_update_plain_string_backward_compat(project_dir):
    """Plain string entry is treated as OTHERS with oth-NNN ID."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=["use structured logging"])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["text"] == "use structured logging"
    assert kp["name"].startswith("oth-")
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# @tests REQ-SECT-005
def test_update_case_insensitive_match(project_dir):
    """Section matching is case-insensitive."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "use patterns", "section": "patterns & approaches"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1


# @tests REQ-SECT-005
def test_update_missing_null_empty_section(project_dir):
    """Missing, None, and empty section fields fall back to OTHERS."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "insight one"},
        {"text": "insight two", "section": None},
        {"text": "insight three", "section": ""},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 3
    for kp in result["sections"]["OTHERS"]:
        assert kp["name"].startswith("oth-")


# @tests REQ-SECT-005
def test_update_empty_text_skipped(project_dir):
    """Empty text in new_key_points is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "", "section": "OTHERS"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SECT-005
def test_update_duplicate_text_skipped(project_dir):
    """Duplicate text across sections is skipped."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "existing tip", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(new_key_points=[
        {"text": "existing tip", "section": "OTHERS"},
    ])
    result = update_playbook_data(playbook, extraction)
    # Should not be added -- duplicate
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SECT-005
def test_update_mixed_string_and_dict(project_dir):
    """Mixed list of strings and dicts processes correctly."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        "plain string tip",
        {"text": "dict tip", "section": "PATTERNS & APPROACHES"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["text"] == "plain string tip"
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1
    assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "dict tip"


# @tests SCN-SECT-004-01
def test_scn_dict_with_valid_section(project_dir):
    """SCN-SECT-004-01: Dict with valid section MISTAKES TO AVOID -> mis-001."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "avoid globals", "section": "MISTAKES TO AVOID"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 1
    kp = result["sections"]["MISTAKES TO AVOID"][0]
    assert kp["name"] == "mis-001"
    assert kp["text"] == "avoid globals"


# @tests SCN-SECT-004-02
def test_scn_dict_with_unknown_section(project_dir):
    """SCN-SECT-004-02: Dict with unknown section 'RANDOM STUFF' -> OTHERS."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "some tip", "section": "RANDOM STUFF"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["name"].startswith("oth-")


# @tests SCN-SECT-004-03
def test_scn_plain_string_backward_compat(project_dir):
    """SCN-SECT-004-03: Plain string -> OTHERS with oth-NNN."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=["use structured logging"])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["text"] == "use structured logging"
    assert kp["name"].startswith("oth-")


# @tests SCN-SECT-004-04
def test_scn_case_mismatch_and_whitespace(project_dir):
    """SCN-SECT-004-04: Case mismatch and whitespace -> PATTERNS & APPROACHES."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "use patterns", "section": "patterns & approaches"},
        {"text": "another pattern", "section": "  patterns & approaches  "},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2


# @tests SCN-SECT-004-05
def test_scn_missing_null_empty_section_to_others(project_dir, enable_diagnostic):
    """SCN-SECT-004-05: Missing, None, empty section -> OTHERS, no OBS-SECT-002."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "Some insight"},
        {"text": "Another", "section": None},
        {"text": "Third", "section": ""},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 3

    # Verify no OBS-SECT-002 diagnostic was emitted for missing/None/empty sections
    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        unknown_section_files = list(diag_dir.glob("*_sections_unknown_section.txt"))
        assert len(unknown_section_files) == 0, (
            "OBS-SECT-002 diagnostic was emitted for missing/null/empty section fields, "
            "but SCN-SECT-004-05 requires no OBS-SECT-002 for these cases"
        )


# ===========================================================================
# REQ-SECT-006: Migration from Flat Format to Sections
# ===========================================================================


# @tests REQ-SECT-006
def test_load_migrates_flat_to_sections(project_dir, playbook_path):
    """Flat key_points array is migrated to sections with all entries in OTHERS."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-15T10:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert len(playbook["sections"]["OTHERS"]) == 2

    # Other sections are empty
    for section_name in SECTION_SLUGS:
        if section_name != "OTHERS":
            assert playbook["sections"][section_name] == []

    # IDs preserved
    names = [kp["name"] for kp in playbook["sections"]["OTHERS"]]
    assert "kpt_001" in names
    assert "kpt_002" in names


# @tests REQ-SECT-006
def test_load_migrates_flat_with_legacy_scores(project_dir, playbook_path):
    """Flat playbook with legacy scores is migrated correctly."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "some tip", "score": -3},
        ],
    })
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    others = playbook["sections"]["OTHERS"]
    assert len(others) == 2

    # Bare string -> kpt_001, helpful=0, harmful=0
    bare = others[0]
    assert bare["name"] == "kpt_001"
    assert bare["text"] == "bare string entry"
    assert bare["helpful"] == 0
    assert bare["harmful"] == 0

    # Score=-3 -> helpful=0, harmful=3
    scored = others[1]
    assert scored["name"] == "kpt_002"
    assert scored["helpful"] == 0
    assert scored["harmful"] == 3
    assert "score" not in scored


# @tests SCN-SECT-006-01
def test_scn_migrate_flat_with_mixed_ids(project_dir, playbook_path):
    """SCN-SECT-006-01: Migrate flat playbook with kpt_001, kpt_002."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-15T10:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    others = playbook["sections"]["OTHERS"]
    assert len(others) == 2
    assert others[0]["name"] == "kpt_001"
    assert others[1]["name"] == "kpt_002"
    for section_name in SECTION_SLUGS:
        if section_name != "OTHERS":
            assert playbook["sections"][section_name] == []


# @tests SCN-SECT-006-02
def test_scn_migrate_flat_with_legacy_score_field(project_dir, playbook_path):
    """SCN-SECT-006-02: Migrate flat playbook with bare string and score field."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "some tip", "score": -3},
        ],
    })
    playbook = load_playbook()
    others = playbook["sections"]["OTHERS"]
    assert len(others) == 2
    # Bare string
    assert others[0]["name"] == "kpt_001"
    assert others[0]["text"] == "bare string entry"
    assert others[0]["helpful"] == 0
    assert others[0]["harmful"] == 0
    # Score migration
    assert others[1]["name"] == "kpt_002"
    assert others[1]["helpful"] == 0
    assert others[1]["harmful"] == 3
    assert "score" not in others[1]


# @tests SCN-SECT-006-03
def test_scn_load_already_sections_based(project_dir, playbook_path):
    """SCN-SECT-006-03: Already sections-based playbook is loaded as-is."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["PATTERNS & APPROACHES"] = [
        {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-02-01T00:00:00",
        "sections": sections_data,
    })
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["name"] == "pat-001"


# ===========================================================================
# REQ-SECT-007: Dual-Key File Handling
# ===========================================================================


# @tests REQ-SECT-007
def test_load_dual_key_sections_precedence(project_dir, playbook_path):
    """Dual-key file: sections takes precedence, key_points ignored."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["PATTERNS & APPROACHES"] = [
        {"name": "pat-001", "text": "from sections", "helpful": 1, "harmful": 0},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "sections": sections_data,
        "key_points": [
            {"name": "kpt_001", "text": "from key_points", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["text"] == "from sections"
    # key_points data should NOT appear anywhere
    all_names = []
    for entries in playbook["sections"].values():
        for kp in entries:
            all_names.append(kp["name"])
    assert "kpt_001" not in all_names


# @tests SCN-SECT-006-04
def test_scn_dual_key_file_handling(project_dir, playbook_path):
    """SCN-SECT-006-04: Dual-key file -> sections used, key_points ignored."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["OTHERS"] = [
        {"name": "oth-001", "text": "from sections", "helpful": 0, "harmful": 0},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "sections": sections_data,
        "key_points": [
            {"name": "kpt_999", "text": "ignored", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    assert "key_points" not in playbook
    assert len(playbook["sections"]["OTHERS"]) == 1
    assert playbook["sections"]["OTHERS"][0]["name"] == "oth-001"


# ===========================================================================
# REQ-SECT-008: Evaluations and Pruning Across Sections
# ===========================================================================


# @tests REQ-SECT-008
def test_evaluations_across_sections(project_dir):
    """Evaluations find key points across sections."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(evaluations=[
        {"name": "pat-001", "rating": "helpful"},
        {"name": "kpt_001", "rating": "harmful"},
    ])
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"][0]
    assert pat["helpful"] == 4
    oth = result["sections"]["OTHERS"][0]
    assert oth["harmful"] == 1


# @tests REQ-SECT-008
def test_pruning_across_sections(project_dir):
    """Pruning removes entries from correct sections."""
    playbook = _make_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 1, "harmful": 4},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "good tip", "helpful": 5, "harmful": 0},
        ],
    })
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0  # pruned
    assert len(result["sections"]["OTHERS"]) == 1  # retained


# @tests SCN-SECT-008-01
def test_scn_evaluation_finds_keypoint_across_sections(project_dir):
    """SCN-SECT-008-01: Evaluation finds key points regardless of section."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(evaluations=[
        {"name": "pat-001", "rating": "helpful"},
        {"name": "kpt_001", "rating": "harmful"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert result["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 4
    assert result["sections"]["OTHERS"][0]["harmful"] == 1


# @tests SCN-SECT-008-02
def test_scn_pruning_removes_from_correct_section(project_dir):
    """SCN-SECT-008-02: Pruned entry removed from MISTAKES TO AVOID, not from OTHERS."""
    playbook = _make_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 1, "harmful": 4},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "good tip", "helpful": 5, "harmful": 0},
        ],
    })
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"] == "kpt_001"


# ===========================================================================
# REQ-SECT-009: Flat Key Point Extraction for LLM Prompt
# ===========================================================================


# @tests REQ-SECT-009
def test_extract_keypoints_flat_dict(monkeypatch):
    """extract_keypoints builds flat {name: text} dict from all sections."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })

    mock_client = _setup_extract_keypoints_mocks(monkeypatch)

    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Verify the mock was called
    mock_client.messages.create.assert_called_once()

    # Extract the prompt that was sent to the LLM
    call_kwargs = mock_client.messages.create.call_args
    prompt_content = call_kwargs.kwargs["messages"][0]["content"]

    # Verify the playbook dict in the prompt contains the expected flat dict
    expected_dict = {"pat-001": "use types", "kpt_001": "legacy tip"}
    assert json.dumps(expected_dict, indent=2, ensure_ascii=False) in prompt_content

    # Verify the return value
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-SECT-009
def test_extract_keypoints_empty_sections(monkeypatch):
    """Empty sections -> empty playbook dict sent to LLM."""
    playbook = _make_playbook()

    mock_client = _setup_extract_keypoints_mocks(monkeypatch)

    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Verify the mock was called
    mock_client.messages.create.assert_called_once()

    # Extract the prompt and verify empty dict was sent
    call_kwargs = mock_client.messages.create.call_args
    prompt_content = call_kwargs.kwargs["messages"][0]["content"]
    assert json.dumps({}, indent=2, ensure_ascii=False) in prompt_content

    # Verify the return value
    assert result == {"new_key_points": [], "evaluations": []}


# @tests SCN-SECT-009-01
def test_scn_extract_flat_dict_from_sections(monkeypatch):
    """SCN-SECT-009-01: Flat dict from sections includes all entries."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy tip", "helpful": 0, "harmful": 0},
        ],
    })

    mock_client = _setup_extract_keypoints_mocks(monkeypatch)

    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Verify the mock was called
    mock_client.messages.create.assert_called_once()

    # Extract the prompt sent to the LLM
    call_kwargs = mock_client.messages.create.call_args
    prompt_content = call_kwargs.kwargs["messages"][0]["content"]

    # Verify the playbook dict in the prompt contains the expected flat dict
    expected_dict = {"pat-001": "use types", "kpt_001": "legacy tip"}
    playbook_json_str = json.dumps(expected_dict, indent=2, ensure_ascii=False)
    assert playbook_json_str in prompt_content

    # Extract the playbook JSON from the prompt and verify keys
    playbook_start = prompt_content.index("Playbook: ") + len("Playbook: ")
    playbook_json = prompt_content[playbook_start:]
    parsed_dict = json.loads(playbook_json)
    assert "pat-001" in parsed_dict
    assert "kpt_001" in parsed_dict
    assert parsed_dict["pat-001"] == "use types"
    assert parsed_dict["kpt_001"] == "legacy tip"
    # Section names should NOT be keys in the dict
    for section_name in SECTION_SLUGS:
        assert section_name not in parsed_dict

    # Verify the return value
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# REQ-SECT-010: Canonical Section-to-Slug Mapping
# ===========================================================================


# @tests REQ-SECT-010
def test_section_slugs_constant():
    """SECTION_SLUGS has 5 canonical entries with correct slug values."""
    assert SECTION_SLUGS == {
        "PATTERNS & APPROACHES": "pat",
        "MISTAKES TO AVOID": "mis",
        "USER PREFERENCES": "pref",
        "PROJECT CONTEXT": "ctx",
        "OTHERS": "oth",
    }
    # Iteration order is canonical (Python 3.7+ guarantee)
    names = list(SECTION_SLUGS.keys())
    assert names == [
        "PATTERNS & APPROACHES",
        "MISTAKES TO AVOID",
        "USER PREFERENCES",
        "PROJECT CONTEXT",
        "OTHERS",
    ]


# @tests REQ-SECT-010
def test_all_slugs_produce_correct_ids():
    """For each slug in SECTION_SLUGS, generate_keypoint_name([],slug) returns {slug}-001."""
    for section_name, slug in SECTION_SLUGS.items():
        result = generate_keypoint_name([], slug)
        assert result == f"{slug}-001", f"Failed for section {section_name}"


# ===========================================================================
# _resolve_section internal function tests
# ===========================================================================


# @tests REQ-SECT-005
def test_resolve_section_exact_match():
    """_resolve_section returns canonical name for exact match."""
    assert _resolve_section("PATTERNS & APPROACHES") == "PATTERNS & APPROACHES"
    assert _resolve_section("MISTAKES TO AVOID") == "MISTAKES TO AVOID"
    assert _resolve_section("USER PREFERENCES") == "USER PREFERENCES"
    assert _resolve_section("PROJECT CONTEXT") == "PROJECT CONTEXT"
    assert _resolve_section("OTHERS") == "OTHERS"


# @tests REQ-SECT-005
def test_resolve_section_case_insensitive():
    """_resolve_section matches case-insensitively."""
    assert _resolve_section("patterns & approaches") == "PATTERNS & APPROACHES"
    assert _resolve_section("Patterns & Approaches") == "PATTERNS & APPROACHES"
    assert _resolve_section("others") == "OTHERS"


# @tests REQ-SECT-005
def test_resolve_section_whitespace_stripping():
    """_resolve_section strips leading/trailing whitespace."""
    assert _resolve_section("  MISTAKES TO AVOID  ") == "MISTAKES TO AVOID"
    assert _resolve_section("  patterns & approaches  ") == "PATTERNS & APPROACHES"


# @tests REQ-SECT-005
def test_resolve_section_unknown_to_others():
    """_resolve_section returns OTHERS for unknown section names."""
    assert _resolve_section("RANDOM STUFF") == "OTHERS"
    assert _resolve_section("NOT A SECTION") == "OTHERS"


# @tests REQ-SECT-005
def test_resolve_section_empty_none():
    """_resolve_section returns OTHERS for empty, whitespace-only, and None."""
    assert _resolve_section("") == "OTHERS"
    assert _resolve_section("   ") == "OTHERS"
    assert _resolve_section(None) == "OTHERS"


# ===========================================================================
# _generate_legacy_keypoint_name internal function tests
# ===========================================================================


# @tests REQ-SECT-006
def test_generate_legacy_keypoint_name():
    """_generate_legacy_keypoint_name generates kpt_NNN from existing names."""
    assert _generate_legacy_keypoint_name(set()) == "kpt_001"
    assert _generate_legacy_keypoint_name({"kpt_001"}) == "kpt_002"
    assert _generate_legacy_keypoint_name({"kpt_001", "kpt_003"}) == "kpt_004"


# ===========================================================================
# INV-SECT-001: Sections Key Always Present After Write
# ===========================================================================


# @tests-invariant INV-SECT-001
def test_invariant_sections_key_always_present_after_save(project_dir, playbook_path):
    """After save_playbook, the JSON file has a 'sections' key."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "test", "helpful": 0, "harmful": 0},
        ],
    })
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "sections" in saved


# @tests-invariant INV-SECT-001
def test_invariant_save_rejects_missing_sections():
    """save_playbook raises AssertionError if 'sections' key is missing."""
    bad_playbook = {"version": "1.0", "last_updated": None}
    with pytest.raises(AssertionError):
        save_playbook(bad_playbook)


# ===========================================================================
# INV-SECT-002: Section Names from Canonical Set
# ===========================================================================


# @tests-invariant INV-SECT-002
def test_invariant_section_names_canonical(project_dir, playbook_path):
    """After load_playbook from various formats, section names are canonical."""
    canonical_set = set(SECTION_SLUGS.keys())

    # Test 1: Missing file
    playbook = load_playbook()
    assert set(playbook["sections"].keys()) == canonical_set

    # Test 2: Flat format
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [{"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0}],
    })
    playbook = load_playbook()
    assert set(playbook["sections"].keys()) == canonical_set

    # Test 3: Sections format missing one section
    sections_data = {name: [] for name in SECTION_SLUGS}
    del sections_data["PROJECT CONTEXT"]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
    })
    playbook = load_playbook()
    assert set(playbook["sections"].keys()) == canonical_set


# ===========================================================================
# INV-SECT-003: Counter Non-Negativity
# ===========================================================================


# @tests-invariant INV-SECT-003
def test_invariant_counters_non_negative(project_dir, playbook_path):
    """After migration, all entries have helpful >= 0 and harmful >= 0."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "no score"},
            {"name": "kpt_003", "text": "neg score", "score": -5},
            {"name": "kpt_004", "text": "pos score", "score": 3},
            {"name": "kpt_005", "text": "canonical", "helpful": 2, "harmful": 1},
        ],
    })
    playbook = load_playbook()
    for section_entries in playbook["sections"].values():
        for kp in section_entries:
            assert kp["helpful"] >= 0, f"{kp['name']} has negative helpful"
            assert kp["harmful"] >= 0, f"{kp['name']} has negative harmful"


# ===========================================================================
# INV-SECT-004: Legacy IDs Preserved During Migration
# ===========================================================================


# @tests-invariant INV-SECT-004
def test_invariant_legacy_ids_preserved(project_dir, playbook_path):
    """Legacy kpt_NNN IDs are preserved during flat-to-sections migration."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            {"name": "kpt_001", "text": "first", "helpful": 0, "harmful": 0},
            {"name": "kpt_002", "text": "second", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    names = [kp["name"] for kp in playbook["sections"]["OTHERS"]]
    assert "kpt_001" in names
    assert "kpt_002" in names


# ===========================================================================
# INV-SECT-005: Section-Slug ID Prefix Consistency
# ===========================================================================


# @tests-invariant INV-SECT-005
def test_invariant_slug_id_prefix_consistency(project_dir):
    """New key points in each section use the correct slug prefix."""
    playbook = _make_playbook()
    # Add entries to each section
    new_key_points = []
    for section_name in SECTION_SLUGS:
        new_key_points.append({"text": f"tip for {section_name}", "section": section_name})

    extraction = _make_extraction(new_key_points=new_key_points)
    result = update_playbook_data(playbook, extraction)

    for section_name, slug in SECTION_SLUGS.items():
        entries = result["sections"][section_name]
        assert len(entries) == 1, f"Expected 1 entry in {section_name}, got {len(entries)}"
        assert entries[0]["name"].startswith(f"{slug}-"), \
            f"Expected {slug}-NNN prefix in {section_name}, got {entries[0]['name']}"


# ===========================================================================
# INV-SECT-006: Migration Round-Trip Stability
# ===========================================================================


# @tests-invariant INV-SECT-006
def test_invariant_migration_round_trip_stability(project_dir, playbook_path):
    """Load flat playbook -> save -> load again: sections and version identical."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "dict no score"},
            {"name": "kpt_003", "text": "has score", "score": -3},
        ],
    })
    # First load (migration runs)
    playbook1 = load_playbook()
    sections_1 = json.dumps(playbook1["sections"], sort_keys=True)
    version_1 = playbook1["version"]

    # Save
    save_playbook(playbook1)

    # Second load (no migration needed)
    playbook2 = load_playbook()
    sections_2 = json.dumps(playbook2["sections"], sort_keys=True)
    version_2 = playbook2["version"]

    assert sections_1 == sections_2
    assert version_1 == version_2


# ===========================================================================
# INV-SECT-007: No key_points Key in Output
# ===========================================================================


# @tests-invariant INV-SECT-007
def test_invariant_no_key_points_key_after_load(project_dir, playbook_path):
    """After load_playbook from flat format, no key_points key in result."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    assert "key_points" not in playbook


# @tests-invariant INV-SECT-007
def test_invariant_no_key_points_key_after_save(project_dir, playbook_path):
    """After save_playbook, no key_points key in JSON file."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "test", "helpful": 0, "harmful": 0},
        ],
    })
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "key_points" not in saved


# @tests-invariant INV-SECT-007
def test_invariant_save_strips_key_points_if_present(project_dir, playbook_path):
    """save_playbook strips key_points key even if caller passes a dict containing it."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "test", "helpful": 0, "harmful": 0},
        ],
    })
    # Inject a stale key_points key to simulate a buggy caller
    playbook["key_points"] = [{"name": "kpt_001", "text": "stale", "helpful": 0, "harmful": 0}]
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert "key_points" not in saved
    assert "sections" in saved


# ===========================================================================
# LOG-SECT-001: Sections Migration Diagnostic
# ===========================================================================


# @tests-instrumentation LOG-SECT-001
def test_instrumentation_migration_diagnostic_created(
    project_dir, playbook_path, enable_diagnostic
):
    """Diagnostic mode on + flat playbook with entries -> migration diagnostic file created."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            {"name": "kpt_001", "text": "tip one", "helpful": 0, "harmful": 0},
            {"name": "kpt_002", "text": "tip two", "helpful": 1, "harmful": 0},
        ],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_sections_migration.txt"))
    assert len(files) >= 1, "Migration diagnostic file not created"

    content = files[0].read_text()
    assert "2" in content  # count of migrated entries


# @tests-instrumentation LOG-SECT-001
def test_instrumentation_migration_diagnostic_not_created_when_disabled(
    project_dir, playbook_path
):
    """Diagnostic mode off + flat playbook -> no migration diagnostic file."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            {"name": "kpt_001", "text": "tip", "helpful": 0, "harmful": 0},
        ],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_migration.txt"))
        assert len(files) == 0, "Migration diagnostic created when disabled"


# @tests-instrumentation LOG-SECT-001
def test_instrumentation_migration_diagnostic_not_created_when_no_migration(
    project_dir, playbook_path, enable_diagnostic
):
    """Diagnostic mode on + already sections-based -> no migration diagnostic."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["OTHERS"] = [
        {"name": "oth-001", "text": "existing", "helpful": 0, "harmful": 0},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_migration.txt"))
        assert len(files) == 0, "Migration diagnostic created when no migration occurred"


# ===========================================================================
# LOG-SECT-002: Unknown Section Fallback Diagnostic
# ===========================================================================


# @tests-instrumentation LOG-SECT-002
def test_instrumentation_unknown_section_diagnostic_created(
    project_dir, enable_diagnostic
):
    """Diagnostic mode on + unknown section name -> unknown section diagnostic created."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "some tip", "section": "RANDOM STUFF"},
    ])
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_sections_unknown_section.txt"))
    assert len(files) >= 1, "Unknown section diagnostic file not created"

    content = files[0].read_text()
    assert "RANDOM STUFF" in content
    assert "some tip" in content


# @tests-instrumentation LOG-SECT-002
def test_instrumentation_unknown_section_diagnostic_not_created_when_disabled(
    project_dir
):
    """Diagnostic mode off + unknown section -> no diagnostic file."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "some tip", "section": "RANDOM STUFF"},
    ])
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_unknown_section.txt"))
        assert len(files) == 0, "Unknown section diagnostic created when disabled"


# @tests-instrumentation LOG-SECT-002
def test_instrumentation_unknown_section_diagnostic_not_emitted_for_missing_null_empty(
    project_dir, enable_diagnostic
):
    """Diagnostic mode on + missing/None/empty section -> no OBS-SECT-002 diagnostic."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": "insight a", "section": None},
        {"text": "insight b", "section": ""},
        {"text": "insight c"},
    ])
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_unknown_section.txt"))
        assert len(files) == 0, (
            "Unknown section diagnostic emitted for missing/null/empty section"
        )


# @tests-instrumentation LOG-SECT-002
def test_instrumentation_unknown_section_text_truncated(
    project_dir, enable_diagnostic
):
    """Unknown section diagnostic truncates key point text to 80 chars."""
    long_text = "x" * 200
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        {"text": long_text, "section": "NONEXISTENT"},
    ])
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_sections_unknown_section.txt"))
    assert len(files) >= 1

    content = files[0].read_text()
    # Full 200-char text should NOT appear
    assert long_text not in content
    # First 80 chars should appear
    assert long_text[:80] in content


# ===========================================================================
# LOG-SECT-003: Dual-Key Warning Diagnostic
# ===========================================================================


# @tests-instrumentation LOG-SECT-003
def test_instrumentation_dual_key_diagnostic_created(
    project_dir, playbook_path, enable_diagnostic
):
    """Diagnostic mode on + dual-key file -> dual-key warning diagnostic created."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
        "key_points": [{"name": "kpt_001", "text": "ignored", "helpful": 0, "harmful": 0}],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_sections_dual_key_warning.txt"))
    assert len(files) >= 1, "Dual-key diagnostic file not created"

    content = files[0].read_text()
    assert "sections" in content.lower() or "dual" in content.lower()


# @tests-instrumentation LOG-SECT-003
def test_instrumentation_dual_key_diagnostic_not_created_when_disabled(
    project_dir, playbook_path
):
    """Diagnostic mode off + dual-key file -> no dual-key diagnostic."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
        "key_points": [{"name": "kpt_001", "text": "ignored", "helpful": 0, "harmful": 0}],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_dual_key_warning.txt"))
        assert len(files) == 0, "Dual-key diagnostic created when disabled"


# @tests-instrumentation LOG-SECT-003
def test_instrumentation_dual_key_diagnostic_not_created_for_normal_files(
    project_dir, playbook_path, enable_diagnostic
):
    """Diagnostic mode on + sections-only file -> no dual-key diagnostic."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_sections_dual_key_warning.txt"))
        assert len(files) == 0, "Dual-key diagnostic created for normal file"


# ===========================================================================
# Adversarial: Migration Correctness (TC-MIG-*)
# ===========================================================================


# @tests REQ-SECT-006 (TC-MIG-001)
def test_mig_001_all_legacy_types_migrate(project_dir, playbook_path):
    """TC-MIG-001: Bare string + dict-without-score + dict-with-score + already-migrated."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "no score dict"},
            {"name": "kpt_003", "text": "has score", "score": -3},
            {"name": "kpt_004", "text": "canonical", "helpful": 2, "harmful": 1},
        ],
    })
    playbook = load_playbook()
    assert len(playbook["sections"]["OTHERS"]) == 4
    for kp in playbook["sections"]["OTHERS"]:
        assert "score" not in kp
        assert kp["helpful"] >= 0
        assert kp["harmful"] >= 0


# @tests REQ-SECT-006 (TC-MIG-002)
def test_mig_002_empty_key_points_migrates(project_dir, playbook_path):
    """TC-MIG-002: Empty key_points migrates to all-empty sections."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "key_points": [],
    })
    playbook = load_playbook()
    assert "sections" in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SECT-007 (TC-MIG-003)
def test_mig_003_dual_key_sections_precedence(project_dir, playbook_path):
    """TC-MIG-003: Dual-key file: sections used, key_points ignored."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["PATTERNS & APPROACHES"] = [
        {"name": "pat-001", "text": "from sections", "helpful": 0, "harmful": 0},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
        "key_points": [
            {"name": "kpt_001", "text": "from key_points", "helpful": 0, "harmful": 0},
        ],
    })
    playbook = load_playbook()
    assert "key_points" not in playbook
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["text"] == "from sections"


# @tests SCN-SECT-006-03, INV-SECT-006 (TC-MIG-004)
def test_mig_004_double_load_no_change(project_dir, playbook_path):
    """TC-MIG-004: Already sections-based file loaded twice -> identical result."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    sections_data["OTHERS"] = [
        {"name": "oth-001", "text": "test", "helpful": 0, "harmful": 0},
    ]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "sections": sections_data,
    })
    playbook1 = load_playbook()
    save_playbook(playbook1)
    playbook2 = load_playbook()
    assert json.dumps(playbook1["sections"], sort_keys=True) == \
           json.dumps(playbook2["sections"], sort_keys=True)
    assert playbook1["version"] == playbook2["version"]


# @tests REQ-SECT-001 (TC-MIG-005)
def test_mig_005_missing_file_default(project_dir):
    """TC-MIG-005: Missing file -> default empty playbook."""
    playbook = load_playbook()
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    assert "sections" in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SECT-001 (TC-MIG-006)
def test_mig_006_corrupt_json_default(project_dir, playbook_path):
    """TC-MIG-006: Corrupt JSON -> default empty playbook."""
    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    playbook_path.write_text("{invalid json]]")
    playbook = load_playbook()
    assert "sections" in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SECT-001 (TC-MIG-007)
def test_mig_007_sections_missing_one_canonical(project_dir, playbook_path):
    """TC-MIG-007: Sections file missing one section -> added as empty."""
    sections_data = {name: [] for name in SECTION_SLUGS}
    del sections_data["PROJECT CONTEXT"]
    _write_playbook(playbook_path, {
        "version": "1.0",
        "sections": sections_data,
    })
    playbook = load_playbook()
    assert "PROJECT CONTEXT" in playbook["sections"]
    assert playbook["sections"]["PROJECT CONTEXT"] == []


# @tests INV-SECT-006 (TC-MIG-008)
def test_mig_008_round_trip_stability(project_dir, playbook_path):
    """TC-MIG-008: load->save->load: only last_updated changes."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        ],
    })
    playbook1 = load_playbook()
    save_playbook(playbook1)
    playbook2 = load_playbook()

    assert json.dumps(playbook1["sections"], sort_keys=True) == \
           json.dumps(playbook2["sections"], sort_keys=True)
    assert playbook1["version"] == playbook2["version"]


# ===========================================================================
# Adversarial: Section Name Resolution Edge Cases (TC-RES-*)
# ===========================================================================


# @tests REQ-SECT-005 (TC-RES-001)
def test_res_001_exact_canonical():
    """TC-RES-001: Exact canonical name returns itself."""
    assert _resolve_section("PATTERNS & APPROACHES") == "PATTERNS & APPROACHES"


# @tests REQ-SECT-005 (TC-RES-002)
def test_res_002_case_insensitive():
    """TC-RES-002: Case-insensitive match."""
    assert _resolve_section("patterns & approaches") == "PATTERNS & APPROACHES"


# @tests REQ-SECT-005 (TC-RES-003)
def test_res_003_whitespace():
    """TC-RES-003: Whitespace stripped before matching."""
    assert _resolve_section("  MISTAKES TO AVOID  ") == "MISTAKES TO AVOID"


# @tests REQ-SECT-005 (TC-RES-004)
def test_res_004_unknown():
    """TC-RES-004: Unknown section name -> OTHERS."""
    assert _resolve_section("RANDOM STUFF") == "OTHERS"


# @tests REQ-SECT-005 (TC-RES-005)
def test_res_005_whitespace_only():
    """TC-RES-005: Whitespace-only -> OTHERS."""
    assert _resolve_section("   ") == "OTHERS"


# @tests REQ-SECT-005 (TC-RES-006)
def test_res_006_none():
    """TC-RES-006: None -> OTHERS."""
    assert _resolve_section(None) == "OTHERS"


# @tests REQ-SECT-005 (TC-RES-007)
def test_res_007_empty():
    """TC-RES-007: Empty string -> OTHERS."""
    assert _resolve_section("") == "OTHERS"


# @tests REQ-SECT-005 (TC-RES-009)
def test_res_009_others_lowercase():
    """TC-RES-009: 'others' (lowercase) -> OTHERS."""
    assert _resolve_section("others") == "OTHERS"


# ===========================================================================
# Adversarial: ID Generation (TC-ID-*)
# ===========================================================================


# @tests REQ-SECT-002 (TC-ID-001)
def test_id_001_empty_section():
    """TC-ID-001: Empty section, slug 'pat' -> 'pat-001'."""
    assert generate_keypoint_name([], "pat") == "pat-001"


# @tests REQ-SECT-002 (TC-ID-002)
def test_id_002_gap_in_ids():
    """TC-ID-002: Section with pat-001, pat-003 -> pat-004."""
    entries = [
        {"name": "pat-001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "pat-003", "text": "b", "helpful": 0, "harmful": 0},
    ]
    assert generate_keypoint_name(entries, "pat") == "pat-004"


# @tests REQ-SECT-002 (TC-ID-003)
def test_id_003_legacy_and_new_coexist():
    """TC-ID-003: kpt_001, kpt_005, oth-002 -> oth-003."""
    entries = [
        {"name": "kpt_001", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "kpt_005", "text": "b", "helpful": 0, "harmful": 0},
        {"name": "oth-002", "text": "c", "helpful": 0, "harmful": 0},
    ]
    assert generate_keypoint_name(entries, "oth") == "oth-003"


# @tests REQ-SECT-002 (TC-ID-004)
def test_id_004_no_name_key_defensive():
    """TC-ID-004: Entry without 'name' key -> returns {slug}-001."""
    entries = [{"text": "a", "helpful": 0, "harmful": 0}]
    assert generate_keypoint_name(entries, "pat") == "pat-001"


# @tests REQ-SECT-010, INV-SECT-005 (TC-ID-005)
def test_id_005_all_slugs_correct_format():
    """TC-ID-005: All slugs produce correct {slug}-001 for empty sections."""
    for section_name, slug in SECTION_SLUGS.items():
        result = generate_keypoint_name([], slug)
        assert result == f"{slug}-001", f"Failed for {section_name}: got {result}"


# ===========================================================================
# Adversarial: Format Output (TC-FMT-*)
# ===========================================================================


# @tests REQ-SECT-003 (TC-FMT-003)
def test_fmt_003_only_others_has_entries(project_dir, mock_template):
    """TC-FMT-003: Only OTHERS has entries -> only ## OTHERS header."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "tip", "helpful": 0, "harmful": 0},
        ],
    })
    result = format_playbook(playbook)
    assert "## OTHERS" in result
    assert "## PATTERNS" not in result
    assert "## MISTAKES" not in result
    assert "## USER" not in result
    assert "## PROJECT" not in result


# @tests REQ-SECT-003 (TC-FMT-005)
def test_fmt_005_single_entry_one_section(project_dir, mock_template):
    """TC-FMT-005: Single entry in one section."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "single", "helpful": 1, "harmful": 0},
        ],
    })
    result = format_playbook(playbook)
    assert "## PATTERNS & APPROACHES" in result
    assert "[pat-001] helpful=1 harmful=0 :: single" in result


# @tests REQ-SECT-003 (TC-FMT-006)
def test_fmt_006_entry_format_unchanged_from_scoring(project_dir, mock_template):
    """TC-FMT-006: Entry format is [name] helpful=X harmful=Y :: text."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy point", "helpful": 3, "harmful": 2},
        ],
    })
    result = format_playbook(playbook)
    assert "[kpt_001] helpful=3 harmful=2 :: legacy point" in result


# ===========================================================================
# Adversarial: Backward Compatibility (TC-BC-*)
# ===========================================================================


# @tests REQ-SECT-005 (TC-BC-001)
def test_bc_001_plain_strings_in_new_key_points(project_dir):
    """TC-BC-001: Plain strings -> OTHERS with oth-NNN."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=["plain tip"])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"].startswith("oth-")


# @tests INV-SECT-005 (TC-BC-002)
def test_bc_002_legacy_kpt_and_oth_coexist(project_dir):
    """TC-BC-002: Legacy kpt_NNN and oth-NNN coexist in OTHERS."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy", "helpful": 0, "harmful": 0},
            {"name": "oth-001", "text": "new", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(new_key_points=["another tip"])
    result = update_playbook_data(playbook, extraction)
    names = [kp["name"] for kp in result["sections"]["OTHERS"]]
    assert "kpt_001" in names
    assert "oth-001" in names
    # New entry should be oth-002 (scans only oth-NNN pattern)
    assert "oth-002" in names


# @tests REQ-SECT-008 (TC-BC-003)
def test_bc_003_evaluations_find_legacy_across_sections(project_dir):
    """TC-BC-003: Evaluations find legacy kpt_001 in OTHERS."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "new", "helpful": 0, "harmful": 0},
        ],
        "OTHERS": [
            {"name": "kpt_001", "text": "legacy", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert result["sections"]["OTHERS"][0]["helpful"] == 1


# @tests REQ-SECT-005 (TC-BC-004)
def test_bc_004_mixed_strings_and_dicts(project_dir):
    """TC-BC-004: Mixed list of strings and dicts processes correctly."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[
        "string tip",
        {"text": "dict tip", "section": "PATTERNS & APPROACHES"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1


# @tests REQ-SECT-005 (TC-BC-005)
def test_bc_005_empty_text_skipped(project_dir):
    """TC-BC-005: Empty text in new_key_points is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(new_key_points=[""])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SECT-005 (TC-BC-006)
def test_bc_006_duplicate_text_skipped(project_dir):
    """TC-BC-006: Duplicate text across sections is skipped."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "existing tip", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(new_key_points=[
        {"text": "existing tip", "section": "OTHERS"},
    ])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# ===========================================================================
# Deliverable Test: Full Lifecycle
# ===========================================================================


# @tests REQ-SECT-001, REQ-SECT-003, REQ-SECT-005, REQ-SECT-006, REQ-SECT-008
def test_full_lifecycle_migration_update_format(project_dir, playbook_path, mock_template):
    """Full lifecycle: flat file -> load (migration) -> update -> save -> load -> format."""
    # Step 1: Write flat-format playbook
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    })

    # Step 2: Load (migration runs)
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    assert len(playbook["sections"]["OTHERS"]) == 2

    # Step 3: Update with section-aware new key points and evaluations
    extraction = _make_extraction(
        new_key_points=[
            {"text": "always test edge cases", "section": "PATTERNS & APPROACHES"},
            {"text": "never use eval()", "section": "MISTAKES TO AVOID"},
            "uncategorized tip",
        ],
        evaluations=[
            {"name": "kpt_001", "rating": "helpful"},
        ],
    )
    playbook = update_playbook_data(playbook, extraction)

    # kpt_001 helpful should be incremented
    kpt_001 = next(
        kp for kp in playbook["sections"]["OTHERS"] if kp["name"] == "kpt_001"
    )
    assert kpt_001["helpful"] == 6

    # New entries in correct sections
    assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
    assert playbook["sections"]["PATTERNS & APPROACHES"][0]["name"] == "pat-001"
    assert len(playbook["sections"]["MISTAKES TO AVOID"]) == 1
    assert playbook["sections"]["MISTAKES TO AVOID"][0]["name"] == "mis-001"

    # Uncategorized in OTHERS (with migrated entries)
    oth_names = [kp["name"] for kp in playbook["sections"]["OTHERS"]]
    assert "kpt_001" in oth_names
    assert "kpt_002" in oth_names
    assert any(n.startswith("oth-") for n in oth_names)

    # Step 4: Save
    save_playbook(playbook)

    # Step 5: Load again (round-trip)
    playbook2 = load_playbook()
    assert "sections" in playbook2
    assert "key_points" not in playbook2

    # Step 6: Format
    formatted = format_playbook(playbook2)
    assert "## PATTERNS & APPROACHES" in formatted
    assert "## MISTAKES TO AVOID" in formatted
    assert "## OTHERS" in formatted
    assert "HEADER" in formatted
    assert "FOOTER" in formatted
