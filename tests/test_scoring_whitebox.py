# Spec: docs/scoring/spec.md
# Testing: docs/scoring/testing.md
"""
White-box tests for the scoring module (src/hooks/common.py).

Covers all REQ-SCORE-*, SCN-SCORE-*, INV-SCORE-*, LOG-SCORE-* from spec.md
and observability.md, plus adversarial test categories TC-BOUND-*, TC-INVAL-*,
TC-EDGE-*, TC-INV-*.
"""

import json
import os
import sys
import glob

import pytest

# Ensure the project root is on sys.path so we can import from src.hooks.common
sys.path.insert(0, "/data/agentic_context_engineering")

from src.hooks.common import (
    load_playbook,
    save_playbook,
    update_playbook_data,
    format_playbook,
    generate_keypoint_name,
    is_diagnostic_mode,
    save_diagnostic,
)


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


def _make_playbook(key_points, section="OTHERS"):
    """Helper to construct a sections-based playbook dict.

    Places the given key_points into the specified section (default OTHERS).
    All other canonical sections are initialized as empty lists.
    """
    from src.hooks.common import SECTION_SLUGS
    sections = {name: [] for name in SECTION_SLUGS}
    sections[section] = key_points
    return {"version": "1.0", "last_updated": None, "sections": sections}


def _make_extraction(new_key_points=None, evaluations=None):
    """Helper to construct an extraction_result dict."""
    return {
        "new_key_points": new_key_points or [],
        "evaluations": evaluations or [],
    }


# ===========================================================================
# REQ-SCORE-001: PlaybookEntry Schema
# ===========================================================================


# @tests REQ-SCORE-001
def test_save_playbook_entry_schema(project_dir, playbook_path):
    """After save_playbook, entries have exactly {name, text, helpful, harmful}
    and no 'score' field."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
    ])
    save_playbook(playbook)

    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    entry = saved["sections"]["OTHERS"][0]
    assert entry["name"] == "kpt_001"
    assert entry["text"] == "use types"
    assert entry["helpful"] == 5
    assert entry["harmful"] == 1
    assert "score" not in entry
    assert saved["version"] == "1.0"
    assert saved["last_updated"] is not None
    assert "key_points" not in saved


# ===========================================================================
# REQ-SCORE-002: Counter Increment on Rating
# ===========================================================================


# @tests REQ-SCORE-002, SCN-SCORE-002-01
def test_update_helpful_rating(project_dir):
    """'helpful' rating increments the helpful counter by 1."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 4
    assert kp["harmful"] == 1


# @tests REQ-SCORE-002, SCN-SCORE-002-02
def test_update_harmful_rating(project_dir):
    """'harmful' rating increments the harmful counter by 1."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "harmful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 2


# @tests REQ-SCORE-002, SCN-SCORE-002-03
def test_update_neutral_rating(project_dir):
    """'neutral' rating changes neither counter."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "neutral"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# @tests REQ-SCORE-002, SCN-SCORE-002-04
def test_update_unknown_rating(project_dir):
    """Unrecognized rating changes neither counter."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "bogus"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# @tests REQ-SCORE-002
def test_update_nonexistent_name(project_dir):
    """Evaluation referencing a name not in the playbook is silently ignored."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_999", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# Scenario-level tests (exact spec scenarios)

# @tests SCN-SCORE-002-01
def test_scn_helpful_rating_increments_counter(project_dir):
    """SCN-SCORE-002-01: kpt_001 helpful=3->4, harmful=1 unchanged."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 4
    assert kp["harmful"] == 1


# @tests SCN-SCORE-002-02
def test_scn_harmful_rating_increments_counter(project_dir):
    """SCN-SCORE-002-02: kpt_001 helpful=3 unchanged, harmful=1->2."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "harmful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 2


# @tests SCN-SCORE-002-03
def test_scn_neutral_rating_changes_nothing(project_dir):
    """SCN-SCORE-002-03: neutral leaves counters unchanged."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "neutral"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# @tests SCN-SCORE-002-04
def test_scn_unknown_rating_changes_nothing(project_dir):
    """SCN-SCORE-002-04: bogus rating leaves counters unchanged."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "bogus"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1


# ===========================================================================
# REQ-SCORE-003: Formatted Output with Counts
# ===========================================================================


# @tests REQ-SCORE-003, SCN-SCORE-003-01
def test_format_playbook_with_counts(project_dir, mock_template):
    """format_playbook outputs [name] helpful=X harmful=Y :: text format."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use type hints", "helpful": 5, "harmful": 1},
        {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
    ])
    result = format_playbook(playbook)
    assert "[kpt_001] helpful=5 harmful=1 :: use type hints" in result
    assert "[kpt_002] helpful=0 harmful=0 :: prefer pathlib" in result
    assert result.startswith("HEADER\n")
    assert result.endswith("\nFOOTER")


# @tests SCN-SCORE-003-01
def test_scn_format_includes_counts(project_dir, mock_template):
    """SCN-SCORE-003-01: Format includes helpful and harmful counts."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "use type hints", "helpful": 5, "harmful": 1},
        {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
    ])
    result = format_playbook(playbook)
    # Verify both entries are in the expected format
    lines = result.split("\n")
    key_points_lines = [l for l in lines if l.startswith("[kpt_")]
    assert len(key_points_lines) == 2
    assert key_points_lines[0] == "[kpt_001] helpful=5 harmful=1 :: use type hints"
    assert key_points_lines[1] == "[kpt_002] helpful=0 harmful=0 :: prefer pathlib"


# @tests SCN-SCORE-003-02
def test_scn_empty_playbook_returns_empty(project_dir, mock_template):
    """SCN-SCORE-003-02: Empty key_points list returns empty string."""
    playbook = _make_playbook([])
    result = format_playbook(playbook)
    assert result == ""


# ===========================================================================
# REQ-SCORE-004: Migration -- Bare String Entries
# ===========================================================================


# @tests REQ-SCORE-004, SCN-SCORE-004-01
def test_load_migrates_bare_string(project_dir, playbook_path):
    """Bare string entry is migrated to {name, text, helpful: 0, harmful: 0}."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": ["always use type hints"],
    })
    playbook = load_playbook()
    assert len(playbook["sections"]["OTHERS"]) == 1
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["name"] == "kpt_001"
    assert kp["text"] == "always use type hints"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0
    assert "score" not in kp


# @tests SCN-SCORE-004-01
def test_scn_load_bare_string_entry(project_dir, playbook_path):
    """SCN-SCORE-004-01: Load bare string entry -- full scenario check."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": ["always use type hints"],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["name"] == "kpt_001"
    assert kp["text"] == "always use type hints"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0
    assert "score" not in kp


# ===========================================================================
# REQ-SCORE-005: Migration -- Dict Without Score
# ===========================================================================


# @tests REQ-SCORE-005, SCN-SCORE-005-01
def test_load_migrates_dict_without_score(project_dir, playbook_path):
    """Dict without score or counters gets helpful=0, harmful=0."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "use types"}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["name"] == "kpt_001"
    assert kp["text"] == "use types"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0
    assert "score" not in kp


# @tests SCN-SCORE-005-01
def test_scn_load_dict_without_score(project_dir, playbook_path):
    """SCN-SCORE-005-01: Dict without score or counters migrated correctly."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "use types"}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0
    assert "score" not in kp


# ===========================================================================
# REQ-SCORE-006: Migration -- Dict With Score
# ===========================================================================


# @tests REQ-SCORE-006, SCN-SCORE-006-01
def test_load_migrates_dict_with_score(project_dir, playbook_path):
    """Dict with score=-3 migrated to helpful=0, harmful=3. Score dropped."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "use types", "score": -3}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["name"] == "kpt_001"
    assert kp["text"] == "use types"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 3
    assert "score" not in kp


# @tests SCN-SCORE-006-01
def test_scn_load_dict_with_score_field(project_dir, playbook_path):
    """SCN-SCORE-006-01: Dict with score field migrated with formula."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "use types", "score": -3}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 0
    assert kp["harmful"] == 3
    assert "score" not in kp


# @tests SCN-SCORE-006-02
def test_scn_load_dict_with_score_and_counters(project_dir, playbook_path):
    """SCN-SCORE-006-02: Dict with helpful, harmful, AND score -- canonical
    fields preserved, score defensively dropped."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "use types",
                        "helpful": 3, "harmful": 1, "score": 2}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 3
    assert kp["harmful"] == 1
    assert "score" not in kp


# ===========================================================================
# REQ-SCORE-007: Pruning Rule
# ===========================================================================


# @tests REQ-SCORE-007, SCN-SCORE-007-01
def test_pruning_removes_harmful_entry(project_dir):
    """Entry with harmful >= 3 AND harmful > helpful is pruned."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "bad advice", "helpful": 1, "harmful": 4},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SCORE-007, SCN-SCORE-007-02
def test_pruning_retains_helpful_majority(project_dir):
    """Entry with high harmful but higher helpful is retained."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "controversial", "helpful": 10, "harmful": 4},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    assert result["sections"]["OTHERS"][0]["name"] == "kpt_001"


# @tests REQ-SCORE-007, SCN-SCORE-007-03
def test_pruning_retains_zero_evaluation(project_dir):
    """Zero-evaluation entry (helpful=0, harmful=0) is never pruned."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "new untested", "helpful": 0, "harmful": 0},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# @tests REQ-SCORE-007, SCN-SCORE-007-04
def test_pruning_retains_below_floor(project_dir):
    """Entry with harmful < 3 is retained even if harmful > helpful."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "new entry", "helpful": 0, "harmful": 2},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1


# @tests SCN-SCORE-007-01
def test_scn_prune_consistently_harmful(project_dir):
    """SCN-SCORE-007-01: Consistently harmful entry is pruned."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "bad advice", "helpful": 1, "harmful": 4},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    names = [kp["name"] for kp in result["sections"]["OTHERS"]]
    assert "kpt_001" not in names


# @tests SCN-SCORE-007-02
def test_scn_retain_high_harmful_higher_helpful(project_dir):
    """SCN-SCORE-007-02: Retained because helpful > harmful."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "controversial", "helpful": 10, "harmful": 4},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    names = [kp["name"] for kp in result["sections"]["OTHERS"]]
    assert "kpt_001" in names


# @tests SCN-SCORE-007-03
def test_scn_retain_zero_evaluation(project_dir):
    """SCN-SCORE-007-03: Zero-evaluation entry retained."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "new untested", "helpful": 0, "harmful": 0},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    names = [kp["name"] for kp in result["sections"]["OTHERS"]]
    assert "kpt_001" in names


# @tests SCN-SCORE-007-04
def test_scn_retain_harmful_below_floor(project_dir):
    """SCN-SCORE-007-04: Below-floor harmful entry retained."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "new entry", "helpful": 0, "harmful": 2},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    names = [kp["name"] for kp in result["sections"]["OTHERS"]]
    assert "kpt_001" in names


# ===========================================================================
# REQ-SCORE-008: Playbook Template Update
# ===========================================================================


# @tests REQ-SCORE-008, SCN-SCORE-008-01
def test_template_explains_scoring_semantics():
    """The playbook.txt template explains helpful/harmful semantics."""
    template_path = "/data/agentic_context_engineering/src/prompts/playbook.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "{key_points}" in content
    assert "helpful" in content.lower()
    assert "harmful" in content.lower()
    assert "ratio" in content.lower()


# @tests SCN-SCORE-008-01
def test_scn_template_content():
    """SCN-SCORE-008-01: Template contains guidance about helpful/harmful counts
    and ratio weighting."""
    template_path = "/data/agentic_context_engineering/src/prompts/playbook.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Template must explain these semantic concepts per REQ-SCORE-008
    assert "helpful" in content
    assert "harmful" in content
    assert "ratio" in content
    assert "{key_points}" in content
    # Template must mention proven value and problematic guidance
    assert "proven" in content.lower() or "valuable" in content.lower()
    assert "problematic" in content.lower()


# ===========================================================================
# INV-SCORE-001: Helpful Counter Non-Negative
# ===========================================================================


# @tests-invariant INV-SCORE-001
def test_invariant_helpful_non_negative(project_dir, playbook_path):
    """After migrating any legacy format, helpful >= 0."""
    # Test all 3 migration paths + canonical
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "dict no score"},
            {"name": "kpt_003", "text": "dict with score", "score": -5},
            {"name": "kpt_004", "text": "dict with score positive", "score": 3},
            {"name": "kpt_005", "text": "canonical", "helpful": 2, "harmful": 1},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert kp["helpful"] >= 0, f"{kp['name']} has negative helpful: {kp['helpful']}"


# ===========================================================================
# INV-SCORE-002: Harmful Counter Non-Negative
# ===========================================================================


# @tests-invariant INV-SCORE-002
def test_invariant_harmful_non_negative(project_dir, playbook_path):
    """After migrating any legacy format, harmful >= 0."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "dict no score"},
            {"name": "kpt_003", "text": "dict with score", "score": -5},
            {"name": "kpt_004", "text": "dict with score positive", "score": 3},
            {"name": "kpt_005", "text": "canonical", "helpful": 2, "harmful": 1},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert kp["harmful"] >= 0, f"{kp['name']} has negative harmful: {kp['harmful']}"


# ===========================================================================
# INV-SCORE-003: Zero-Evaluation Entries Never Pruned
# ===========================================================================


# @tests-invariant INV-SCORE-003
def test_invariant_zero_evaluation_never_pruned(project_dir):
    """Zero-evaluation entries (helpful=0, harmful=0) are never pruned."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "entry a", "helpful": 0, "harmful": 0},
        {"name": "kpt_002", "text": "entry b", "helpful": 0, "harmful": 0},
        {"name": "kpt_003", "text": "entry c", "helpful": 0, "harmful": 0},
    ])
    extraction = _make_extraction()
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 3


# ===========================================================================
# INV-SCORE-004: No Score Field in Output
# ===========================================================================


# @tests-invariant INV-SCORE-004
def test_invariant_no_score_field_after_load(project_dir, playbook_path):
    """After load_playbook(), no entry has a 'score' key."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "no score dict"},
            {"name": "kpt_003", "text": "has score", "score": -3},
            {"name": "kpt_004", "text": "canonical with residual score",
             "helpful": 2, "harmful": 1, "score": 5},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert "score" not in kp, f"{kp['name']} still has score field"


# @tests-invariant INV-SCORE-004
def test_invariant_no_score_field_after_save(project_dir, playbook_path):
    """After save_playbook() and re-read, no entry has a 'score' key."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "a", "helpful": 1, "harmful": 0},
    ])
    save_playbook(playbook)
    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    for kp in saved["sections"]["OTHERS"]:
        assert "score" not in kp


# ===========================================================================
# INV-SCORE-005: Migration Round-Trip Stability
# ===========================================================================


# @tests-invariant INV-SCORE-005
def test_invariant_migration_round_trip_stability(project_dir, playbook_path):
    """Load a legacy playbook, save immediately, load again --
    key_points and version are identical."""
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
# LOG-SCORE-001: Migration Diagnostic
# ===========================================================================


# @tests-instrumentation LOG-SCORE-001
def test_instrumentation_migration_diagnostic_created(
    project_dir, playbook_path, enable_diagnostic
):
    """When diagnostic mode is enabled and legacy entries exist,
    a migration diagnostic file is created."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            "bare string entry",
            {"name": "kpt_002", "text": "dict no score"},
            {"name": "kpt_003", "text": "has score", "score": -3},
        ],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_playbook_migration.txt"))
    assert len(files) >= 1, "Migration diagnostic file not created"

    content = files[0].read_text()
    assert "3" in content  # count of migrated entries
    assert "bare_string" in content
    assert "dict_no_score" in content
    assert "dict_with_score" in content


# @tests-instrumentation LOG-SCORE-001
def test_instrumentation_migration_diagnostic_not_created_when_disabled(
    project_dir, playbook_path
):
    """When diagnostic mode is disabled, no migration diagnostic file is created."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": ["bare string entry"],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_playbook_migration.txt"))
        assert len(files) == 0, "Migration diagnostic created when disabled"


# @tests-instrumentation LOG-SCORE-001
def test_instrumentation_migration_diagnostic_not_created_when_no_migration(
    project_dir, playbook_path, enable_diagnostic
):
    """When all entries are canonical, no migration diagnostic is created."""
    _write_playbook(playbook_path, {
        "version": "1.0",
        "last_updated": None,
        "key_points": [
            {"name": "kpt_001", "text": "canonical", "helpful": 1, "harmful": 0},
        ],
    })
    load_playbook()

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_playbook_migration.txt"))
        assert len(files) == 0, "Migration diagnostic created when no migration occurred"


# ===========================================================================
# LOG-SCORE-002: Pruning Diagnostic
# ===========================================================================


# @tests-instrumentation LOG-SCORE-002
def test_instrumentation_pruning_diagnostic_created(
    project_dir, enable_diagnostic
):
    """When diagnostic mode is enabled and entries are pruned,
    a pruning diagnostic file is created."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "bad advice", "helpful": 1, "harmful": 4},
    ])
    extraction = _make_extraction()
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_playbook_pruning.txt"))
    assert len(files) >= 1, "Pruning diagnostic file not created"

    content = files[0].read_text()
    assert "1" in content  # count of pruned entries
    assert "kpt_001" in content
    assert "bad advice" in content
    assert "helpful=" in content or "helpful" in content
    assert "harmful=" in content or "harmful" in content


# @tests-instrumentation LOG-SCORE-002
def test_instrumentation_pruning_diagnostic_not_created_when_disabled(
    project_dir
):
    """When diagnostic mode is disabled, no pruning diagnostic is created."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "bad advice", "helpful": 1, "harmful": 4},
    ])
    extraction = _make_extraction()
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_playbook_pruning.txt"))
        assert len(files) == 0, "Pruning diagnostic created when disabled"


# @tests-instrumentation LOG-SCORE-002
def test_instrumentation_pruning_diagnostic_not_created_when_no_pruning(
    project_dir, enable_diagnostic
):
    """When no entries meet pruning condition, no pruning diagnostic is created."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "good advice", "helpful": 10, "harmful": 1},
    ])
    extraction = _make_extraction()
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    if diag_dir.exists():
        files = list(diag_dir.glob("*_playbook_pruning.txt"))
        assert len(files) == 0, "Pruning diagnostic created when no pruning"


# @tests-instrumentation LOG-SCORE-002
def test_instrumentation_pruning_text_truncated(
    project_dir, enable_diagnostic
):
    """When pruned entry has text > 80 chars, diagnostic truncates it."""
    long_text = "x" * 200
    playbook = _make_playbook([
        {"name": "kpt_001", "text": long_text, "helpful": 0, "harmful": 5},
    ])
    extraction = _make_extraction()
    update_playbook_data(playbook, extraction)

    diag_dir = project_dir / ".claude" / "diagnostic"
    files = list(diag_dir.glob("*_playbook_pruning.txt"))
    assert len(files) >= 1

    content = files[0].read_text()
    # The text should be truncated -- the full 200-char string should NOT appear
    assert long_text not in content
    # But the first 80 chars should appear
    assert long_text[:80] in content


# ===========================================================================
# Adversarial Tests: TC-BOUND-* (Boundary Conditions)
# ===========================================================================


# @tests REQ-SCORE-007 (TC-BOUND-001)
def test_bound_001_pruning_at_exact_threshold(project_dir):
    """TC-BOUND-001: helpful=2, harmful=3 -- IS pruned (boundary)."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 2, "harmful": 3},
    ])
    result = update_playbook_data(playbook, _make_extraction())
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SCORE-007 (TC-BOUND-002)
def test_bound_002_pruning_equal_threshold(project_dir):
    """TC-BOUND-002: helpful=3, harmful=3 -- NOT pruned (equal, not majority)."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 3, "harmful": 3},
    ])
    result = update_playbook_data(playbook, _make_extraction())
    assert len(result["sections"]["OTHERS"]) == 1


# @tests REQ-SCORE-007 (TC-BOUND-003)
def test_bound_003_harmful_at_exact_floor(project_dir):
    """TC-BOUND-003: helpful=0, harmful=3 -- pruned (minimum trigger)."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 0, "harmful": 3},
    ])
    result = update_playbook_data(playbook, _make_extraction())
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SCORE-007, SCN-SCORE-007-04 (TC-BOUND-004)
def test_bound_004_harmful_one_below_floor(project_dir):
    """TC-BOUND-004: helpful=0, harmful=2 -- NOT pruned (below floor)."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 0, "harmful": 2},
    ])
    result = update_playbook_data(playbook, _make_extraction())
    assert len(result["sections"]["OTHERS"]) == 1


# @tests REQ-SCORE-006 (TC-BOUND-005)
def test_bound_005_score_migration_zero(project_dir, playbook_path):
    """TC-BOUND-005: score=0 -> helpful=0, harmful=0."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x", "score": 0}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# @tests REQ-SCORE-006 (TC-BOUND-006)
def test_bound_006_score_migration_positive(project_dir, playbook_path):
    """TC-BOUND-006: score=1 -> helpful=1, harmful=0."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x", "score": 1}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1
    assert kp["harmful"] == 0


# @tests REQ-SCORE-006 (TC-BOUND-007)
def test_bound_007_score_migration_small_negative(project_dir, playbook_path):
    """TC-BOUND-007: score=-1 -> helpful=0, harmful=1."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x", "score": -1}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 0
    assert kp["harmful"] == 1


# @tests REQ-SCORE-003, SCN-SCORE-003-02 (TC-BOUND-008)
def test_bound_008_empty_key_points(project_dir, mock_template):
    """TC-BOUND-008: Empty key_points -> format returns ''."""
    playbook = _make_playbook([])
    assert format_playbook(playbook) == ""


# @tests REQ-SCORE-003 (TC-BOUND-009)
def test_bound_009_single_entry(project_dir, mock_template):
    """TC-BOUND-009: Single entry produces exactly one formatted line."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "single", "helpful": 1, "harmful": 0},
    ])
    result = format_playbook(playbook)
    assert "[kpt_001] helpful=1 harmful=0 :: single" in result


# ===========================================================================
# Adversarial Tests: TC-INVAL-* (Invalid Inputs)
# ===========================================================================


# @tests REQ-SCORE-002 (TC-INVAL-001)
def test_inval_001_unrecognized_rating(project_dir):
    """TC-INVAL-001: Unrecognized rating 'bogus' is a no-op."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 1, "harmful": 1},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "bogus"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1
    assert kp["harmful"] == 1


# @tests REQ-SCORE-002 (TC-INVAL-002)
def test_inval_002_nonexistent_keypoint(project_dir):
    """TC-INVAL-002: Evaluation references nonexistent key point -- silently ignored."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 1, "harmful": 0},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "nonexistent", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1  # unchanged


# @tests REQ-SCORE-002 (TC-INVAL-003)
def test_inval_003_empty_evaluation_name(project_dir):
    """TC-INVAL-003: Empty string name matches no key point."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 1, "harmful": 0},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "", "rating": "helpful"},
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1  # unchanged


# @tests REQ-SCORE-002 (TC-INVAL-004)
def test_inval_004_missing_rating_key(project_dir):
    """TC-INVAL-004: Evaluation dict missing 'rating' key -- no-op."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 1, "harmful": 0},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001"},  # no "rating" key
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1
    assert kp["harmful"] == 0


# @tests REQ-SCORE-002 (TC-INVAL-005)
def test_inval_005_missing_name_key(project_dir):
    """TC-INVAL-005: Evaluation dict missing 'name' key -- silently ignored."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "x", "helpful": 1, "harmful": 0},
    ])
    extraction = _make_extraction(evaluations=[
        {"rating": "helpful"},  # no "name" key
    ])
    result = update_playbook_data(playbook, extraction)
    kp = result["sections"]["OTHERS"][0]
    assert kp["helpful"] == 1  # unchanged


# @tests REQ-SCORE-001 (TC-INVAL-006)
def test_inval_006_playbook_file_not_exists(project_dir):
    """TC-INVAL-006: playbook.json missing -> empty sections-based playbook returned."""
    playbook = load_playbook()
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    assert "sections" in playbook
    assert "key_points" not in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SCORE-001 (TC-INVAL-007)
def test_inval_007_invalid_json(project_dir, playbook_path):
    """TC-INVAL-007: playbook.json contains invalid JSON -> empty sections-based playbook."""
    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    playbook_path.write_text("NOT VALID JSON {{{")
    playbook = load_playbook()
    assert playbook["version"] == "1.0"
    assert playbook["last_updated"] is None
    assert "sections" in playbook
    assert "key_points" not in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SCORE-001 (TC-INVAL-008)
def test_inval_008_missing_key_points_key(project_dir, playbook_path):
    """TC-INVAL-008: playbook.json missing both 'sections' and 'key_points' -> defaults to empty sections."""
    _write_playbook(playbook_path, {"version": "1.0", "last_updated": None})
    playbook = load_playbook()
    assert "sections" in playbook
    assert "key_points" not in playbook
    for section_entries in playbook["sections"].values():
        assert section_entries == []


# @tests REQ-SCORE-002 (TC-INVAL-009)
def test_inval_009_new_keypoint_empty_text(project_dir):
    """TC-INVAL-009: Empty text in new_key_points should not be appended."""
    playbook = _make_playbook([])
    extraction = _make_extraction(new_key_points=[""])
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SCORE-002 (TC-INVAL-010)
def test_inval_010_duplicate_new_keypoint(project_dir):
    """TC-INVAL-010: Duplicate new key point text is silently skipped."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "existing tip", "helpful": 0, "harmful": 0},
    ])
    extraction = _make_extraction(new_key_points=["existing tip"])
    result = update_playbook_data(playbook, extraction)
    # Should still have only 1 entry (duplicate skipped)
    assert len(result["sections"]["OTHERS"]) == 1


# ===========================================================================
# Adversarial Tests: TC-EDGE-* (Edge Cases / Migration Corner Cases)
# ===========================================================================


# @tests REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006 (TC-EDGE-001)
def test_edge_001_mixed_format_playbook(project_dir, playbook_path):
    """TC-EDGE-001: All 3 legacy types + 1 canonical entry in one file."""
    _write_playbook(playbook_path, {
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
    assert len(playbook["sections"]["OTHERS"]) == 4

    kp1 = playbook["sections"]["OTHERS"][0]
    assert kp1["text"] == "Use type hints"
    assert kp1["helpful"] == 0
    assert kp1["harmful"] == 0
    assert "score" not in kp1

    kp2 = playbook["sections"]["OTHERS"][1]
    assert kp2["name"] == "kpt_002"
    assert kp2["helpful"] == 0
    assert kp2["harmful"] == 0

    kp3 = playbook["sections"]["OTHERS"][2]
    assert kp3["name"] == "kpt_003"
    assert kp3["helpful"] == 0
    assert kp3["harmful"] == 3
    assert "score" not in kp3

    kp4 = playbook["sections"]["OTHERS"][3]
    assert kp4["name"] == "kpt_004"
    assert kp4["helpful"] == 8
    assert kp4["harmful"] == 2


# @tests REQ-SCORE-006, SCN-SCORE-006-02 (TC-EDGE-002)
def test_edge_002_dict_with_score_and_counters(project_dir, playbook_path):
    """TC-EDGE-002: Dict with score AND helpful/harmful -- canonical wins."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x",
                        "helpful": 5, "harmful": 2, "score": 10}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 5  # original preserved
    assert kp["harmful"] == 2  # original preserved
    assert "score" not in kp


# @tests REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006 (TC-EDGE-003)
def test_edge_003_dict_without_name(project_dir, playbook_path):
    """TC-EDGE-003: Dict without 'name' gets auto-generated name."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [
            {"text": "no name dict"},
            {"text": "also no name", "score": 2},
        ],
    })
    playbook = load_playbook()
    names = [kp["name"] for kp in playbook["sections"]["OTHERS"]]
    assert len(set(names)) == 2  # unique names generated
    for name in names:
        assert name.startswith("kpt_")


# @tests REQ-SCORE-006 (TC-EDGE-004)
def test_edge_004_large_negative_score(project_dir, playbook_path):
    """TC-EDGE-004: score=-100 -> helpful=0, harmful=100."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x", "score": -100}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 0
    assert kp["harmful"] == 100


# @tests REQ-SCORE-006 (TC-EDGE-005)
def test_edge_005_large_positive_score(project_dir, playbook_path):
    """TC-EDGE-005: score=50 -> helpful=50, harmful=0."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [{"name": "kpt_001", "text": "x", "score": 50}],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["helpful"] == 50
    assert kp["harmful"] == 0


# @tests REQ-SCORE-007 (TC-EDGE-006)
def test_edge_006_pruning_after_update_in_same_call(project_dir):
    """TC-EDGE-006: Entry at harmful=2 receives harmful rating -> harmful=3 -> pruned."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "borderline", "helpful": 0, "harmful": 2},
    ])
    extraction = _make_extraction(evaluations=[
        {"name": "kpt_001", "rating": "harmful"},
    ])
    result = update_playbook_data(playbook, extraction)
    # After increment: harmful=3, helpful=0 -> harmful >= 3 AND harmful > helpful -> PRUNED
    assert len(result["sections"]["OTHERS"]) == 0


# @tests REQ-SCORE-007, INV-SCORE-003 (TC-EDGE-007)
def test_edge_007_new_keypoints_never_pruned(project_dir):
    """TC-EDGE-007: New key points start at helpful=0, harmful=0 and are never pruned."""
    playbook = _make_playbook([])
    extraction = _make_extraction(
        new_key_points=["brand new tip"],
    )
    result = update_playbook_data(playbook, extraction)
    assert len(result["sections"]["OTHERS"]) == 1
    kp = result["sections"]["OTHERS"][0]
    assert kp["text"] == "brand new tip"
    assert kp["helpful"] == 0
    assert kp["harmful"] == 0


# ===========================================================================
# Adversarial Tests: TC-INV-* (Invariant Verification)
# ===========================================================================


# @tests-invariant INV-SCORE-001 (TC-INV-001)
def test_inv_001_helpful_non_negative_all_paths(project_dir, playbook_path):
    """TC-INV-001: helpful >= 0 after all migration paths."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [
            "bare string",
            {"text": "no name no score"},
            {"name": "kpt_003", "text": "negative score", "score": -10},
            {"name": "kpt_004", "text": "positive score", "score": 7},
            {"name": "kpt_005", "text": "zero score", "score": 0},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert kp["helpful"] >= 0


# @tests-invariant INV-SCORE-002 (TC-INV-002)
def test_inv_002_harmful_non_negative_all_paths(project_dir, playbook_path):
    """TC-INV-002: harmful >= 0 after all migration paths."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [
            "bare string",
            {"text": "no name no score"},
            {"name": "kpt_003", "text": "negative score", "score": -10},
            {"name": "kpt_004", "text": "positive score", "score": 7},
            {"name": "kpt_005", "text": "zero score", "score": 0},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert kp["harmful"] >= 0


# @tests-invariant INV-SCORE-003 (TC-INV-003)
def test_inv_003_zero_evaluation_never_pruned(project_dir):
    """TC-INV-003: Run pruning on playbook with only zero-eval entries."""
    playbook = _make_playbook([
        {"name": f"kpt_{i:03d}", "text": f"entry {i}", "helpful": 0, "harmful": 0}
        for i in range(1, 11)
    ])
    result = update_playbook_data(playbook, _make_extraction())
    assert len(result["sections"]["OTHERS"]) == 10


# @tests-invariant INV-SCORE-004 (TC-INV-004)
def test_inv_004_no_score_after_load_all_branches(project_dir, playbook_path):
    """TC-INV-004: No 'score' key after load across all migration branches."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "no score dict"},
            {"name": "kpt_003", "text": "has score", "score": -5},
            {"name": "kpt_004", "text": "canonical with score",
             "helpful": 1, "harmful": 0, "score": 3},
        ],
    })
    playbook = load_playbook()
    for kp in playbook["sections"]["OTHERS"]:
        assert "score" not in kp


# @tests-invariant INV-SCORE-004 (TC-INV-005)
def test_inv_005_no_score_after_save(project_dir, playbook_path):
    """TC-INV-005: No 'score' key in saved JSON file."""
    playbook = _make_playbook([
        {"name": "kpt_001", "text": "a", "helpful": 2, "harmful": 0},
    ])
    save_playbook(playbook)
    with open(playbook_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    for kp in saved["sections"]["OTHERS"]:
        assert "score" not in kp


# @tests REQ-SCORE-004 (generate_keypoint_name malformed names)
def test_generate_keypoint_name_malformed(project_dir):
    """generate_keypoint_name ignores entries not matching {slug}-NNN pattern."""
    # Section entries with various name formats; only oth-001 matches the slug pattern
    section_entries = [
        {"name": "kpt_abc", "text": "a", "helpful": 0, "harmful": 0},
        {"name": "kpt_", "text": "b", "helpful": 0, "harmful": 0},
        {"name": "oth-001", "text": "c", "helpful": 0, "harmful": 0},
    ]
    name = generate_keypoint_name(section_entries, "oth")
    assert name == "oth-002"  # should skip non-matching, use max from oth-001


# @tests REQ-SCORE-006 (canonical dict without name field)
def test_canonical_dict_without_name_generates_name(project_dir, playbook_path):
    """Canonical dict (has helpful/harmful) but missing 'name' gets generated name."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": None,
        "key_points": [
            {"text": "canonical but nameless", "helpful": 5, "harmful": 1},
        ],
    })
    playbook = load_playbook()
    kp = playbook["sections"]["OTHERS"][0]
    assert kp["name"].startswith("kpt_")
    assert kp["text"] == "canonical but nameless"
    assert kp["helpful"] == 5
    assert kp["harmful"] == 1


# @tests-invariant INV-SCORE-005 (TC-INV-006)
def test_inv_006_round_trip_stability(project_dir, playbook_path):
    """TC-INV-006: Load-save-load round trip produces identical key_points and version."""
    _write_playbook(playbook_path, {
        "version": "1.0", "last_updated": "2026-01-01T00:00:00",
        "key_points": [
            "bare string",
            {"name": "kpt_002", "text": "dict no score"},
            {"name": "kpt_003", "text": "has score", "score": -3},
            {"name": "kpt_004", "text": "canonical", "helpful": 1, "harmful": 0},
        ],
    })
    p1 = load_playbook()
    save_playbook(p1)
    p2 = load_playbook()

    assert json.dumps(p1["sections"], sort_keys=True) == json.dumps(p2["sections"], sort_keys=True)
    assert p1["version"] == p2["version"]
