#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title LEANN Search
# @raycast.mode fullOutput

# Optional parameters:
# @raycast.icon 🔍
# @raycast.argument1 { "type": "text", "placeholder": "Search query" }
# @raycast.argument2 { "type": "text", "placeholder": "Index name (optional)", "optional": true }
# @raycast.packageName LEANN

# Documentation:
# @raycast.description Semantic search across your LEANN indexes
# @raycast.author kgory

LEANN_BIN="$HOME/.local/bin/leann"
CONFIG_FILE="$HOME/.leann-search/config.yaml"

query="$1"
index_name="$2"

if [ -z "$query" ]; then
  echo "Error: Please provide a search query."
  exit 1
fi

# Read work_dir and default index name from config
if [ -f "$CONFIG_FILE" ]; then
  WORK_DIR=$(python3 -c "
import yaml, os
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
print(os.path.expanduser(cfg.get('work_dir', '~/.leann-search')))
" 2>/dev/null)
  if [ -z "$index_name" ]; then
    index_name=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('index_name', 'mac-search'))
" 2>/dev/null)
  fi
else
  WORK_DIR="$HOME/.leann-search"
fi

if [ -z "$index_name" ]; then
  index_name="mac-search"
fi

# cd to work dir so leann finds the index
cd "$WORK_DIR" 2>/dev/null || cd "$HOME"

INDEX_DIR="$WORK_DIR/.leann/indexes/$index_name"
if [ ! -d "$INDEX_DIR" ]; then
  echo "Index '$index_name' not found at $INDEX_DIR"
  echo ""
  echo "Build it first using the LEANN Manager or run:"
  echo "  cd $WORK_DIR && leann build $index_name --docs ~/Documents"
  exit 1
fi

echo "🔍 Query: $query"
echo "📁 Index: $index_name"
echo "---"

"$LEANN_BIN" search "$index_name" "$query" --top-k 5 --show-metadata 2>/dev/null \
  | grep -v '^\[read_HNSW' \
  | grep -v '^INFO:' \
  | grep -v '^ZmqDistance'
