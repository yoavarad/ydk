#!/bin/bash
# SubagentStop hook: blocks session end if a task is still in progress.
# Exit 0 = allow (task was completed or never started)
# Exit 2 = block (task started but not done — message fed back to agent)

ACTIVE_TASK=".odk/active-task.json"

if [ ! -f "$ACTIVE_TASK" ]; then
    # No active task — session can end normally
    exit 0
fi

# Task is still in progress
TASK_ID=$(python3 -c "import json; print(json.load(open('$ACTIVE_TASK'))['task_id'])" 2>/dev/null)

if [ -z "$TASK_ID" ]; then
    exit 0
fi

echo "BLOCKED: Task $TASK_ID is still in progress."
echo ""
echo "You must complete the task before finishing:"
echo "  1. Ensure all tests pass"
echo "  2. Ensure lint is clean"
echo "  3. Run: odk task done $TASK_ID"
echo ""
echo "The session cannot end until the task is properly completed with a PR."
exit 2
