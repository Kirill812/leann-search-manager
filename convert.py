#!/usr/bin/env python3
"""LEANN Search Manager — Markdown Conversion Preprocessor.

Converts all indexed files to Markdown using Microsoft markitdown.
Only re-converts files that have changed (mtime-based tracking).
Output goes to ~/.leann-search/md-cache/ preserving directory structure.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import yaml
from markitdown import MarkItDown

# --- Config ---

DEFAULT_CONFIG = Path.home() / ".leann-search" / "config.yaml"
DEFAULT_CACHE_DIR = Path.home() / ".leann-search" / "md-cache"
MANIFEST_FILE = "convert-manifest.json"

# Extensions that are already plain text — just copy, don't convert
PASSTHROUGH_EXTENSIONS = {
    ".md", ".txt", ".csv", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".sh", ".py", ".js", ".ts", ".vue",
    ".html", ".css", ".go", ".rs", ".java", ".rb", ".cfg",
    ".conf", ".ini", ".env", ".log", ".rst", ".tex",
}


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_enabled_extensions(cfg: dict) -> set[str]:
    exts = set()
    for group in cfg.get("file_types", {}).values():
        if group.get("enabled", False):
            exts.update(group.get("extensions", []))
    return exts


def get_enabled_folders(cfg: dict) -> list[Path]:
    folders = []
    for entry in cfg.get("folders", []):
        if entry.get("enabled", True):
            p = Path(os.path.expanduser(entry["path"]))
            if p.is_dir():
                folders.append(p)
    return folders


def cache_path_for(source: Path, cache_dir: Path) -> Path:
    """Generate a unique cache path for a source file.

    Preserves readability: ~/Documents/report.pdf -> md-cache/Documents/report.pdf.md
    Uses a hash suffix for files outside home to avoid collisions.
    """
    home = Path.home()
    try:
        rel = source.relative_to(home)
        return cache_dir / rel.parent / (rel.name + ".md")
    except ValueError:
        # Outside home dir — use hash prefix
        h = hashlib.md5(str(source.parent).encode()).hexdigest()[:8]
        return cache_dir / h / (source.name + ".md")


def load_manifest(cache_dir: Path) -> dict:
    manifest_path = cache_dir / MANIFEST_FILE
    if manifest_path.exists():
        with open(manifest_path) as f:
            return json.load(f)
    return {}


def save_manifest(cache_dir: Path, manifest: dict):
    manifest_path = cache_dir / MANIFEST_FILE
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def collect_files(folders: list[Path], extensions: set[str]) -> list[Path]:
    """Walk folders and collect files matching enabled extensions."""
    files = []
    for folder in folders:
        for root, dirs, filenames in os.walk(folder):
            # Skip hidden dirs and common junk
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "__pycache__", ".git", "venv", ".venv"}
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                ext = Path(name).suffix.lower()
                if ext in extensions:
                    files.append(Path(root) / name)
    return files


def convert_file(md: MarkItDown, source: Path, dest: Path) -> bool:
    """Convert a single file to markdown. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    ext = source.suffix.lower()

    # Plain text files — copy with metadata header
    if ext in PASSTHROUGH_EXTENSIONS:
        try:
            text = source.read_text(errors="replace")
            header = f"<!-- source: {source} -->\n"
            dest.write_text(header + text)
            return True
        except Exception as e:
            print(f"  ⚠ Copy failed {source.name}: {e}", file=sys.stderr)
            return False

    # Binary/rich formats — convert via markitdown
    try:
        result = md.convert(str(source))
        if result and result.text_content:
            header = f"<!-- source: {source} -->\n# {source.name}\n\n"
            dest.write_text(header + result.text_content)
            return True
        else:
            print(f"  ⚠ Empty result for {source.name}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ⚠ Convert failed {source.name}: {e}", file=sys.stderr)
        return False


def clean_removed(manifest: dict, current_sources: set[str], cache_dir: Path) -> int:
    """Remove cached files for sources that no longer exist."""
    removed = 0
    to_remove = [src for src in manifest if src not in current_sources]
    for src in to_remove:
        cached = Path(manifest[src]["cache_path"])
        if cached.exists():
            cached.unlink()
        del manifest[src]
        removed += 1
    return removed


def main():
    config_path = Path(os.environ.get("LEANN_SEARCH_CONFIG", str(DEFAULT_CONFIG)))
    cfg = load_config(config_path)

    cache_dir = Path(os.path.expanduser(
        cfg.get("settings", {}).get("md_cache_dir", str(DEFAULT_CACHE_DIR))
    ))
    cache_dir.mkdir(parents=True, exist_ok=True)

    folders = get_enabled_folders(cfg)
    extensions = get_enabled_extensions(cfg)

    if not folders:
        print("No enabled folders configured.")
        return

    if not extensions:
        print("No file types enabled.")
        return

    print(f"📂 Scanning {len(folders)} folder(s) for {len(extensions)} file type(s)...")
    all_files = collect_files(folders, extensions)
    print(f"📄 Found {len(all_files)} files")

    manifest = load_manifest(cache_dir)
    current_sources = {str(f) for f in all_files}

    # Clean removed files
    removed = clean_removed(manifest, current_sources, cache_dir)
    if removed:
        print(f"🗑  Removed {removed} stale cache entries")

    # Determine what needs conversion
    to_convert = []
    skipped = 0
    for source in all_files:
        src_key = str(source)
        mtime = source.stat().st_mtime

        if src_key in manifest and manifest[src_key].get("mtime") == mtime:
            cached = Path(manifest[src_key]["cache_path"])
            if cached.exists():
                skipped += 1
                continue

        dest = cache_path_for(source, cache_dir)
        to_convert.append((source, dest, mtime))

    print(f"⏭  {skipped} unchanged, 🔄 {len(to_convert)} to convert")

    if not to_convert:
        print("✅ Cache is up to date")
        save_manifest(cache_dir, manifest)
        return

    # Convert
    md = MarkItDown()
    success = 0
    failed = 0
    start = time.time()

    for i, (source, dest, mtime) in enumerate(to_convert, 1):
        if i % 50 == 0 or i == len(to_convert):
            print(f"  Converting {i}/{len(to_convert)}...")

        if convert_file(md, source, dest):
            manifest[str(source)] = {
                "cache_path": str(dest),
                "mtime": mtime,
                "size": source.stat().st_size,
            }
            success += 1
        else:
            failed += 1

    elapsed = time.time() - start
    save_manifest(cache_dir, manifest)

    print(f"✅ Done in {elapsed:.1f}s: {success} converted, {failed} failed, {skipped} unchanged")
    print(f"📁 Cache: {cache_dir}")


if __name__ == "__main__":
    main()
