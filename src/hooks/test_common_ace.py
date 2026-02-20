#!/usr/bin/env python3
# Spec: docs/reflector/spec.md, docs/dedup/spec.md, docs/curator/spec.md
# Contract: docs/curator/contract.md
# Testing: docs/testing.md
#
# White-box + contract tests for Phase 1 ACE implementation.
# All tests run without network, API keys, or ML model downloads.

import asyncio
import copy
import json
import math
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure common.py is importable from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common
from common import (
    extract_cited_ids,
    apply_bullet_tags,
    _extract_json_robust,
    run_deduplication,
    apply_structured_operations,
    prune_harmful,
    _apply_curator_operations,
    run_reflector,
    run_curator,
    extract_keypoints,
    update_playbook_data,
    SECTION_SLUGS,
    _default_playbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_playbook(sections_dict=None):
    """Create a well-formed playbook dict for testing."""
    pb = _default_playbook()
    if sections_dict:
        for sec_name, entries in sections_dict.items():
            pb["sections"][sec_name] = entries
    return pb


def _run_async(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_mock_response(text_content):
    """Create a mock Anthropic API response with given text content."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text_content
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    return mock_response


def _make_mock_numpy():
    """Create a minimal mock numpy module that supports array operations needed by dedup."""
    mock_np = MagicMock()

    class FakeArray:
        """Minimal numpy array replacement supporting @ (matmul) and indexing."""
        def __init__(self, data):
            if isinstance(data, FakeArray):
                self.data = data.data
            elif isinstance(data, list):
                self.data = data
            else:
                self.data = data

        def __matmul__(self, other):
            """Matrix multiply for cosine similarity computation."""
            # self is NxD, other should be DxN (transpose)
            rows_a = self.data
            rows_b = other.data
            n = len(rows_a)
            result = []
            for i in range(n):
                row = []
                for j in range(n):
                    dot = sum(a * b for a, b in zip(rows_a[i], rows_b[j]))
                    row.append(dot)
                result.append(row)
            return FakeArray(result)

        @property
        def T(self):
            """Transpose for NxD -> DxN, but for similarity we just return self."""
            # For normalized embeddings, sim = E @ E.T
            # Our embeddings are NxD. E.T should be DxN.
            # But since we compute row-by-row dot products, we just return self.
            return self

        def __getitem__(self, idx):
            return self.data[idx]

        def __len__(self):
            return len(self.data)

    def array_func(data):
        return FakeArray(data)

    mock_np.array = array_func
    return mock_np


def _make_embeddings_with_similarity(n, sim_pairs, dim=2):
    """Create embedding vectors (as lists) with specified pairwise cosine similarities.

    sim_pairs: list of (i, j, similarity) tuples.
    Returns list of lists (n x dim).
    Default: all pairs not in sim_pairs have similarity 0.
    """
    import math

    if n == 2 and len(sim_pairs) == 1:
        _, _, sim = sim_pairs[0]
        angle = math.acos(max(-1, min(1, sim)))
        e0 = [1.0, 0.0]
        e1 = [math.cos(angle), math.sin(angle)]
        return [e0, e1]

    if n == 3:
        # For 3 entries, use 3D vectors
        dim = 3
        a = [1.0, 0.0, 0.0]
        # Find pairs involving entry 0 and entry 1
        ab_sim = 0.0
        bc_sim = 0.0
        for i, j, s in sim_pairs:
            if (i, j) == (0, 1) or (i, j) == (1, 0):
                ab_sim = s
            if (i, j) == (1, 2) or (i, j) == (2, 1):
                bc_sim = s

        # b such that a.b = ab_sim
        angle_ab = math.acos(max(-1, min(1, ab_sim)))
        b = [math.cos(angle_ab), math.sin(angle_ab), 0.0]

        # c such that b.c = bc_sim and a.c < threshold (say < 0.85)
        # c = alpha*b + beta*perp
        # b.c = alpha*(b.b) = alpha*1 = alpha
        alpha = bc_sim
        beta = math.sqrt(max(0, 1 - alpha**2))
        # perp to b in z direction
        c = [alpha * b[0], alpha * b[1], beta]
        # normalize
        norm_c = math.sqrt(sum(x**2 for x in c))
        c = [x / norm_c for x in c]

        return [a, b, c]

    # Default: orthogonal vectors
    embeddings = []
    for i in range(n):
        vec = [0.0] * max(dim, n)
        vec[i] = 1.0
        embeddings.append(vec[:max(dim, n)])
    return embeddings


# ===========================================================================
# extract_cited_ids() tests
# ===========================================================================


class TestExtractCitedIds(unittest.TestCase):
    """White-box tests for extract_cited_ids()."""

    # @tests REQ-REFL-001, SCN-REFL-001-01
    def test_extract_cited_ids_assistant_only(self):
        """User messages are NOT scanned; only assistant messages yield IDs."""
        messages = [
            {"role": "user", "content": "Help me refactor this code"},
            {"role": "assistant", "content": "Based on [pat-001] and [mis-002], I recommend..."},
            {"role": "user", "content": "What about [pat-003]?"},
            {"role": "assistant", "content": "Good point. Also applying [pat-001] here..."},
        ]
        result = extract_cited_ids(messages)
        assert set(result) == {"pat-001", "mis-002"}
        # pat-003 from user is NOT included
        assert "pat-003" not in result

    # @tests REQ-REFL-001, SCN-REFL-001-02
    def test_extract_cited_ids_empty(self):
        """No citations in assistant messages returns empty list."""
        messages = [
            {"role": "user", "content": "Help me with this"},
            {"role": "assistant", "content": "Sure, here is the solution..."},
        ]
        result = extract_cited_ids(messages)
        assert result == []

    # @tests REQ-REFL-001, SCN-REFL-001-03
    def test_extract_cited_ids_legacy_ids(self):
        """Legacy kpt_NNN format is supported alongside modern slug-NNN format."""
        messages = [
            {"role": "assistant", "content": "Following [kpt_001] and [oth-003], I suggest..."},
        ]
        result = extract_cited_ids(messages)
        assert set(result) == {"kpt_001", "oth-003"}

    # @tests-invariant INV-REFL-001
    def test_extract_cited_ids_deduplication(self):
        """Duplicate IDs are deduplicated -- each appears at most once."""
        messages = [
            {"role": "assistant", "content": "[pat-001] is great. [pat-001] again. [pat-001]."},
        ]
        result = extract_cited_ids(messages)
        assert result == ["pat-001"]

    # @tests REQ-REFL-001
    def test_extract_cited_ids_all_slug_prefixes(self):
        """All five section slug prefixes are recognized."""
        messages = [
            {"role": "assistant", "content": "[pat-001] [mis-002] [pref-003] [ctx-004] [oth-005]"},
        ]
        result = extract_cited_ids(messages)
        assert set(result) == {"pat-001", "mis-002", "pref-003", "ctx-004", "oth-005"}

    # @tests REQ-REFL-001
    def test_extract_cited_ids_empty_messages_list(self):
        """Empty messages list returns empty list."""
        result = extract_cited_ids([])
        assert result == []

    # @tests REQ-REFL-001
    def test_extract_cited_ids_no_assistant_messages(self):
        """Messages with only user role returns empty list."""
        messages = [
            {"role": "user", "content": "[pat-001] some text"},
        ]
        result = extract_cited_ids(messages)
        assert result == []


# ===========================================================================
# apply_bullet_tags() tests
# ===========================================================================


class TestApplyBulletTags(unittest.TestCase):
    """White-box tests for apply_bullet_tags()."""

    # @tests REQ-REFL-007, SCN-REFL-006-01
    # @tests-invariant INV-REFL-003, INV-REFL-004
    def test_apply_bullet_tags_increments_counters(self):
        """Helpful and harmful tags increment the corresponding counters by 1."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "legacy tip", "helpful": 0, "harmful": 0},
            ],
        })
        bullet_tags = [
            {"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly"},
            {"name": "oth-001", "tag": "harmful", "rationale": "Led to wrong approach"},
        ]
        result = apply_bullet_tags(playbook, bullet_tags)
        assert result is playbook  # same reference, mutated in place
        pat = playbook["sections"]["PATTERNS & APPROACHES"][0]
        oth = playbook["sections"]["OTHERS"][0]
        assert pat["helpful"] == 4  # was 3, +1
        assert pat["harmful"] == 1  # unchanged
        assert oth["harmful"] == 1  # was 0, +1
        assert oth["helpful"] == 0  # unchanged

    # @tests REQ-REFL-007, SCN-REFL-006-02
    def test_apply_bullet_tags_neutral_no_change(self):
        """Neutral tag causes no counter changes."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
            ],
        })
        bullet_tags = [
            {"name": "pat-001", "tag": "neutral", "rationale": "Not relevant"},
        ]
        apply_bullet_tags(playbook, bullet_tags)
        pat = playbook["sections"]["PATTERNS & APPROACHES"][0]
        assert pat["helpful"] == 3
        assert pat["harmful"] == 1

    # @tests REQ-REFL-007, SCN-REFL-004-02
    def test_apply_bullet_tags_unmatched_name_skipped(self):
        """Tags for non-existent key points are skipped (no exception)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use types", "helpful": 3, "harmful": 1},
            ],
        })
        bullet_tags = [
            {"name": "pat-999", "tag": "helpful", "rationale": "Phantom entry"},
        ]
        # Should not raise
        apply_bullet_tags(playbook, bullet_tags)
        # pat-001 unchanged
        pat = playbook["sections"]["PATTERNS & APPROACHES"][0]
        assert pat["helpful"] == 3
        assert pat["harmful"] == 1

    # @tests REQ-REFL-007
    def test_apply_bullet_tags_all_sections(self):
        """Bullet tags lookup iterates ALL sections."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use types", "helpful": 0, "harmful": 0},
            ],
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "avoid any", "helpful": 0, "harmful": 0},
            ],
            "USER PREFERENCES": [
                {"name": "pref-001", "text": "dark mode", "helpful": 0, "harmful": 0},
            ],
            "PROJECT CONTEXT": [
                {"name": "ctx-001", "text": "python 3.12", "helpful": 0, "harmful": 0},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "misc", "helpful": 0, "harmful": 0},
            ],
        })
        bullet_tags = [
            {"name": "pat-001", "tag": "helpful", "rationale": "good"},
            {"name": "mis-001", "tag": "harmful", "rationale": "bad"},
            {"name": "pref-001", "tag": "neutral", "rationale": "n/a"},
            {"name": "ctx-001", "tag": "helpful", "rationale": "good"},
            {"name": "oth-001", "tag": "harmful", "rationale": "bad"},
        ]
        apply_bullet_tags(playbook, bullet_tags)
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 1
        assert playbook["sections"]["MISTAKES TO AVOID"][0]["harmful"] == 1
        assert playbook["sections"]["USER PREFERENCES"][0]["helpful"] == 0  # neutral
        assert playbook["sections"]["PROJECT CONTEXT"][0]["helpful"] == 1
        assert playbook["sections"]["OTHERS"][0]["harmful"] == 1

    # @tests REQ-REFL-007
    def test_apply_bullet_tags_unrecognized_tag_value_skipped(self):
        """Unrecognized tag values do not modify counters."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use types", "helpful": 2, "harmful": 1},
            ],
        })
        bullet_tags = [
            {"name": "pat-001", "tag": "unknown_value", "rationale": "weird"},
        ]
        apply_bullet_tags(playbook, bullet_tags)
        pat = playbook["sections"]["PATTERNS & APPROACHES"][0]
        assert pat["helpful"] == 2
        assert pat["harmful"] == 1


# ===========================================================================
# _extract_json_robust() tests
# ===========================================================================


class TestExtractJsonRobust(unittest.TestCase):
    """White-box tests for _extract_json_robust()."""

    # @tests REQ-REFL-008, REQ-CUR-016, SCN-REFL-008-02
    def test_extract_json_robust_code_fence_json(self):
        """Strategy 1: ```json fence extraction succeeds."""
        response = '```json\n{"analysis": "No observations.", "bullet_tags": []}\n```'
        result = _extract_json_robust(response)
        assert result is not None
        assert result["analysis"] == "No observations."
        assert result["bullet_tags"] == []

    # @tests REQ-REFL-008, REQ-CUR-016, SCN-REFL-008-01
    def test_extract_json_robust_balanced_brace(self):
        """Strategy 3: Balanced-brace counting extracts JSON from prose."""
        response = (
            "Here is my analysis of the session:\n\n"
            '{"analysis": "Good session.", "bullet_tags": [{"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly."}]}\n\n'
            "Let me know if you need more detail."
        )
        result = _extract_json_robust(response)
        assert result is not None
        assert result["analysis"] == "Good session."
        assert len(result["bullet_tags"]) == 1
        assert result["bullet_tags"][0]["name"] == "pat-001"

    # @tests REQ-REFL-008, REQ-CUR-016
    def test_extract_json_robust_raw_json(self):
        """Strategy 4: Raw json.loads() on full response."""
        response = '{"analysis": "Direct JSON.", "bullet_tags": []}'
        result = _extract_json_robust(response)
        assert result is not None
        assert result["analysis"] == "Direct JSON."

    # @tests REQ-REFL-008, REQ-CUR-016
    def test_extract_json_robust_all_fail_returns_none(self):
        """All strategies fail -> returns None."""
        response = "This is plain text with no JSON at all."
        result = _extract_json_robust(response)
        assert result is None

    # @tests REQ-REFL-008
    def test_extract_json_robust_code_fence_no_lang_tag(self):
        """Strategy 2: ``` fence (no json tag) extraction."""
        response = '```\n{"analysis": "No lang tag.", "bullet_tags": []}\n```'
        result = _extract_json_robust(response)
        assert result is not None
        assert result["analysis"] == "No lang tag."

    # @tests REQ-REFL-008
    def test_extract_json_robust_partial_keys_accepted(self):
        """Partial JSON (missing some keys) is accepted, not rejected."""
        response = '{"analysis": "only analysis"}'
        result = _extract_json_robust(response)
        assert result is not None
        assert result["analysis"] == "only analysis"
        # bullet_tags key absent -- callers use .get() with defaults

    # @tests REQ-REFL-008
    def test_extract_json_robust_malformed_json_in_fence_only(self):
        """Malformed JSON inside code fence with no valid fallback returns None."""
        # When the only JSON-like content is malformed inside a fence,
        # all 4 strategies fail.
        response = '```json\n{invalid json\n```'
        result = _extract_json_robust(response)
        assert result is None

    # @tests REQ-CUR-016
    def test_extract_json_robust_nested_braces(self):
        """Balanced-brace counting handles nested objects correctly."""
        response = (
            'Preamble: {"reasoning": "test", "operations": [{"type": "ADD", "text": "hello"}]} trailing text'
        )
        result = _extract_json_robust(response)
        assert result is not None
        assert result["reasoning"] == "test"
        assert len(result["operations"]) == 1

    # @tests REQ-REFL-008
    def test_extract_json_robust_json_with_escaped_quotes(self):
        """Balanced-brace handles strings with escaped quotes."""
        response = r'{"analysis": "He said \"hello\"", "bullet_tags": []}'
        result = _extract_json_robust(response)
        assert result is not None
        assert result["bullet_tags"] == []


# ===========================================================================
# run_deduplication() tests
# ===========================================================================


class TestRunDeduplication(unittest.TestCase):
    """White-box tests for run_deduplication()."""

    # @tests REQ-DEDUP-005, SCN-DEDUP-003-01
    # @tests-invariant INV-DEDUP-001
    def test_dedup_missing_deps_returns_unmodified(self):
        """When sentence-transformers is not importable, returns playbook unmodified."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "always use type hints", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "use type hints on all params", "helpful": 3, "harmful": 1},
            ],
        })
        original_id = id(playbook)
        with patch.dict("sys.modules", {"sentence_transformers": None, "numpy": None}):
            result = run_deduplication(playbook)
        assert result is playbook
        assert id(result) == original_id
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2

    # @tests INV-DEDUP-001, SCN-DEDUP-003-02
    def test_dedup_unexpected_exception_returns_unmodified(self):
        """RuntimeError during encode returns playbook unmodified."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "always use type hints", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "use type hints on all params", "helpful": 3, "harmful": 1},
            ],
        })
        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("model corrupted")
        mock_st_module.SentenceTransformer.return_value = mock_model

        mock_np = _make_mock_numpy()

        with patch.dict("sys.modules", {
            "sentence_transformers": mock_st_module,
            "numpy": mock_np,
        }):
            result = run_deduplication(playbook)

        assert result is playbook
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2

    # @tests REQ-DEDUP-006, SCN-DEDUP-005-01
    def test_dedup_empty_playbook_no_op(self):
        """Empty playbook returns unmodified."""
        playbook = _make_playbook()
        result = run_deduplication(playbook)
        assert result is playbook

    # @tests REQ-DEDUP-006, SCN-DEDUP-005-02
    def test_dedup_single_entry_no_op(self):
        """Single entry playbook returns unmodified."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "only entry", "helpful": 1, "harmful": 0},
            ],
        })
        result = run_deduplication(playbook)
        assert result is playbook

    # @tests REQ-DEDUP-004, SCN-DEDUP-004-01
    def test_dedup_threshold_from_env_var(self):
        """AGENTIC_CONTEXT_DEDUP_THRESHOLD env var overrides default."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "prefer composition", "helpful": 3, "harmful": 0},
            ],
        })

        # Embeddings with similarity ~0.87 (above 0.85, below 0.90)
        embeddings = _make_embeddings_with_similarity(2, [(0, 1, 0.87)])
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch.dict(os.environ, {"AGENTIC_CONTEXT_DEDUP_THRESHOLD": "0.90"}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook)

        # Both entries should remain (0.87 < 0.90 threshold)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2

    # @tests REQ-DEDUP-004
    def test_dedup_threshold_clamping(self):
        """Threshold values outside [0,1] are clamped."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
            ],
        })

        # Orthogonal embeddings -> sim = 0
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            # threshold > 1.0 should be clamped to 1.0 -- nothing merges
            result = run_deduplication(playbook, threshold=2.0)

        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 2

        # threshold < 0.0 should be clamped to 0.0 -- identical vectors merge
        embeddings2 = [[1.0, 0.0], [1.0, 0.0]]
        mock_model.encode.return_value = embeddings2

        playbook2 = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 2, "harmful": 1},
            ],
        })

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result2 = run_deduplication(playbook2, threshold=-1.0)

        assert len(result2["sections"]["PATTERNS & APPROACHES"]) == 1

    # @tests REQ-DEDUP-001, REQ-DEDUP-002, SCN-DEDUP-001-01
    def test_dedup_first_entry_wins(self):
        """First entry in iteration order is the survivor; text preserved."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "always use type hints for function parameters", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "use type hints on all function parameters", "helpful": 3, "harmful": 1},
            ],
        })

        # Identical embeddings -> sim = 1.0 >= 0.85
        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["name"] == "pat-001"
        assert entries[0]["text"] == "always use type hints for function parameters"
        assert entries[0]["helpful"] == 8  # 5 + 3
        assert entries[0]["harmful"] == 1  # 0 + 1

    # @tests REQ-DEDUP-002, SCN-DEDUP-006-01
    # @tests-invariant INV-DEDUP-002
    def test_dedup_counter_summing(self):
        """Merged entry's counters are the sum of all group members."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "always add type hints", "helpful": 10, "harmful": 2},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "remember to add type hints always", "helpful": 3, "harmful": 0},
            ],
        })

        # Identical embeddings -> sim = 1.0 >= 0.85
        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        pat_entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(pat_entries) == 1
        assert pat_entries[0]["name"] == "pat-001"
        assert pat_entries[0]["helpful"] == 13  # 10 + 3
        assert pat_entries[0]["harmful"] == 2  # 2 + 0
        assert len(result["sections"]["OTHERS"]) == 0

    # @tests REQ-DEDUP-001, SCN-DEDUP-001-02
    def test_dedup_cross_section_merge(self):
        """Cross-section duplicates are merged; survivor stays in its original section."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "avoid using the any type", "helpful": 4, "harmful": 0},
            ],
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "don't use any type in TypeScript", "helpful": 2, "harmful": 1},
            ],
        })

        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1
        assert len(result["sections"]["MISTAKES TO AVOID"]) == 0
        survivor = result["sections"]["PATTERNS & APPROACHES"][0]
        assert survivor["name"] == "pat-001"
        assert survivor["helpful"] == 6  # 4 + 2
        assert survivor["harmful"] == 1  # 0 + 1

    # @tests REQ-DEDUP-003, SCN-DEDUP-002-01
    # @tests-invariant INV-DEDUP-004
    def test_dedup_transitive_grouping(self):
        """Transitive duplicates are all merged (A-B, B-C connected -> A survives)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 2, "harmful": 0},
                {"name": "pat-003", "text": "C", "helpful": 3, "harmful": 0},
            ],
        })

        # Build 3D embeddings: A-B=0.90, B-C=0.88, A-C<0.85
        embeddings = _make_embeddings_with_similarity(3, [(0, 1, 0.90), (1, 2, 0.88)])
        mock_np = _make_mock_numpy()

        # Verify A-C < 0.85
        ac_sim = sum(a * c for a, c in zip(embeddings[0], embeddings[2]))
        assert ac_sim < 0.85, f"A-C similarity is {ac_sim}, expected < 0.85"

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["name"] == "pat-001"
        assert entries[0]["helpful"] == 6  # 1+2+3
        assert entries[0]["harmful"] == 0

    # @tests REQ-DEDUP-001, SCN-DEDUP-001-03
    def test_dedup_no_merge_below_threshold(self):
        """Entries with similarity below threshold are NOT merged."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "prefer composition over inheritance", "helpful": 3, "harmful": 0},
            ],
        })

        # Orthogonal embeddings -> sim = 0
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 2
        assert entries[0]["helpful"] == 5
        assert entries[1]["helpful"] == 3

    # @tests REQ-DEDUP-001, REQ-DEDUP-002, SCN-DEDUP-002-02
    def test_dedup_multiple_independent_groups(self):
        """Multiple independent duplicate groups are each merged independently."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "group A first", "helpful": 1, "harmful": 0},
                {"name": "pat-002", "text": "group A second", "helpful": 2, "harmful": 0},
                {"name": "pat-003", "text": "group B first", "helpful": 3, "harmful": 0},
                {"name": "pat-004", "text": "group B second", "helpful": 4, "harmful": 0},
            ],
        })

        # 4D embeddings: entries 0+1 identical (sim=1.0), entries 2+3 identical (sim=1.0),
        # but groups are orthogonal (sim=0)
        embeddings = [[1, 0, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 1, 0, 0]]
        mock_np = _make_mock_numpy()

        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 2  # one survivor from each group
        names = {e["name"] for e in entries}
        assert "pat-001" in names  # survivor of group A
        assert "pat-003" in names  # survivor of group B
        # Verify counter summing
        for e in entries:
            if e["name"] == "pat-001":
                assert e["helpful"] == 3  # 1 + 2
            elif e["name"] == "pat-003":
                assert e["helpful"] == 7  # 3 + 4

    # @tests-invariant INV-DEDUP-003
    def test_dedup_section_names_remain_canonical(self):
        """After dedup with cross-section merge, section names are still canonical."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "avoid using any", "helpful": 4, "harmful": 0},
            ],
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "don't use any type", "helpful": 2, "harmful": 1},
            ],
        })

        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        mock_np = _make_mock_numpy()
        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        for sec_name in result["sections"]:
            assert sec_name in SECTION_SLUGS, f"Non-canonical section: {sec_name}"

    # @tests-invariant INV-DEDUP-005
    def test_dedup_top_level_structure_preserved(self):
        """After dedup that merges entries, result has version, last_updated, sections."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 2, "harmful": 0},
            ],
        })

        embeddings = [[1.0, 0.0], [1.0, 0.0]]
        mock_np = _make_mock_numpy()
        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}), \
             patch("common.is_diagnostic_mode", return_value=False):
            result = run_deduplication(playbook, threshold=0.85)

        assert "version" in result
        assert "last_updated" in result
        assert "sections" in result


# ===========================================================================
# apply_structured_operations() tests
# ===========================================================================


class TestApplyStructuredOperations(unittest.TestCase):
    """White-box tests for apply_structured_operations()."""

    # @tests REQ-CUR-014, SCN-CUR-014-04
    def test_apply_ops_empty_returns_same_reference(self):
        """Empty operations list returns the SAME reference (no deep copy)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 5, "harmful": 1},
            ],
        })
        result = apply_structured_operations(playbook, [])
        assert result is playbook

    # @tests REQ-CUR-014, SCN-CUR-014-01
    # @tests-invariant INV-CUR-010
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_apply_ops_deep_copy_isolation(self, _mock_diag):
        """Original playbook is NOT mutated when operations are applied."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 5, "harmful": 1},
            ],
        })
        original_entries = copy.deepcopy(playbook["sections"]["PATTERNS & APPROACHES"])

        operations = [{"type": "ADD", "text": "new insight", "section": "OTHERS"}]
        result = apply_structured_operations(playbook, operations)

        assert result is not playbook
        assert playbook["sections"]["PATTERNS & APPROACHES"] == original_entries
        assert len(playbook["sections"]["OTHERS"]) == 0
        assert len(result["sections"]["OTHERS"]) == 1

    # @tests REQ-CUR-014, SCN-CUR-014-02
    # @tests-invariant INV-CUR-001
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_apply_ops_rollback_on_exception(self, _mock_diag):
        """On exception, original playbook is returned unchanged."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 5, "harmful": 1},
            ],
        })

        operations = [{"type": "ADD", "text": "will trigger exception"}]

        with patch("common._apply_curator_operations", side_effect=RuntimeError("injected failure")):
            result = apply_structured_operations(playbook, operations)

        assert result is playbook
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 5

    # @tests REQ-CUR-014, REQ-CUR-013, SCN-CUR-014-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_apply_ops_supports_update(self, _mock_diag):
        """UPDATE operation revises text and preserves counters."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "old text", "helpful": 3, "harmful": 0},
            ],
        })
        operations = [{"type": "UPDATE", "target_id": "pat-001", "text": "revised text"}]
        result = apply_structured_operations(playbook, operations)

        updated = result["sections"]["PATTERNS & APPROACHES"][0]
        assert updated["text"] == "revised text"
        assert updated["name"] == "pat-001"
        assert updated["helpful"] == 3
        assert updated["harmful"] == 0
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["text"] == "old text"


# ===========================================================================
# prune_harmful() tests
# ===========================================================================


class TestPruneHarmful(unittest.TestCase):
    """White-box tests for prune_harmful()."""

    # @tests REQ-CUR-015, SCN-CUR-015-01
    # @tests-invariant INV-CUR-011
    def test_prune_harmful_removes_above_threshold(self):
        """Entries with harmful >= 3 AND harmful > helpful are pruned."""
        playbook = _make_playbook({
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "bad advice", "helpful": 1, "harmful": 4},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "good tip", "helpful": 5, "harmful": 0},
            ],
        })
        result = prune_harmful(playbook)
        assert result is playbook
        assert len(result["sections"]["MISTAKES TO AVOID"]) == 0
        assert len(result["sections"]["OTHERS"]) == 1

    # @tests REQ-CUR-015, SCN-CUR-015-02
    def test_prune_harmful_preserves_zero_eval(self):
        """Zero-evaluation entries (helpful=0, harmful=0) are never pruned."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "new entry", "helpful": 0, "harmful": 0},
            ],
        })
        result = prune_harmful(playbook)
        assert len(result["sections"]["OTHERS"]) == 1

    # @tests REQ-CUR-015, SCN-CUR-015-03
    # @tests-invariant INV-CUR-011
    def test_prune_harmful_equal_counters_not_pruned(self):
        """Equal harmful and helpful counters: NOT pruned (harmful > helpful is FALSE)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "controversial", "helpful": 3, "harmful": 3},
            ],
        })
        result = prune_harmful(playbook)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1

    # @tests REQ-CUR-015
    def test_prune_harmful_harmful_below_3_not_pruned(self):
        """Harmful < 3 even if harmful > helpful: NOT pruned (first condition fails)."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "slightly bad", "helpful": 0, "harmful": 2},
            ],
        })
        result = prune_harmful(playbook)
        assert len(result["sections"]["OTHERS"]) == 1

    # @tests REQ-CUR-015
    def test_prune_harmful_multiple_sections(self):
        """Pruning iterates all sections."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "bad", "helpful": 0, "harmful": 5},
            ],
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "also bad", "helpful": 1, "harmful": 4},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "good", "helpful": 10, "harmful": 0},
            ],
        })
        result = prune_harmful(playbook)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 0
        assert len(result["sections"]["MISTAKES TO AVOID"]) == 0
        assert len(result["sections"]["OTHERS"]) == 1


# ===========================================================================
# _apply_curator_operations() -- UPDATE operation tests
# ===========================================================================


class TestApplyCuratorOperationsUpdate(unittest.TestCase):
    """White-box tests for UPDATE operation in _apply_curator_operations()."""

    # @tests REQ-CUR-013, SCN-CUR-013-01
    # @tests-invariant INV-CUR-007
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_revises_text_preserves_counters(self, _mock_diag):
        """UPDATE changes text but preserves name, helpful, harmful, and section."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "UPDATE", "target_id": "pat-001", "text": "use type hints for all function parameters and return values"}]
        result = _apply_curator_operations(pb_copy, operations)

        entry = result["sections"]["PATTERNS & APPROACHES"][0]
        assert entry["text"] == "use type hints for all function parameters and return values"
        assert entry["name"] == "pat-001"
        assert entry["helpful"] == 5
        assert entry["harmful"] == 1

    # @tests REQ-CUR-013, SCN-CUR-013-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_skips_nonexistent_target_id(self, _mock_diag):
        """UPDATE with non-existent target_id is skipped; no exception."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "UPDATE", "target_id": "pat-999", "text": "new text"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "use type hints"

    # @tests REQ-CUR-013, SCN-CUR-013-03
    # @tests-invariant INV-CUR-009
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_skips_empty_target_id(self, _mock_diag):
        """UPDATE with empty target_id is skipped (validation failure)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "UPDATE", "target_id": "", "text": "new text"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "use type hints"

    # @tests REQ-CUR-013, SCN-CUR-013-04
    # @tests-invariant INV-CUR-009
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_skips_empty_text(self, _mock_diag):
        """UPDATE with empty text is skipped; entry retains original text."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "UPDATE", "target_id": "pat-001", "text": ""}]
        result = _apply_curator_operations(pb_copy, operations)
        assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "use type hints"


# ===========================================================================
# run_reflector() error handling tests
# ===========================================================================


class TestRunReflector(unittest.TestCase):
    """White-box tests for run_reflector() error handling."""

    def _setup_anthropic_mock(self):
        """Ensure common.anthropic attribute exists for patching."""
        if not hasattr(common, 'anthropic'):
            common.anthropic = MagicMock()
            self._created_anthropic = True
        else:
            self._created_anthropic = False

    def _teardown_anthropic_mock(self):
        """Remove mock anthropic attribute if we created it."""
        if getattr(self, '_created_anthropic', False):
            delattr(common, 'anthropic')

    # @tests REQ-REFL-006, SCN-REFL-005-01
    # @tests-invariant INV-REFL-002
    def test_run_reflector_returns_empty_on_api_failure(self):
        """API failure returns empty result without raising."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            messages = [{"role": "user", "content": "test"}]

            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("connection failed")

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{transcript}\n{playbook}\n{cited_ids}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch("time.sleep"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_reflector(messages, playbook, []))

            assert result == {"analysis": "", "bullet_tags": []}
        finally:
            self._teardown_anthropic_mock()

    # @tests REQ-REFL-006, SCN-REFL-005-02
    # @tests-invariant INV-REFL-002
    def test_run_reflector_returns_empty_on_json_parse_failure(self):
        """Unparseable JSON response returns empty result."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            messages = [{"role": "user", "content": "test"}]

            mock_response = _make_mock_response("This is not JSON at all, just text.")
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{transcript}\n{playbook}\n{cited_ids}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_reflector(messages, playbook, []))

            assert result == {"analysis": "", "bullet_tags": []}
        finally:
            self._teardown_anthropic_mock()

    # @tests REQ-REFL-006
    # @tests-invariant INV-REFL-002
    @patch.object(common, 'ANTHROPIC_AVAILABLE', False)
    def test_run_reflector_returns_empty_when_anthropic_unavailable(self):
        """When anthropic is not available, returns empty result."""
        playbook = _make_playbook()
        messages = [{"role": "user", "content": "test"}]
        result = _run_async(run_reflector(messages, playbook, []))
        assert result == {"analysis": "", "bullet_tags": []}

    # @tests REQ-REFL-003, REQ-REFL-004, REQ-REFL-005
    def test_run_reflector_parses_valid_response(self):
        """Valid JSON response is parsed and returned correctly."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            messages = [{"role": "user", "content": "test"}]

            response_json = json.dumps({
                "analysis": "Good session.",
                "bullet_tags": [{"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly."}]
            })
            mock_response = _make_mock_response(response_json)
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{transcript}\n{playbook}\n{cited_ids}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_reflector(messages, playbook, []))

            assert result["analysis"] == "Good session."
            assert len(result["bullet_tags"]) == 1
            assert result["bullet_tags"][0]["name"] == "pat-001"
        finally:
            self._teardown_anthropic_mock()


# ===========================================================================
# run_curator() error handling tests
# ===========================================================================


class TestRunCurator(unittest.TestCase):
    """White-box tests for run_curator() error handling."""

    def _setup_anthropic_mock(self):
        """Ensure common.anthropic attribute exists for patching."""
        if not hasattr(common, 'anthropic'):
            common.anthropic = MagicMock()
            self._created_anthropic = True
        else:
            self._created_anthropic = False

    def _teardown_anthropic_mock(self):
        """Remove mock anthropic attribute if we created it."""
        if getattr(self, '_created_anthropic', False):
            delattr(common, 'anthropic')

    # @tests REQ-CUR-012, SCN-CUR-010-02
    # @tests-invariant INV-CUR-008
    def test_run_curator_returns_empty_on_api_failure(self):
        """API failure returns empty result without raising."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            reflector_output = {"analysis": "test", "bullet_tags": []}

            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("connection failed")

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{reflector_output}\n{playbook}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch("time.sleep"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_curator(reflector_output, playbook))

            assert result == {"reasoning": "", "operations": []}
        finally:
            self._teardown_anthropic_mock()

    # @tests REQ-CUR-012, SCN-CUR-012-01
    # @tests-invariant INV-CUR-008
    def test_run_curator_returns_empty_on_json_parse_failure(self):
        """Unparseable JSON response returns empty result."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            reflector_output = {"analysis": "test", "bullet_tags": []}

            mock_response = _make_mock_response("Not valid JSON at all, random text output.")
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{reflector_output}\n{playbook}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_curator(reflector_output, playbook))

            assert result == {"reasoning": "", "operations": []}
        finally:
            self._teardown_anthropic_mock()

    # @tests REQ-CUR-012
    # @tests-invariant INV-CUR-008
    @patch.object(common, 'ANTHROPIC_AVAILABLE', False)
    def test_run_curator_returns_empty_when_anthropic_unavailable(self):
        """When anthropic is not available, returns empty result."""
        playbook = _make_playbook()
        reflector_output = {"analysis": "", "bullet_tags": []}
        result = _run_async(run_curator(reflector_output, playbook))
        assert result == {"reasoning": "", "operations": []}

    # @tests REQ-CUR-010, REQ-CUR-011
    def test_run_curator_parses_valid_response(self):
        """Valid JSON response is parsed and returned correctly."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            reflector_output = {"analysis": "test analysis", "bullet_tags": []}

            response_json = json.dumps({
                "reasoning": "Curator reasoning.",
                "operations": [{"type": "ADD", "text": "new insight", "section": "OTHERS"}]
            })
            mock_response = _make_mock_response(response_json)
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{reflector_output}\n{playbook}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_curator(reflector_output, playbook))

            assert result["reasoning"] == "Curator reasoning."
            assert len(result["operations"]) == 1
            assert result["operations"][0]["type"] == "ADD"
        finally:
            self._teardown_anthropic_mock()


# ===========================================================================
# Backward compatibility tests (QG-ACE-001)
# ===========================================================================


class TestBackwardCompatibility(unittest.TestCase):
    """Verify existing function signatures are unchanged."""

    # @tests QG-ACE-001
    def test_backward_compat_extract_keypoints_signature(self):
        """extract_keypoints() signature accepts (messages, playbook, diagnostic_name)."""
        import inspect
        sig = inspect.signature(extract_keypoints)
        params = list(sig.parameters.keys())
        assert "messages" in params
        assert "playbook" in params
        assert "diagnostic_name" in params

    # @tests QG-ACE-001
    def test_backward_compat_update_playbook_data_signature(self):
        """update_playbook_data() signature accepts (playbook, extraction_result)."""
        import inspect
        sig = inspect.signature(update_playbook_data)
        params = list(sig.parameters.keys())
        assert "playbook" in params
        assert "extraction_result" in params

    # @tests QG-ACE-001
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_backward_compat_update_playbook_data_basic_call(self, _mock_diag):
        """Basic call to update_playbook_data with old-format extraction result works."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "existing", "helpful": 0, "harmful": 0},
            ],
        })
        extraction_result = {
            "new_key_points": ["a new point"],
            "evaluations": [],
        }
        result = update_playbook_data(playbook, extraction_result)
        assert len(result["sections"]["OTHERS"]) == 2
        assert result["sections"]["OTHERS"][1]["text"] == "a new point"


# ===========================================================================
# Contract-style tests -- testing public API from contract.md only
# ===========================================================================


class TestContractExtractCitedIds(unittest.TestCase):
    """Contract tests for extract_cited_ids() -- public API behavior only."""

    # @tests-contract REQ-REFL-001
    def test_contract_extract_cited_ids_returns_list(self):
        """Contract: returns a list of strings."""
        messages = [
            {"role": "assistant", "content": "See [pat-001] for details."},
        ]
        result = extract_cited_ids(messages)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    # @tests-contract REQ-REFL-001
    def test_contract_extract_cited_ids_no_duplicates(self):
        """Contract: returned IDs are deduplicated."""
        messages = [
            {"role": "assistant", "content": "[pat-001] and [pat-001] again."},
        ]
        result = extract_cited_ids(messages)
        assert len(result) == len(set(result))


class TestContractApplyBulletTags(unittest.TestCase):
    """Contract tests for apply_bullet_tags()."""

    # @tests-contract REQ-REFL-007
    def test_contract_apply_bullet_tags_returns_playbook(self):
        """Contract: returns the playbook dict."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "test", "helpful": 0, "harmful": 0},
            ],
        })
        result = apply_bullet_tags(playbook, [])
        assert isinstance(result, dict)
        assert "sections" in result


class TestContractApplyStructuredOperations(unittest.TestCase):
    """Contract tests for apply_structured_operations()."""

    # @tests-contract REQ-CUR-014
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_contract_apply_ops_returns_dict_with_sections(self, _mock_diag):
        """Contract: returns a dict with 'sections' key."""
        playbook = _make_playbook()
        result = apply_structured_operations(playbook, [])
        assert isinstance(result, dict)
        assert "sections" in result

    # @tests-contract REQ-CUR-014
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_contract_apply_ops_add_creates_entry(self, _mock_diag):
        """Contract: ADD operation creates an entry in the target section."""
        playbook = _make_playbook()
        ops = [{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}]
        result = apply_structured_operations(playbook, ops)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1
        entry = result["sections"]["PATTERNS & APPROACHES"][0]
        assert entry["text"] == "new insight"
        assert entry["helpful"] == 0
        assert entry["harmful"] == 0


class TestContractPruneHarmful(unittest.TestCase):
    """Contract tests for prune_harmful()."""

    # @tests-contract REQ-CUR-015
    def test_contract_prune_harmful_returns_playbook(self):
        """Contract: returns a dict with 'sections' key."""
        playbook = _make_playbook()
        result = prune_harmful(playbook)
        assert isinstance(result, dict)
        assert "sections" in result

    # @tests-contract REQ-CUR-015
    def test_contract_prune_harmful_removes_high_harmful(self):
        """Contract: entries meeting threshold are removed."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "bad", "helpful": 0, "harmful": 5},
                {"name": "oth-002", "text": "good", "helpful": 10, "harmful": 0},
            ],
        })
        result = prune_harmful(playbook)
        names = [e["name"] for e in result["sections"]["OTHERS"]]
        assert "oth-001" not in names
        assert "oth-002" in names


class TestExtractJsonRobustAdditional(unittest.TestCase):
    """Additional white-box tests for _extract_json_robust()."""

    # @tests REQ-REFL-008, REQ-CUR-016
    def test_extract_json_returns_dict_or_none(self):
        """Returns a parsed dict or None."""
        result_good = _extract_json_robust('{"key": "value"}')
        assert isinstance(result_good, dict)

        result_bad = _extract_json_robust("no json here")
        assert result_bad is None


class TestContractRunDeduplication(unittest.TestCase):
    """Contract tests for run_deduplication()."""

    # @tests-contract REQ-DEDUP-005
    def test_contract_dedup_returns_playbook_dict(self):
        """Contract: always returns a dict with 'sections' key."""
        playbook = _make_playbook()
        result = run_deduplication(playbook)
        assert isinstance(result, dict)
        assert "sections" in result

    # @tests-contract REQ-DEDUP-006
    def test_contract_dedup_empty_playbook_unchanged(self):
        """Contract: empty playbook is returned unmodified."""
        playbook = _make_playbook()
        result = run_deduplication(playbook)
        assert result is playbook


# ===========================================================================
# Additional white-box tests for _apply_curator_operations
# ===========================================================================


class TestApplyCuratorOperationsAdditional(unittest.TestCase):
    """Additional white-box tests covering more curator operation scenarios."""

    # @tests REQ-CUR-009
    # @tests-invariant INV-CUR-005
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_operations_truncated_to_10(self, _mock_diag):
        """Operations list longer than 10 is truncated to first 10."""
        playbook = _make_playbook()
        operations = [
            {"type": "ADD", "text": f"unique text number {i}", "section": "OTHERS"}
            for i in range(15)
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["OTHERS"]) == 10

    # @tests REQ-CUR-009
    # @tests-invariant INV-CUR-002
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_unknown_operation_type_skipped(self, _mock_diag):
        """Unknown operation type is skipped; no exception raised."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [
            {"type": "REPLACE", "target_id": "pat-001", "text": "rewritten"},
            {"type": "ADD", "text": "good add", "section": "OTHERS"},
        ]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["OTHERS"]) == 1
        assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "A"

    # @tests REQ-CUR-004, SCN-CUR-004-01
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_delete_removes_entry(self, _mock_diag):
        """DELETE operation removes the entry from its section."""
        playbook = _make_playbook({
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "bad advice", "helpful": 0, "harmful": 2},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "DELETE", "target_id": "mis-001", "reason": "contradicts standards"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["MISTAKES TO AVOID"]) == 0

    # @tests REQ-CUR-002, SCN-CUR-002-01
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_add_creates_entry_with_correct_schema(self, _mock_diag):
        """ADD creates entry with name, text, helpful=0, harmful=0."""
        playbook = _make_playbook()
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "ADD", "text": "prefer composition", "section": "PATTERNS & APPROACHES"}]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["text"] == "prefer composition"
        assert entry["helpful"] == 0
        assert entry["harmful"] == 0
        assert entry["name"].startswith("pat-")

    # @tests REQ-CUR-002, SCN-CUR-002-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_add_skips_duplicate_text(self, _mock_diag):
        """ADD with text that already exists across sections is skipped."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "prefer pathlib", "helpful": 2, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "ADD", "text": "prefer pathlib", "section": "PATTERNS & APPROACHES"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 0
        assert len(result["sections"]["OTHERS"]) == 1

    # @tests REQ-CUR-003, SCN-CUR-003-01
    # @tests-invariant INV-CUR-003
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_combines_entries(self, _mock_diag):
        """MERGE removes sources and creates merged entry with summed counters."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
                {"name": "pat-003", "text": "annotate return types", "helpful": 3, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-003"],
            "merged_text": "use complete type annotations",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        merged = entries[0]
        assert merged["text"] == "use complete type annotations"
        assert merged["helpful"] == 8
        assert merged["harmful"] == 1

    # --- F8: MERGE additional scenarios ---

    # @tests REQ-CUR-003, SCN-CUR-003-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_with_explicit_section_override(self, _mock_diag):
        """MERGE with explicit section places merged entry there."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "hint A", "helpful": 2, "harmful": 0},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "hint B", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-001", "oth-001"],
            "merged_text": "combined hint",
            "section": "PATTERNS & APPROACHES",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        pat_entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(pat_entries) == 1
        assert pat_entries[0]["text"] == "combined hint"
        assert pat_entries[0]["helpful"] == 3  # 2 + 1
        assert len(result["sections"]["OTHERS"]) == 0

    # @tests REQ-CUR-003, SCN-CUR-003-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_with_nonexistent_source_ids_filtered(self, _mock_diag):
        """MERGE filters out non-existent source IDs; proceeds if 2+ valid remain."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-002", "pat-999"],
            "merged_text": "combined",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["text"] == "combined"
        assert entries[0]["helpful"] == 3  # 2 + 1

    # @tests REQ-CUR-003, SCN-CUR-003-04
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_skipped_when_fewer_than_2_valid_source_ids(self, _mock_diag):
        """MERGE skipped when only 1 valid source ID remains after filtering."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-001", "pat-999"],
            "merged_text": "combined",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["name"] == "pat-001"  # NOT removed

    # @tests REQ-CUR-003, REQ-CUR-009, SCN-CUR-003-05
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_skipped_when_source_ids_has_fewer_than_2_entries(self, _mock_diag):
        """MERGE skipped when source_ids has only 1 entry (validation failure)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-001"],
            "merged_text": "rewritten",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["name"] == "pat-001"

    # @tests REQ-CUR-003, SCN-CUR-003-06
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_inherits_section_from_first_valid_source_id(self, _mock_diag):
        """MERGE with no section field inherits section from first valid source."""
        playbook = _make_playbook({
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "avoid globals", "helpful": 3, "harmful": 0},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "no bare except", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["mis-001", "oth-001"],
            "merged_text": "combined advice",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        mis_entries = result["sections"]["MISTAKES TO AVOID"]
        assert len(mis_entries) == 1
        assert mis_entries[0]["text"] == "combined advice"
        assert mis_entries[0]["name"].startswith("mis-")
        assert len(result["sections"]["OTHERS"]) == 0

    # @tests REQ-CUR-003, REQ-CUR-005, SCN-CUR-003-07
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_where_first_source_deleted_by_prior_op(self, _mock_diag):
        """MERGE where first source_id was deleted by a prior DELETE op."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 2, "harmful": 0},
                {"name": "pat-002", "text": "B", "helpful": 1, "harmful": 0},
                {"name": "pat-003", "text": "C", "helpful": 3, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [
            {"type": "DELETE", "target_id": "pat-001", "reason": "obsolete"},
            {"type": "MERGE", "source_ids": ["pat-001", "pat-002", "pat-003"], "merged_text": "combined"},
        ]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["text"] == "combined"
        # pat-001 deleted, so merge uses pat-002 section; counters: 1+3=4
        assert entries[0]["helpful"] == 4

    # @tests REQ-CUR-003, SCN-CUR-003-08
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_merge_skipped_when_all_source_ids_nonexistent(self, _mock_diag):
        """MERGE skipped when all source_ids are nonexistent."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 5, "harmful": 1},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{
            "type": "MERGE",
            "source_ids": ["pat-999", "pat-888"],
            "merged_text": "combined",
        }]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["PATTERNS & APPROACHES"]
        assert len(entries) == 1
        assert entries[0]["name"] == "pat-001"
        assert entries[0]["text"] == "use type hints"

    # --- F8: DELETE additional scenarios ---

    # @tests REQ-CUR-004, SCN-CUR-004-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_delete_skips_nonexistent_target_id(self, _mock_diag):
        """DELETE with nonexistent target_id is skipped; no exception."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1

    # @tests REQ-CUR-004, REQ-CUR-009, SCN-CUR-004-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_delete_skips_empty_target_id(self, _mock_diag):
        """DELETE with empty target_id is skipped (validation failure)."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 1, "harmful": 0},
            ],
        })
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "DELETE", "target_id": "", "reason": "cleanup"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["PATTERNS & APPROACHES"]) == 1

    # --- F8: ADD additional scenarios ---

    # @tests REQ-CUR-002, SCN-CUR-002-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_add_defaults_to_others_when_section_missing(self, _mock_diag):
        """ADD with no section field defaults to OTHERS."""
        playbook = _make_playbook()
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "ADD", "text": "some insight"}]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["OTHERS"]
        assert len(entries) == 1
        assert entries[0]["text"] == "some insight"
        assert entries[0]["name"].startswith("oth-")

    # @tests REQ-CUR-002, REQ-CUR-009, SCN-CUR-002-04
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_add_skips_empty_text(self, _mock_diag):
        """ADD with empty text is skipped."""
        playbook = _make_playbook()
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "ADD", "text": "", "section": "OTHERS"}]
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["OTHERS"]) == 0

    # @tests REQ-CUR-002, SCN-CUR-002-05
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_add_resolves_section_case_insensitively(self, _mock_diag):
        """ADD with lowercase section resolves to canonical name."""
        playbook = _make_playbook()
        pb_copy = copy.deepcopy(playbook)
        operations = [{"type": "ADD", "text": "new tip", "section": "mistakes to avoid"}]
        result = _apply_curator_operations(pb_copy, operations)
        entries = result["sections"]["MISTAKES TO AVOID"]
        assert len(entries) == 1
        assert entries[0]["text"] == "new tip"
        assert entries[0]["name"].startswith("mis-")

    # --- F8: Truncation boundary tests ---

    # @tests REQ-CUR-009, SCN-CUR-009-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_exactly_10_operations_no_truncation(self, _mock_diag):
        """Exactly 10 operations: all processed, no truncation."""
        playbook = _make_playbook()
        operations = [
            {"type": "ADD", "text": f"distinct text {i}", "section": "OTHERS"}
            for i in range(10)
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["OTHERS"]) == 10

    # @tests REQ-CUR-009, SCN-CUR-009-04
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_exactly_11_operations_truncated_to_10(self, _mock_diag):
        """Exactly 11 operations: truncated to 10."""
        playbook = _make_playbook()
        operations = [
            {"type": "ADD", "text": f"distinct text {i}", "section": "OTHERS"}
            for i in range(11)
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        assert len(result["sections"]["OTHERS"]) == 10


# ===========================================================================
# F1: REQ-REFL-002 -- playbook.txt citation directive tests
# ===========================================================================


class TestPlaybookCitationDirective(unittest.TestCase):
    """White-box tests for the citation directive in playbook.txt."""

    @staticmethod
    def _load_src_template(name):
        """Load template from src/prompts/ directory (canonical source)."""
        src_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent / "prompts"
        with open(src_dir / name, "r", encoding="utf-8") as f:
            return f.read()

    # @tests REQ-REFL-002, SCN-REFL-002-01
    def test_playbook_txt_contains_citation_directive(self):
        """playbook.txt template contains citation instruction text."""
        template = self._load_src_template("playbook.txt")
        # Must contain directive to cite IDs
        assert "cite its id" in template.lower()
        # Must contain bracket notation example like [pat-001] or [pat-
        assert "[pat-" in template or "[pat-001]" in template

    # @tests REQ-REFL-002, SCN-REFL-002-02
    def test_format_playbook_preserves_key_points_placeholder(self):
        """format_playbook() still works correctly with updated template."""
        template = self._load_src_template("playbook.txt")
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 3, "harmful": 0},
            ],
        })
        with patch("common.load_template", return_value=template):
            result = common.format_playbook(playbook)
        # Output must contain section content from the formatted playbook
        assert "pat-001" in result
        assert "use type hints" in result
        assert "PATTERNS & APPROACHES" in result


# ===========================================================================
# F2: REQ-CUR-001 -- extract_keypoints operations handling
# ===========================================================================


class TestExtractKeypointsOperations(unittest.TestCase):
    """White-box tests for how extract_keypoints handles the operations key."""

    def _setup_anthropic_mock(self):
        """Ensure common.anthropic attribute exists for patching."""
        if not hasattr(common, 'anthropic'):
            common.anthropic = MagicMock()
            self._created_anthropic = True
        else:
            self._created_anthropic = False

    def _teardown_anthropic_mock(self):
        """Remove mock anthropic attribute if we created it."""
        if getattr(self, '_created_anthropic', False):
            delattr(common, 'anthropic')

    def _run_extract_keypoints_with_response(self, response_json_str):
        """Helper to run extract_keypoints with a mocked API response."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook()
            messages = [{"role": "user", "content": "test"}]

            mock_response = _make_mock_response(response_json_str)
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{trajectories}\n{playbook}"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(extract_keypoints(messages, playbook, "test"))
            return result
        finally:
            self._teardown_anthropic_mock()

    # @tests REQ-CUR-001, SCN-CUR-001-01
    def test_extract_keypoints_includes_operations_key(self):
        """When LLM response contains operations list, result includes operations."""
        response_data = json.dumps({
            "evaluations": [{"name": "pat-001", "rating": "helpful"}],
            "operations": [{"type": "ADD", "text": "new insight", "section": "OTHERS"}],
        })
        result = self._run_extract_keypoints_with_response(response_data)
        assert "operations" in result
        assert isinstance(result["operations"], list)
        assert len(result["operations"]) == 1
        assert result["operations"][0]["type"] == "ADD"
        assert "evaluations" in result

    # @tests REQ-CUR-001, SCN-CUR-001-02
    def test_extract_keypoints_includes_empty_operations(self):
        """When LLM response contains operations: [], result has operations with empty list."""
        response_data = json.dumps({
            "evaluations": [{"name": "pat-001", "rating": "helpful"}],
            "operations": [],
        })
        result = self._run_extract_keypoints_with_response(response_data)
        assert "operations" in result
        assert result["operations"] == []

    # @tests REQ-CUR-001, SCN-CUR-001-03
    def test_extract_keypoints_no_operations_key_absent_from_result(self):
        """When LLM response lacks operations key, result dict does NOT have operations."""
        response_data = json.dumps({
            "new_key_points": ["some new point"],
            "evaluations": [{"name": "pat-001", "rating": "helpful"}],
        })
        result = self._run_extract_keypoints_with_response(response_data)
        assert "operations" not in result
        assert "new_key_points" in result
        assert "evaluations" in result

    # @tests REQ-CUR-001, SCN-CUR-001-04
    def test_extract_keypoints_non_list_operations_treated_as_absent(self):
        """When operations is null (non-list), it is treated as absent from result."""
        response_data = json.dumps({
            "evaluations": [{"name": "pat-001", "rating": "helpful"}],
            "operations": None,
        })
        result = self._run_extract_keypoints_with_response(response_data)
        assert "operations" not in result


# ===========================================================================
# F3: REQ-CUR-005 -- sequential processing order tests
# ===========================================================================


class TestSequentialProcessing(unittest.TestCase):
    """White-box tests for sequential operation processing order."""

    # @tests REQ-CUR-005, SCN-CUR-005-01
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_sequential_delete_then_merge(self, _mock_diag):
        """DELETE followed by MERGE: deleted entry absent from merge sources."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "A", "helpful": 1, "harmful": 0},
                {"name": "oth-002", "text": "B", "helpful": 2, "harmful": 0},
                {"name": "oth-003", "text": "C", "helpful": 3, "harmful": 0},
            ],
        })
        operations = [
            {"type": "DELETE", "target_id": "oth-001", "reason": "outdated"},
            {"type": "MERGE", "source_ids": ["oth-002", "oth-003"], "merged_text": "combined BC"},
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        others = result["sections"]["OTHERS"]
        assert len(others) == 1
        assert others[0]["text"] == "combined BC"
        assert others[0]["helpful"] == 5  # 2 + 3
        # oth-001 must not be present
        names = [e["name"] for e in others]
        assert "oth-001" not in names

    # @tests REQ-CUR-005, SCN-CUR-005-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_sequential_add_then_merge_references_new_entry(self, _mock_diag):
        """ADD creates entry, then MERGE references the newly created entry."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "prefer pathlib", "helpful": 2, "harmful": 0},
            ],
        })
        operations = [
            {"type": "ADD", "text": "use structured logging", "section": "OTHERS"},
            {"type": "MERGE", "source_ids": ["oth-002", "oth-001"],
             "merged_text": "prefer pathlib and use structured logging for all file operations"},
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        others = result["sections"]["OTHERS"]
        assert len(others) == 1
        assert "prefer pathlib" in others[0]["text"]
        assert others[0]["helpful"] == 2  # 0 + 2

    # @tests REQ-CUR-005, REQ-CUR-006, SCN-CUR-005-04
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_sequential_skipped_op_does_not_trigger_rollback(self, _mock_diag):
        """Skipped DELETE (nonexistent) does not prevent subsequent ADD."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "keep me", "helpful": 1, "harmful": 0},
            ],
        })
        operations = [
            {"type": "DELETE", "target_id": "nonexistent", "reason": "cleanup"},
            {"type": "ADD", "text": "new entry", "section": "OTHERS"},
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        others = result["sections"]["OTHERS"]
        assert len(others) == 2
        names = [e["name"] for e in others]
        assert "oth-001" in names
        texts = [e["text"] for e in others]
        assert "new entry" in texts


# ===========================================================================
# F4: REQ-CUR-006 -- update_playbook_data atomicity tests
# ===========================================================================


class TestUpdatePlaybookDataAtomicity(unittest.TestCase):
    """White-box tests for update_playbook_data deep copy atomicity."""

    # @tests REQ-CUR-006
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_playbook_data_uses_operations_path(self, _mock_diag):
        """update_playbook_data applies operations to add new entry."""
        playbook = _make_playbook({
            "OTHERS": [
                {"name": "oth-001", "text": "existing", "helpful": 0, "harmful": 0},
            ],
        })
        extraction_result = {
            "operations": [{"type": "ADD", "text": "new", "section": "OTHERS"}],
            "evaluations": [],
        }
        result = update_playbook_data(playbook, extraction_result)
        assert len(result["sections"]["OTHERS"]) == 2
        texts = [e["text"] for e in result["sections"]["OTHERS"]]
        assert "new" in texts

    # @tests REQ-CUR-006, SCN-CUR-005-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_update_playbook_data_rollback_on_exception(self, _mock_diag):
        """On exception in _apply_curator_operations, original playbook returned."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "A", "helpful": 5, "harmful": 1},
            ],
        })
        extraction_result = {
            "operations": [{"type": "ADD", "text": "will fail"}],
            "evaluations": [],
        }
        with patch("common._apply_curator_operations", side_effect=RuntimeError("injected failure")):
            result = update_playbook_data(playbook, extraction_result)
        # Original playbook returned unchanged
        assert result["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 5
        assert result["sections"]["PATTERNS & APPROACHES"][0]["text"] == "A"


# ===========================================================================
# F5: REQ-CUR-007 -- reflector.txt prompt structure tests
# ===========================================================================


class TestReflectorTxtTemplate(unittest.TestCase):
    """White-box tests for the reflector.txt template structure."""

    @staticmethod
    def _load_src_template(name):
        """Load template from src/prompts/ directory (canonical source)."""
        src_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent / "prompts"
        with open(src_dir / name, "r", encoding="utf-8") as f:
            return f.read()

    # @tests REQ-CUR-007, SCN-CUR-007-01, REQ-REFL-003
    def test_reflector_txt_template_structure(self):
        """reflector.txt template has required placeholders and schema fields."""
        template = self._load_src_template("reflector.txt")
        # Must contain transcript, playbook, cited_ids placeholders
        assert "{transcript}" in template
        assert "{playbook}" in template
        assert "{cited_ids}" in template
        # Must reference bullet_tags and analysis
        assert "bullet_tags" in template
        assert "analysis" in template
        # Must use "tag" (not "rating") and "name" field in example
        assert '"tag"' in template
        assert '"name"' in template


# ===========================================================================
# F6: REQ-CUR-008 -- operations vs new_key_points precedence tests
# ===========================================================================


class TestUpdatePlaybookDataPrecedence(unittest.TestCase):
    """White-box tests for operations vs new_key_points precedence."""

    # @tests REQ-CUR-008, SCN-CUR-008-01
    # @tests-invariant INV-CUR-006
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_operations_key_present_ignores_new_key_points(self, _mock_diag):
        """When operations key present, new_key_points is ignored."""
        playbook = _make_playbook()
        extraction_result = {
            "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
            "new_key_points": ["from nkp"],
            "evaluations": [],
        }
        result = update_playbook_data(playbook, extraction_result)
        texts = [e["text"] for e in result["sections"]["OTHERS"]]
        assert "from ops" in texts
        assert "from nkp" not in texts

    # @tests REQ-CUR-008, SCN-CUR-008-02
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_no_operations_key_uses_new_key_points(self, _mock_diag):
        """When operations key absent, new_key_points is used."""
        playbook = _make_playbook()
        extraction_result = {
            "new_key_points": ["legacy point"],
            "evaluations": [],
        }
        result = update_playbook_data(playbook, extraction_result)
        texts = [e["text"] for e in result["sections"]["OTHERS"]]
        assert "legacy point" in texts

    # @tests REQ-CUR-008, SCN-CUR-008-03
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_empty_operations_list_ignores_new_key_points(self, _mock_diag):
        """Empty operations list still ignores new_key_points."""
        playbook = _make_playbook()
        extraction_result = {
            "operations": [],
            "new_key_points": ["should not be added"],
            "evaluations": [],
        }
        result = update_playbook_data(playbook, extraction_result)
        # No entries added at all
        all_texts = []
        for entries in result["sections"].values():
            for e in entries:
                all_texts.append(e["text"])
        assert "should not be added" not in all_texts


# ===========================================================================
# F7: SCN-DEDUP-002-02 -- multiple independent dedup groups
# ===========================================================================

# (Added to existing TestRunDeduplication class below via separate edit)


# ===========================================================================
# F8: Additional curator SCN-* tests
# ===========================================================================

# (Added to existing TestApplyCuratorOperationsAdditional class below via separate edit)


# ===========================================================================
# F9: INV-DEDUP-003, INV-DEDUP-005 -- dedup invariant tests
# ===========================================================================

# (Added to existing TestRunDeduplication class below via separate edit)


# ===========================================================================
# F10: INV-CUR-004 -- Section names canonical after operations
# ===========================================================================


class TestCuratorInvariantsAdditional(unittest.TestCase):
    """White-box tests for curator invariants not covered elsewhere."""

    # @tests-invariant INV-CUR-004
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_section_names_canonical_after_operations(self, _mock_diag):
        """After ADD to a canonical section, all section names are still canonical."""
        playbook = _make_playbook()
        operations = [
            {"type": "ADD", "text": "new tip", "section": "PATTERNS & APPROACHES"},
        ]
        pb_copy = copy.deepcopy(playbook)
        result = _apply_curator_operations(pb_copy, operations)
        for sec_name in result["sections"]:
            assert sec_name in SECTION_SLUGS, f"Non-canonical section name: {sec_name}"


# ===========================================================================
# F5 continued: curator.txt template structure test
# ===========================================================================


class TestCuratorTxtTemplate(unittest.TestCase):
    """White-box tests for the curator.txt template structure."""

    @staticmethod
    def _load_src_template(name):
        """Load template from src/prompts/ directory (canonical source)."""
        src_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent / "prompts"
        with open(src_dir / name, "r", encoding="utf-8") as f:
            return f.read()

    # @tests SCN-CUR-011-01
    def test_curator_txt_template_structure(self):
        """curator.txt template has required placeholders and field names."""
        template = self._load_src_template("curator.txt")
        # Must contain reflector_output and playbook placeholders
        assert "{reflector_output}" in template
        assert "{playbook}" in template
        # Must reference reasoning and operations
        assert "reasoning" in template
        assert "operations" in template
        # Must contain field names for operations
        assert "target_id" in template
        assert "source_ids" in template
        assert "merged_text" in template


# ===========================================================================
# F8 continued: run_curator with empty reflector output
# ===========================================================================


class TestRunCuratorAdditional(unittest.TestCase):
    """Additional white-box tests for run_curator scenarios."""

    def _setup_anthropic_mock(self):
        if not hasattr(common, 'anthropic'):
            common.anthropic = MagicMock()
            self._created_anthropic = True
        else:
            self._created_anthropic = False

    def _teardown_anthropic_mock(self):
        if getattr(self, '_created_anthropic', False):
            delattr(common, 'anthropic')

    # @tests REQ-CUR-010, SCN-CUR-010-03
    def test_run_curator_with_empty_reflector_output(self):
        """Curator with empty reflector output still returns valid result."""
        self._setup_anthropic_mock()
        try:
            playbook = _make_playbook({
                "PATTERNS & APPROACHES": [
                    {"name": "pat-001", "text": "use types", "helpful": 1, "harmful": 0},
                ],
            })
            reflector_output = {"analysis": "", "bullet_tags": []}

            response_json = json.dumps({
                "reasoning": "No changes needed based on empty analysis.",
                "operations": [],
            })
            mock_response = _make_mock_response(response_json)
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{reflector_output}\n{playbook}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                result = _run_async(run_curator(reflector_output, playbook))

            assert "reasoning" in result
            assert "operations" in result
            assert isinstance(result["operations"], list)
        finally:
            self._teardown_anthropic_mock()


# ===========================================================================
# F8 continued: prune_harmful log test
# ===========================================================================


class TestPruneHarmfulLogs(unittest.TestCase):
    """White-box tests for prune_harmful stderr logging."""

    # @tests REQ-CUR-015, SCN-CUR-015-04
    def test_prune_harmful_logs_pruned_entries(self):
        """prune_harmful emits log line to stderr for pruned entries."""
        playbook = _make_playbook({
            "MISTAKES TO AVOID": [
                {"name": "mis-001", "text": "bad advice that is very long and should be truncated", "helpful": 0, "harmful": 5},
            ],
        })
        import io
        from contextlib import redirect_stderr
        stderr_capture = io.StringIO()
        with redirect_stderr(stderr_capture):
            prune_harmful(playbook)
        stderr_output = stderr_capture.getvalue()
        assert "prune_harmful" in stderr_output
        assert "mis-001" in stderr_output


# ===========================================================================
# Integration-level test: pipeline exercise
# ===========================================================================


class TestPipelineIntegration(unittest.TestCase):
    """Integration test exercising the session_end pipeline with mocked LLM calls."""

    # @tests REQ-REFL-001, REQ-REFL-007, REQ-CUR-014, REQ-CUR-015
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_full_pipeline_no_llm(self, _mock_diag):
        """Exercise the full pipeline (minus LLM calls) to verify integration."""
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 2, "harmful": 0},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "bad advice", "helpful": 0, "harmful": 4},
            ],
        })

        messages = [
            {"role": "user", "content": "Help me"},
            {"role": "assistant", "content": "I used [pat-001] to help."},
        ]

        # Step 1: Extract cited IDs
        cited_ids = extract_cited_ids(messages)
        assert set(cited_ids) == {"pat-001"}

        # Step 2: Apply bullet tags (simulated reflector output)
        reflector_output = {
            "analysis": "Good session. pat-001 was applied well.",
            "bullet_tags": [
                {"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly"},
                {"name": "oth-001", "tag": "harmful", "rationale": "Led to confusion"},
            ],
        }
        apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 3
        assert playbook["sections"]["OTHERS"][0]["harmful"] == 5

        # Step 3: Apply structured operations (simulated curator output)
        curator_output = {
            "reasoning": "pat-001 is good, oth-001 should be updated",
            "operations": [
                {"type": "UPDATE", "target_id": "pat-001", "text": "always use complete type hints"},
            ],
        }
        playbook = apply_structured_operations(playbook, curator_output.get("operations", []))
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["text"] == "always use complete type hints"
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 3

        # Step 4: Prune harmful
        playbook = prune_harmful(playbook)
        assert len(playbook["sections"]["OTHERS"]) == 0
        assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1


    # @tests REQ-DEDUP-001, REQ-DEDUP-002
    @patch("common.is_diagnostic_mode", return_value=False)
    def test_full_pipeline_with_dedup(self, _mock_diag):
        """Integration: run_deduplication is exercised as step 10 of the pipeline."""
        # Start with a playbook that has TWO entries with identical embeddings
        playbook = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "always use type hints for function parameters", "helpful": 5, "harmful": 0},
                {"name": "pat-002", "text": "use type hints on all function parameters", "helpful": 3, "harmful": 1},
            ],
            "OTHERS": [
                {"name": "oth-001", "text": "bad advice", "helpful": 0, "harmful": 4},
            ],
        })

        messages = [
            {"role": "user", "content": "Help me"},
            {"role": "assistant", "content": "I used [pat-001] to help."},
        ]

        # Step 5: Extract cited IDs
        cited_ids = extract_cited_ids(messages)
        assert set(cited_ids) == {"pat-001"}

        # Step 7: Apply bullet tags (simulated reflector output)
        reflector_output = {
            "analysis": "Good session. pat-001 was applied.",
            "bullet_tags": [
                {"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly"},
            ],
        }
        apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))
        assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 6  # was 5, +1

        # Step 9: Apply structured operations (simulated curator output -- no-op here)
        curator_output = {"reasoning": "no changes needed", "operations": []}
        playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

        # Step 10: Deduplication -- this is the core of this test
        # Mock sentence_transformers so run_deduplication actually runs (not degrades)
        # pat-001 and pat-002 have identical embeddings -> cosine sim = 1.0 >= 0.85
        embeddings = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]  # 3 entries: pat-001, pat-002, oth-001
        mock_np = _make_mock_numpy()
        mock_st_module = MagicMock()
        mock_model = MagicMock()
        mock_model.encode.return_value = embeddings
        mock_st_module.SentenceTransformer.return_value = mock_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_st_module, "numpy": mock_np}):
            playbook = run_deduplication(playbook)

        # pat-001 and pat-002 should be merged into one (pat-001 survives)
        assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1
        survivor = playbook["sections"]["PATTERNS & APPROACHES"][0]
        assert survivor["name"] == "pat-001"
        assert survivor["helpful"] == 9  # 6 (after bullet tag) + 3 (from pat-002)
        assert survivor["harmful"] == 1  # 0 + 1 (from pat-002)
        # oth-001 is orthogonal, should not be merged
        assert len(playbook["sections"]["OTHERS"]) == 1

        # Step 11: Prune harmful
        playbook = prune_harmful(playbook)
        # oth-001 has harmful=4 > helpful=0, harmful >= 3 -> pruned
        assert len(playbook["sections"]["OTHERS"]) == 0
        assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 1

    # @tests REQ-REFL-003, REQ-CUR-010
    def test_full_pipeline_with_mocked_llm_calls(self):
        """Integration: run_reflector and run_curator called with mocked Anthropic."""
        if not hasattr(common, 'anthropic'):
            common.anthropic = MagicMock()
            created_anthropic = True
        else:
            created_anthropic = False

        try:
            playbook = _make_playbook({
                "PATTERNS & APPROACHES": [
                    {"name": "pat-001", "text": "use type hints", "helpful": 2, "harmful": 0},
                ],
            })

            messages = [
                {"role": "user", "content": "Help me"},
                {"role": "assistant", "content": "I used [pat-001] to help."},
            ]

            cited_ids = extract_cited_ids(messages)
            assert set(cited_ids) == {"pat-001"}

            # Mock Anthropic responses: first call is reflector, second is curator
            reflector_json = {
                "analysis": "Good session. pat-001 was applied.",
                "bullet_tags": [{"name": "pat-001", "tag": "helpful", "rationale": "Applied well"}],
            }
            curator_json = {
                "reasoning": "pat-001 is good, add a new entry",
                "operations": [{"type": "ADD", "text": "always test your code", "section": "PATTERNS & APPROACHES"}],
            }

            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [
                _make_mock_response(json.dumps(reflector_json)),
                _make_mock_response(json.dumps(curator_json)),
            ]

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{transcript}\n{playbook}\n{cited_ids}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                # Step 6: run_reflector (actual LLM call, mocked)
                reflector_output = _run_async(run_reflector(messages, playbook, cited_ids))

            assert reflector_output["analysis"] == "Good session. pat-001 was applied."
            assert len(reflector_output["bullet_tags"]) == 1
            assert reflector_output["bullet_tags"][0]["name"] == "pat-001"

            # Step 7: Apply bullet tags from reflector output
            apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))
            assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 3  # was 2, +1

            with patch.object(common, 'ANTHROPIC_AVAILABLE', True), \
                 patch("common.is_diagnostic_mode", return_value=False), \
                 patch("common.load_template", return_value="{reflector_output}\n{playbook}"), \
                 patch("common.format_playbook", return_value="formatted"), \
                 patch.object(common.anthropic, 'Anthropic', return_value=mock_client), \
                 patch.dict(os.environ, {"AGENTIC_CONTEXT_API_KEY": "test-key", "AGENTIC_CONTEXT_MODEL": "test-model"}):
                # Step 8: run_curator (actual LLM call, mocked)
                curator_output = _run_async(run_curator(reflector_output, playbook))

            assert curator_output["reasoning"] == "pat-001 is good, add a new entry"
            assert len(curator_output["operations"]) == 1
            assert curator_output["operations"][0]["type"] == "ADD"

            # Step 9: Apply structured operations from curator output
            playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

            # Verify: pat-001 counter was incremented by bullet_tags
            assert playbook["sections"]["PATTERNS & APPROACHES"][0]["helpful"] == 3
            assert playbook["sections"]["PATTERNS & APPROACHES"][0]["name"] == "pat-001"

            # Verify: new entry was added by curator ADD operation
            assert len(playbook["sections"]["PATTERNS & APPROACHES"]) == 2
            new_entry = playbook["sections"]["PATTERNS & APPROACHES"][1]
            assert new_entry["text"] == "always test your code"
            assert new_entry["helpful"] == 0
            assert new_entry["harmful"] == 0

        finally:
            if created_anthropic:
                delattr(common, 'anthropic')


class TestSessionEndSubprocess(unittest.TestCase):
    """Tests that run session_end.py end-to-end -- deliverable-level tests."""

    # @tests REQ-REFL-006, REQ-CUR-012, INV-REFL-002, INV-CUR-008
    def test_session_end_subprocess_no_crash(self):
        """session_end.py runs end-to-end without crashing when API is unavailable.

        With ANTHROPIC_AVAILABLE=False, reflector and curator return empty results,
        but the pipeline still runs: extract_cited_ids, apply_bullet_tags,
        run_deduplication, and prune_harmful all execute. Playbook is saved.
        This verifies the full session_end.py wiring.
        """
        import io
        import session_end

        playbook_data = _make_playbook({
            "PATTERNS & APPROACHES": [
                {"name": "pat-001", "text": "use type hints", "helpful": 2, "harmful": 0},
            ],
        })

        saved_playbook = {}

        def mock_save_playbook(pb):
            saved_playbook.update(pb)

        # Provide stdin with the JSON input that session_end.main() reads
        stdin_data = json.dumps({
            "transcript_path": "/fake/transcript.jsonl",
            "reason": "clear",
        })

        settings_data = {"playbook_update_on_exit": True, "playbook_update_on_clear": True}

        with patch("sys.stdin", io.StringIO(stdin_data)), \
             patch("session_end.load_transcript", return_value=[
                 {"role": "user", "content": "Help me refactor"},
                 {"role": "assistant", "content": "Sure, applying [pat-001]."},
             ]), \
             patch("session_end.load_playbook", return_value=copy.deepcopy(playbook_data)), \
             patch("session_end.save_playbook", side_effect=mock_save_playbook), \
             patch("session_end.load_settings", return_value=settings_data), \
             patch("session_end.clear_session"), \
             patch.object(common, 'ANTHROPIC_AVAILABLE', False):
            # Run session_end.main() directly. Reflector and curator will return
            # empty results (ANTHROPIC_AVAILABLE=False), but the rest of the
            # pipeline (extract_cited_ids, apply_bullet_tags, run_deduplication,
            # prune_harmful) all execute normally.
            _run_async(session_end.main())

        # Verify: playbook was saved (pipeline completed without crash)
        assert "sections" in saved_playbook, "Playbook should have been saved with sections key"
        assert "PATTERNS & APPROACHES" in saved_playbook["sections"]

        # Verify: pat-001 survived (no harmful pruning, counters unchanged since
        # reflector returned empty bullet_tags)
        pat_entries = saved_playbook["sections"]["PATTERNS & APPROACHES"]
        assert len(pat_entries) == 1
        assert pat_entries[0]["name"] == "pat-001"
        assert pat_entries[0]["helpful"] == 2  # unchanged, no bullet_tags applied
        assert pat_entries[0]["harmful"] == 0


if __name__ == "__main__":
    unittest.main()
