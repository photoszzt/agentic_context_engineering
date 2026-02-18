# Spec: docs/scoring/spec.md
# Contract: docs/scoring/contract.md
# Testing: docs/scoring/testing.md
"""
Contract (black-box) tests for the scoring module.

These tests exercise the public API as documented in contract.md.
They do NOT reference internal branches, implementation details, or design.md.
They verify only behaviors promised by the data contracts.
"""

import json
import os
import sys

import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, "/data/agentic_context_engineering")

from src.hooks.common import (
    load_playbook,
    save_playbook,
    update_playbook_data,
    format_playbook,
)


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


# ===========================================================================
# REQ-SCORE-001: PlaybookEntry Schema
# ===========================================================================


# @tests-contract REQ-SCORE-001
def test_contract_playbook_entry_schema(project_dir, playbook_path):
    """Contract: After save, entries conform to PlaybookEntry schema
    with {name, text, helpful, harmful} and no 'score' field."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
        ],
    }
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert "version" in saved
    assert "last_updated" in saved
    assert "key_points" in saved

    entry = saved["key_points"][0]
    assert isinstance(entry["name"], str)
    assert isinstance(entry["text"], str)
    assert isinstance(entry["helpful"], int)
    assert isinstance(entry["harmful"], int)
    assert entry["helpful"] >= 0
    assert entry["harmful"] >= 0
    assert "score" not in entry


# ===========================================================================
# REQ-SCORE-002: Counter Increment on Rating
# ===========================================================================


# @tests-contract REQ-SCORE-002
def test_contract_helpful_increment(project_dir):
    """Contract: 'helpful' rating increments helpful counter by 1."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "tip", "helpful": 3, "harmful": 1},
        ],
    }
    extraction_result = {
        "new_key_points": [],
        "evaluations": [{"name": "kpt_001", "rating": "helpful"}],
    }
    result = update_playbook_data(playbook, extraction_result)
    kp = result["key_points"][0]
    assert kp["helpful"] == 4
    assert kp["harmful"] == 1  # unchanged


# @tests-contract REQ-SCORE-002
def test_contract_harmful_increment(project_dir):
    """Contract: 'harmful' rating increments harmful counter by 1."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "tip", "helpful": 3, "harmful": 1},
        ],
    }
    extraction_result = {
        "new_key_points": [],
        "evaluations": [{"name": "kpt_001", "rating": "harmful"}],
    }
    result = update_playbook_data(playbook, extraction_result)
    kp = result["key_points"][0]
    assert kp["helpful"] == 3  # unchanged
    assert kp["harmful"] == 2


# @tests-contract REQ-SCORE-002
def test_contract_neutral_no_change(project_dir):
    """Contract: 'neutral' rating changes neither counter."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "tip", "helpful": 3, "harmful": 1},
        ],
    }
    extraction_result = {
        "new_key_points": [],
        "evaluations": [{"name": "kpt_001", "rating": "neutral"}],
    }
    result = update_playbook_data(playbook, extraction_result)
    kp = result["key_points"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# ===========================================================================
# REQ-SCORE-003: Formatted Output with Counts
# ===========================================================================


# @tests-contract REQ-SCORE-003
def test_contract_format_output_structure(project_dir, mock_template):
    """Contract: format_playbook outputs [name] helpful=X harmful=Y :: text format."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "use type hints", "helpful": 5, "harmful": 1},
            {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
        ],
    }
    result = format_playbook(playbook)

    # Per contract.md: format is [name] helpful=N harmful=N :: text
    assert "[kpt_001] helpful=5 harmful=1 :: use type hints" in result
    assert "[kpt_002] helpful=0 harmful=0 :: prefer pathlib" in result

    # Template wraps the key points
    assert "HEADER" in result
    assert "FOOTER" in result


# @tests-contract REQ-SCORE-003
def test_contract_format_empty_returns_empty(project_dir, mock_template):
    """Contract: Empty key_points list -> returns empty string."""
    playbook = {"version": "1.0", "last_updated": None, "key_points": []}
    result = format_playbook(playbook)
    assert result == ""


# ===========================================================================
# REQ-SCORE-004: Migration -- Bare String Entries
# ===========================================================================


# @tests-contract REQ-SCORE-004
def test_contract_bare_string_migration(project_dir, playbook_path):
    """Contract: Bare string entry migrated to canonical PlaybookEntry schema."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": ["Always use type hints for function signatures"],
    })
    playbook = load_playbook()

    assert len(playbook["key_points"]) == 1
    entry = playbook["key_points"][0]

    # Per contract.md: name is generated, text is the string, helpful=0, harmful=0
    assert isinstance(entry["name"], str)
    assert entry["name"].startswith("kpt_")
    assert entry["text"] == "Always use type hints for function signatures"
    assert entry["helpful"] == 0
    assert entry["harmful"] == 0
    assert "score" not in entry


# ===========================================================================
# REQ-SCORE-005: Migration -- Dict Without Score
# ===========================================================================


# @tests-contract REQ-SCORE-005
def test_contract_dict_no_score_migration(project_dir, playbook_path):
    """Contract: Dict without score/counters migrated with helpful=0, harmful=0."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_003", "text": "Prefer pathlib over os.path"}],
    })
    playbook = load_playbook()

    entry = playbook["key_points"][0]
    assert entry["name"] == "kpt_003"
    assert entry["text"] == "Prefer pathlib over os.path"
    assert entry["helpful"] == 0
    assert entry["harmful"] == 0
    assert "score" not in entry


# ===========================================================================
# REQ-SCORE-006: Migration -- Dict With Score
# ===========================================================================


# @tests-contract REQ-SCORE-006
def test_contract_dict_with_score_migration(project_dir, playbook_path):
    """Contract: Dict with score=-3 migrated per formula: helpful=max(s,0), harmful=max(-s,0)."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_005", "text": "Avoid global state", "score": -3},
        ],
    })
    playbook = load_playbook()

    entry = playbook["key_points"][0]
    assert entry["name"] == "kpt_005"
    assert entry["text"] == "Avoid global state"
    # Per contract.md migration formula:
    # score=-3 -> helpful = max(-3, 0) = 0, harmful = max(3, 0) = 3
    assert entry["helpful"] == 0
    assert entry["harmful"] == 3
    assert "score" not in entry


# @tests-contract REQ-SCORE-006
def test_contract_dict_with_positive_score_migration(project_dir, playbook_path):
    """Contract: Dict with score=5 migrated: helpful=5, harmful=0."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "good tip", "score": 5},
        ],
    })
    playbook = load_playbook()

    entry = playbook["key_points"][0]
    assert entry["helpful"] == 5
    assert entry["harmful"] == 0
    assert "score" not in entry


# @tests-contract REQ-SCORE-006
def test_contract_dict_with_zero_score_migration(project_dir, playbook_path):
    """Contract: Dict with score=0 migrated: helpful=0, harmful=0."""
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "neutral tip", "score": 0},
        ],
    })
    playbook = load_playbook()

    entry = playbook["key_points"][0]
    assert entry["helpful"] == 0
    assert entry["harmful"] == 0
    assert "score" not in entry


# ===========================================================================
# REQ-SCORE-007: Pruning Rule
# ===========================================================================


# @tests-contract REQ-SCORE-007
def test_contract_pruning_removes_harmful(project_dir):
    """Contract: Entry meeting pruning condition (harmful >= 3 AND harmful > helpful)
    is removed."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "bad advice", "helpful": 1, "harmful": 4},
            {"name": "kpt_002", "text": "good advice", "helpful": 10, "harmful": 1},
        ],
    }
    extraction_result = {"new_key_points": [], "evaluations": []}
    result = update_playbook_data(playbook, extraction_result)

    names = [kp["name"] for kp in result["key_points"]]
    assert "kpt_001" not in names  # pruned
    assert "kpt_002" in names  # retained


# @tests-contract REQ-SCORE-007
def test_contract_pruning_retains_helpful(project_dir):
    """Contract: Entry with harmful >= 3 but helpful >= harmful is retained."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "controversial", "helpful": 10, "harmful": 4},
        ],
    }
    extraction_result = {"new_key_points": [], "evaluations": []}
    result = update_playbook_data(playbook, extraction_result)

    assert len(result["key_points"]) == 1
    assert result["key_points"][0]["name"] == "kpt_001"


# @tests-contract REQ-SCORE-007
def test_contract_pruning_decision_table(project_dir):
    """Contract: Verify the full pruning decision table from contract.md."""
    playbook = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "keep_zero", "text": "a", "helpful": 0, "harmful": 0},     # No
            {"name": "keep_below", "text": "b", "helpful": 0, "harmful": 2},     # No
            {"name": "prune_a", "text": "c", "helpful": 0, "harmful": 3},        # Yes
            {"name": "prune_b", "text": "d", "helpful": 1, "harmful": 4},        # Yes
            {"name": "keep_majority", "text": "e", "helpful": 10, "harmful": 4}, # No
            {"name": "keep_equal", "text": "f", "helpful": 3, "harmful": 3},     # No
            {"name": "prune_c", "text": "g", "helpful": 5, "harmful": 6},        # Yes
            {"name": "prune_d", "text": "h", "helpful": 0, "harmful": 100},      # Yes
        ],
    }
    extraction_result = {"new_key_points": [], "evaluations": []}
    result = update_playbook_data(playbook, extraction_result)

    surviving_names = {kp["name"] for kp in result["key_points"]}
    # Should be retained
    assert "keep_zero" in surviving_names
    assert "keep_below" in surviving_names
    assert "keep_majority" in surviving_names
    assert "keep_equal" in surviving_names
    # Should be pruned
    assert "prune_a" not in surviving_names
    assert "prune_b" not in surviving_names
    assert "prune_c" not in surviving_names
    assert "prune_d" not in surviving_names


# ===========================================================================
# REQ-SCORE-008: Playbook Template Update
# ===========================================================================


# @tests-contract REQ-SCORE-008
def test_contract_template_explains_semantics():
    """Contract: Template contains guidance about helpful/harmful counts,
    ratio weighting, and the {key_points} placeholder."""
    template_path = "/data/agentic_context_engineering/src/prompts/playbook.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Per contract.md: template must explain helpful/harmful semantics
    assert "{key_points}" in content, "Template must have {key_points} placeholder"
    assert "helpful" in content.lower(), "Template must mention 'helpful'"
    assert "harmful" in content.lower(), "Template must mention 'harmful'"
    assert "ratio" in content.lower(), "Template must mention ratio weighting"


# ===========================================================================
# Deliverable Tests: Full Lifecycle (End-to-End)
# ===========================================================================


# @tests-contract REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006
def test_contract_full_lifecycle_mixed_migration(project_dir, playbook_path, mock_template):
    """Deliverable test: Write a mixed-format legacy playbook, load (migration),
    update with evaluations, save, reload, and format."""
    # Step 1: Write a legacy playbook.json with all 3 legacy formats + 1 canonical
    legacy_data = {
        "version": "1.0",
        "last_updated": "2026-01-15T10:00:00",
        "key_points": [
            "Use type hints",
            {"name": "kpt_002", "text": "Prefer pathlib"},
            {"name": "kpt_003", "text": "Avoid globals", "score": -3},
            {"name": "kpt_004", "text": "Write tests", "helpful": 8, "harmful": 2},
        ],
    }
    _write_playbook_file(playbook_path, legacy_data)

    # Step 2: Load (migration runs)
    playbook = load_playbook()
    assert len(playbook["key_points"]) == 4

    # Verify all entries conform to PlaybookEntry schema
    for entry in playbook["key_points"]:
        assert isinstance(entry["name"], str)
        assert isinstance(entry["text"], str)
        assert isinstance(entry["helpful"], int)
        assert isinstance(entry["harmful"], int)
        assert entry["helpful"] >= 0
        assert entry["harmful"] >= 0
        assert "score" not in entry

    # Step 3: Update with evaluations
    extraction_result = {
        "new_key_points": ["New discovery"],
        "evaluations": [
            {"name": "kpt_004", "rating": "helpful"},
        ],
    }
    playbook = update_playbook_data(playbook, extraction_result)

    # kpt_004 should have helpful incremented
    kpt_004 = next(kp for kp in playbook["key_points"] if kp["name"] == "kpt_004")
    assert kpt_004["helpful"] == 9

    # New entry should be added; note kpt_003 (harmful=3, helpful=0) meets pruning
    # condition so is removed, making total = 4 (3 surviving + 1 new)
    names = [kp["name"] for kp in playbook["key_points"]]
    assert "kpt_003" not in names  # pruned per pruning contract
    new_entries = [kp for kp in playbook["key_points"] if kp["text"] == "New discovery"]
    assert len(new_entries) == 1
    assert new_entries[0]["helpful"] == 0
    assert new_entries[0]["harmful"] == 0

    # Step 4: Save
    save_playbook(playbook)

    # Step 5: Reload (round-trip stability)
    playbook2 = load_playbook()
    # 4 entries survive: kpt_001, kpt_002, kpt_004, kpt_005 (new discovery)
    # kpt_003 was pruned before save
    assert len(playbook2["key_points"]) == 4
    for entry in playbook2["key_points"]:
        assert "score" not in entry
        assert entry["helpful"] >= 0
        assert entry["harmful"] >= 0

    # Step 6: Format
    formatted = format_playbook(playbook2)
    assert "HEADER" in formatted
    assert "FOOTER" in formatted
    assert "helpful=" in formatted
    assert "harmful=" in formatted


# @tests-contract REQ-SCORE-001, REQ-SCORE-002, REQ-SCORE-007
def test_contract_full_lifecycle_round_trip(project_dir, playbook_path, mock_template):
    """Deliverable test: Full lifecycle with pruning -- write, load, update
    (with harmful ratings), save, reload, verify pruned entry is gone."""
    # Write initial playbook with an entry near pruning threshold
    initial_data = {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "keep me", "helpful": 5, "harmful": 0},
            {"name": "kpt_002", "text": "borderline", "helpful": 0, "harmful": 2},
        ],
    }
    _write_playbook_file(playbook_path, initial_data)

    # Load
    playbook = load_playbook()
    assert len(playbook["key_points"]) == 2

    # Update: push kpt_002 over the pruning threshold
    extraction_result = {
        "new_key_points": [],
        "evaluations": [
            {"name": "kpt_002", "rating": "harmful"},  # harmful: 2 -> 3
        ],
    }
    playbook = update_playbook_data(playbook, extraction_result)

    # kpt_002 should be pruned (harmful=3 >= 3 AND harmful=3 > helpful=0)
    names = [kp["name"] for kp in playbook["key_points"]]
    assert "kpt_001" in names
    assert "kpt_002" not in names

    # Save
    save_playbook(playbook)

    # Reload
    playbook2 = load_playbook()
    names2 = [kp["name"] for kp in playbook2["key_points"]]
    assert "kpt_001" in names2
    assert "kpt_002" not in names2

    # Format
    formatted = format_playbook(playbook2)
    assert "kpt_001" in formatted
    assert "kpt_002" not in formatted


# @tests-contract REQ-SCORE-002
def test_contract_full_lifecycle_new_keypoints(project_dir, playbook_path, mock_template):
    """Deliverable test: New key points are added, persisted, and formatted correctly."""
    # Start with empty playbook
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [],
    })

    playbook = load_playbook()
    assert playbook["key_points"] == []

    # Add new key points
    extraction_result = {
        "new_key_points": ["tip one", "tip two"],
        "evaluations": [],
    }
    playbook = update_playbook_data(playbook, extraction_result)
    assert len(playbook["key_points"]) == 2

    # Save and reload
    save_playbook(playbook)
    playbook2 = load_playbook()
    assert len(playbook2["key_points"]) == 2

    # Rate them
    extraction_result2 = {
        "new_key_points": [],
        "evaluations": [
            {"name": playbook2["key_points"][0]["name"], "rating": "helpful"},
            {"name": playbook2["key_points"][1]["name"], "rating": "harmful"},
        ],
    }
    playbook2 = update_playbook_data(playbook2, extraction_result2)

    assert playbook2["key_points"][0]["helpful"] == 1
    assert playbook2["key_points"][1]["harmful"] == 1

    # Format
    formatted = format_playbook(playbook2)
    assert "helpful=1" in formatted
    assert "harmful=1" in formatted


# @tests-contract REQ-SCORE-001
def test_contract_empty_playbook_schema(project_dir):
    """Contract: When no playbook.json exists, load returns empty playbook
    with canonical schema."""
    playbook = load_playbook()
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    assert playbook["key_points"] == []
    assert isinstance(playbook["key_points"], list)


# @tests-contract REQ-SCORE-004
def test_contract_mixed_format_migration(project_dir, playbook_path):
    """Contract: Mixed-format playbook.json from contract.md example is
    correctly migrated."""
    # This is the exact example from contract.md "Mixed Format Example"
    _write_playbook_file(playbook_path, {
        "version": "1.0",
        "last_updated": "2026-01-15T10:00:00",
        "key_points": [
            "Use type hints",
            {"name": "kpt_002", "text": "Prefer pathlib"},
            {"name": "kpt_003", "text": "Avoid globals", "score": -3},
            {"name": "kpt_004", "text": "Write tests", "helpful": 8, "harmful": 2},
        ],
    })
    playbook = load_playbook()

    assert len(playbook["key_points"]) == 4

    # All must conform to PlaybookEntry schema
    for entry in playbook["key_points"]:
        assert "name" in entry
        assert "text" in entry
        assert "helpful" in entry
        assert "harmful" in entry
        assert "score" not in entry
        assert entry["helpful"] >= 0
        assert entry["harmful"] >= 0

    # Verify specific expected values from contract.md
    by_name = {kp["name"]: kp for kp in playbook["key_points"]}

    # Bare string -> generated name, helpful=0, harmful=0
    bare_entry = playbook["key_points"][0]
    assert bare_entry["text"] == "Use type hints"
    assert bare_entry["helpful"] == 0
    assert bare_entry["harmful"] == 0

    # Dict no score -> helpful=0, harmful=0
    assert by_name["kpt_002"]["helpful"] == 0
    assert by_name["kpt_002"]["harmful"] == 0

    # Dict with score=-3 -> helpful=0, harmful=3
    assert by_name["kpt_003"]["helpful"] == 0
    assert by_name["kpt_003"]["harmful"] == 3

    # Already canonical -> unchanged
    assert by_name["kpt_004"]["helpful"] == 8
    assert by_name["kpt_004"]["harmful"] == 2
