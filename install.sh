#!/bin/bash
# LEANN Search Manager — Installer
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.leann-search"
RAYCAST_DIR="$HOME/.raycast-scripts"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "📦 LEANN Search Manager — Installer"
echo "===================================="

# 1. Check prerequisites
echo ""
echo "🔍 Checking prerequisites..."

if ! command -v leann &>/dev/null && [ ! -x "$HOME/.local/bin/leann" ]; then
  echo "❌ leann CLI not found. Install it first:"
  echo "   uv tool install leann-core --with leann"
  exit 1
fi
echo "  ✅ leann CLI found"

if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found"
  exit 1
fi
echo "  ✅ python3 found"

# 2. Create venv and install dependencies
echo ""
echo "🐍 Setting up Python environment..."
if [ ! -d "$PROJECT_DIR/.venv" ]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
echo "  ✅ Dependencies installed"

# 3. Create config directory
echo ""
echo "📁 Setting up config..."
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  cp "$PROJECT_DIR/config.yaml" "$CONFIG_DIR/config.yaml"
  echo "  ✅ Default config created at $CONFIG_DIR/config.yaml"
else
  echo "  ⏭  Config already exists, skipping"
fi

# 4. Make scripts executable
chmod +x "$PROJECT_DIR/reindex.sh"
chmod +x "$PROJECT_DIR/raycast-scripts/"*.sh

# 5. Install Raycast script commands
echo ""
echo "🔮 Installing Raycast scripts..."
mkdir -p "$RAYCAST_DIR"
cp "$PROJECT_DIR/raycast-scripts/leann-search.sh" "$RAYCAST_DIR/"
cp "$PROJECT_DIR/raycast-scripts/leann-manager.sh" "$RAYCAST_DIR/"
chmod +x "$RAYCAST_DIR/"*.sh
echo "  ✅ Scripts copied to $RAYCAST_DIR"
echo "  ⚠️  Add $RAYCAST_DIR to Raycast → Settings → Script Commands → Add Directories"

# 6. Install launchd agent
echo ""
echo "⏰ Setting up background reindexing..."
mkdir -p "$LAUNCH_AGENTS"

# Update plist with correct paths
sed "s|/Users/kgory/dev/leann-search-manager|$PROJECT_DIR|g; s|/Users/kgory|$HOME|g" \
  "$PROJECT_DIR/com.leann.reindex.plist" > "$LAUNCH_AGENTS/com.leann.reindex.plist"

echo "  ✅ launchd plist installed"
echo ""
read -p "  Start background reindexing now? (y/N): " START_AGENT
if [ "$START_AGENT" = "y" ] || [ "$START_AGENT" = "Y" ]; then
  launchctl unload "$LAUNCH_AGENTS/com.leann.reindex.plist" 2>/dev/null || true
  launchctl load "$LAUNCH_AGENTS/com.leann.reindex.plist"
  echo "  ✅ Background reindexing started (every 30 minutes)"
else
  echo "  ⏭  Skipped. Start later with:"
  echo "     launchctl load ~/Library/LaunchAgents/com.leann.reindex.plist"
fi

echo ""
echo "✨ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Open the manager:  $PROJECT_DIR/.venv/bin/python $PROJECT_DIR/manager.py"
echo "  2. Or from Raycast:   Search 'LEANN Manager'"
echo "  3. Add folders and file types in the GUI"
echo "  4. Click 'Reindex Now' to build your first index"
echo "  5. Search from Raycast: 'LEANN Search'"
