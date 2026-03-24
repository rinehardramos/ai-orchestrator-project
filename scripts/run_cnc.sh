#!/usr/bin/env bash
# run_cnc.sh — Standard entry point for Genesis Node (CNC) with auto-restart on memory crash.

VENV_PYTHON="venv/bin/python3"
MAIN_SCRIPT="main.py"

# If venv doesn't exist, try system python
if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "🚀 Starting Gemini CLI (CNC Node)..."

while true; do
    # Run the main script with all arguments passed to this wrapper
    PYTHONPATH=. $VENV_PYTHON $MAIN_SCRIPT "$@"
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "✅ Genesis Node finished successfully."
        break
    elif [ $EXIT_CODE -eq 137 ]; then
        echo "⚠️  [WATCHDOG] CNC Node exited due to memory pressure (137). Saving state and restarting..."
    else
        echo "❌ [WATCHDOG] CNC Node crashed with exit code $EXIT_CODE."
        # If it's a normal error, don't restart immediately to avoid tight loops
        read -p "Press [Enter] to restart, or [Ctrl+C] to abort..."
    fi

    echo "🔄 Restarting in 3 seconds..."
    sleep 3
done
