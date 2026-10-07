#!/bin/bash
# SubagentStop hook: blocks session end if a task is still in progress.
# Exit 0 = allow (task was completed or never started)
# Exit 2 = block (task started but not done — message fed back to agent)

ACTIVE_TASK=".ydk/active-task.json"

# From a linked worktree (.ydk/worktrees/<id>) active-task.json lives in the
# main checkout: the parent of the shared (common) .git dir. In the main
# checkout or outside git, keep the cwd-relative path.
WT_GIT_DIR=$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)
WT_COMMON_DIR=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
if [ -n "$WT_COMMON_DIR" ] && [ "$WT_GIT_DIR" != "$WT_COMMON_DIR" ]; then
    ACTIVE_TASK="$(dirname "$WT_COMMON_DIR")/.ydk/active-task.json"
fi

if [ ! -f "$ACTIVE_TASK" ]; then
    # No active task — session can end normally
    exit 0
fi

# active-task.json is keyed by task_id (multiple tasks can be in flight at
# once), so list every task still recorded there rather than a single slot.
TASK_IDS=$(python3 -c "import json, sys; print(','.join(json.load(open(sys.argv[1])).get('tasks', {})))" "$ACTIVE_TASK" 2>/dev/null)

if [ -z "$TASK_IDS" ]; then
    exit 0
fi

echo "BLOCKED: Task(s) $TASK_IDS still in progress."
echo ""
echo "You must complete the task before finishing:"
echo "  1. Ensure all tests pass"
echo "  2. Ensure lint is clean"
echo "  3. Run: ydk task done <task-id>"
echo ""
echo "The session cannot end until the task is properly completed with a PR."
exit 2
