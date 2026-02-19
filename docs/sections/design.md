# Implementation Design: Sections Module

## Overview

This document specifies the exact changes to `src/hooks/common.py`, `src/prompts/reflection.txt`, and `src/prompts/playbook.txt` required to implement section-based playbook organization. Each section maps to REQ-* in `spec.md`.

---

## New Constant: SECTION_SLUGS

**File**: `src/hooks/common.py` (add near the top, after imports)

**Implements**: REQ-SECT-010, QG-SECT-001

```python
SECTION_SLUGS = {
    "PATTERNS & APPROACHES": "pat",
    "MISTAKES TO AVOID": "mis",
    "USER PREFERENCES": "pref",
    "PROJECT CONTEXT": "ctx",
    "OTHERS": "oth",
}
```

This is the single source of truth for:
- Canonical section names (the dict keys)
- Section ordering (dict iteration order in Python 3.7+ is insertion order)
- Slug lookup for ID generation

All code paths that need section names, slugs, or ordering MUST use this constant. No other location defines slug mappings.

---

## Function Changes

### 1. `generate_keypoint_name()` -- New Signature

**File**: `src/hooks/common.py`, current lines 65-75

**Current signature**: `generate_keypoint_name(existing_names: set) -> str`

**New signature**: `generate_keypoint_name(section_entries: list[dict], slug: str) -> str`

**Implements**: REQ-SECT-002

**Current behavior**: Scans `existing_names` set for `kpt_NNN` pattern, returns `kpt_{max+1:03d}`.

**New behavior**:

```python
def generate_keypoint_name(section_entries: list[dict], slug: str) -> str:
    """Generate the next key point name for a section.

    Scans section_entries for names matching {slug}-NNN pattern,
    finds the highest NNN, returns {slug}-{max+1:03d}.

    Legacy kpt_NNN names in section_entries are ignored.
    """
    import re
    pattern = re.compile(rf"^{re.escape(slug)}-(\d+)$")
    max_num = 0
    for entry in section_entries:
        match = pattern.match(entry.get("name", ""))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"{slug}-{max_num + 1:03d}"
```

**Key changes**:
- Parameter changed from `existing_names: set` to `section_entries: list[dict], slug: str`
- Regex matches `{slug}-(\d+)` instead of `kpt_(\d+)`
- Legacy `kpt_NNN` entries are ignored because they do not match the `{slug}-NNN` regex (SCN-SECT-002-03)

---

### 2. `load_playbook()` -- Migration to Sections Format

**File**: `src/hooks/common.py`, current lines 92-162

**Implements**: REQ-SECT-006, REQ-SECT-007, INV-SECT-001, INV-SECT-004, INV-SECT-006

**Current behavior**: Reads `playbook.json`, iterates `key_points` array, applies scoring migration (bare string, dict without score, dict with score), returns `{version, last_updated, key_points: [...]}`.

**New behavior**: Detect whether the file has a `sections` key or a flat `key_points` key, and return a sections-based dict in all cases.

#### Detection and Migration Algorithm

```
load file as JSON -> data

if file does not exist or is corrupt:
    return default_playbook()   # {version: "1.0", last_updated: None, sections: {all empty}}

if "sections" in data AND "key_points" in data:
    --> DUAL-KEY: sections takes precedence, key_points ignored, warn (REQ-SECT-007)
    delete data["key_points"]
    use data["sections"]

elif "sections" in data:
    --> ALREADY MIGRATED: use data["sections"] as-is
    ensure all 5 canonical sections exist (add empty lists for any missing)

elif "key_points" in data:
    --> FLAT FORMAT: migrate to sections (REQ-SECT-006)
    1. Apply scoring migration to each entry (same branches as before: bare string, dict with score, dict without score, already migrated)
    2. Place ALL migrated entries into "OTHERS" section with IDs preserved
    3. Initialize all other sections as empty lists
    4. Remove "key_points" from data
    5. Emit OBS-SECT-001 diagnostic

else:
    --> NO KEY POINTS, NO SECTIONS: return default playbook with empty sections
```

#### Default Playbook

```python
def _default_playbook() -> dict:
    return {
        "version": "1.0",
        "last_updated": None,
        "sections": {name: [] for name in SECTION_SLUGS},
    }
```

#### Detailed Migration Steps (flat -> sections)

The scoring migration (branches 0-3 from `docs/scoring/design.md`) still applies to each entry in `key_points` during the flat-format migration. The only addition is that after scoring migration, ALL entries go into `OTHERS`:

```python
# After scoring migration produces `migrated_keypoints` list:
sections = {name: [] for name in SECTION_SLUGS}
sections["OTHERS"] = migrated_keypoints  # All flat entries go to OTHERS

# OBS-SECT-001: Log migration
if migrated_keypoints and is_diagnostic_mode():
    save_diagnostic(
        f"Migrated {len(migrated_keypoints)} entries from flat key_points to OTHERS section",
        "sections_migration"
    )

data["sections"] = sections
data.pop("key_points", None)
```

#### Dual-Key Warning

```python
if "sections" in data and "key_points" in data:
    data.pop("key_points")
    if is_diagnostic_mode():
        save_diagnostic(
            "Dual-key playbook.json detected: both 'sections' and 'key_points' present. "
            "Using 'sections', ignoring 'key_points'.",
            "sections_dual_key_warning"
        )
```

#### Ensuring Canonical Sections Exist

After loading sections (whether from migration or existing file), ensure all 5 canonical sections are present:

```python
for section_name in SECTION_SLUGS:
    if section_name not in data["sections"]:
        data["sections"][section_name] = []
```

This handles the case where a new section is added to `SECTION_SLUGS` in a future update -- old files missing the new section get an empty list.

---

### 3. `save_playbook()` -- Assertion of sections Key

**File**: `src/hooks/common.py`, current lines 165-171

**Implements**: INV-SECT-001, INV-SECT-007

**Current behavior**: Serializes the entire playbook dict via `json.dump()`.

**New behavior**: Add an assertion before writing:

```python
def save_playbook(playbook: dict):
    assert "sections" in playbook, (
        "Playbook must have 'sections' key. "
        "Got keys: " + str(list(playbook.keys()))
    )
    playbook["last_updated"] = datetime.now().isoformat()
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(playbook, f, indent=2, ensure_ascii=False)
```

**Design rationale**: The assertion catches FM-SECT-008 at the write boundary. If any code path accidentally passes a flat-format playbook, the error is loud and immediate rather than silently corrupting the file.

---

### 4. `format_playbook()` -- Section Headers in Output

**File**: `src/hooks/common.py`, current lines 174-186

**Implements**: REQ-SECT-003, CON-SECT-004

**Current behavior**: Iterates `playbook["key_points"]`, formats each as `[name] helpful=X harmful=Y :: text`, joins with newlines, inserts into template.

**New behavior**: Iterate sections in canonical order, emit section headers, format entries within each section.

```python
def format_playbook(playbook: dict) -> str:
    sections = playbook.get("sections", {})

    section_blocks = []
    for section_name in SECTION_SLUGS:  # Canonical order
        entries = sections.get(section_name, [])
        if not entries:
            continue  # Omit empty sections

        lines = [f"## {section_name}"]
        for kp in entries:
            lines.append(
                f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
            )
        section_blocks.append("\n".join(lines))

    if not section_blocks:
        return ""

    key_points_text = "\n\n".join(section_blocks)

    template = load_template("playbook.txt")
    return template.format(key_points=key_points_text)
```

**Format output example** (SCN-SECT-003-01):
```
## PATTERNS & APPROACHES
[pat-001] helpful=5 harmful=1 :: use type hints

## USER PREFERENCES
[pref-001] helpful=2 harmful=0 :: prefer pathlib

## OTHERS
[kpt_001] helpful=0 harmful=0 :: legacy point
```

**Notes**:
- Sections are separated by blank lines (`"\n\n".join(section_blocks)`)
- Within a section, entries are separated by newlines (`"\n".join(lines)`)
- Empty sections produce no output whatsoever (no header, no blank line)
- The section header uses `## SECTION_NAME` format (markdown H2)

---

### 5. `update_playbook_data()` -- Sections-Aware Updates

**File**: `src/hooks/common.py`, current lines 189-246

**Implements**: REQ-SECT-005, REQ-SECT-008

**Signature**: `update_playbook_data(playbook: dict, extraction_result: dict) -> dict` (UNCHANGED). The function internally destructures `new_key_points = extraction_result.get("new_key_points", [])` and `evaluations = extraction_result.get("evaluations", [])`.

**Current behavior**: Operates on `playbook["key_points"]` flat list. Adds new key points, applies evaluations, prunes.

**New behavior**: Operates on `playbook["sections"]` dict. Two major changes: (a) evaluations/pruning traverse all sections, (b) new key point insertion uses section field and slug-based IDs.

#### Section Name Resolution Helper

```python
def _resolve_section(section_name: str) -> str:
    """Resolve a section name via case-insensitive exact match.

    Strips leading/trailing whitespace before matching.
    Returns the canonical section name if matched, or "OTHERS" as fallback.
    """
    if not section_name or not section_name.strip():
        return "OTHERS"
    stripped = section_name.strip()
    for canonical in SECTION_SLUGS:
        if canonical.upper() == stripped.upper():
            return canonical
    return "OTHERS"
```

#### New Key Point Insertion (change a)

```python
# Collect all existing texts across all sections for dedup
existing_texts = set()
for entries in playbook["sections"].values():
    for kp in entries:
        existing_texts.add(kp["text"])

for item in new_key_points:
    # Backward compat: plain string -> {"text": str, "section": "OTHERS"}
    if isinstance(item, str):
        text = item
        section_name = "OTHERS"
    elif isinstance(item, dict):
        text = item.get("text", "")
        raw_section = item.get("section", "") or ""
        section_name = _resolve_section(raw_section)
        # OBS-SECT-002: Log fallback to OTHERS for unknown section
        if section_name == "OTHERS" and raw_section and raw_section.upper().strip() != "OTHERS":
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Unknown section '{raw_section}' for key point: \"{text[:80]}\". "
                    f"Assigned to OTHERS.",
                    "sections_unknown_section"
                )
    else:
        continue  # Skip invalid entry types

    if not text or text in existing_texts:
        continue

    slug = SECTION_SLUGS[section_name]
    target_entries = playbook["sections"][section_name]
    name = generate_keypoint_name(target_entries, slug)
    target_entries.append({"name": name, "text": text, "helpful": 0, "harmful": 0})
    existing_texts.add(text)
```

#### Evaluations Across All Sections (change b)

```python
# Build name-to-keypoint lookup across ALL sections
name_to_kp = {}
for entries in playbook["sections"].values():
    for kp in entries:
        name_to_kp[kp["name"]] = kp

for eval_item in evaluations:
    name = eval_item.get("name", "")
    rating = eval_item.get("rating", "")
    if name in name_to_kp:
        if rating == "helpful":
            name_to_kp[name]["helpful"] += 1
        elif rating == "harmful":
            name_to_kp[name]["harmful"] += 1
        # "neutral" and unrecognized: no-op
```

#### Pruning Across All Sections

```python
pruned_entries = []
for section_name in playbook["sections"]:
    surviving = []
    for kp in playbook["sections"][section_name]:
        harmful = kp.get("harmful", 0)
        helpful = kp.get("helpful", 0)
        if harmful >= 3 and harmful > helpful:
            pruned_entries.append(kp)
        else:
            surviving.append(kp)
    playbook["sections"][section_name] = surviving

# LOG-SCORE-002: Diagnostic logging for pruning (same pattern as before)
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
```

---

### 6. `extract_keypoints()` -- Flat Dict from Sections

**File**: `src/hooks/common.py`, current lines 301-386

**Implements**: REQ-SECT-009

**Current behavior** (lines 330-334):
```python
playbook_dict = (
    {kp["name"]: kp["text"] for kp in playbook["key_points"]}
    if playbook["key_points"]
    else {}
)
```

**New behavior**:
```python
playbook_dict = {}
for entries in playbook.get("sections", {}).values():
    for kp in entries:
        playbook_dict[kp["name"]] = kp["text"]
```

**Notes**: The flat `{name: text}` dict is used to populate the `{playbook}` variable in `reflection.txt`. The LLM sees section context from the `format_playbook()` output (injected into the system prompt via `playbook.txt`), not from this dict.

---

### 7. `reflection.txt` Template -- Section Categorization

**File**: `src/prompts/reflection.txt`

**Implements**: REQ-SECT-004

**Current content** (lines 24-33):
```
# Output Format
{{
  "new_key_points": [
    "First key point extracted from the reasoning trajectories",
    "Second key point extracted from the reasoning trajectories"
  ],
  "evaluations": [
    {{"name": "kpt_001", "rating": "helpful"}},
    {{"name": "kpt_002", "rating": "neutral"}}
  ]
}}
```

**New content**:
```
# Sections
Assign each new key point to one of these sections:
- PATTERNS & APPROACHES: Successful solutions, design patterns, architectural decisions
- MISTAKES TO AVOID: Failed approaches, common pitfalls, anti-patterns
- USER PREFERENCES: User's coding style, tool preferences, workflow habits
- PROJECT CONTEXT: Project-specific facts, architecture, dependencies, conventions
- OTHERS: Key points that don't fit the above categories

# Output Format
{{
  "new_key_points": [
    {{"text": "First key point", "section": "PATTERNS & APPROACHES"}},
    {{"text": "Second key point", "section": "MISTAKES TO AVOID"}}
  ],
  "evaluations": [
    {{"name": "pat-001", "rating": "helpful"}},
    {{"name": "kpt_001", "rating": "neutral"}}
  ]
}}
```

**Changes**:
1. Added `# Sections` block listing all canonical section names with descriptions
2. Changed `new_key_points` from `list[str]` to `list[dict]` with `text` and `section` fields
3. Updated example evaluation to show both new-style (`pat-001`) and legacy (`kpt_001`) IDs

---

### 8. `playbook.txt` Template -- Section-Based Format

**File**: `src/prompts/playbook.txt`

**No change to the template text itself.** The existing `{key_points}` placeholder now receives section-headed output from `format_playbook()` (REQ-SECT-003). The template's explanatory text about helpful/harmful counts remains accurate because the per-entry format is unchanged.

**Why no change**: The template explains the scoring system. The section headers (`## SECTION_NAME`) are self-explanatory markdown that Claude understands natively. No additional template text is needed to explain sections.

---

## Function Composition

### Call Graph (updated)

```
PostToolUseHook / StopHook
    --> load_playbook()               # reads playbook.json, detects format, migrates if needed
        --> _default_playbook()       # empty sections-based playbook
        --> generate_keypoint_name()  # (during scoring migration of bare strings)
    --> load_transcript()             # reads session transcript (unchanged)
    --> extract_keypoints()           # calls LLM to evaluate key points
        --> _build_playbook_dict()    # flat {name: text} from all sections
    --> update_playbook_data()        # applies increments + pruning across sections
        --> _resolve_section()        # normalize section names from LLM
        --> generate_keypoint_name()  # per-section slug-based ID generation
    --> save_playbook()               # writes playbook.json (asserts sections key)

PreToolUseHook (context injection)
    --> load_playbook()               # reads playbook.json
    --> format_playbook()             # formats with section headers for injection
        --> load_template()           # reads playbook.txt (unchanged)
```

### Data Flow

```
playbook.json on disk
    |
    v
load_playbook()
    |  detects format: sections? flat key_points? dual-key?
    |  applies scoring migration (if flat format)
    |  migrates flat -> sections (all entries to OTHERS)
    |
    v
playbook dict {version, last_updated, sections: {name: [entries]}}
    |
    +--[injection path]--> format_playbook(playbook)
    |                         |  iterates sections in canonical order
    |                         |  emits "## SECTION_NAME" headers
    |                         |  omits empty sections
    |                         v
    |                      formatted string --> playbook.txt template --> prompt
    |
    +--[update path]----> update_playbook_data(playbook, extraction_result)
                              |
                              +--> resolve section names (_resolve_section)
                              +--> add new key points to target sections (slug-based IDs)
                              +--> build cross-section name lookup
                              +--> increment counters per evaluations
                              +--> prune across all sections
                              +--> return modified playbook
                              |
                              v
                          save_playbook(playbook)
                              |  assert "sections" in playbook
                              v
                          playbook.json on disk
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
| LLM API (extract_keypoints) | Not changed by this task | Not relevant to sections tests |
| `SECTION_SLUGS` constant | Importable from `common.py` | Tests can reference directly for canonical names/slugs |

### Test Strategy for Migration

Tests for `load_playbook()` sections migration should:
1. Create a temp directory
2. Set `CLAUDE_PROJECT_DIR` to the temp directory
3. Write a `playbook.json` with flat `key_points` format (various legacy entry types)
4. Call `load_playbook()`
5. Assert the returned dict has `sections` key with all entries in OTHERS
6. Assert original IDs are preserved (INV-SECT-004)
7. Assert no `key_points` key in the returned dict (INV-SECT-007)

### Test Strategy for Dual-Key Handling

1. Write a `playbook.json` with both `sections` and `key_points` keys
2. Call `load_playbook()`
3. Assert `sections` data is used, `key_points` data is ignored
4. If diagnostic mode enabled, assert diagnostic file was written

### Test Strategy for Section-Based Updates

Tests for `update_playbook_data()` should:
1. Construct a sections-based playbook dict directly (no file I/O)
2. Construct new_key_points as `list[dict]` with `text` and `section` fields
3. Call `update_playbook_data(playbook, new_key_points, evaluations)`
4. Assert new entries are in the correct sections with correct slug-prefixed IDs
5. Assert evaluations modify entries regardless of which section they are in

### Test Strategy for Section Name Resolution

Tests for `_resolve_section()` should verify:
- Exact match: `"PATTERNS & APPROACHES"` -> `"PATTERNS & APPROACHES"`
- Case-insensitive: `"patterns & approaches"` -> `"PATTERNS & APPROACHES"`
- Unknown: `"RANDOM"` -> `"OTHERS"`
- Empty/None: `""` -> `"OTHERS"`, `None` -> `"OTHERS"`

### Test Strategy for Format Output Overhead

Tests for CON-SECT-004 should:
1. Create a synthetic playbook with 20 entries distributed across all 5 sections (4 per section)
2. Format with `format_playbook()` to get sections-based output
3. Compute flat-list equivalent (same entries, no headers)
4. Assert `len(sections_output) <= len(flat_output) * 1.20`

### Test Strategy for generate_keypoint_name

Tests should verify:
1. Empty section: `generate_keypoint_name([], "pat")` -> `"pat-001"`
2. Existing entries: `generate_keypoint_name([{name: "pat-003"}], "pat")` -> `"pat-004"`
3. Legacy entries ignored: `generate_keypoint_name([{name: "kpt_001"}, {name: "oth-002"}], "oth")` -> `"oth-003"`

---

## Instrumentation Hooks

### Diagnostic Pattern (OBS-SECT-001, OBS-SECT-002)

This module continues to use the existing diagnostic pattern (`is_diagnostic_mode()` + `save_diagnostic()`) consistent with the scoring module.

| OBS-* | Diagnostic File Name | When Written | Content |
|-------|---------------------|--------------|---------|
| OBS-SECT-001 | `sections_migration` | When `load_playbook()` migrates a flat `key_points` array to `sections` format | Count of migrated entries |
| OBS-SECT-002 | `sections_unknown_section` | When `update_playbook_data()` encounters an unrecognized section name from the LLM and falls back to OTHERS | Original section name from LLM, key point text (truncated to 80 chars) |
| (dual-key) | `sections_dual_key_warning` | When `load_playbook()` detects both `sections` and `key_points` keys | Warning message |
| (scoring carry-forward) | `playbook_migration` | When scoring-level migration occurs within flat-format entries | Same as LOG-SCORE-001 |
| (scoring carry-forward) | `playbook_pruning` | When pruning removes entries | Same as LOG-SCORE-002 |

### Wiring

All diagnostic outputs are gated by `is_diagnostic_mode()` and written via `save_diagnostic()`. No new instrumentation infrastructure is needed.
