# Bootstrap Playbook

Analyze all historic session transcripts for this project and use them to build up the playbook with accumulated insights.

## Instructions

Run the bootstrap playbook script. The script will:
1. Discover all session transcripts for this project
2. Process each transcript chronologically through the reflector/curator pipeline
3. Build up the playbook cumulatively, saving after each session

Execute this command:

```bash
uv run --project $CLAUDE_PROJECT_DIR python ~/.claude/hooks/bootstrap_playbook.py
```

Report the output to the user. The script prints progress to stderr showing discovery, per-session processing, and a final summary.

If the script reports an error (missing API key, missing templates, etc.), inform the user of the issue and suggest remediation.

This is a long-running operation (may take 30-60+ minutes for projects with many sessions). The script saves progress after each session, so it can be interrupted and resumed.
