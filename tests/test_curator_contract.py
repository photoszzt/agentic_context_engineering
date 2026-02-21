# Spec: docs/curator/spec.md
# Contract: docs/curator/contract.md
# Testing: docs/curator/testing.md
"""
Contract (black-box) tests for the curator operations module.

These tests exercise the public API as documented in contract.md.
They do NOT reference internal branches, implementation details, or design.md.
They verify only behaviors promised by the data contracts.
"""

import asyncio
import copy
import json
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


def _make_sections_playbook(sections_dict=None):
    """Construct a sections-based playbook per contract.md schema."""
    sections = {name: [] for name in SECTION_SLUGS}
    if sections_dict:
        sections.update(sections_dict)
    return {"version": "1.0", "last_updated": None, "sections": sections}


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


# ===========================================================================
# REQ-CUR-001: Structured Operations in Extraction Result
# ===========================================================================


# @tests-contract REQ-CUR-001
def test_contract_extraction_includes_operations(monkeypatch):
    """Contract: extract_keypoints returns operations when present in LLM response."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "evaluations": [{"name": "pat-001", "rating": "helpful"}],
        "operations": [{"type": "ADD", "text": "new insight", "section": "OTHERS"}],
    })
    playbook = _make_sections_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Contract: operations key present with the list from LLM
    assert "operations" in result
    assert isinstance(result["operations"], list)
    assert len(result["operations"]) == 1
    # Contract: evaluations still present
    assert "evaluations" in result


# @tests-contract REQ-CUR-001
def test_contract_extraction_omits_operations_when_absent(monkeypatch):
    """Contract: extract_keypoints omits operations key when LLM does not return it."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "new_key_points": ["some point"],
        "evaluations": [],
    })
    playbook = _make_sections_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Contract: operations key absent
    assert "operations" not in result
    # Contract: new_key_points present
    assert "new_key_points" in result


# @tests-contract REQ-CUR-001
def test_contract_extraction_non_list_operations_treated_as_absent(monkeypatch):
    """Contract: non-list operations value treated as if key were absent."""
    mock_client, mock_text_block = _setup_extract_keypoints_mocks(monkeypatch)
    mock_text_block.text = json.dumps({
        "evaluations": [],
        "operations": None,
    })
    playbook = _make_sections_playbook()
    result = asyncio.run(extract_keypoints(messages=[], playbook=playbook))

    # Contract: operations key absent for non-list value
    assert "operations" not in result


# ===========================================================================
# REQ-CUR-002: ADD Operation
# ===========================================================================


# @tests-contract REQ-CUR-002
def test_contract_add_operation(project_dir):
    """Contract: ADD creates a new entry with correct schema in the target section."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [
            {"type": "ADD", "text": "Use structured logging", "section": "PATTERNS & APPROACHES"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    entry = pat[0]
    # Contract: entry has name, text, helpful, harmful
    assert "name" in entry
    assert entry["text"] == "Use structured logging"
    assert entry["helpful"] == 0
    assert entry["harmful"] == 0
    # Contract: name has section slug prefix
    assert entry["name"].startswith("pat-")


# @tests-contract REQ-CUR-002
def test_contract_add_defaults_section_to_others(project_dir):
    """Contract: ADD with missing section defaults to OTHERS."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "some insight"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "some insight"
    assert oth[0]["name"].startswith("oth-")


# @tests-contract REQ-CUR-002
def test_contract_add_skips_duplicate(project_dir):
    """Contract: ADD skips when text already exists in playbook."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "existing text", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{"type": "ADD", "text": "existing text", "section": "PATTERNS & APPROACHES"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # No new entry created
    assert len(result["sections"]["PATTERNS & APPROACHES"]) == 0
    assert len(result["sections"]["OTHERS"]) == 1


# @tests-contract REQ-CUR-002
def test_contract_add_skips_empty_text(project_dir):
    """Contract: ADD with empty text is skipped."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "", "section": "OTHERS"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# ===========================================================================
# REQ-CUR-003: MERGE Operation
# ===========================================================================


# @tests-contract REQ-CUR-003
def test_contract_merge_operation(project_dir):
    """Contract: MERGE combines entries with summed counters and removes sources."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "hint A", "helpful": 2, "harmful": 0},
            {"name": "pat-002", "text": "hint B", "helpful": 3, "harmful": 1},
        ],
    })
    extraction = {
        "operations": [{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-002"],
            "merged_text": "combined hints",
        }],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    merged = pat[0]
    # Contract: merged entry has summed counters
    assert merged["helpful"] == 5
    assert merged["harmful"] == 1
    assert merged["text"] == "combined hints"
    # Contract: sources removed (pat-001 and pat-002 gone)
    names = [kp["name"] for kp in pat]
    assert "pat-001" not in names
    assert "pat-002" not in names


# @tests-contract REQ-CUR-003
def test_contract_merge_skips_fewer_than_2_source_ids(project_dir):
    """Contract: MERGE skipped when source_ids has fewer than 2 entries."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{
            "type": "MERGE",
            "source_ids": ["oth-001"],
            "merged_text": "rewritten",
        }],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # oth-001 should still be present
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"] == "oth-001"


# @tests-contract REQ-CUR-003
def test_contract_merge_skips_nonexistent_source_ids(project_dir):
    """Contract: MERGE filters non-existent source IDs; skips if fewer than 2 remain."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{
            "type": "MERGE",
            "source_ids": ["oth-001", "oth-999"],
            "merged_text": "combined",
        }],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # MERGE skipped: oth-001 still present
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"] == "oth-001"


# ===========================================================================
# REQ-CUR-004: DELETE Operation
# ===========================================================================


# @tests-contract REQ-CUR-004
def test_contract_delete_operation(project_dir):
    """Contract: DELETE removes the specified entry."""
    playbook = _make_sections_playbook({
        "MISTAKES TO AVOID": [
            {"name": "mis-001", "text": "bad advice", "helpful": 0, "harmful": 2},
        ],
    })
    extraction = {
        "operations": [{
            "type": "DELETE",
            "target_id": "mis-001",
            "reason": "outdated",
        }],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0


# @tests-contract REQ-CUR-004
def test_contract_delete_skips_nonexistent(project_dir):
    """Contract: DELETE skips when target_id does not exist."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{
            "type": "DELETE",
            "target_id": "nonexistent",
            "reason": "cleanup",
        }],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# @tests-contract REQ-CUR-004
def test_contract_delete_skips_empty_target_id(project_dir):
    """Contract: DELETE skips when target_id is empty."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "keep me", "helpful": 0, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [{"type": "DELETE", "target_id": "", "reason": "cleanup"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# ===========================================================================
# REQ-CUR-005: Sequential Processing Order
# ===========================================================================


# @tests-contract REQ-CUR-005
def test_contract_sequential_processing(project_dir):
    """Contract: Operations are applied sequentially; later ops see earlier state."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
            {"name": "oth-002", "text": "B", "helpful": 2, "harmful": 0},
            {"name": "oth-003", "text": "C", "helpful": 3, "harmful": 0},
        ],
    })
    extraction = {
        "operations": [
            {"type": "DELETE", "target_id": "oth-001", "reason": "outdated"},
            {
                "type": "MERGE",
                "source_ids": ["oth-002", "oth-003"],
                "merged_text": "combined BC",
            },
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "combined BC"
    assert oth[0]["helpful"] == 5


# ===========================================================================
# REQ-CUR-006: Deep Copy Atomicity and Exception Rollback
# ===========================================================================


# @tests-contract REQ-CUR-006
def test_contract_rollback_on_exception(project_dir, monkeypatch):
    """Contract: On exception during operations, original playbook returned."""
    playbook = _make_sections_playbook({
        "PATTERNS & APPROACHES": [
            {"name": "pat-001", "text": "original", "helpful": 5, "harmful": 1},
        ],
    })

    def _raise_on_call(pb, ops):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(_common_module, "_apply_curator_operations", _raise_on_call)

    extraction = {
        "operations": [{"type": "ADD", "text": "will fail"}],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # Contract: original returned unchanged
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["text"] == "original"
    assert pat[0]["helpful"] == 5


# @tests-contract REQ-CUR-006
def test_contract_deep_copy_isolation(project_dir):
    """Contract: Operations do not mutate the original playbook dict."""
    playbook = _make_sections_playbook({
        "OTHERS": [
            {"name": "oth-001", "text": "original", "helpful": 1, "harmful": 0},
        ],
    })
    original_copy = copy.deepcopy(playbook)

    extraction = {
        "operations": [
            {"type": "DELETE", "target_id": "oth-001", "reason": "remove"},
            {"type": "ADD", "text": "new entry", "section": "OTHERS"},
        ],
        "evaluations": [],
    }
    update_playbook_data(playbook, extraction)

    # The passed-in playbook should be unchanged
    assert playbook["sections"]["OTHERS"] == original_copy["sections"]["OTHERS"]


# ===========================================================================
# REQ-CUR-007: Updated Prompt Structure
# ===========================================================================


# @tests-contract REQ-CUR-007
def test_contract_prompt_structure():
    """Contract: reflection.txt template includes operation examples and instructions."""
    template_path = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src" / "prompts" / "reflection.txt")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Contract: ADD example
    assert '"type": "ADD"' in content
    # Contract: MERGE example
    assert '"type": "MERGE"' in content
    # Contract: DELETE example
    assert '"type": "DELETE"' in content
    # Contract: max 10 operations
    assert "10" in content
    # Contract: zero operations allowed
    assert "[]" in content
    # Contract: playbook variable
    assert "{playbook}" in content
    # Contract: all canonical section names present
    for section_name in SECTION_SLUGS:
        assert section_name in content


# ===========================================================================
# REQ-CUR-008: Operations vs new_key_points Precedence
# ===========================================================================


# @tests-contract REQ-CUR-008
def test_contract_operations_precedence(project_dir):
    """Contract: When operations present, new_key_points is ignored."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
        "new_key_points": ["from nkp"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # Only operations-added entry should exist
    all_texts = set()
    for entries in result["sections"].values():
        for kp in entries:
            all_texts.add(kp["text"])
    assert "from ops" in all_texts
    assert "from nkp" not in all_texts


# @tests-contract REQ-CUR-008
def test_contract_operations_absent_uses_new_key_points(project_dir):
    """Contract: When operations key absent, new_key_points is used (backward compat)."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": ["legacy point"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "legacy point"


# @tests-contract REQ-CUR-008
def test_contract_empty_operations_still_ignores_nkp(project_dir):
    """Contract: Empty operations list still suppresses new_key_points."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [],
        "new_key_points": ["should not be added"],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    all_texts = set()
    for entries in result["sections"].values():
        for kp in entries:
            all_texts.add(kp["text"])
    assert "should not be added" not in all_texts


# ===========================================================================
# REQ-CUR-009: Operations Validation and Truncation
# ===========================================================================


# @tests-contract REQ-CUR-009
def test_contract_operations_validation(project_dir):
    """Contract: Invalid operations are skipped; valid ones proceed."""
    playbook = _make_sections_playbook()
    extraction = {
        "operations": [
            {"type": "UPDATE", "text": "unknown type"},  # unknown type
            {"type": "ADD", "text": "", "section": "OTHERS"},  # empty text
            {"type": "ADD", "text": "valid entry", "section": "OTHERS"},  # valid
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    oth = result["sections"]["OTHERS"]
    assert len(oth) == 1
    assert oth[0]["text"] == "valid entry"


# @tests-contract REQ-CUR-009
def test_contract_operations_truncated_to_10(project_dir):
    """Contract: More than 10 operations are truncated to the first 10."""
    playbook = _make_sections_playbook()
    ops = [{"type": "ADD", "text": f"entry {i}", "section": "OTHERS"} for i in range(15)]
    extraction = {
        "operations": ops,
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    oth = result["sections"]["OTHERS"]
    assert len(oth) == 10


# ===========================================================================
# Deliverable Tests: Full Lifecycle
# ===========================================================================


# @tests-contract REQ-CUR-002, REQ-CUR-003, REQ-CUR-004, REQ-CUR-005, REQ-CUR-008
def test_contract_full_lifecycle_operations(project_dir):
    """Deliverable: Full operations lifecycle with ADD, MERGE, DELETE, and evaluations."""
    playbook = _make_sections_playbook({
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
            {"type": "ADD", "text": "prefer composition", "section": "PATTERNS & APPROACHES"},
            {
                "type": "MERGE",
                "source_ids": ["pat-001", "pat-002"],
                "merged_text": "use types and dataclasses",
            },
            {"type": "DELETE", "target_id": "mis-001", "reason": "outdated"},
        ],
        "evaluations": [
            {"name": "oth-001", "rating": "helpful"},
        ],
        "new_key_points": ["should be ignored"],
    }
    result = update_playbook_data(playbook, extraction)

    # Contract: ADD created new entry
    pat = result["sections"]["PATTERNS & APPROACHES"]
    pat_texts = [kp["text"] for kp in pat]
    assert "prefer composition" in pat_texts

    # Contract: MERGE created merged entry, removed sources
    assert "use types and dataclasses" in pat_texts
    pat_names = [kp["name"] for kp in pat]
    assert "pat-001" not in pat_names
    assert "pat-002" not in pat_names

    # Contract: merged entry has summed counters
    merged = next(kp for kp in pat if kp["text"] == "use types and dataclasses")
    assert merged["helpful"] == 8
    assert merged["harmful"] == 1

    # Contract: DELETE removed entry
    assert len(result["sections"]["MISTAKES TO AVOID"]) == 0

    # Contract: evaluations applied
    oth_001 = next(kp for kp in result["sections"]["OTHERS"] if kp["name"] == "oth-001")
    assert oth_001["helpful"] == 2

    # Contract: new_key_points ignored
    all_texts = set()
    for entries in result["sections"].values():
        for kp in entries:
            all_texts.add(kp["text"])
    assert "should be ignored" not in all_texts


# @tests-contract REQ-CUR-008
def test_contract_full_lifecycle_backward_compat(project_dir):
    """Deliverable: Old-format extraction with new_key_points still works."""
    playbook = _make_sections_playbook()
    extraction = {
        "new_key_points": [
            "legacy tip one",
            {"text": "legacy tip two", "section": "PATTERNS & APPROACHES"},
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)

    # Legacy path: entries added
    oth = result["sections"]["OTHERS"]
    assert any(kp["text"] == "legacy tip one" for kp in oth)

    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert any(kp["text"] == "legacy tip two" for kp in pat)
