from __future__ import annotations

import argparse
import time
from pathlib import Path

from .config import AppConfig, load_config
from .exporter import Exporter

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover
    FileSystemEventHandler = object
    Observer = None


class ZoteroChangeHandler(FileSystemEventHandler):
    def __init__(self, exporter: Exporter, paper_filter: str | None, debounce_seconds: int):
        self.exporter = exporter
        self.paper_filter = paper_filter
        self.debounce_seconds = debounce_seconds
        self.last_run = 0.0

    def on_modified(self, event):  # pragma: no cover
        if getattr(event, "is_directory", False):
            return
        self._maybe_refresh()

    def on_created(self, event):  # pragma: no cover
        if getattr(event, "is_directory", False):
            return
        self._maybe_refresh()

    def _maybe_refresh(self):  # pragma: no cover
        now = time.time()
        if now - self.last_run < self.debounce_seconds:
            return
        self.last_run = now
        changed = self.exporter.refresh(self.paper_filter)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if changed:
            print(f"[{stamp}] Updated {len(changed)} note(s):")
            for title in changed:
                print(f"  - {title}")
        else:
            print(f"[{stamp}] No note changes detected")


def get_watch_signature(db_path: Path) -> tuple[tuple[str, int, int], ...]:
    candidates = [db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")]
    signature: list[tuple[str, int, int]] = []
    for candidate in candidates:
        if not candidate.exists():
            continue
        stats = candidate.stat()
        signature.append((candidate.name, stats.st_mtime_ns, stats.st_size))
    return tuple(signature)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="zotrian.json", help="Path to the Zotrian config file.")
    common.add_argument("--vault", help="Override the Obsidian vault path from the config file.")
    common.add_argument("--db", help="Override the Zotero database path from the config file.")
    common.add_argument("--storage", help="Override the Zotero storage path from the config file.")

    parser = argparse.ArgumentParser(
        prog="zotrian",
        description="Convert Zotero annotations into Obsidian markdown notes.",
        parents=[common],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser("convert", help="Export notes from Zotero into Obsidian.", parents=[common])
    convert_parser.add_argument("--paper", help="Filter papers by title, citation key, or Zotero key.")

    watch_parser = subparsers.add_parser("watch", help="Watch Zotero for changes and keep notes in sync.", parents=[common])
    watch_parser.add_argument("--paper", help="Filter watched exports by title, citation key, or Zotero key.")

    return parser


def apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.vault:
        config.obsidian.vault_path = Path(args.vault).expanduser().resolve()
    if args.db:
        config.zotero.database_path = Path(args.db).expanduser().resolve()
    if args.storage:
        config.zotero.storage_path = Path(args.storage).expanduser().resolve()
    return config


def confirm_no_toc(exporter: Exporter, paper_filter: str | None, action_name: str) -> bool:
    if not paper_filter:
        return True

    missing_toc_titles: list[str] = []
    for paper in exporter.db.get_papers(paper_filter=paper_filter):
        parser = exporter.load_parser(paper.get("pdf_path"))
        if not parser or not parser.toc or len(parser.toc) < 2:
            missing_toc_titles.append(paper.get("title") or paper.get("citekey") or paper.get("key") or "Untitled")

    if not missing_toc_titles:
        return True

    print("Warning: no usable table of contents was detected for:")
    for title in missing_toc_titles:
        print(f"  - {title}")
    response = input(f"Continue with {action_name} anyway? [y/N] ").strip().lower()
    return response in {"y", "yes"}


def run_convert(exporter: Exporter, paper_filter: str | None) -> int:
    if not paper_filter:
        print("No paper title provided. Use --paper to convert a specific paper.")
        return 0
    if not confirm_no_toc(exporter, paper_filter, "convert"):
        return 0
    changed = exporter.run(paper_filter=paper_filter)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] Exported {len(changed)} note(s)")
    for title in changed:
        print(f"  - {title}")
    return 0


def run_watch(exporter: Exporter, paper_filter: str | None, config: AppConfig) -> int:
    if not paper_filter:
        print("No paper title provided. Use --paper to watch a specific paper.")
        return 0
    if not confirm_no_toc(exporter, paper_filter, "watch"):
        return 0
    changed = exporter.run(paper_filter=paper_filter)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] Initial sync exported {len(changed)} note(s)")
    if Observer is None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] watchdog not available; using polling mode.")
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Watching {config.zotero.database_path} for Zotero changes...")
        last_signature = get_watch_signature(config.zotero.database_path)
        try:
            while True:
                time.sleep(config.watch.interval_seconds)
                current_signature = get_watch_signature(config.zotero.database_path)
                if current_signature == last_signature:
                    continue
                last_signature = current_signature
                changed = exporter.refresh(paper_filter)
                poll_stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                if changed:
                    print(f"[{poll_stamp}] Updated {len(changed)} note(s):")
                    for title in changed:
                        print(f"  - {title}")
                else:
                    print(f"[{poll_stamp}] No note changes detected")
        except KeyboardInterrupt:
            return 0

    handler = ZoteroChangeHandler(exporter, paper_filter, config.watch.debounce_seconds)
    observer = Observer()
    observer.schedule(handler, str(config.watch_root), recursive=False)
    observer.start()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Watching {config.zotero.database_path} for Zotero changes...")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(config.watch.interval_seconds)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


def main() -> int:
    args = build_parser().parse_args()
    config = apply_overrides(load_config(Path(args.config)), args)
    exporter = Exporter(config)

    if args.command == "convert":
        return run_convert(exporter, args.paper)
    if args.command == "watch":
        return run_watch(exporter, args.paper, config)
    raise RuntimeError(f"Unsupported command: {args.command}")
