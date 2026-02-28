#!/bin/bash
# LEANN Search Manager — Reindex Script
# Reads config.yaml, builds/updates the LEANN index.
# Used by launchd for periodic reindexing and by the GUI for manual triggers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${LEANN_SEARCH_CONFIG:-$HOME/.leann-search/config.yaml}"
LEANN_BIN="${LEANN_BIN:-$HOME/.local/bin/leann}"
LOG_FILE="${LEANN_SEARCH_LOG:-$HOME/.leann-search/reindex.log}"
LOCK_FILE="$HOME/.leann-search/.reindex.lock"
STATUS_FILE="$HOME/.leann-search/status.json"

# Use project venv python (has PyYAML) or fall back to system python3
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

# --- Helpers ---

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

write_status() {
  local status="$1"
  local message="${2:-}"
  cat > "$STATUS_FILE" <<EOF
{
  "status": "$status",
  "message": "$message",
  "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "pid": $$
}
EOF
}

cleanup() {
  rm -f "$LOCK_FILE"
  if [ "${1:-}" = "error" ]; then
    write_status "error" "Reindex failed"
  fi
}
trap 'cleanup error' ERR
trap 'rm -f "$LOCK_FILE"' EXIT

# --- Preflight ---

if [ ! -f "$CONFIG_FILE" ]; then
  log "ERROR: Config file not found: $CONFIG_FILE"
  write_status "error" "Config file not found"
  exit 1
fi

if [ ! -x "$LEANN_BIN" ] && ! command -v leann &>/dev/null; then
  log "ERROR: leann binary not found at $LEANN_BIN"
  write_status "error" "leann binary not found"
  exit 1
fi

if [ -f "$LOCK_FILE" ]; then
  OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    log "SKIP: Reindex already running (pid $OLD_PID)"
    exit 0
  fi
  log "WARN: Stale lock file removed"
  rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"

# --- Parse Config (using python for YAML) ---

read_config() {
  $PYTHON -c "
import yaml, os, json

with open('$CONFIG_FILE') as f:
    cfg = yaml.safe_load(f)

# Expand ~ in paths
work_dir = os.path.expanduser(cfg.get('work_dir', '~/.leann-search'))
index_name = cfg.get('index_name', 'mac-search')

# Collect enabled folders
folders = []
for f_entry in cfg.get('folders', []):
    if f_entry.get('enabled', True):
        path = os.path.expanduser(f_entry['path'])
        if os.path.isdir(path):
            folders.append(path)

# Collect enabled file types
extensions = []
for group_name, group in cfg.get('file_types', {}).items():
    if group.get('enabled', False):
        extensions.extend(group.get('extensions', []))

# Build options
build_opts = cfg.get('build_options', {})
backend = build_opts.get('backend', 'hnsw')
compact = build_opts.get('compact', False)
embedding_model = build_opts.get('embedding_model', 'facebook/contriever')

# Settings
settings = cfg.get('settings', {})
pause_on_battery = settings.get('pause_on_battery', True)
max_log_size_mb = settings.get('max_log_size_mb', 50)

result = {
    'work_dir': work_dir,
    'index_name': index_name,
    'folders': folders,
    'extensions': ','.join(extensions) if extensions else '',
    'backend': backend,
    'compact': compact,
    'embedding_model': embedding_model,
    'pause_on_battery': pause_on_battery,
    'max_log_size_mb': max_log_size_mb,
}
print(json.dumps(result))
"
}

CONFIG_JSON=$(read_config)
WORK_DIR=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['work_dir'])")
INDEX_NAME=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['index_name'])")
FOLDERS=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(' '.join(json.load(sys.stdin)['folders']))")
EXTENSIONS=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['extensions'])")
BACKEND=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['backend'])")
COMPACT=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['compact'])")
EMBEDDING_MODEL=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['embedding_model'])")

if [ -z "$FOLDERS" ]; then
  log "SKIP: No enabled folders found in config"
  write_status "idle" "No folders configured"
  exit 0
fi

# --- Battery Check ---

PAUSE_ON_BATTERY=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('pause_on_battery', True))" 2>/dev/null || echo "True")

if [ "$PAUSE_ON_BATTERY" = "True" ] || [ "$PAUSE_ON_BATTERY" = "true" ]; then
  POWER_SOURCE=$(pmset -g batt 2>/dev/null | head -1 || echo "")
  if echo "$POWER_SOURCE" | grep -q "Battery Power"; then
    log "SKIP: Running on battery power (pause_on_battery=true)"
    write_status "idle" "Paused: on battery power"
    exit 0
  fi
fi

# --- Log Rotation ---

MAX_LOG_MB=$(echo "$CONFIG_JSON" | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('max_log_size_mb', 50))" 2>/dev/null || echo "50")
if [ -f "$LOG_FILE" ]; then
  LOG_SIZE_MB=$(( $(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0) / 1048576 ))
  if [ "$LOG_SIZE_MB" -ge "$MAX_LOG_MB" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.old"
    log "Log rotated (was ${LOG_SIZE_MB}MB, limit ${MAX_LOG_MB}MB)"
  fi
fi

# --- Build Index ---

mkdir -p "$WORK_DIR"

log "Starting reindex: index=$INDEX_NAME folders=$FOLDERS"
write_status "indexing" "Indexing in progress..."

BUILD_CMD="$LEANN_BIN build $INDEX_NAME --docs $FOLDERS --backend-name $BACKEND --embedding-model $EMBEDDING_MODEL"

if [ -n "$EXTENSIONS" ]; then
  BUILD_CMD="$BUILD_CMD --file-types $EXTENSIONS"
fi

if [ "$COMPACT" = "False" ] || [ "$COMPACT" = "false" ]; then
  BUILD_CMD="$BUILD_CMD --no-compact"
fi

START_TIME=$(date +%s)

cd "$WORK_DIR"
log "Running: $BUILD_CMD"
eval "$BUILD_CMD" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

if [ $EXIT_CODE -eq 0 ]; then
  log "Reindex completed in ${DURATION}s"
  write_status "idle" "Last reindex: ${DURATION}s ($(date '+%H:%M'))"
else
  log "ERROR: Reindex failed with exit code $EXIT_CODE"
  write_status "error" "Build failed (exit $EXIT_CODE)"
  exit $EXIT_CODE
fi
