"""DiskScope CLI - ui.py

Rendering layer built on `rich`: banner, bars, tables, panels,
animated spinner during scans, interactive menus and selection lists.
All output adapts when rich is unavailable or stdout is not a terminal.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable, Iterable, Sequence

try:
    from rich.align import Align
    from rich.box import HEAVY, DOUBLE
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    RICH = True
except ImportError:  # pragma: no cover - rich is a hard dependency in practice
    RICH = False

APP_NAME = "DISKSCOPE CLI"
APP_SUB = "Windows Storage Analyzer"
APP_VERSION = "2.1.0"

# Windows consoles: force UTF-8 output and the ANSI (non-legacy) renderer
# so unicode glyphs never crash on cp1252 code pages.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

if RICH:
    console: Any = Console(highlight=False, emoji=False, legacy_windows=False)
else:  # minimal fallback so the tool still runs without rich
    class _Plain:
        def print(self, *a, **k):
            print(*[a_ for a_ in a if isinstance(a_, str)], **{k_: v for k_, v in k.items() if k_ in ("end", "flush")})

        def rule(self, *a, **k):
            print("-" * 60)

        def clear(self):
            pass

        @property
        def is_terminal(self):
            return True

    console = _Plain()  # type: ignore[assignment]

# ANSI colour helpers used by the fallback path (and always safe on Win10+)
RESET, DIM, BOLD, CYAN, GREEN, YELLOW, RED, MAGENTA = (
    "\033[0m", "\033[2m", "\033[1m", "\033[96m",
    "\033[92m", "\033[93m", "\033[91m", "\033[95m",
)


# --------------------------------------------------------------------------- #
#  Sizes & durations
# --------------------------------------------------------------------------- #
UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human(n: int | float) -> str:
    """1234567 -> '1.2 MB'"""
    n = float(max(0, n))
    for u in UNITS:
        if n < 1024.0 or u == UNITS[-1]:
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} PB"


def human_compact(n: int | float) -> str:
    """1234567 -> '1.2M' (for tables that must stay narrow)"""
    n = float(max(0, n))
    for u in ("", "K", "M", "G", "T"):
        if n < 1024.0 or u == "T":
            return f"{n:.0f}{u}" if u else f"{int(n)}"
        n /= 1024.0
    return f"{n:.0f}T"


def human_age(seconds: int | float) -> str:
    s = int(max(0, seconds))
    if s < 3600:
        return f"{max(1, s // 60)} min"
    if s < 86400:
        h = s // 3600
        return f"{h} h"
    days = s // 86400
    if days < 60:
        return f"{days} j"
    if days < 365:
        return f"{max(1, days // 30)} mois"
    years = days // 365
    return f"{years} an{'s' if years > 1 else ''}"


# --------------------------------------------------------------------------- #
#  Colour helpers
# --------------------------------------------------------------------------- #
def c(text: str, color: str, bold: bool = False) -> str:
    """Plain-string ANSI colour (safe everywhere, even without rich)."""
    codes = {"red": 91, "green": 92, "yellow": 93, "blue": 94,
             "magenta": 95, "cyan": 96, "white": 97, "grey": 37}
    code = codes.get(color, 97)
    pref = "\033[1m" if bold else ""
    return f"{pref}\033[{code}m{text}{RESET}"


def _plain(text: Any) -> str:
    """Strip rich markup for the no-rich fallback."""
    if not RICH:
        import re
        return re.compile(r"\[/?.*?\]").sub("", str(text))
    return str(text)


def colorize(size_bytes: int) -> str:
    """Colour a human size by magnitude."""
    s = human(size_bytes)
    gb = size_bytes / 1024 ** 3
    if gb >= 50:
        return c(s, "red", True)
    if gb >= 5:
        return c(s, "yellow")
    if gb >= 0.5:
        return c(s, "cyan")
    return c(s, "grey")


def severity_color(ratio: float) -> str:
    if ratio >= 0.90:
        return "red"
    if ratio >= 0.75:
        return "yellow"
    if ratio >= 0.50:
        return "cyan"
    return "green"


# --------------------------------------------------------------------------- #
#  Banner
# --------------------------------------------------------------------------- #
BANNER = r"""
   ___  _  _  ____  ____  _  _  ____  ____     _  _  ____
  / __)/ )( \(  _ \(_  _)/ )( \(  _ \(  __)   / )( \(  _ \
 ( (__ ) __ ( ) __/  )(  ) __ ( ) __/ ) _)    ) __ ( )   /
  \___)_)(_(_)__)   (__)_)(_)(_)(__)  (__)   (_)(_/(__\_)
"""


def show_banner() -> None:
    console.clear()
    if RICH:
        t = Text(BANNER, style="bold cyan")
        t.append(f"  v{APP_VERSION}", style="dim")
        console.print(Align.center(t))
        console.print(Align.center(Text(APP_SUB, style="bold magenta")))
        console.print(Rule(style="cyan"))
    else:
        print(c("=" * 62, "cyan", True))
        print(c(BANNER, "cyan", True))
        print(c(APP_SUB.center(62), "magenta", True))
        print(c("=" * 62, "cyan", True))


def show_cache_info(meta: dict[str, Any] | None) -> None:
    if not meta:
        return
    ts = time.strftime("%H:%M", time.localtime(meta.get("finished", 0)))
    dur = meta.get("duration", 0)
    files = meta.get("files")
    line = f"Dernier scan : {ts}  ·  durée : {_fmt_dur(dur)}"
    if files and dur:
        rate = files / dur
        line += f"  ·  {rate / 1000:.0f}k fichiers/s"
    if files:
        line += f"  ·  {files:,} fichiers".replace(",", " ")
    console.print(c("  " + line, "grey"))


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


# --------------------------------------------------------------------------- #
#  Menus
# --------------------------------------------------------------------------- #
MENU_ITEMS: list[tuple[str, str]] = [
    ("1", "Analyse complète", "scan de tous les disques"),
    ("2", "Analyse rapide", "aperçu des disques"),
    ("3", "Applications", "logiciels installés"),
    ("4", "Jeux", "Steam, Epic, Battle.net..."),
    ("5", "Gros fichiers", "top fichiers volumineux"),
    ("6", "Fichiers anciens", "jamais modifiés depuis..."),
    ("D", "Doublons", "gros fichiers en double (hash)"),
    ("C", "Nettoyage express", "Téléchargements + corbeille + caches"),
    ("7", "Nettoyage avancé", "recommandations SAFE/REVIEW"),
    ("8", "Rapport", "résumé + export"),
    ("9", "Recherche", "/search <motif>"),
    ("S", "Paramètres", "dry run, cache, filtres"),
    ("Q", "Quitter", ""),
]


def _menu_table() -> "Table":
    t = Table(show_header=False, box=None, padding=(0, 1), expand=False)
    t.add_column(justify="right", width=3)   # key
    t.add_column(width=20)                    # label
    t.add_column(width=38)                    # description
    return t


def show_menu(settings_line: str = "") -> str:
    """Print the main menu, return the user's choice key (upper-cased)."""
    console.print()
    if RICH:
        t = _menu_table()
        for key, label, desc in MENU_ITEMS:
            k = Text(f"[{key}]", style="bold yellow")
            if key == "C":
                label = Text(label, style="bold green")
            elif key == "Q":
                t.add_row("", "", "")  # breathing space before Quit
            label = Text(label) if isinstance(label, str) else label
            d = Text(desc, style="grey70") if desc else Text("")
            t.add_row(k, label, d)
        console.print(Panel(t, title=f"[bold cyan]{APP_NAME}[/]", border_style="cyan",
                            width=78, padding=(0, 2)))
    else:
        print(c(f"  {APP_NAME.center(60)}", "cyan", True))
        for key, label, desc in MENU_ITEMS:
            print(f"  [{c(key, 'yellow', True)}] {label:<20} {c(desc, 'dim') if desc else ''}")
    if settings_line:
        console.print(c("  " + settings_line, "dim"))
    try:
        return input(c("\n  Sélection > ", "cyan", True)).strip().upper()
    except (EOFError, KeyboardInterrupt):
        return "Q"


def confirm(question: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        ans = input(c(f"  {question}{suffix} > ", "yellow")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default
    return ans in ("y", "yes", "o", "oui")


def press_enter(msg: str = "Entrée pour continuer") -> None:
    try:
        input(c(f"\n  ({msg})...", "dim"))
    except (EOFError, KeyboardInterrupt):
        pass


def pause_or_continue(title: str, count: int) -> None:
    """When a long listing was cut short, tell the user why."""
    if count > 0:
        console.print(c(f"  ... {count} ligne(s) tronquée(s)", "dim"))


# --------------------------------------------------------------------------- #
#  Spinner / progress
# --------------------------------------------------------------------------- #
class NullProgress:
    """No-op progress used when rich is missing or stdout isn't a TTY."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def start(self):
        pass

    def stop(self):
        pass

    def update(self, *a, **k):
        pass

    def reset(self, *a, **k):
        pass

    def advance(self, *a, **k):
        pass

    def add_task(self, *a, **k) -> int:
        return 0

    @property
    def tasks(self):
        return []

    @property
    def finished(self):
        return True

    def console(self):  # pragma: no cover
        return console


class ScanProgress:
    """Progress display during scans.

    Rich mode : bar + files counter + current path (truncated by rich).
    Fallback  : inline ASCII bar refreshed on the same line.
    """

    def __init__(self, label: str = "Scanning", enabled: bool | None = None):
        self.label = label
        if enabled is None:
            enabled = RICH and console.is_terminal  # type: ignore[attr-defined]
        self.enabled = enabled and RICH
        self._progress = None
        self._task = None
        self._fallback_files = 0
        self._fallback_bytes = 0
        self._last_paint = 0.0
        self._current = ""
        self._errors = 0
        self._t0 = time.monotonic()

    def __enter__(self):
        if self.enabled:
            self._progress = Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("[progress.description]{task.description}", justify="left"),
                BarColumn(bar_width=None, style="grey35", complete_style="cyan"),
                TextColumn("[cyan]{task.percentage:>3.0f}%[/]"),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            )
            self._progress.__enter__()
            self._task = self._progress.add_task(self.label, total=None)
        return self

    def __exit__(self, *a):
        if self._progress:
            self._progress.__exit__(*a)
        return False

    # -- callbacks used by the scanner -------------------------------------
    def tick(self, files: int, errors: int, current: str) -> None:
        """Called periodically by scanner threads with running totals."""
        self._errors = errors
        self._current = current
        if self._progress and self._task is not None:
            self._progress.update(self._task, completed=files)
            self._progress.tasks[0].description = (
                f"[cyan]{self.label}[/]  {c(_short(current), 'grey')}"
                if not self._progress.tasks[0].total
                else self._progress.tasks[0].description
            )
            self._progress.refresh()
        else:
            self._paint_fallback(files)

    def set_total(self, total: int | float) -> None:
        if self._progress and self._task is not None:
            self._progress.update(self._task, total=total or None)

    def _paint_fallback(self, files: int) -> None:
        now = time.monotonic()
        if now - self._last_paint < 0.2:
            return
        self._last_paint = now
        width = 28
        elapsed = now - self._t0
        rate = files / elapsed if elapsed > 0 else 0.0
        eta = _fmt_dur((self._fallback_total_guess - files) / rate) if rate > 1000 and self._fallback_total_guess else ""
        bar = "#" * width
        line = f"\r  {self.label}  [{c(bar, 'cyan')}]  {files:,} files  {rate:,.0f}/s  {self._errors} errors {c(_short(self._current), 'grey'):40s}"
        print(line, end="", flush=True)

    _fallback_total_guess: int | None = None


def _short(path: str, width: int = 38) -> str:
    if len(path) <= width:
        return path
    return "..." + path[-(width - 3):]


def spinner_note(msg: str) -> None:
    console.print(c(f"  » {msg}", "dim"))


# --------------------------------------------------------------------------- #
#  Tables & panels
# --------------------------------------------------------------------------- #
def size_table(rows: Sequence[tuple[str, Any, str]], title: str = "") -> None:
    """rows: list of (name, size_bytes, extra_note)."""
    if RICH:
        t = Table(title=title, title_style="bold cyan", box=HEAVY, header_style="bold", expand=False)
        t.add_column("#", justify="right", style="dim")
        t.add_column("Name", ratio=1, overflow="fold")
        t.add_column("Size", justify="right")
        t.add_column("Info", style="dim", overflow="fold")
        for i, (name, sz, info) in enumerate(rows, 1):
            t.add_row(str(i), name, colorize(sz), info or "")
        console.print(t)
    else:
        if title:
            print(c(f"  {title}", "cyan", True))
        for i, (name, sz, info) in enumerate(rows, 1):
            print(f"  {i:>3}. {name:<38.38} {colorize(sz):>12}  {info}")


def games_table(rows: Sequence[tuple[str, Any, str, str]], title: str = "") -> None:
    """rows: list of (name, size_bytes_or_None, launcher, age_label)."""
    if RICH:
        from rich.box import SIMPLE
        t = Table(title=title, title_style="bold cyan", box=SIMPLE,
                  header_style="bold", padding=(0, 1), expand=False)
        t.add_column("#", justify="right", width=3)
        t.add_column("Jeu", max_width=40, overflow="ellipsis")
        t.add_column("Taille", justify="right", width=10)
        t.add_column("Launcher", width=16, overflow="ellipsis")
        t.add_column("Dernier usage*", width=14)
        for i, (name, sz, launcher, age) in enumerate(rows, 1):
            size_cell = Text("n/d", style="dim") if not sz else Text(human(sz),
                            style="red bold" if sz >= 50 * 1024**3 else
                            ("yellow" if sz >= 5 * 1024**3 else "cyan"))
            t.add_row(str(i), str(name)[:40], size_cell, launcher, age)
        console.print(t)
    else:
        if title:
            print(c(f"  {title}", "cyan", True))
        for i, (name, sz, launcher, age) in enumerate(rows, 1):
            s = human(sz) if sz else "n/d"
            print(f"  {i:>3}. {str(name)[:40]:<40.40} {s:>10}  {launcher:<16} {age}")


def drive_panel(drive: dict[str, Any], top_folders: list[tuple[str, int]] | None = None) -> None:
    """Render one drive block with an ASCII usage bar and top folders."""
    total = drive.get("total", 0)
    free = drive.get("free", 0)
    used = max(0, total - free)
    pct = used / total if total else 0.0

    bar_w = 24
    filled = int(round(pct * bar_w))
    if RICH:
        bar = Text("█" * filled, style=severity_color(pct))
        bar.append("░" * (bar_w - filled), style="grey35")
        head = Text.assemble((drive["mount"] + "  ", "bold yellow"), ("[" + drive.get("label", "") + "]", "dim"))
        body = Group(
            head,
            Align.center(bar, vertical="middle"),
            Text(f"  Total: {human(total)}   Used: {human(used)} ({pct * 100:.0f}%)   Free: {human(free)}"),
            Text(f"  FS: {drive.get('fstype', '?')}   Type: {drive.get('kind', '?')}   SN: {drive.get('serial', '-')}", style="dim"),
        )
        if top_folders:
            tf = Table(box=None, show_header=False, padding=(0, 1))
            tf.add_column(justify="right", style="dim")
            tf.add_column(ratio=1, overflow="fold")
            tf.add_column(justify="right")
            for i, (name, sz) in enumerate(top_folders[:8], 1):
                share = f"{sz / used * 100:.0f}%" if used else ""
                tf.add_row(f"{i}.", name, colorize(sz) + ("  " + c(share, "dim") if share else ""))
            body = Group(body, Text("  Top folders:", style="bold"), tf)
        console.print(Panel(body, border_style=severity_color(pct), title=f"[bold]{drive['mount']}[/]",
                            subtitle=c(f"{drive.get('kind', '')}", "dim"), width=64, expand=False))
    else:
        print(c(f"  {drive['mount']}  [{drive.get('label', '')}]", "yellow", True))
        bar = "#" * filled + "-" * (bar_w - filled)
        print(f"  [{bar}] {pct * 100:3.0f}%")
        print(f"  Total: {human(total)}  Used: {human(used)}  Free: {human(free)}")
        if top_folders:
            print("  Top folders:")
            for i, (name, sz) in enumerate(top_folders[:8], 1):
                print(f"    {i:>2}. {name:<30.30} {human(sz)}")


def tree_lines(root: dict[str, Any], max_depth: int = 3, max_children: int = 6) -> list[str]:
    """ASCII tree of biggest subfolders (used by analyse détaillée)."""
    out: list[str] = []

    def walk(node: dict[str, Any], depth: int, prefix: str) -> None:
        children = node.get("children") or []
        kids = sorted(children, key=lambda x: x.get("size", 0), reverse=True)[:max_children]
        hidden = len(children) - len(kids)
        for i, ch in enumerate(kids):
            last = i == len(kids) - 1
            conn = "└── " if last else "├── "
            out.append(f"{prefix}{conn}{ch['name']:<28.28} {human(ch.get('size', 0)):>10}  {ch.get('files', 0):,} files")
            if depth < max_depth and ch.get("children"):
                walk(ch, depth + 1, prefix + ("    " if last else "│   "))
        if hidden:
            out.append(f"{prefix}└── {c(f'... +{hidden} more', 'dim')}")

    out.append(f"{root['path']}  [{human(root.get('size', 0))}]")
    walk(root, 1, "")
    return out


def choose_index(title: str, count: int, allow_zero: bool = False) -> int | None:
    """Ask the user to pick 1..count. Returns None on cancel/invalid."""
    lo = 0 if allow_zero else 1
    try:
        raw = input(c(f"  {title} [{lo}-{count}] (vide = annuler) > ", "cyan")).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        return None
    return idx if lo <= idx <= count else None


def ask(text: str, default: str = "") -> str:
    try:
        raw = input(c(f"  {text} > ", "cyan")).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return raw or default


def choose_multi(title: str, count: int) -> list[int]:
    """Ask for a selection like '1,3-5' (1-based). Empty/invalid -> []."""
    try:
        raw = input(c(f"  {title} > ", "cyan")).strip()
    except (EOFError, KeyboardInterrupt):
        return []
    if not raw or raw.lower() in ("n", "non", "0"):
        return []
    picked: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            picked.update(range(a, b + 1))
            continue
        if part.isdigit():
            picked.add(int(part))
    return sorted(i for i in picked if 1 <= i <= count)


def ok(msg: str) -> None:
    console.print(c(f"  ✔ {msg}", "green"))


def warn(msg: str) -> None:
    console.print(c(f"  ⚠ {msg}", "yellow"))


def err(msg: str) -> None:
    console.print(c(f"  ✖ {msg}", "red", True))


def info(msg: str) -> None:
    console.print(c(f"  • {msg}", "dim"))
