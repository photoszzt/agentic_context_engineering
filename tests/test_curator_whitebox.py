# Spec: docs/curator/spec.md
# Testing: docs/curator/testing.md
"""
White-box tests for the curator operations module (src/hooks/common.py).

Covers all REQ-CUR-001 through REQ-CUR-009, all 32 SCN-CUR-* scenarios,
all 6 INV-CUR-* invariants, and LOG-CUR-001/002/003 instrumentation tests.
"""

import asyncio
import copy
import json
import os
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Ensure the project root is on sys.path so we can import from src.hooks.common
sys.path.insert(0, "/data/agentic_context_engineering")

import src.hooks.common as _common_module

from src.hooks.common import (
    SECTION_SLUGS,
    _apply_curator_operations,
    _default_playbook,
    _resolve_section,
    extract_keypoints,
    generate_keypoint_name,
    update_playbook_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_extract_keypoints_mocks(monkeypatch):
    """Set up all mocks needed to call extract_keypoints() without a real LLM.

    Returns (mock_client, mock_text_block) so callers can set mock_text_block.text.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AGENTIC_CONTEXT_MODEL", "claude-test")
    monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(
        _common_module,
        "load_template",
        lambda name: "Trajectories: {trajectories}\nPlaybook: {playbook}",
    )

    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = '{"new_key_points": [], "evaluations": []}'
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_cls = MagicMock(return_value=mock_client)
    fake_anthropic = ModuleType("anthropic")
    setattr(fake_anthropic, "Anthropic", mock_anthropic_cls)
    monkeypatch.setattr(_common_module, "anthropic", fake_anthropic, raising=False)

    return mock_client, mock_text_block


def _make_playbook(sections_dict=None):
    """Construct a sections-based playbook dict."""
    if sections_dict is None:
        return _default_playbook()
    sections = {name: [] for name in SECTION_SLUGS}
    sections.update(sections_dict)
    return {"version": "1.0", "last_updated": None, "sections": sections}


def _make_extraction(operations=None, new_key_points=None, evaluations=None):
    """Construct an extraction_result dict with operations support."""
    result = {"evaluations": evaluations or []}
    if operations is not None:
        result["operations"] = operations
    if new_key_points is not None:
        result["new_key_points"] = new_key_points
    if "new_key_points" not in result and operations is None:
        result["new_key_points"] = []
    return result


def _collect_all_entries(playbook):
    """Flatten all entries from all sections into a single list."""
    entries = []
    for section_entries in playbook["sections"].values():
        entries.extend(section_entries)
    return entries


def _collect_all_texts(playbook):
    """Collect all entry texts from all sections into a set."""
    texts = set()
    for section_entries in playbook["sections"].values():
        for kp in section_entries:
            texts.add(kp["text"])
    return texts


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


# ===========================================================================
# REQ-CUR-001: Structured Operations in Extraction Result
# ===========================================================================


# @tests REQ-CUR-001
def test_extract_keypoints_returns_operations(monkeypatch):
    """extract_keypoints returns operations when LLM response includes them."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "evaluations": [{"name": "pat-001", "rating": "helpful"}],
        "operations": [{"type": "ADD", "text": "new insight", "section": "OTHERS"}],
    })
    playbook = _make_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))
    assert "operations" in result
    assert len(result["operations"]) == 1
    assert result["operations"][0]["type"] == "ADD"
    assert "evaluations" in result
    assert len(result["evaluations"]) == 1


# @tests SCN-CUR-001-01
def test_scn_extract_operations_present(monkeypatch):
    """SCN-CUR-001-01: LLM returns operations and evaluations."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "evaluations": [{"name": "pat-001", "rating": "helpful"}],
        "operations": [{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}],
    })
    playbook = _make_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))
    assert result["evaluations"] == [{"name": "pat-001", "rating": "helpful"}]
    assert result["operations"] == [{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}]


# @tests SCN-CUR-001-02
def test_scn_extract_empty_operations(monkeypatch):
    """SCN-CUR-001-02: LLM returns empty operations list."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "evaluations": [{"name": "pat-001", "rating": "helpful"}],
        "operations": [],
    })
    playbook = _make_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))
    assert "operations" in result
    assert result["operations"] == []
    assert result["evaluations"] == [{"name": "pat-001", "rating": "helpful"}]


# @tests SCN-CUR-001-03
def test_scn_extract_no_operations_key(monkeypatch):
    """SCN-CUR-001-03: LLM returns old format without operations key."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "new_key_points": ["some new point"],
        "evaluations": [{"name": "pat-001", "rating": "helpful"}],
    })
    playbook = _make_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))
    assert "operations" not in result
    assert result["new_key_points"] == ["some new point"]
    assert result["evaluations"] == [{"name": "pat-001", "rating": "helpful"}]


# @tests SCN-CUR-001-04
def test_scn_extract_non_list_operations(monkeypatch):
    """SCN-CUR-001-04: LLM returns non-list operations (null, string, int)."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    playbook = _make_playbook()

    for non_list_value in [None, "not a list", 42, {}, True]:
        mock_text_block.text = json.dumps({
            "evaluations": [{"name": "pat-001", "rating": "helpful"}],
            "operations": non_list_value,
        })
        result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))
        assert "operations" not in result, (
            f"operations key should be absent for non-list value {non_list_value!r}"
        )


# ===========================================================================
# REQ-CUR-002: ADD Operation
# ===========================================================================


# @tests REQ-CUR-002
def test_add_creates_entry_in_target_section(project_dir):
    """ADD operation creates a new entry in the specified section."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["text"] == "new insight"
    assert pat[0]["name"] == "pat-001"
    assert pat[0]["helpful"] == 0
    assert pat[0]["harmful"] == 0


# @tests SCN-CUR-002-01
def test_scn_add_creates_entry_in_target_section(project_dir):
    """SCN-CUR-002-01: ADD creates entry with correct schema in target section."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "prefer composition", "section": "PATTERNS & APPROACHES"}]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 2
    assert pat[0]["name"] == "pat-001"
    assert pat[1]["name"] == "pat-002"
    assert pat[1]["text"] == "prefer composition"
    assert pat[1]["helpful"] == 0
    assert pat[1]["harmful"] == 0


# @tests SCN-CUR-002-02
def test_scn_add_defaults_to_others(project_dir):
    """SCN-CUR-002-02: ADD with no section field defaults to OTHERS."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "some insight"}]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["name"].startswith("oth-")
    assert oth[0]["text"] == "some insight"


# @tests SCN-CUR-002-03
def test_scn_add_skips_duplicate_text(project_dir):
    """SCN-CUR-002-03: ADD skips when duplicate text exists in any section."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "prefer pathlib", "helpful": 2, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "prefer pathlib", "section": "PATTERNS & APPROACHES"}]
    )
    result = update_playbook_data(playbook, extraction)
    # No new entry in PATTERNS
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 0
    # Original still in OTHERS
    assert len(result["sections"]["OTHERS"]) == 1


# @tests SCN-CUR-002-04
def test_scn_add_skips_empty_text(project_dir):
    """SCN-CUR-002-04: ADD with empty text is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "", "section": "OTHERS"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests SCN-CUR-002-05
def test_scn_add_resolves_section_case_insensitive(project_dir):
    """SCN-CUR-002-05: ADD resolves section name case-insensitively."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "new tip", "section": "mistakes to avoid"}]
    )
    result = update_playbook_data(playbook, extraction)
    mis = result["sections"]["MISTAKES TO AVOID"]
    assert len(mis) == 1
    assert mis[0]["name"].startswith("mis-")


# ===========================================================================
# REQ-CUR-003: MERGE Operation
# ===========================================================================


# @tests REQ-CUR-003
def test_merge_combines_two_entries(project_dir):
    """MERGE combines two entries with summed counters."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            {"name": "pat-003", "text": "annotate return types", "helpful": 3, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-003"],
            "merged_text": "use complete type annotations",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    merged = pat[0]
    assert merged["text"] == "use complete type annotations"
    assert merged["helpful"] == 8
    assert merged["harmful"] == 1


# @tests SCN-CUR-003-01
def test_scn_merge_combines_two_entries(project_dir):
    """SCN-CUR-003-01: MERGE combines two entries with counter summing."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            {"name": "pat-003", "text": "annotate return types", "helpful": 3, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-003"],
            "merged_text": "use complete type annotations",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    merged = pat[0]
    assert merged["name"] == "pat-004"
    assert merged["text"] == "use complete type annotations"
    assert merged["helpful"] == 8
    assert merged["harmful"] == 1


# @tests SCN-CUR-003-02
def test_scn_merge_explicit_section_override(project_dir):
    """SCN-CUR-003-02: MERGE with explicit section override places entry there."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "hint A", "helpful": 2, "harmful": 0},
        ],
        "OTHERS": [
            {"name": "oth-001", "text": "hint B", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "oth-001"],
            "merged_text": "combined hint",
            "section": "PATTERNS & APPROACHES",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["name"] == "pat-002"
    assert pat[0]["text"] == "combined hint"
    assert pat[0]["helpful"] == 3
    assert pat[0]["harmful"] == 0
    assert len(result["sections"]["OTHERS"]) == 0


# @tests SCN-CUR-003-03
def test_scn_merge_some_nonexistent_source_ids(project_dir):
    """SCN-CUR-003-03: MERGE with some non-existent source IDs proceeds with valid ones."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
            {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-002", "pat-999"],
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    merged = pat[0]
    assert merged["helpful"] == 3
    assert merged["harmful"] == 0


# @tests SCN-CUR-003-04
def test_scn_merge_skipped_fewer_than_2_valid(project_dir):
    """SCN-CUR-003-04: MERGE skipped when fewer than 2 valid source IDs remain."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-999"],
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    # pat-001 should NOT be removed since MERGE was skipped
    assert len(pat) == 1
    assert pat[0]["name"] == "pat-001"


# @tests SCN-CUR-003-05
def test_scn_merge_skipped_source_ids_fewer_than_2(project_dir):
    """SCN-CUR-003-05: MERGE skipped when source_ids has fewer than 2 entries."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001"],
            "merged_text": "rewritten",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["name"] == "pat-001"


# @tests SCN-CUR-003-06
def test_scn_merge_inherits_section_from_first_valid(project_dir):
    """SCN-CUR-003-06: MERGE inherits section from first valid source_id."""
    playbook = _make_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "avoid globals", "helpful": 3, "harmful": 0},
        ],
        "OTHERS": [
            {"name": "oth-001", "text": "no bare except", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["mis-001", "oth-001"],
            "merged_text": "combined advice",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    # Merged entry should be in MISTAKES TO AVOID (section of first valid: mis-001)
    mis = result["sections"]["MISTAKES TO AVOID"]
    assert len(mis) == 1
    assert mis[0]["name"].startswith("mis-")
    assert mis[0]["text"] == "combined advice"
    assert mis[0]["helpful"] == 4
    assert len(result["sections"]["OTHERS"]) == 0


# @tests SCN-CUR-003-07
def test_scn_merge_first_source_deleted_by_prior_op(project_dir):
    """SCN-CUR-003-07: MERGE where first source_id was deleted by a prior op."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
            {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
            {"name": "pat-003", "text": "C", "helpful": 3, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "DELETE", "target_id": "pat-001", "reason": "obsolete"},
            {
                "type": "MERGE",
                "source_ids": ["pat-001", "pat-002", "pat-003"],
                "merged_text": "combined",
            },
        ]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    # pat-001 deleted, pat-002 and pat-003 merged
    assert len(pat) == 1
    merged = pat[0]
    assert merged["helpful"] == 4  # 1 + 3 (pat-001 was already deleted)
    assert merged["harmful"] == 0


# @tests SCN-CUR-003-08
def test_scn_merge_all_source_ids_nonexistent(project_dir):
    """SCN-CUR-003-08: MERGE skipped when all source_ids are non-existent."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-999", "pat-888"],
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["name"] == "pat-001"
    assert pat[0]["helpful"] == 5


# ===========================================================================
# REQ-CUR-004: DELETE Operation
# ===========================================================================


# @tests REQ-CUR-004
def test_delete_removes_entry(project_dir):
    """DELETE operation removes entry from its section."""
    playbook = _make_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "mis-001", "reason": "contradicts standards"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0


# @tests SCN-CUR-004-01
def test_scn_delete_removes_entry(project_dir):
    """SCN-CUR-004-01: DELETE removes entry from section."""
    playbook = _make_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "DELETE",
            "target_id": "mis-001",
            "reason": "contradicts project standards",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0


# @tests SCN-CUR-004-02
def test_scn_delete_skips_nonexistent_id(project_dir):
    """SCN-CUR-004-02: DELETE skips non-existent target_id."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "keep me", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}]
    )
    result = update_playbook_data(playbook, extraction)
    # playbook unchanged
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1
    assert result["sections"]["PATTERNS & APPROACHES"][0]["name"] == "pat-001"


# @tests SCN-CUR-004-03
def test_scn_delete_empty_target_id(project_dir):
    """SCN-CUR-004-03: DELETE with empty target_id is skipped."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "", "reason": "cleanup"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# ===========================================================================
# REQ-CUR-005: Sequential Processing Order
# ===========================================================================


# @tests REQ-CUR-005
def test_sequential_processing_order(project_dir):
    """Operations are applied sequentially in list order."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "oth-002", "text": "B", "helpful": 2, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "DELETE", "target_id": "oth-001", "reason": "outdated"},
            {"type": "ADD", "text": "C", "section": "OTHERS"},
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    texts = [kp["text"] for kp in oth]
    assert "A" not in texts
    assert "B" in texts
    assert "C" in texts


# @tests SCN-CUR-005-01
def test_scn_delete_before_merge(project_dir):
    """SCN-CUR-005-01: DELETE before MERGE in same batch."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "oth-002", "text": "B", "helpful": 2, "harmful": 0},
            {"name": "oth-003", "text": "C", "helpful": 3, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "DELETE", "target_id": "oth-001", "reason": "outdated"},
            {
                "type": "MERGE",
                "source_ids": ["oth-002", "oth-003"],
                "merged_text": "combined BC",
            },
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "combined BC"
    assert oth[0]["helpful"] == 5
    assert oth[0]["harmful"] == 0


# @tests SCN-CUR-005-02
def test_scn_add_then_merge_referencing_new_entry(project_dir):
    """SCN-CUR-005-02: ADD then MERGE referencing the newly created entry."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "prefer pathlib", "helpful": 2, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "use structured logging", "section": "OTHERS"},
            {
                "type": "MERGE",
                "source_ids": ["oth-002", "oth-001"],
                "merged_text": "prefer pathlib and use structured logging for all file operations",
            },
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "prefer pathlib and use structured logging for all file operations"
    assert oth[0]["helpful"] == 2  # 0 + 2
    assert oth[0]["harmful"] == 0
    assert oth[0]["name"] == "oth-003"


# @tests SCN-CUR-005-03
def test_scn_exception_rollback_returns_original(project_dir, monkeypatch):
    """SCN-CUR-005-03: Exception rollback returns original playbook."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 5, "harmful": 1},
        ],
    })
    original_sections = copy.deepcopy(playbook["sections"])

    # Monkeypatch _apply_curator_operations to raise
    monkeypatch.setattr(
        _common_module,
        "_apply_curator_operations",
        lambda pb, ops: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )

    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "will fail"}]
    )
    result = update_playbook_data(playbook, extraction)

    # Original should be returned unchanged
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["name"] == "pat-001"
    assert pat[0]["helpful"] == 5
    assert pat[0]["harmful"] == 1


# @tests SCN-CUR-005-04
def test_scn_skipped_ops_do_not_trigger_rollback(project_dir):
    """SCN-CUR-005-04: Skipped operations do not trigger rollback."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "DELETE", "target_id": "nonexistent", "reason": "cleanup"},
            {"type": "ADD", "text": "new entry", "section": "OTHERS"},
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    texts = [kp["text"] for kp in oth]
    assert "keep me" in texts
    assert "new entry" in texts
    assert len(oth) == 2


# ===========================================================================
# REQ-CUR-006: Deep Copy Atomicity and Exception Rollback
# ===========================================================================


# @tests REQ-CUR-006
def test_rollback_on_exception(project_dir, monkeypatch):
    """Deep copy atomicity: exception during operations returns original playbook."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "original", "helpful": 1, "harmful": 0},
        ],
    })

    def _raise_on_call(pb, ops):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(_common_module, "_apply_curator_operations", _raise_on_call)

    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "will fail"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["text"] == "original"


# ===========================================================================
# REQ-CUR-007: Updated Prompt Structure
# ===========================================================================


# @tests REQ-CUR-007
def test_prompt_includes_operations_instructions():
    """reflection.txt template includes operation instructions and examples."""
    template_path = "/data/agentic_context_engineering/src/prompts/reflection.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Operation types mentioned
    assert "ADD" in content
    assert "MERGE" in content
    assert "DELETE" in content

    # JSON examples present
    assert '"type"' in content
    assert '"text"' in content
    assert '"source_ids"' in content
    assert '"merged_text"' in content
    assert '"target_id"' in content
    assert '"reason"' in content


# @tests SCN-CUR-007-01
def test_scn_prompt_includes_entry_ids_and_examples():
    """SCN-CUR-007-01: Prompt has ADD/MERGE/DELETE examples, max 10, zero ops allowance."""
    template_path = "/data/agentic_context_engineering/src/prompts/reflection.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ADD example
    assert '"type": "ADD"' in content
    # MERGE example
    assert '"type": "MERGE"' in content
    # DELETE example
    assert '"type": "DELETE"' in content
    # Max 10 operations
    assert "10" in content
    # Zero ops allowance
    assert "operations" in content.lower()
    assert "[]" in content
    # playbook variable
    assert "{playbook}" in content


# ===========================================================================
# REQ-CUR-008: Operations vs new_key_points Precedence
# ===========================================================================


# @tests REQ-CUR-008
def test_operations_suppress_new_key_points(project_dir):
    """When operations key is present, new_key_points is ignored."""
    playbook = _make_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
        "new_key_points": ["from nkp"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    all_texts = _collect_all_texts(result)
    assert "from ops" in all_texts
    assert "from nkp" not in all_texts


# @tests SCN-CUR-008-01
def test_scn_operations_key_present_nkp_ignored(project_dir):
    """SCN-CUR-008-01: Operations key present, new_key_points ignored."""
    playbook = _make_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
        "new_key_points": ["from nkp"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    all_texts = _collect_all_texts(result)
    assert "from ops" in all_texts
    assert "from nkp" not in all_texts


# @tests SCN-CUR-008-02
def test_scn_operations_key_absent_nkp_used(project_dir):
    """SCN-CUR-008-02: Operations key absent, new_key_points is used."""
    playbook = _make_playbook()
    extraction = {
        "new_key_points": ["legacy point"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "legacy point"


# @tests SCN-CUR-008-03
def test_scn_empty_operations_list_nkp_still_ignored(project_dir):
    """SCN-CUR-008-03: Empty operations list still ignores new_key_points."""
    playbook = _make_playbook()
    extraction = {
        "operations": [],
        "new_key_points": ["should not be added"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    all_texts = _collect_all_texts(result)
    assert "should not be added" not in all_texts
    assert len(_collect_all_entries(result)) == 0


# ===========================================================================
# REQ-CUR-009: Operations Validation and Truncation
# ===========================================================================


# @tests REQ-CUR-009
def test_operations_truncated_to_10(project_dir):
    """Operations list truncated to first 10."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"entry {i}", "section": "OTHERS"} for i in range(15)]
    extraction = _make_extraction(operations=ops)
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10


# @tests SCN-CUR-009-01
def test_scn_operations_truncated_15_to_10(project_dir):
    """SCN-CUR-009-01: 15 operations truncated to 10."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"entry {i}", "section": "OTHERS"} for i in range(15)]
    extraction = _make_extraction(operations=ops)
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10
    # Verify only first 10 were processed
    texts = [kp["text"] for kp in oth]
    for i in range(10):
        assert f"entry {i}" in texts
    for i in range(10, 15):
        assert f"entry {i}" not in texts


# @tests SCN-CUR-009-02
def test_scn_unknown_operation_type_skipped(project_dir):
    """SCN-CUR-009-02: Unknown operation types and missing type key are skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[
            {"type": "UPDATE", "target_id": "pat-001", "text": "rewritten"},
            {"target_id": "pat-001", "text": "rewritten"},
            {"type": "ADD", "text": "valid entry", "section": "OTHERS"},
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    # Only the valid ADD should have been processed
    assert len(oth) == 1
    assert oth[0]["text"] == "valid entry"


# @tests SCN-CUR-009-03
def test_scn_exactly_10_operations_no_truncation(project_dir):
    """SCN-CUR-009-03: Exactly 10 operations processed without truncation."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"entry {i}", "section": "OTHERS"} for i in range(10)]
    extraction = _make_extraction(operations=ops)
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10


# @tests SCN-CUR-009-04
def test_scn_exactly_11_operations_truncation(project_dir):
    """SCN-CUR-009-04: Exactly 11 operations truncated to 10."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"entry {i}", "section": "OTHERS"} for i in range(11)]
    extraction = _make_extraction(operations=ops)
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10
    texts = [kp["text"] for kp in oth]
    assert "entry 10" not in texts


# ===========================================================================
# INV-CUR-001: Deep Copy Isolation
# ===========================================================================


# @tests-invariant INV-CUR-001
def test_invariant_deep_copy_isolation(project_dir):
    """Original playbook is not mutated by operations processing."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "original", "helpful": 5, "harmful": 1},
        ],
    })
    original_copy = copy.deepcopy(playbook)

    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "new entry", "section": "PATTERNS & APPROACHES"},
            {"type": "DELETE", "target_id": "pat-001", "reason": "remove"},
        ]
    )
    result = update_playbook_data(playbook, extraction)

    # The result should show changes
    pat_result = result["sections"]["PATTERNS & APPROACHES"]
    result_texts = [kp["text"] for kp in pat_result]
    assert "new entry" in result_texts

    # The original playbook passed in should be unchanged
    assert playbook["sections"]["PATTERNS & APPROACHES"] == original_copy["sections"]["PATTERNS & APPROACHES"]


# ===========================================================================
# INV-CUR-002: No Crash on Invalid Operations
# ===========================================================================


# @tests-invariant INV-CUR-002
def test_invariant_no_crash_on_invalid_operations(project_dir):
    """No individual operation causes update_playbook_data to raise."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "", "section": "OTHERS"},           # empty text
            {"type": "ADD", "section": "OTHERS"},                        # missing text
            {"type": "ADD", "text": None, "section": "OTHERS"},          # None text
            {"type": "MERGE", "source_ids": "not-a-list", "merged_text": "x"},  # source_ids not list
            {"type": "MERGE", "source_ids": ["one"], "merged_text": "x"},       # too few source_ids
            {"type": "MERGE", "source_ids": ["a", "b"], "merged_text": ""},     # empty merged_text
            {"type": "DELETE", "target_id": "", "reason": "x"},           # empty target_id
            {"type": "DELETE", "target_id": None, "reason": "x"},         # None target_id
            {"type": "UPDATE", "target_id": "oth-001"},                   # unknown type
            {},                                                            # no type key
        ]
    )
    # Should not raise
    result = update_playbook_data(playbook, extraction)
    # Original entry should still be present
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"] == "oth-001"


# ===========================================================================
# INV-CUR-003: Counter Non-Negativity Preserved Through MERGE
# ===========================================================================


# @tests-invariant INV-CUR-003
def test_invariant_counter_non_negativity_through_merge(project_dir):
    """MERGE produces summed counters that are >= 0."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
            {"name": "pat-002", "text": "B", "helpful": 3, "harmful": 1},
            {"name": "pat-003", "text": "C", "helpful": 5, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-002", "pat-003"],
            "merged_text": "combined ABC",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    merged = pat[0]
    assert merged["helpful"] == 10
    assert merged["harmful"] == 1
    assert merged["helpful"] >= 0
    assert merged["harmful"] >= 0


# ===========================================================================
# INV-CUR-004: Section Names Canonical After Operations
# ===========================================================================


# @tests-invariant INV-CUR-004
def test_invariant_section_names_canonical_after_ops(project_dir):
    """After operations, all section keys are canonical."""
    canonical_set = set(SECTION_SLUGS.keys())
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "new tip", "section": "mistakes to avoid"},
            {
                "type": "MERGE",
                "source_ids": ["pat-001", "pat-002"],
                "merged_text": "combined",
                "section": "PATTERNS & APPROACHES",
            },
        ]
    )
    result = update_playbook_data(playbook, extraction)
    assert set(result["sections"].keys()) == canonical_set


# ===========================================================================
# INV-CUR-005: Operations Bounded by Max 10
# ===========================================================================


# @tests-invariant INV-CUR-005
def test_invariant_operations_bounded_to_10(project_dir):
    """At most 10 operations are processed."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"item {i}", "section": "OTHERS"} for i in range(20)]
    extraction = _make_extraction(operations=ops)
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10


# ===========================================================================
# INV-CUR-006: Precedence Prevents Double-Processing
# ===========================================================================


# @tests-invariant INV-CUR-006
def test_invariant_precedence_prevents_double_processing(project_dir):
    """Operations + new_key_points: only operations path runs, not both."""
    playbook = _make_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
        "new_key_points": ["from nkp"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    all_entries = _collect_all_entries(result)
    assert len(all_entries) == 1
    assert all_entries[0]["text"] == "from ops"


# ===========================================================================
# Adversarial: Invalid Inputs (TC-INVAL-*)
# ===========================================================================


# @tests REQ-CUR-002, REQ-CUR-009 (TC-INVAL-002)
def test_tc_inval_002_add_text_none(project_dir):
    """TC-INVAL-002: ADD with text=None is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": None, "section": "OTHERS"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-CUR-002, REQ-CUR-009 (TC-INVAL-003)
def test_tc_inval_003_add_missing_text_key(project_dir):
    """TC-INVAL-003: ADD with missing text key is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "section": "OTHERS"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-CUR-003, REQ-CUR-009 (TC-INVAL-004)
def test_tc_inval_004_merge_source_ids_string(project_dir):
    """TC-INVAL-004: MERGE with source_ids as string (not list) is skipped."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": "pat-001",
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1


# @tests REQ-CUR-003, REQ-CUR-009 (TC-INVAL-006)
def test_tc_inval_006_merge_empty_merged_text(project_dir):
    """TC-INVAL-006: MERGE with empty merged_text is skipped."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-002"],
            "merged_text": "",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    # MERGE skipped: both entries still present
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2


# @tests REQ-CUR-004, REQ-CUR-009 (TC-INVAL-008)
def test_tc_inval_008_delete_target_id_none(project_dir):
    """TC-INVAL-008: DELETE with target_id=None is skipped."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": None, "reason": "cleanup"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# @tests REQ-CUR-009, INV-CUR-002 (TC-INVAL-011)
def test_tc_inval_011_non_dict_operation(project_dir):
    """TC-INVAL-011: A non-dict operation does not crash update_playbook_data."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 0, "harmful": 0},
        ],
    })
    # Non-dict in operations list: string "ADD" triggers AttributeError on .get()
    # This should be caught by the try/except rollback
    extraction = _make_extraction(
        operations=["ADD", {"type": "ADD", "text": "valid", "section": "OTHERS"}]
    )
    result = update_playbook_data(playbook, extraction)
    # Due to rollback, original entry should still be present
    assert any(kp["text"] == "keep me" for kp in result["sections"]["OTHERS"])


# @tests REQ-CUR-002, REQ-CUR-009 (TC-INVAL-016)
def test_tc_inval_016_add_whitespace_only_text(project_dir):
    """TC-INVAL-016: ADD with whitespace-only text is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "   ", "section": "OTHERS"}]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-CUR-003, REQ-CUR-009 (TC-INVAL-015)
def test_tc_inval_015_merge_empty_source_ids_list(project_dir):
    """TC-INVAL-015: MERGE with empty source_ids list is skipped."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": [],
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    assert len(_collect_all_entries(result)) == 0


# ===========================================================================
# Adversarial: Ordering (TC-ORD-*)
# ===========================================================================


# @tests REQ-CUR-002 (TC-ORD-004)
def test_tc_ord_004_add_duplicate_text_twice(project_dir):
    """TC-ORD-004: ADD same text twice: first succeeds, second is dedup'd."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "same text", "section": "OTHERS"},
            {"type": "ADD", "text": "same text", "section": "OTHERS"},
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "same text"


# @tests REQ-CUR-005 (TC-ORD-005)
def test_tc_ord_005_delete_then_add_same_text(project_dir):
    """TC-ORD-005: DELETE then ADD same text: ADD succeeds (text was removed)."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "some text", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "DELETE", "target_id": "oth-001", "reason": "remove"},
            {"type": "ADD", "text": "some text", "section": "OTHERS"},
        ]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "some text"
    assert oth[0]["helpful"] == 0  # fresh entry, not the old one


# ===========================================================================
# Adversarial: Data Integrity (TC-INTEG-*)
# ===========================================================================


# @tests REQ-CUR-002 (TC-INTEG-006)
def test_tc_integ_006_add_entry_schema(project_dir):
    """TC-INTEG-006: New ADD entries have helpful=0, harmful=0."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "new tip", "section": "PATTERNS & APPROACHES"}]
    )
    result = update_playbook_data(playbook, extraction)
    entry = result["sections"]["PATTERNS & APPROACHES"][0]
    assert entry["helpful"] == 0
    assert entry["harmful"] == 0
    assert "name" in entry
    assert "text" in entry


# @tests REQ-CUR-003 (TC-INTEG-007)
def test_tc_integ_007_merge_entry_schema(project_dir):
    """TC-INTEG-007: Merged entry has correct schema."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "oth-002", "text": "B", "helpful": 2, "harmful": 1},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["oth-001", "oth-002"],
            "merged_text": "combined AB",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    entry = result["sections"]["OTHERS"][0]
    assert set(entry.keys()) == {"name", "text", "helpful", "harmful"}
    assert entry["text"] == "combined AB"


# @tests REQ-CUR-004 (TC-INTEG-008)
def test_tc_integ_008_delete_reason_not_stored(project_dir):
    """TC-INTEG-008: DELETE reason is not stored in playbook."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "removed", "helpful": 0, "harmful": 0},
            {"name": "oth-002", "text": "kept", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "oth-001", "reason": "secret reason"}]
    )
    result = update_playbook_data(playbook, extraction)
    # The reason should not appear anywhere in the playbook
    playbook_json = json.dumps(result)
    assert "secret reason" not in playbook_json


# ===========================================================================
# Adversarial: Backward Compatibility (TC-COMPAT-*)
# ===========================================================================


# @tests REQ-CUR-005, REQ-CUR-006 (TC-COMPAT-004)
def test_tc_compat_004_evaluations_work_after_operations(project_dir):
    """TC-COMPAT-004: Evaluations still apply after operations."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "existing", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{"type": "ADD", "text": "new", "section": "OTHERS"}],
        "evaluations": [{"name": "oth-001", "rating": "helpful"}],
    }
    result = update_playbook_data(playbook, extraction)
    # oth-001 should have incremented helpful
    oth_001 = next(kp for kp in result["sections"]["OTHERS"] if kp["name"] == "oth-001")
    assert oth_001["helpful"] == 1


# @tests REQ-CUR-006 (TC-COMPAT-005)
def test_tc_compat_005_pruning_runs_after_operations(project_dir):
    """TC-COMPAT-005: Pruning removes merged entry with high harmful count."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 0, "harmful": 2},
            {"name": "oth-002", "text": "B", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["oth-001", "oth-002"],
            "merged_text": "combined",
        }]
    )
    result = update_playbook_data(playbook, extraction)
    oth = result["sections"]["OTHERS"]
    # Merged entry: helpful=0, harmful=4 -> harmful>=3 and harmful>helpful -> pruned
    assert len(oth) == 0


# ===========================================================================
# LOG-CUR-001: Curator Operations Summary (Instrumentation)
# ===========================================================================


# @tests-instrumentation LOG-CUR-001
def test_instrumentation_ops_summary_created(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + operations applied -> summary file created."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[
            {"type": "ADD", "text": "new entry", "section": "OTHERS"},
            {"type": "DELETE", "target_id": "nonexistent", "reason": "cleanup"},
            {"type": "DELETE", "target_id": "oth-001", "reason": "remove"},
        ]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_ops_summary.txt"))
    assert len(files) >= 1, "Curator ops summary diagnostic not created"

    content = files[0].read_text()
    assert "ADD" in content
    assert "DELETE" in content
    assert "applied" in content
    assert "skipped" in content


# @tests-instrumentation LOG-CUR-001
def test_instrumentation_ops_summary_not_created_when_disabled(project_dir):
    """Diagnostic mode off + operations applied -> no summary file."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "ADD", "text": "entry", "section": "OTHERS"}]
    )
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_curator_ops_summary.txt"))
        assert len(files) == 0, "Summary diagnostic created when disabled"


# @tests-instrumentation LOG-CUR-001
def test_instrumentation_truncation_diagnostic_created(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + 15 operations -> truncation diagnostic created."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"e{i}", "section": "OTHERS"} for i in range(15)]
    extraction = _make_extraction(operations=ops)
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_ops_truncated.txt"))
    assert len(files) >= 1, "Truncation diagnostic not created"

    content = files[0].read_text()
    assert "15" in content
    assert "10" in content


# @tests-instrumentation LOG-CUR-001
def test_instrumentation_truncation_not_emitted_at_10(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + exactly 10 operations -> no truncation diagnostic."""
    playbook = _make_playbook()
    ops = [{"type": "ADD", "text": f"e{i}", "section": "OTHERS"} for i in range(10)]
    extraction = _make_extraction(operations=ops)
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_ops_truncated.txt"))
    assert len(files) == 0, "Truncation diagnostic created at exactly 10 (should not)"


# ===========================================================================
# LOG-CUR-002: Non-Existent ID Reference (Instrumentation)
# ===========================================================================


# @tests-instrumentation LOG-CUR-002
def test_instrumentation_nonexistent_id_merge(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + MERGE with non-existent source_id -> diagnostic created."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 0, "harmful": 0},
            {"name": "oth-002", "text": "B", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "MERGE",
            "source_ids": ["oth-001", "oth-002", "oth-999"],
            "merged_text": "combined",
        }]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_nonexistent_id.txt"))
    assert len(files) >= 1, "Nonexistent ID diagnostic not created for MERGE"

    content = files[0].read_text()
    assert "oth-999" in content
    assert "MERGE" in content


# @tests-instrumentation LOG-CUR-002
def test_instrumentation_nonexistent_id_delete(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + DELETE with non-existent target_id -> diagnostic created."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_nonexistent_id.txt"))
    assert len(files) >= 1, "Nonexistent ID diagnostic not created for DELETE"

    content = files[0].read_text()
    assert "pat-999" in content
    assert "DELETE" in content


# @tests-instrumentation LOG-CUR-002
def test_instrumentation_nonexistent_id_not_created_when_disabled(project_dir):
    """Diagnostic mode off + non-existent ID -> no diagnostic file."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}]
    )
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_curator_nonexistent_id.txt"))
        assert len(files) == 0, "Nonexistent ID diagnostic created when disabled"


# ===========================================================================
# LOG-CUR-003: DELETE Reason Audit (Instrumentation)
# ===========================================================================


# @tests-instrumentation LOG-CUR-003
def test_instrumentation_delete_audit_created(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + DELETE applied -> delete audit diagnostic created."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "DELETE",
            "target_id": "oth-001",
            "reason": "contradicts standards",
        }]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_delete_audit.txt"))
    assert len(files) >= 1, "Delete audit diagnostic not created"

    content = files[0].read_text()
    assert "oth-001" in content
    assert "bad advice" in content
    assert "contradicts standards" in content


# @tests-instrumentation LOG-CUR-003
def test_instrumentation_delete_audit_not_created_when_disabled(project_dir):
    """Diagnostic mode off + DELETE applied -> no delete audit diagnostic."""
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "DELETE",
            "target_id": "oth-001",
            "reason": "contradicts standards",
        }]
    )
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_curator_delete_audit.txt"))
        assert len(files) == 0, "Delete audit diagnostic created when disabled"


# @tests-instrumentation LOG-CUR-003
def test_instrumentation_delete_audit_not_created_when_skipped(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + DELETE skipped (non-existent) -> no delete audit."""
    playbook = _make_playbook()
    extraction = _make_extraction(
        operations=[{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_delete_audit.txt"))
    assert len(files) == 0, "Delete audit created for skipped DELETE"


# @tests-instrumentation LOG-CUR-003
def test_instrumentation_delete_audit_text_truncated(
    project_dir, enable_diagnostic, diagnostic_dir
):
    """Diagnostic mode on + DELETE entry text > 80 chars -> text truncated in audit."""
    long_text = "x" * 200
    playbook = _make_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": long_text, "helpful": 0, "harmful": 0},
        ],
    })
    extraction = _make_extraction(
        operations=[{
            "type": "DELETE",
            "target_id": "oth-001",
            "reason": "too long",
        }]
    )
    update_playbook_data(playbook, extraction)

    files = list(diagnostic_dir.glob("*_curator_delete_audit.txt"))
    assert len(files) >= 1

    content = files[0].read_text()
    # Full 200-char text should NOT appear
    assert long_text not in content
    # First 80 chars should appear
    assert long_text[:80] in content


# ===========================================================================
# Deliverable Test: Full Curator Lifecycle
# ===========================================================================


# @tests REQ-CUR-002, REQ-CUR-003, REQ-CUR-004, REQ-CUR-005, REQ-CUR-008
def test_full_curator_lifecycle(project_dir):
    """Full lifecycle: mixed operations + evaluations + pruning in one cycle."""
    playbook = _make_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "use types", "helpful": 5, "harmful": 1},
            {"name": "pat-002", "text": "use dataclasses", "helpful": 3, "harmful": 0},
        ],
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
        "OTHERS": [
            {"name": "oth-001", "text": "random tip", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [
            # ADD a new entry
            {"type": "ADD", "text": "prefer composition", "section": "PATTERNS & APPROACHES"},
            # MERGE two entries
            {
                "type": "MERGE",
                "source_ids": ["pat-001", "pat-002"],
                "merged_text": "use types and dataclasses",
            },
            # DELETE an entry
            {"type": "DELETE", "target_id": "mis-001", "reason": "outdated"},
        ],
        "evaluations": [
            # Evaluate surviving entry
            {"name": "oth-001", "rating": "helpful"},
        ],
        "new_key_points": ["ignored because operations present"],
    }
    result = update_playbook_data(playbook, extraction)

    # ADD: pat-003 created
    pat = result["sections"]["PATTERNS & APPROACHES"]
    pat_texts = [kp["text"] for kp in pat]
    assert "prefer composition" in pat_texts

    # MERGE: pat-001 and pat-002 removed, new merged entry created
    assert "use types and dataclasses" in pat_texts
    pat_names = [kp["name"] for kp in pat]
    assert "pat-001" not in pat_names
    assert "pat-002" not in pat_names

    # DELETE: mis-001 removed
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0

    # Evaluations: oth-001 helpful incremented
    oth_001 = next(kp for kp in result["sections"]["OTHERS"] if kp["name"] == "oth-001")
    assert oth_001["helpful"] == 2

    # new_key_points ignored (operations present)
    all_texts = _collect_all_texts(result)
    assert "ignored because operations present" not in all_texts
