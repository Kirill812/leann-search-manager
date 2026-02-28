# LEANN Search Manager

A macOS GUI application and Raycast integration for [LEANN](https://github.com/yichuan-w/LEANN) — the lightweight vector database that uses 97% less storage than traditional solutions.

**Replace Spotlight with semantic search.** Index your documents, code, and notes, then search by *meaning* instead of keywords — all locally on your Mac.

## Features

- **📁 Folder Manager** — Add/remove folders with native macOS file picker, toggle indexing per folder
- **📄 File Type Filters** — Grouped by Documents, Text, Code with per-extension checkboxes + custom extensions
- **📊 Index Statistics** — Size, file count, chunk count, backend info, last indexed time, incremental update status
- **🔄 Background Reindexing** — Automatic periodic reindexing via macOS launchd (configurable interval)
- **🔍 Raycast Integration** — Semantic search directly from Raycast with one keystroke
- **🔒 100% Private** — Everything runs locally, no cloud, no telemetry

## Prerequisites

- macOS 13.3+
- [LEANN CLI](https://github.com/yichuan-w/LEANN) installed globally:
  ```bash
  uv tool install leann-core --with leann
  ```
- Python 3.10+
- [Raycast](https://raycast.com) (optional, for search integration)

## Installation

```bash
git clone https://github.com/kgory/leann-search-manager.git
cd leann-search-manager
bash install.sh
```

The installer will:
1. Create a Python venv and install PyQt6
2. Copy default config to `~/.leann-search/config.yaml`
3. Install Raycast Script Commands to `~/.raycast-scripts/`
4. Set up a launchd agent for background reindexing

## Usage

### GUI Manager

Launch the manager from terminal:
```bash
./venv/bin/python manager.py
```

Or from Raycast — search for **"LEANN Manager"**.

The manager has three tabs:

| Tab | What it does |
|-----|-------------|
| **📁 Folders** | Add/remove/toggle folders to index via native file picker |
| **📄 File Types** | Enable file type groups (Documents, Text, Code) or individual extensions |
| **📊 Stats** | View index stats, trigger manual reindex, view logs |

### Raycast Search

After building an index, search from Raycast:

1. Open Raycast (⌘ Space)
2. Type **"LEANN Search"**
3. Enter your semantic query

### Configuration

Edit `~/.leann-search/config.yaml` directly or use the GUI:

```yaml
index_name: mac-search
work_dir: ~/.leann-search

folders:
  - path: ~/Documents
    enabled: true
  - path: ~/dev
    enabled: false

file_types:
  documents:
    enabled: true
    extensions: [.pdf, .docx, .xlsx, .pptx, .doc, .rtf]
  text:
    enabled: true
    extensions: [.md, .txt, .csv, .json, .yaml, .yml, .toml, .xml]
  code:
    enabled: false
    extensions: [.py, .js, .ts, .vue, .html, .css, .sh, .go, .rs, .java, .rb, .ipynb]

reindex_interval_minutes: 30

build_options:
  backend: hnsw
  compact: false        # false enables incremental updates
  embedding_model: facebook/contriever
```

### Background Reindexing

The launchd agent runs reindexing every 30 minutes (configurable). Manage it with:

```bash
# Start
launchctl load ~/Library/LaunchAgents/com.leann.reindex.plist

# Stop
launchctl unload ~/Library/LaunchAgents/com.leann.reindex.plist

# Run manually
bash reindex.sh
```

Logs are written to `~/.leann-search/reindex.log`.

## Architecture

```
~/.leann-search/
├── config.yaml          # User configuration
├── status.json          # Current indexing status (read by GUI)
├── reindex.log          # Build/update logs
└── .leann/
    └── indexes/
        └── mac-search/  # LEANN index files
            ├── documents.leann
            ├── documents.leann.meta.json
            └── documents.leann.passages.jsonl

~/dev/leann-search-manager/  # This project
├── manager.py               # PyQt6 GUI
├── reindex.sh               # Reindex script (reads config, calls leann build)
├── config.yaml              # Default config template
├── install.sh               # One-step installer
├── com.leann.reindex.plist  # launchd template
├── requirements.txt
└── raycast-scripts/
    ├── leann-search.sh      # Raycast: semantic search
    └── leann-manager.sh     # Raycast: open GUI
```

### How Reindexing Works

LEANN supports **incremental updates** when built with `--no-compact`:
- **New files** → added without full rebuild
- **Modified/removed files** → triggers full rebuild (LEANN limitation)

The `reindex.sh` script:
1. Reads enabled folders and file types from `config.yaml`
2. Acquires a lock file (prevents parallel runs)
3. Runs `leann build` in the work directory
4. LEANN detects changes and does minimal work
5. Writes status to `status.json` (read by the GUI)

## License

MIT
