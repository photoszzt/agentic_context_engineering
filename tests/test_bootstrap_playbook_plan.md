# Test Plan: Bootstrap Playbook Command

## Spec Coverage

| REQ-* / SCN-* | Test Category | Test Function(s) |
|---|---|---|
| REQ-BOOT-002 | White-box / Unit | TestEncodeProjectDir (4 cases from spec) |
| REQ-BOOT-011 | White-box / Unit | TestCountKeypoints (empty, populated) |
| REQ-BOOT-012 | White-box / Unit | TestLoadState (non-existent, valid, corrupted, missing key) |
| REQ-BOOT-013 | White-box / Unit | TestSaveState (atomic write, JSON correctness) |
| INV-BOOT-008 | White-box / Unit | TestSaveState verifies temp + os.replace |
| QG-BOOT-001 | Git check | TestCommonPyUnchanged (git diff) |
| QG-BOOT-003 | Import smoke | TestImportSmoke |
| QG-BOOT-004 | File check | TestCommandFileValidMarkdown |
| REQ-BOOT-011 | White-box | TestProgressEventFormats (format strings match spec) |

## Mocking Strategy

| Dependency | How Mocked | Notes |
|---|---|---|
| common.py functions | monkeypatch on module attributes | Same pattern as test_subagent_stop_whitebox.py |
| Filesystem (state file) | tmp_path fixture | Pytest built-in |
| Anthropic API | NOT called | We test sync helpers only (no pytest-asyncio) |
| asyncio.sleep | NOT needed | We test sync functions directly |

## Adversarial Categories (3+ of 6)

1. **Boundary**: encode_project_dir with empty string, single slash; count_keypoints with no sections key
2. **Invalid input**: load_state with corrupted JSON, missing key, non-dict file; encode_project_dir with special chars
3. **Failure injection**: load_state with OS error (permission denied mock)

## Test File Organization

| File | Purpose |
|---|---|
| test_bootstrap_playbook.py | All white-box unit tests + QG checks |

## Notes

- pytest-asyncio is NOT installed, so we test only synchronous helper functions
- The main() async function requires full pipeline mocking; we verify helpers and source-level properties instead
- QG-BOOT-002 (existing tests pass) verified by running full `uv run pytest tests/ -v`
