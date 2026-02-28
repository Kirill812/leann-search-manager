#!/usr/bin/env python3
"""LEANN Search Manager — macOS GUI for managing LEANN indexes."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from PyQt6.QtCore import QProcess, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# --- Constants ---

DEFAULT_CONFIG_PATH = Path.home() / ".leann-search" / "config.yaml"
DEFAULT_STATUS_PATH = Path.home() / ".leann-search" / "status.json"
DEFAULT_LOG_PATH = Path.home() / ".leann-search" / "reindex.log"
LEANN_BIN = Path.home() / ".local" / "bin" / "leann"
REINDEX_SCRIPT = Path(__file__).parent / "reindex.sh"

FILE_TYPE_GROUPS = {
    "documents": {
        "label": "📄 Documents",
        "extensions": [".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".rtf"],
    },
    "text": {
        "label": "📝 Text",
        "extensions": [".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".toml", ".xml"],
    },
    "code": {
        "label": "💻 Code",
        "extensions": [
            ".py", ".js", ".ts", ".vue", ".html", ".css",
            ".sh", ".go", ".rs", ".java", ".rb", ".ipynb",
        ],
    },
}


# --- Config ---

def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg: dict, path: Path = DEFAULT_CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_work_dir(cfg: dict) -> Path:
    return Path(os.path.expanduser(cfg.get("work_dir", "~/.leann-search")))


# --- Stats helpers ---

def get_index_stats(cfg: dict) -> dict:
    """Read index metadata and compute stats."""
    work_dir = get_work_dir(cfg)
    index_name = cfg.get("index_name", "mac-search")
    index_dir = work_dir / ".leann" / "indexes" / index_name

    stats = {
        "index_exists": False,
        "index_size_mb": 0,
        "num_files": 0,
        "num_chunks": 0,
        "backend": "—",
        "embedding_model": "—",
        "last_modified": "—",
        "is_compact": None,
        "is_recompute": None,
    }

    if not index_dir.exists():
        return stats

    stats["index_exists"] = True

    # Total index size
    total_size = sum(f.stat().st_size for f in index_dir.rglob("*") if f.is_file())
    stats["index_size_mb"] = round(total_size / (1024 * 1024), 2)

    # Last modified
    mtimes = [f.stat().st_mtime for f in index_dir.rglob("*") if f.is_file()]
    if mtimes:
        stats["last_modified"] = datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M")

    # Read meta.json
    meta_path = index_dir / "documents.leann.meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        stats["backend"] = meta.get("backend_name", "—")
        stats["embedding_model"] = meta.get("embedding_model", "—")
        stats["is_compact"] = meta.get("is_compact")
        stats["is_recompute"] = meta.get("is_pruned")

    # Count chunks from passages file
    passages_path = index_dir / "documents.leann.passages.jsonl"
    if passages_path.exists():
        chunk_count = 0
        files_seen = set()
        with open(passages_path) as f:
            for line in f:
                chunk_count += 1
                try:
                    obj = json.loads(line)
                    fp = obj.get("metadata", {}).get("file_path", "")
                    if fp:
                        files_seen.add(fp)
                except json.JSONDecodeError:
                    pass
        stats["num_chunks"] = chunk_count
        stats["num_files"] = len(files_seen)

    return stats


def get_status() -> dict:
    if DEFAULT_STATUS_PATH.exists():
        try:
            with open(DEFAULT_STATUS_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"status": "unknown", "message": "No status file found"}


def get_log_tail(n: int = 20) -> str:
    if DEFAULT_LOG_PATH.exists():
        with open(DEFAULT_LOG_PATH) as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    return "No log file yet."


def format_folder_size(path: str) -> str:
    """Get human-readable folder size (fast estimate: top-level only)."""
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return "not found"
    try:
        total = sum(f.stat().st_size for f in p.iterdir() if f.is_file())
        if total < 1024:
            return f"{total} B"
        elif total < 1024 * 1024:
            return f"{total // 1024} KB"
        elif total < 1024 * 1024 * 1024:
            return f"{total // (1024 * 1024)} MB"
        else:
            return f"{total / (1024 * 1024 * 1024):.1f} GB"
    except PermissionError:
        return "no access"


# --- Folders Tab ---

class FoldersTab(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Folder list
        self.folder_list = QListWidget()
        self.folder_list.setAlternatingRowColors(True)
        layout.addWidget(self.folder_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Folder")
        self.add_btn.clicked.connect(self._add_folder)
        self.remove_btn = QPushButton("− Remove")
        self.remove_btn.clicked.connect(self._remove_folder)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._populate()

    def _populate(self):
        self.folder_list.clear()
        for entry in self.cfg.get("folders", []):
            path = entry.get("path", "")
            enabled = entry.get("enabled", True)
            size = format_folder_size(path)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(4, 2, 4, 2)
            cb = QCheckBox()
            cb.setChecked(enabled)
            cb.stateChanged.connect(lambda state, p=path: self._toggle(p, state))
            label = QLabel(f"{path}")
            label.setFont(QFont("SF Mono", 12))
            size_label = QLabel(f"({size})")
            size_label.setStyleSheet("color: gray;")
            row.addWidget(cb)
            row.addWidget(label, 1)
            row.addWidget(size_label)
            item.setSizeHint(widget.sizeHint())
            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, widget)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder to Index")
        if path:
            # Collapse home dir
            home = str(Path.home())
            display_path = path.replace(home, "~") if path.startswith(home) else path
            folders = self.cfg.setdefault("folders", [])
            if not any(f["path"] == display_path for f in folders):
                folders.append({"path": display_path, "enabled": True})
                self._populate()
                self.config_changed.emit()

    def _remove_folder(self):
        current = self.folder_list.currentItem()
        if current:
            path = current.data(Qt.ItemDataRole.UserRole)
            self.cfg["folders"] = [
                f for f in self.cfg.get("folders", []) if f["path"] != path
            ]
            self._populate()
            self.config_changed.emit()

    def _toggle(self, path: str, state: int):
        for entry in self.cfg.get("folders", []):
            if entry["path"] == path:
                entry["enabled"] = state == Qt.CheckState.Checked.value
                break
        self.config_changed.emit()


# --- File Types Tab ---

class FileTypesTab(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        ft = self.cfg.setdefault("file_types", {})

        for group_key, group_info in FILE_TYPE_GROUPS.items():
            group = ft.setdefault(group_key, {
                "enabled": group_key != "code",
                "extensions": group_info["extensions"][:],
            })
            box = QGroupBox(group_info["label"])
            box_layout = QVBoxLayout(box)

            # Group-level checkbox
            group_cb = QCheckBox("Enable all")
            group_cb.setChecked(group.get("enabled", False))
            group_cb.stateChanged.connect(
                lambda state, gk=group_key: self._toggle_group(gk, state)
            )
            box_layout.addWidget(group_cb)

            # Individual extension checkboxes in a flow grid
            grid = QGridLayout()
            exts = group.get("extensions", group_info["extensions"])
            for i, ext in enumerate(exts):
                cb = QCheckBox(ext)
                cb.setChecked(group.get("enabled", False))
                cb.setProperty("group_key", group_key)
                cb.setProperty("ext", ext)
                grid.addWidget(cb, i // 4, i % 4)
            box_layout.addLayout(grid)
            layout.addWidget(box)

        # Custom extensions
        custom_group = ft.setdefault("custom", {"enabled": False, "extensions": []})
        custom_box = QGroupBox("🔧 Custom Extensions")
        custom_layout = QHBoxLayout(custom_box)
        custom_cb = QCheckBox("Enable")
        custom_cb.setChecked(custom_group.get("enabled", False))
        custom_cb.stateChanged.connect(
            lambda state: self._toggle_group("custom", state)
        )
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("e.g. .log,.env,.ini (comma-separated)")
        current_custom = ",".join(custom_group.get("extensions", []))
        if current_custom:
            self.custom_input.setText(current_custom)
        self.custom_input.editingFinished.connect(self._update_custom)
        custom_layout.addWidget(custom_cb)
        custom_layout.addWidget(self.custom_input, 1)
        layout.addWidget(custom_box)

        layout.addStretch()

    def _toggle_group(self, group_key: str, state: int):
        enabled = state == Qt.CheckState.Checked.value
        self.cfg.setdefault("file_types", {}).setdefault(group_key, {})["enabled"] = enabled
        self.config_changed.emit()

    def _update_custom(self):
        text = self.custom_input.text().strip()
        exts = [e.strip() for e in text.split(",") if e.strip()]
        exts = [e if e.startswith(".") else f".{e}" for e in exts]
        self.cfg.setdefault("file_types", {}).setdefault("custom", {})["extensions"] = exts
        self.config_changed.emit()


# --- Stats Tab ---

class StatsTab(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.reindex_process = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Status indicator
        status_box = QGroupBox("Status")
        status_layout = QHBoxLayout(status_box)
        self.status_icon = QLabel("⏸")
        self.status_icon.setFont(QFont("Apple Color Emoji", 24))
        self.status_label = QLabel("Loading...")
        self.status_label.setFont(QFont(".AppleSystemUIFont", 14))
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_label, 1)
        layout.addWidget(status_box)

        # Stats grid
        stats_box = QGroupBox("Index Statistics")
        grid = QGridLayout(stats_box)
        grid.setSpacing(8)

        self.stat_labels = {}
        stat_items = [
            ("index_size", "💾 Index Size"),
            ("num_files", "📄 Indexed Files"),
            ("num_chunks", "🧩 Total Chunks"),
            ("backend", "⚙️ Backend"),
            ("embedding_model", "🧠 Embedding Model"),
            ("last_modified", "🕐 Last Indexed"),
            ("incremental", "🔄 Incremental Updates"),
        ]
        for i, (key, label) in enumerate(stat_items):
            name = QLabel(label)
            name.setFont(QFont(".AppleSystemUIFont", 12))
            value = QLabel("—")
            value.setFont(QFont("SF Mono", 12))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, i, 0)
            grid.addWidget(value, i, 1)
            self.stat_labels[key] = value

        layout.addWidget(stats_box)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Actions
        actions_layout = QHBoxLayout()
        self.reindex_btn = QPushButton("🔄 Reindex Now")
        self.reindex_btn.clicked.connect(self._start_reindex)
        self.refresh_btn = QPushButton("↻ Refresh Stats")
        self.refresh_btn.clicked.connect(self.refresh)
        actions_layout.addWidget(self.reindex_btn)
        actions_layout.addWidget(self.refresh_btn)
        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        # Log viewer
        log_box = QGroupBox("Recent Log")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QLabel()
        self.log_text.setFont(QFont("SF Mono", 10))
        self.log_text.setWordWrap(True)
        self.log_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.log_text.setStyleSheet("color: #666; padding: 4px;")
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_box)

        layout.addStretch()
        self.refresh()

    def refresh(self):
        stats = get_index_stats(self.cfg)
        status = get_status()

        # Status
        s = status.get("status", "unknown")
        icons = {"idle": "✅", "indexing": "⏳", "error": "❌", "unknown": "❓"}
        self.status_icon.setText(icons.get(s, "❓"))
        self.status_label.setText(status.get("message", s))

        # Stats
        if stats["index_exists"]:
            self.stat_labels["index_size"].setText(f"{stats['index_size_mb']} MB")
            self.stat_labels["num_files"].setText(f"{stats['num_files']:,}")
            self.stat_labels["num_chunks"].setText(f"{stats['num_chunks']:,}")
            self.stat_labels["backend"].setText(stats["backend"])
            self.stat_labels["embedding_model"].setText(stats["embedding_model"])
            self.stat_labels["last_modified"].setText(stats["last_modified"])
            if stats["is_compact"] is not None:
                inc = "Enabled" if not stats["is_compact"] else "Disabled (compact)"
                self.stat_labels["incremental"].setText(inc)
            else:
                self.stat_labels["incremental"].setText("—")
        else:
            for v in self.stat_labels.values():
                v.setText("—")
            self.stat_labels["index_size"].setText("No index built yet")

        # Log
        self.log_text.setText(get_log_tail(10))

        # Progress
        is_indexing = s == "indexing"
        self.progress.setVisible(is_indexing)
        self.reindex_btn.setEnabled(not is_indexing)

    def _start_reindex(self):
        if self.reindex_process and self.reindex_process.state() != QProcess.ProcessState.NotRunning:
            return

        self.progress.setVisible(True)
        self.reindex_btn.setEnabled(False)
        self.status_icon.setText("⏳")
        self.status_label.setText("Indexing in progress...")

        self.reindex_process = QProcess(self)
        self.reindex_process.finished.connect(self._reindex_finished)
        self.reindex_process.start("bash", [str(REINDEX_SCRIPT)])

    def _reindex_finished(self, exit_code, _status):
        self.progress.setVisible(False)
        self.reindex_btn.setEnabled(True)
        if exit_code == 0:
            self.status_icon.setText("✅")
            self.status_label.setText("Reindex completed!")
        else:
            self.status_icon.setText("❌")
            self.status_label.setText(f"Reindex failed (exit {exit_code})")
        self.refresh()


# --- Settings Tab ---

def is_on_battery() -> bool:
    """Check if Mac is running on battery power."""
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5
        )
        return "Battery Power" in result.stdout
    except Exception:
        return False


class SettingsTab(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        settings = self.cfg.setdefault("settings", {})
        build_opts = self.cfg.setdefault("build_options", {})

        # --- Power Management ---
        power_box = QGroupBox("🔋 Power Management")
        power_layout = QVBoxLayout(power_box)

        self.battery_cb = QCheckBox("Pause indexing when running on battery")
        self.battery_cb.setChecked(settings.get("pause_on_battery", True))
        self.battery_cb.stateChanged.connect(self._on_change)
        power_layout.addWidget(self.battery_cb)

        battery_status = QLabel(
            f"Current: {'🔋 Battery' if is_on_battery() else '🔌 AC Power'}"
        )
        battery_status.setStyleSheet("color: gray; font-size: 11px;")
        power_layout.addWidget(battery_status)

        layout.addWidget(power_box)

        # --- Scheduling ---
        schedule_box = QGroupBox("⏰ Reindex Schedule")
        schedule_layout = QGridLayout(schedule_box)

        schedule_layout.addWidget(QLabel("Reindex interval:"), 0, 0)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 1440)
        self.interval_spin.setSuffix(" min")
        self.interval_spin.setValue(self.cfg.get("reindex_interval_minutes", 30))
        self.interval_spin.valueChanged.connect(self._on_change)
        schedule_layout.addWidget(self.interval_spin, 0, 1)

        interval_hint = QLabel("Applies after reloading the launchd agent")
        interval_hint.setStyleSheet("color: gray; font-size: 11px;")
        schedule_layout.addWidget(interval_hint, 1, 0, 1, 2)

        layout.addWidget(schedule_box)

        # --- Index Configuration ---
        index_box = QGroupBox("📦 Index Configuration")
        index_layout = QGridLayout(index_box)

        index_layout.addWidget(QLabel("Index name:"), 0, 0)
        self.index_name_input = QLineEdit(self.cfg.get("index_name", "mac-search"))
        self.index_name_input.editingFinished.connect(self._on_change)
        index_layout.addWidget(self.index_name_input, 0, 1)

        index_layout.addWidget(QLabel("Work directory:"), 1, 0)
        work_dir_row = QHBoxLayout()
        self.work_dir_input = QLineEdit(self.cfg.get("work_dir", "~/.leann-search"))
        self.work_dir_input.editingFinished.connect(self._on_change)
        work_dir_browse = QPushButton("Browse...")
        work_dir_browse.clicked.connect(self._browse_work_dir)
        work_dir_row.addWidget(self.work_dir_input, 1)
        work_dir_row.addWidget(work_dir_browse)
        index_layout.addLayout(work_dir_row, 1, 1)

        index_layout.addWidget(QLabel("Backend:"), 2, 0)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["hnsw", "diskann"])
        self.backend_combo.setCurrentText(build_opts.get("backend", "hnsw"))
        self.backend_combo.currentTextChanged.connect(self._on_change)
        index_layout.addWidget(self.backend_combo, 2, 1)

        index_layout.addWidget(QLabel("Embedding model:"), 3, 0)
        self.embedding_input = QLineEdit(
            build_opts.get("embedding_model", "facebook/contriever")
        )
        self.embedding_input.editingFinished.connect(self._on_change)
        index_layout.addWidget(self.embedding_input, 3, 1)

        self.compact_cb = QCheckBox("Compact index (disables incremental updates)")
        self.compact_cb.setChecked(build_opts.get("compact", False))
        self.compact_cb.stateChanged.connect(self._on_change)
        index_layout.addWidget(self.compact_cb, 4, 0, 1, 2)

        layout.addWidget(index_box)

        # --- Search ---
        search_box = QGroupBox("🔍 Search")
        search_layout = QGridLayout(search_box)

        search_layout.addWidget(QLabel("Results count (Raycast):"), 0, 0)
        self.results_spin = QSpinBox()
        self.results_spin.setRange(1, 50)
        self.results_spin.setValue(settings.get("search_results_count", 5))
        self.results_spin.valueChanged.connect(self._on_change)
        search_layout.addWidget(self.results_spin, 0, 1)

        layout.addWidget(search_box)

        # --- Logs & Maintenance ---
        maint_box = QGroupBox("🧹 Logs & Maintenance")
        maint_layout = QGridLayout(maint_box)

        maint_layout.addWidget(QLabel("Max log file size:"), 0, 0)
        self.log_size_spin = QSpinBox()
        self.log_size_spin.setRange(1, 500)
        self.log_size_spin.setSuffix(" MB")
        self.log_size_spin.setValue(settings.get("max_log_size_mb", 50))
        self.log_size_spin.valueChanged.connect(self._on_change)
        maint_layout.addWidget(self.log_size_spin, 0, 1)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self._clear_log)
        maint_layout.addWidget(clear_log_btn, 1, 0)

        self.delete_index_btn = QPushButton("⚠️ Delete Index")
        self.delete_index_btn.setStyleSheet("color: red;")
        self.delete_index_btn.clicked.connect(self._delete_index)
        maint_layout.addWidget(self.delete_index_btn, 1, 1)

        layout.addWidget(maint_box)

        # --- Startup ---
        startup_box = QGroupBox("🚀 Startup")
        startup_layout = QVBoxLayout(startup_box)

        self.login_cb = QCheckBox("Launch LEANN Manager at login")
        self.login_cb.setChecked(settings.get("launch_at_login", False))
        self.login_cb.stateChanged.connect(self._on_change)
        startup_layout.addWidget(self.login_cb)

        layout.addWidget(startup_box)

        layout.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_change(self):
        settings = self.cfg.setdefault("settings", {})
        settings["pause_on_battery"] = self.battery_cb.isChecked()
        settings["max_log_size_mb"] = self.log_size_spin.value()
        settings["launch_at_login"] = self.login_cb.isChecked()
        settings["search_results_count"] = self.results_spin.value()

        self.cfg["reindex_interval_minutes"] = self.interval_spin.value()
        self.cfg["index_name"] = self.index_name_input.text().strip() or "mac-search"
        self.cfg["work_dir"] = self.work_dir_input.text().strip() or "~/.leann-search"

        build_opts = self.cfg.setdefault("build_options", {})
        build_opts["backend"] = self.backend_combo.currentText()
        build_opts["embedding_model"] = self.embedding_input.text().strip() or "facebook/contriever"
        build_opts["compact"] = self.compact_cb.isChecked()

        self.config_changed.emit()

    def _browse_work_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Work Directory")
        if path:
            home = str(Path.home())
            display = path.replace(home, "~") if path.startswith(home) else path
            self.work_dir_input.setText(display)
            self._on_change()

    def _clear_log(self):
        if DEFAULT_LOG_PATH.exists():
            DEFAULT_LOG_PATH.unlink()
        old = DEFAULT_LOG_PATH.with_suffix(".log.old")
        if old.exists():
            old.unlink()
        QMessageBox.information(self, "Logs", "Log files cleared.")

    def _delete_index(self):
        work_dir = get_work_dir(self.cfg)
        index_name = self.cfg.get("index_name", "mac-search")
        index_dir = work_dir / ".leann" / "indexes" / index_name

        if not index_dir.exists():
            QMessageBox.information(self, "Delete Index", "No index found.")
            return

        reply = QMessageBox.warning(
            self,
            "Delete Index",
            f"Delete index '{index_name}' at:\n{index_dir}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            shutil.rmtree(index_dir, ignore_errors=True)
            QMessageBox.information(self, "Delete Index", "Index deleted.")


# --- Main Window ---

class LeannManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LEANN Search Manager")
        self.setMinimumSize(640, 560)

        self.cfg = load_config()
        self._ensure_defaults()

        # Tabs
        tabs = QTabWidget()

        self.folders_tab = FoldersTab(self.cfg)
        self.folders_tab.config_changed.connect(self._save)
        tabs.addTab(self.folders_tab, "📁 Folders")

        self.filetypes_tab = FileTypesTab(self.cfg)
        self.filetypes_tab.config_changed.connect(self._save)
        tabs.addTab(self.filetypes_tab, "📄 File Types")

        self.stats_tab = StatsTab(self.cfg)
        tabs.addTab(self.stats_tab, "📊 Stats")

        self.settings_tab = SettingsTab(self.cfg)
        self.settings_tab.config_changed.connect(self._save)
        tabs.addTab(self.settings_tab, "⚙️ Settings")

        self.setCentralWidget(tabs)

        # Auto-refresh stats every 10s
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.stats_tab.refresh)
        self.timer.start(10_000)

    def _ensure_defaults(self):
        self.cfg.setdefault("index_name", "mac-search")
        self.cfg.setdefault("work_dir", "~/.leann-search")
        self.cfg.setdefault("folders", [])
        self.cfg.setdefault("file_types", {})
        self.cfg.setdefault("reindex_interval_minutes", 30)
        self.cfg.setdefault("settings", {
            "pause_on_battery": True,
            "max_log_size_mb": 50,
            "launch_at_login": False,
            "search_results_count": 5,
        })
        self.cfg.setdefault("build_options", {
            "backend": "hnsw",
            "compact": False,
            "embedding_model": "facebook/contriever",
        })

    def _save(self):
        save_config(self.cfg)


# --- Entry point ---

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LEANN Search Manager")
    app.setStyle("macOS" if "macOS" in [s for s in app.style().name()] else "Fusion")

    window = LeannManager()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
