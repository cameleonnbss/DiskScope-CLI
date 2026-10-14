"""DiskScope CLI - scanner.py

Real recursive disk scanner.

Design notes:
  * os.scandir() everywhere, follow_symlinks=False  -> junction/symlink safe
  * one thread-pool task per directory (discover-parallelism)
  * bounded-memory collectors for big files and old-file candidates
  * cooperative cancellation through a threading.Event (Ctrl+C safe)
  * progress callback (files, bytes, errors, current_path) for the UI
"""
from __future__ import annotations

import heapq
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_CPU_COUNT = max(2, min(8, (os.cpu_count() or 4)))

import safety

ProgressCb = Callable[[int, int, int, str], None]

DEFAULT_DEPTH = 32      # deep enough for virtually every real tree
QUICK_DEPTH = 2
DETAIL_DEPTH = 8
MAX_NODES = 400_000     # hard cap of directory nodes kept in memory


def _new_node(name: str, path: str) -> dict[str, Any]:
    return {"name": name, "path": path, "size": 0, "files": 0,
            "dirs": 0, "mtime": 0.0, "children": []}


# --------------------------------------------------------------------------- #
#  Bounded collectors for big / old files
# --------------------------------------------------------------------------- #
class Collectors:
    """Accumulates candidate files with bounded memory usage."""

    def __init__(self, big_keep: int = 500, old_min_size: int = 1024 * 1024,
                 old_max: int = 30_000):
        self.big_keep = big_keep
        self.old_min_size = old_min_size
        self.old_max = old_max
        self._big: list[dict[str, Any]] = []
        self._old: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def add_files(self, batch: list[tuple[str, int, float, str]],
                  drive: str) -> None:
        """Add many (path, size, mtime, ext) files under one lock.

        Batching per directory keeps the number of lock acquisitions at
        one-per-directory instead of one-per-file, which is what makes
        the parallel walk scale on NVMe.
        """
        if not batch:
            return
        with self.lock:
            recs = [{"path": p, "size": s, "mtime": m,
                     "ext": (x or "").lower(), "drive": drive}
                    for p, s, m, x in batch]
            self._big.extend(recs)
            if len(self._big) > self.big_keep * 2:
                self._big = heapq.nlargest(self.big_keep, self._big,
                                           key=lambda x: x["size"])
            old_recs = [r for r in recs if r["size"] >= self.old_min_size]
            if old_recs:
                self._old.extend(old_recs)
                if len(self._old) > self.old_max:
                    self._old.sort(key=lambda x: x["size"], reverse=True)
                    del self._old[self.old_max:]

    def add_file(self, path: str, size: int, mtime: float, ext: str,
                 drive: str) -> None:
        self.add_files([(path, size, mtime, ext)], drive)

    def results(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self.lock:
            big = sorted(self._big, key=lambda x: x["size"], reverse=True)[:self.big_keep]
            old = sorted(self._old, key=lambda x: x["size"], reverse=True)
            return big, old


class _Ctx:
    __slots__ = ("drive", "max_depth", "collectors", "stop", "lock",
                 "pending", "done", "files", "bytes", "dirs", "errors",
                 "last_path", "reported")

    def __init__(self, drive: str, max_depth: int, collectors: Collectors,
                 stop: threading.Event):
        self.drive = drive
        self.max_depth = max_depth
        self.collectors = collectors
        self.stop = stop
        self.lock = threading.Lock()
        self.pending = 1
        self.done = threading.Event()
        self.files = 0
        self.bytes = 0
        self.dirs = 0
        self.errors = 0
        self.last_path = ""
        self.reported = 0


def _worker(ctx: _Ctx, pool: ThreadPoolExecutor, node: dict[str, Any],
            depth: int) -> None:
    kids: list[dict[str, Any]] = []
    if not ctx.stop.is_set():
        try:
            with os.scandir(node["path"]) as it:
                entries = list(it)
        except OSError:
            with ctx.lock:
                ctx.errors += 1
            entries = []
        to_submit: list[dict[str, Any]] = []
        # Accumulate per-file stats locally and flush with ONE lock
        # acquisition per directory - the per-file locks were the main
        # contention point on large trees.
        batch: list[tuple[str, int, float, str]] = []
        local_bytes = 0
        local_files = 0
        local_errors = 0
        local_mtime = node["mtime"]
        for e in entries:
            if ctx.stop.is_set():
                break
            name = e.name
            try:
                if e.is_symlink():
                    continue
                # junctions (ex: Local Settings -> AppData\Local) are NOT
                # symlinks: without this check the same file is counted twice
                if safety.is_reparse_entry(e):
                    continue
                if e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    size = st.st_size
                    mtime = st.st_mtime
                    ext = os.path.splitext(name)[1]
                    local_files += 1
                    local_bytes += size
                    if mtime > local_mtime:
                        local_mtime = mtime
                    batch.append((e.path, size, mtime, ext))
                elif e.is_dir(follow_symlinks=False):
                    if safety.should_skip_dir(name):
                        continue
                    if ctx.dirs >= MAX_NODES:
                        continue
                    to_submit.append(_new_node(name, e.path))
            except OSError:
                local_errors += 1
        with ctx.lock:
            ctx.files += local_files
            ctx.bytes += local_bytes
            ctx.errors += local_errors
            node["size"] += local_bytes
            node["files"] += local_files
            node["mtime"] = local_mtime
        if batch:
            ctx.collectors.add_files(batch, ctx.drive)
        if depth < ctx.max_depth and not ctx.stop.is_set():
            kids = to_submit
            with ctx.lock:
                ctx.pending += len(kids)
            for ch in kids:
                try:
                    pool.submit(_worker, ctx, pool, ch, depth + 1)
                except RuntimeError:
                    with ctx.lock:
                        ctx.pending -= 1
        with ctx.lock:
            node["children"] = kids
            ctx.dirs += len(kids)
        ctx.last_path = node["path"]
    # pending bookkeeping (always, even on early return)
    with ctx.lock:
        ctx.pending -= 1
        if ctx.pending <= 0:
            ctx.done.set()


def _aggregate(node: dict[str, Any]) -> tuple[int, int, int, float]:
    size, files, dirs, mtime = node["size"], node["files"], 0, node["mtime"]
    for ch in node.get("children", ()):
        s, f, d, m = _aggregate(ch)
        size += s
        files += f
        dirs += d + 1
        mtime = max(mtime, m)
    node["size"], node["files"], node["dirs"], node["mtime"] = size, files, dirs, mtime
    return size, files, dirs, mtime


def _sort_children(node: dict[str, Any]) -> None:
    kids = node.get("children")
    if kids:
        kids.sort(key=lambda c: c.get("size", 0), reverse=True)
        for ch in kids:
            _sort_children(ch)


def scan_tree(root: str, drive: str, *, max_depth: int = DEFAULT_DEPTH,
              progress: ProgressCb | None = None,
              collectors: Collectors | None = None,
              stop: threading.Event | None = None,
              max_workers: int | None = None
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recursively scan `root`. Returns (tree_node, stats)."""
    stop = stop or threading.Event()
    collectors = collectors or Collectors()
    workers = max_workers or min(16, (os.cpu_count() or 4) * 2)
    root = os.path.abspath(root)
    root_node = _new_node(os.path.basename(root.rstrip("\\/")) or root, root)
    ctx = _Ctx(drive, max_depth, collectors, stop)
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ds")
    t0 = time.monotonic()
    try:
        pool.submit(_worker, ctx, pool, root_node, 0)
        while not ctx.done.wait(0.2):
            if progress and ctx.files - ctx.reported >= 1024:
                progress(ctx.files, ctx.bytes, ctx.errors, ctx.last_path)
                ctx.reported = ctx.files
            if stop.is_set() and ctx.pending <= 0:
                break
    finally:
        pool.shutdown(wait=True)
    _aggregate(root_node)
    _sort_children(root_node)
    stats = {
        "drive": drive,
        "root": root,
        "files": ctx.files,
        "bytes": ctx.bytes,
        "dirs": ctx.dirs,
        "errors": ctx.errors,
        "duration": time.monotonic() - t0,
        "max_depth": max_depth,
    }
    return root_node, stats


# --------------------------------------------------------------------------- #
#  Simpler helpers for targeted scans (apps, games, cleanup...)
# --------------------------------------------------------------------------- #
def dir_size(path: str, *, max_files: int | None = None,
             stop: threading.Event | None = None) -> tuple[int, int]:
    """(total_bytes, file_count) of a folder. Skips unreadable entries."""
    total = 0
    count = 0
    stack = [path]
    while stack:
        p = stack.pop()
        if stop is not None and stop.is_set():
            return total, count
        try:
            with os.scandir(p) as it:
                for e in it:
                    if stop is not None and stop.is_set():
                        return total, count
                    try:
                        if e.is_symlink() or safety.is_reparse_entry(e):
                            continue
                        if e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            count += 1
                            if max_files is not None and count >= max_files:
                                return total, count
                        elif e.is_dir(follow_symlinks=False):
                            if not safety.should_skip_dir(e.name):
                                stack.append(e.path)
                    except OSError:
                        pass
        except OSError:
            # One retry: transient Windows locks (Defender, Steam, indexer)
            # can make an existing folder briefly unlistable.
            try:
                time.sleep(0.02)
                with os.scandir(p) as it:
                    for e in it:
                        if stop is not None and stop.is_set():
                            return total, count
                        try:
                            if e.is_symlink() or safety.is_reparse_entry(e):
                                continue
                            if e.is_file(follow_symlinks=False):
                                total += e.stat(follow_symlinks=False).st_size
                                count += 1
                                if max_files is not None and count >= max_files:
                                    return total, count
                            elif e.is_dir(follow_symlinks=False):
                                if not safety.should_skip_dir(e.name):
                                    stack.append(e.path)
                        except OSError:
                            pass
            except OSError:
                pass
    return total, count


def top_level_sizes(path: str, *, stop: threading.Event | None = None,
                    on_progress: Callable[[int, int, str, int], None] | None = None
                    ) -> list[tuple[str, str, int, int]]:
    """[(name, path, size, files)] for each direct child folder of `path`.

    `on_progress(done, total, name, files)` fires after each folder is
    measured, so callers can show live progress.
    """
    out: list[tuple[str, str, int, int]] = []
    try:
        with os.scandir(path) as it:
            entries = [e for e in it if e.is_dir(follow_symlinks=False)
                       and not e.is_symlink()
                       and not safety.is_reparse_entry(e)
                       and not safety.should_skip_dir(e.name)]
    except OSError:
        return out
    total = len(entries)
    if total <= 2 or _CPU_COUNT < 2:
        # sequential: not enough parallelism to be worth it
        for i, e in enumerate(entries, 1):
            if stop is not None and stop.is_set():
                break
            size, files = dir_size(e.path, stop=stop)
            if on_progress is not None:
                try:
                    on_progress(i, total, e.name, files)
                except Exception:
                    pass
            out.append((e.name, e.path, size, files))
        out.sort(key=lambda x: x[2], reverse=True)
        return out

    # Parallel: top-level folders are independent subtrees; os.scandir is
    # I/O bound, so a small thread pool gives a real speedup on SSDs.
    lock = threading.Lock()
    done = [0]

    def _work(idx_path: tuple[int, os.DirEntry]) -> tuple[int, str, str, int, int]:
        i, e = idx_path
        size, files = dir_size(e.path, stop=stop)
        return i, e.name, e.path, size, files

    with ThreadPoolExecutor(max_workers=_CPU_COUNT) as ex:
        futs = [ex.submit(_work, (i, e)) for i, e in enumerate(entries)]
        for fut in futs:
            try:
                i, name, epath, size, files = fut.result()
                out.append((name, epath, size, files))
            except Exception:
                continue
            with lock:
                done[0] += 1
                d = done[0]
            if on_progress is not None:
                try:
                    on_progress(d, total, name, files)
                except Exception:
                    pass
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def compact_tree(node: dict[str, Any], max_depth: int = 4,
                 max_children: int = 12) -> dict[str, Any]:
    """Reduce a tree for JSON cache: keep top-N children per level."""
    kids = node.get("children") or []
    if max_depth <= 0 or not kids:
        if kids:
            node["pruned"] = True
        node["children"] = []
        return node
    keep = sorted(kids, key=lambda c: c.get("size", 0), reverse=True)[:max_children]
    for k in keep:
        compact_tree(k, max_depth - 1, max_children)
    if len(keep) < len(kids):
        node["pruned"] = True
    node["children"] = keep
    return node


def newest_mtime(path: str, *, max_entries: int = 200) -> float:
    """Newest mtime among direct children (files only) of a folder."""
    best = 0.0
    try:
        n = 0
        with os.scandir(path) as it:
            for e in it:
                n += 1
                if n > max_entries:
                    break
                try:
                    if e.is_file(follow_symlinks=False):
                        m = e.stat(follow_symlinks=False).st_mtime
                        if m > best:
                            best = m
                except OSError:
                    continue
    except OSError:
        pass
    return best
