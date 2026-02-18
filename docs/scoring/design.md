# Implementation Design: Scoring Module

## Overview

This document specifies the exact changes to `src/hooks/common.py` and `src/prompts/playbook.txt` required to implement the separate helpful/harmful scoring counters. Each section maps to REQ-* in `spec.md`.

---

## Function Changes

### 1. `load_playbook()` -- Migration Logic

**File**: `src/hooks/common.py`, current lines 92-125

**Current behavior** (lines 108-119): Iterates `key_points`, handles bare strings and dicts, defaults `score` to 0.

**New behavior**: Replace the migration block inside the `for item in data["key_points"]` loop with three-branch logic. The function must also detect whether ANY migration occurred to satisfy OBS-SCORE-001.

#### Migration Decision Tree

```
for item in data["key_points"]:
    if isinstance(item, str):
        --> BRANCH 1: Bare string (REQ-SCORE-004)
    elif isinstance(item, dict):
        if "helpful" in item and "harmful" in item:
            --> BRANCH 0: Already migrated (no-op, keep as-is)
        elif "score" in item:
            --> BRANCH 3: Dict with score (REQ-SCORE-006)
        else:
            --> BRANCH 2: Dict without score or counters (REQ-SCORE-005)
```

#### Branch 1: Bare String (REQ-SCORE-004, SCN-SCORE-004-01)

```python
# item is a str
name = generate_keypoint_name(existing_names)
keypoints.append({"name": name, "text": item, "helpful": 0, "harmful": 0})
existing_names.add(name)
migrated_entries.append({"name": name, "from": "bare_string", "original_score": None})
```

#### Branch 2: Dict Without Score or Counters (REQ-SCORE-005, SCN-SCORE-005-01)

```python
# item is a dict, no "helpful"/"harmful" keys, no "score" key
if "name" not in item:
    item["name"] = generate_keypoint_name(existing_names)
item["helpful"] = 0
item["harmful"] = 0
existing_names.add(item["name"])
keypoints.append(item)
migrated_entries.append({"name": item["name"], "from": "dict_no_score", "original_score": None})
```

#### Branch 3: Dict With Score (REQ-SCORE-006, SCN-SCORE-006-01)

```python
# item is a dict with "score" key but no "helpful"/"harmful" keys
if "name" not in item:
    item["name"] = generate_keypoint_name(existing_names)
original_score = item.pop("score")  # Remove score field (INV-SCORE-004)
item["helpful"] = max(original_score, 0)
item["harmful"] = max(-original_score, 0)
existing_names.add(item["name"])
keypoints.append(item)
migrated_entries.append({"name": item["name"], "from": "dict_with_score", "original_score": original_score})
```

#### Branch 0: Already Migrated (no-op)

```python
# item is a dict with both "helpful" and "harmful" keys
if "name" not in item:
    item["name"] = generate_keypoint_name(existing_names)
# Drop "score" if it somehow co-exists (defensive)
item.pop("score", None)
existing_names.add(item["name"])
keypoints.append(item)
# No migration log entry -- already in canonical form
```

#### Diagnostic Logging (OBS-SCORE-001)

After the loop, if `migrated_entries` is non-empty and diagnostic mode is enabled:

```python
if migrated_entries and is_diagnostic_mode():
    migration_summary = json.dumps(migrated_entries, indent=2)
    save_diagnostic(
        f"Migrated {len(migrated_entries)} playbook entries:\n{migration_summary}",
        "playbook_migration"
    )
```

**Design rationale**: Migration logging uses the existing `is_diagnostic_mode()` and `save_diagnostic()` functions rather than introducing a new logging framework. This is consistent with the existing diagnostic pattern (see `extract_keypoints` at line 289-293 which uses the same pattern).

---

### 2. `update_playbook_data()` -- Counter Updates and Pruning

**File**: `src/hooks/common.py`, current lines 150-177

**Current behavior**: Uses `rating_delta = {"helpful": 1, "harmful": -3, "neutral": -1}` to modify `score`, then prunes `score > -5`.

**New behavior**: Replace entirely.

#### New Key Point Creation (line 160 change)

Replace:
```python
playbook["key_points"].append({"name": name, "text": text, "score": 0})
```

With:
```python
playbook["key_points"].append({"name": name, "text": text, "helpful": 0, "harmful": 0})
```

#### Counter Update Logic (lines 163-171 replacement)

Replace the `rating_delta` dict and score arithmetic with:

```python
name_to_kp = {kp["name"]: kp for kp in playbook["key_points"]}

for eval_item in evaluations:
    name = eval_item.get("name", "")
    rating = eval_item.get("rating", "")

    if name in name_to_kp:
        if rating == "helpful":
            name_to_kp[name]["helpful"] += 1
        elif rating == "harmful":
            name_to_kp[name]["harmful"] += 1
        # "neutral" and unrecognized ratings: no change (SC-SCORE-002, SCN-SCORE-002-03, SCN-SCORE-002-04)
```

**Key change**: The default for unrecognized `rating` is now explicit no-op. The old code defaulted unrecognized ratings to `0` delta via `rating_delta.get(rating, 0)`. The new code uses explicit `if/elif` branches, making the behavior obvious.

#### Pruning Logic (lines 173-175 replacement)

Replace:
```python
playbook["key_points"] = [
    kp for kp in playbook["key_points"] if kp.get("score", 0) > -5
]
```

With:
```python
pruned_entries = []
surviving = []
for kp in playbook["key_points"]:
    harmful = kp.get("harmful", 0)
    helpful = kp.get("helpful", 0)
    if harmful >= 3 and harmful > helpful:
        pruned_entries.append(kp)
    else:
        surviving.append(kp)

# OBS-SCORE-002: Log pruned entries in diagnostic mode
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
```

**Pruning condition analysis** (REQ-SCORE-007):
- `harmful >= 3`: Floor check. Requires at least 3 harmful ratings before pruning is even considered. Prevents premature pruning of sparsely-evaluated entries.
- `harmful > helpful`: Majority-harmful check. Entry must have more harmful than helpful ratings.
- Combined: Both conditions must be true (AND). An entry with `helpful=10, harmful=4` is retained (4 > 10 is False). An entry with `helpful=0, harmful=0` is retained (0 >= 3 is False).
- Guard for zero-evaluation (INV-SCORE-003): The `harmful >= 3` condition inherently guards against `helpful=0, harmful=0` since `0 >= 3` is `False`. No separate explicit guard is needed, but the invariant is documented for clarity.

---

### 3. `format_playbook()` -- New Output Format

**File**: `src/hooks/common.py`, current lines 137-147

**Current behavior** (line 142-143):
```python
key_points_text = "\n".join(
    f"- {kp['text'] if isinstance(kp, dict) else kp}" for kp in key_points
)
```

**New behavior** (REQ-SCORE-003, SCN-SCORE-003-01):
```python
key_points_text = "\n".join(
    f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
    for kp in key_points
)
```

**Format string**: `[{name}] helpful={helpful} harmful={harmful} :: {text}`

**Example output**:
```
[kpt_001] helpful=5 harmful=1 :: use type hints everywhere
[kpt_002] helpful=0 harmful=0 :: prefer pathlib over os.path
```

**Notes**:
- The `isinstance(kp, dict) else kp` guard is no longer needed because after `load_playbook()` migration, all entries are dicts. However, keeping a defensive fallback is acceptable if the Coding Agent prefers it.
- The `- ` prefix is replaced with `[name] ... ::` prefix. This is an intentional format change.

---

### 4. `save_playbook()` -- No Logic Change

**File**: `src/hooks/common.py`, current lines 128-134

**No code change required**. The function serializes whatever is in `playbook["key_points"]` via `json.dump()`. Since all entries now have `{name, text, helpful, harmful}` schema (no `score`), the output JSON will automatically reflect the new schema.

**Verification**: INV-SCORE-004 (no score field in output) is enforced by the upstream functions (`load_playbook()` drops `score`, `update_playbook_data()` never creates `score`). `save_playbook()` is a pass-through serializer.

---

### 5. `generate_keypoint_name()` -- No Change

**File**: `src/hooks/common.py`, current lines 65-75

**No change required**. The naming scheme (`kpt_NNN`) is orthogonal to the scoring change.

---

### 6. `playbook.txt` Template -- Updated Content

**File**: `src/prompts/playbook.txt`

**Current content**:
```
# Playbook

The following key points were learned from previous sessions:

{key_points}

Use these key points to improve your responses.
```

**New content** (REQ-SCORE-008, SCN-SCORE-008-01):
```
# Playbook

The following key points were learned from previous sessions. Each entry shows how many times it was rated helpful or harmful by the reflection system.

- Higher helpful counts indicate proven, valuable guidance.
- Higher harmful counts indicate guidance that has been problematic.
- Consider the ratio of helpful to harmful when deciding how much to trust each key point. A key point with many helpful ratings and few harmful ones is highly reliable. A key point with low counts in both is untested.

{key_points}

Use these key points to improve your responses, weighing them by their track record shown above.
```

**Design rationale**: The template is kept concise -- just enough for Claude to understand the semantics without consuming excessive context tokens. The format explanation is placed before `{key_points}` so Claude reads the interpretation guide before the data.

---

## Function Composition

### Call Graph (unchanged by this task)

```
PostToolUseHook / StopHook
    --> load_playbook()           # reads playbook.json, migrates legacy entries
    --> load_transcript()         # reads session transcript
    --> extract_keypoints()       # calls LLM to evaluate key points
    --> update_playbook_data()    # applies increments + pruning
    --> save_playbook()           # writes playbook.json

PreToolUseHook (context injection)
    --> load_playbook()           # reads playbook.json
    --> format_playbook()         # formats for injection into prompt
        --> load_template()       # reads playbook.txt
```

### Data Flow

```
playbook.json on disk
    |
    v
load_playbook() --> playbook dict {version, last_updated, key_points}
    |                   (all entries in canonical {name, text, helpful, harmful} schema)
    |
    +--[injection path]--> format_playbook(playbook) --> formatted string --> prompt
    |
    +--[update path]----> update_playbook_data(playbook, extraction_result)
                              |
                              +--> add new key points (helpful=0, harmful=0)
                              +--> increment counters per evaluations
                              +--> prune harmful entries
                              +--> return modified playbook
                              |
                              v
                          save_playbook(playbook) --> playbook.json on disk
```

### Initialization Order

No change. The existing initialization order is:
1. `load_playbook()` -- must be called first to get playbook state
2. Other operations depend on the returned playbook dict

---

## Testability Hooks

### External Dependencies

| Dependency | Testability Hook | Implementation |
|------------|------------------|----------------|
| File system (playbook.json) | `get_project_dir()` returns a path | Tests can set `CLAUDE_PROJECT_DIR` env var to a temp directory |
| File system (playbook.txt) | `get_user_claude_dir()` returns a path | Tests can place template in `~/.claude/prompts/` or mock `load_template()` |
| Diagnostic mode | `is_diagnostic_mode()` checks for flag file | Tests can create/remove the flag file in the temp directory |
| LLM API (extract_keypoints) | Not changed by this task | Not relevant to scoring tests |

### Test Strategy for Migration

Tests for `load_playbook()` migration should:
1. Create a temp directory
2. Set `CLAUDE_PROJECT_DIR` to the temp directory
3. Write a `playbook.json` with legacy format entries
4. Call `load_playbook()`
5. Assert the returned dict has entries in canonical schema

### Test Strategy for Pruning

Tests for `update_playbook_data()` pruning should:
1. Construct a playbook dict directly (no file I/O needed)
2. Construct an extraction_result dict with evaluations
3. Call `update_playbook_data(playbook, extraction_result)`
4. Assert the returned dict has the correct entries retained/removed

---

## Instrumentation Hooks

### Diagnostic Pattern (OBS-SCORE-001, OBS-SCORE-002)

This module uses the existing diagnostic pattern (`is_diagnostic_mode()` + `save_diagnostic()`) rather than introducing a metrics/logging framework. This is consistent with the codebase's existing approach.

| OBS-* | Diagnostic File Name | When Written | Content |
|-------|---------------------|--------------|---------|
| OBS-SCORE-001 | `playbook_migration` | When `load_playbook()` migrates any legacy entries | Count of migrated entries + per-entry details (name, source format, original score) |
| OBS-SCORE-002 | `playbook_pruning` | When `update_playbook_data()` prunes any entries | Count of pruned entries + per-entry details (name, text truncated to 80 chars, helpful count, harmful count, reason string) |

### Wiring

Both diagnostic outputs are gated by `is_diagnostic_mode()` and written via `save_diagnostic()`. No new instrumentation infrastructure is needed.
