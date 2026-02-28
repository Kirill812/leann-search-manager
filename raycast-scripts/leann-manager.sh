#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title LEANN Manager
# @raycast.mode silent

# Optional parameters:
# @raycast.icon ⚙️
# @raycast.packageName LEANN

# Documentation:
# @raycast.description Open LEANN Search Manager GUI
# @raycast.author kgory

MANAGER_SCRIPT="$HOME/dev/leann-search-manager/manager.py"
PYTHON="$HOME/dev/leann-search-manager/.venv/bin/python"

if [ ! -f "$MANAGER_SCRIPT" ]; then
  echo "Manager not found at $MANAGER_SCRIPT"
  exit 1
fi

if [ -x "$PYTHON" ]; then
  "$PYTHON" "$MANAGER_SCRIPT" &
else
  python3 "$MANAGER_SCRIPT" &
fi

disown
