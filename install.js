#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// Color output helpers
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  red: '\x1b[31m',
};

function log(msg, color = 'reset') {
  console.log(`${colors[color]}${msg}${colors.reset}`);
}

// Get paths
const homeDir = os.homedir();
const claudeDir = path.join(homeDir, '.claude');
const hooksDir = path.join(claudeDir, 'hooks');
const settingsPath = path.join(claudeDir, 'settings.json');
const sourceDir = path.join(__dirname, 'src');

// Ensure directory exists
function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

// Copy directory recursively (excluding settings.json)
function copyDir(src, dest) {
  ensureDir(dest);
  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else if (entry.name !== 'settings.json') {
      // Skip settings.json (handled separately)
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// Merge settings.json
//
// @implements REQ-HOOKS-001, REQ-HOOKS-003, REQ-HOOKS-005, REQ-HOOKS-006
// @invariant INV-HOOKS-001 (exactly one project hook per event type)
// @invariant INV-HOOKS-002 (non-project hooks never modified)
// @invariant INV-HOOKS-005 (non-hook settings preserved)
// @invariant INV-HOOKS-006 (timeout values unchanged)
// @invariant INV-HOOKS-007 (valid JSON output via JSON.stringify)
function mergeSettings(srcSettingsPath, absUvPath, projectDir) {
  // Load source settings with placeholder replacement
  let srcSettings = {};
  if (fs.existsSync(srcSettingsPath)) {
    try {
      let content = fs.readFileSync(srcSettingsPath, 'utf-8');

      // Replace placeholders with actual hook commands
      // REQ-HOOKS-003: command format is <abs_uv_path> run --project "<abs_project_dir>" python "<abs_script_path>"
      const hooks = {
        'HOOK_COMMAND_USER_PROMPT_INJECT': 'user_prompt_inject.py',
        'HOOK_COMMAND_SESSION_END': 'session_end.py',
        'HOOK_COMMAND_PRECOMPACT': 'precompact.py'
      };

      for (const [placeholder, scriptName] of Object.entries(hooks)) {
        const command = `${absUvPath} run --project "${projectDir}" python "${path.join(hooksDir, scriptName)}"`;
        content = content.replace(
          new RegExp(`\\{\\{${placeholder}\\}\\}`, 'g'),
          JSON.stringify(command).slice(1, -1)
        );
      }

      srcSettings = JSON.parse(content);
    } catch (e) {
      log(`⚠ Failed to parse source settings: ${e.message}`, 'yellow');
    }
  }

  // Load destination settings
  let destSettings = {};
  if (fs.existsSync(settingsPath)) {
    try {
      destSettings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
    } catch (e) {
      log(`⚠ Failed to parse destination settings: ${e.message}`, 'yellow');
    }
  }

  // REQ-HOOKS-005: Remove all stale project hook entries before adding new ones
  // Order: remove stale FIRST, then add new (critical for idempotency per INV-HOOKS-001)
  const projectScripts = ['user_prompt_inject.py', 'session_end.py', 'precompact.py'];
  const matchingSubstrings = projectScripts.map(s => `/.claude/hooks/${s}`);

  if (destSettings.hooks) {
    for (const eventName of Object.keys(destSettings.hooks)) {
      for (const group of destSettings.hooks[eventName]) {
        // Per spec algorithm: group.hooks is always an array in valid settings.json (no null guard needed)
        group.hooks = group.hooks.filter(hook =>
          !matchingSubstrings.some(sub => hook.command.includes(sub))
        );
      }
      destSettings.hooks[eventName] = destSettings.hooks[eventName].filter(
        group => group.hooks && group.hooks.length > 0
      );
    }
  }

  // Merge hooks (add new entries after stale removal)
  if (srcSettings.hooks) {
    if (!destSettings.hooks) {
      destSettings.hooks = {};
    }

    for (const [eventName, eventHooks] of Object.entries(srcSettings.hooks)) {
      if (!destSettings.hooks[eventName]) {
        destSettings.hooks[eventName] = [];
      }

      for (const hookGroup of eventHooks) {
        if (hookGroup.hooks && hookGroup.hooks.length > 0) {
          destSettings.hooks[eventName].push(hookGroup);
        }
      }
    }
  }

  // INV-HOOKS-005: Merge other top-level properties (preserve existing, add new only)
  for (const [key, value] of Object.entries(srcSettings)) {
    if (key !== 'hooks' && !(key in destSettings)) {
      destSettings[key] = value;
    }
  }

  return destSettings;
}

// Save settings.json
function saveSettings(settings) {
  ensureDir(path.dirname(settingsPath));
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2), 'utf-8');
}

// Main installation function
//
// @implements REQ-HOOKS-002, REQ-HOOKS-004, REQ-HOOKS-007, REQ-HOOKS-008, REQ-HOOKS-009
// @invariant INV-HOOKS-003 (all paths are absolute)
// @invariant INV-HOOKS-004 (no file modification on error)
function install() {
  log('\n=== Agentic Context Engineering Installation ===\n', 'blue');

  try {
    // Step 1: Check source directory
    if (!fs.existsSync(sourceDir)) {
      log('❌ Source directory not found!', 'red');
      process.exit(1);
    }
    log('✓ Found source directory', 'green');

    // Step 2: Check for uv and resolve absolute path (REQ-HOOKS-007, REQ-HOOKS-008)
    // This MUST happen before any file operations (INV-HOOKS-004)
    let absUvPath;
    try {
      absUvPath = execSync('which uv').toString().trim();
    } catch (_e) {
      process.stderr.write(
        "Error: 'uv' is not installed or not found on PATH. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh\n" +
        "See https://docs.astral.sh/uv/getting-started/installation/ for other methods.\n"
      );
      process.exit(1);
    }
    log(`✓ Found uv at ${absUvPath}`, 'green');

    // Step 3: Run uv sync (REQ-HOOKS-009)
    // This MUST happen before file copy or settings merge (INV-HOOKS-004)
    const projectDir = __dirname;
    try {
      execSync(`${absUvPath} sync --project "${projectDir}"`, { stdio: 'inherit' });
    } catch (e) {
      process.stderr.write(
        `Error: uv sync failed with exit code ${e.status}.\n` +
        `Try running manually: uv sync --project "${projectDir}"\n`
      );
      process.exit(1);
    }
    log('✓ Dependencies synced with uv', 'green');

    // Step 4: Copy hooks and prompts to ~/.claude/
    log(`ℹ Copying files to ${claudeDir}...`, 'blue');
    copyDir(sourceDir, claudeDir);
    log('✓ Files copied to ~/.claude/', 'green');

    // Step 5: Merge settings.json
    log('ℹ Merging settings.json...', 'blue');
    const srcSettingsPath = path.join(sourceDir, 'settings.json');
    if (fs.existsSync(srcSettingsPath)) {
      const mergedSettings = mergeSettings(srcSettingsPath, absUvPath, projectDir);
      saveSettings(mergedSettings);
      log('✓ Settings merged successfully', 'green');
    } else {
      log('⚠ No settings.json found in source directory', 'yellow');
    }

    // Step 6: Display installation results
    log('\n=== Installation Complete! ===\n', 'green');
    log('ℹ Hook files installed to:', 'blue');
    console.log(`  ${claudeDir}/hooks/`);
    console.log(`  ${claudeDir}/prompts/`);
    log('ℹ User settings updated at:', 'blue');
    console.log(`  ${settingsPath}\n`);
    log('📝 Next steps:', 'yellow');
    console.log('1. Restart Claude Code or start a new session');
    console.log('2. Hooks are now active at user level (work across all projects)');
    console.log('3. Check ~/.claude/settings.json to verify hook registration');

  } catch (err) {
    log(`❌ Installation failed: ${err.message}`, 'red');
    console.error(err);
    process.exit(1);
  }
}

// Export mergeSettings for test access (per spec testability section)
module.exports = { mergeSettings };

// Run installation
install();
