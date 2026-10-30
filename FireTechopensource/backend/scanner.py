"""
scanner.py - Safe, bounded repository scanner for Bug Buster.

What it does
------------
* Validates the repository path the user typed (must exist, must be a folder,
  optionally must live under ALLOWED_REPO_ROOTS).
* Walks the repository WITHOUT following symlinks and never leaves the root.
* Only reads .py .js .jsx .ts .tsx .html .css files and skips .git,
  node_modules, virtualenvs, build output, lockfiles, .env files, secrets,
  minified files and binary files.
* Enforces limits on file count, size per file and total bytes read.
* Builds an ASCII directory tree.
* Picks the files most likely to matter for a bug (keyword match against
  screenshot text + issue hint, plus files referenced by those files), and
  falls back to a few likely front-end files.
* Formats the chosen files with line numbers, within a character budget.

Only the Python standard library is used.
"""
from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# What to include / ignore
# --------------------------------------------------------------------------
ALLOWED_EXTENSIONS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css"})
FRONTEND_EXTENSIONS = frozenset({".html", ".css", ".js", ".jsx", ".ts", ".tsx"})

IGNORED_DIR_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env",
        "__pycache__", "build", "dist", ".next", ".nuxt", ".cache", ".idea",
        ".vscode", "coverage", "site-packages", ".mypy_cache", ".pytest_cache",
        ".tox", "secrets", ".secrets",
    }
)
LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
        "pipfile.lock", "composer.lock", "gemfile.lock", "bun.lockb",
        "npm-shrinkwrap.json", "uv.lock",
    }
)
SECRET_NAME_HINTS = ("secret", "credential", "id_rsa", "private_key", "privatekey", "api_key", "apikey")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".keystore")
GENERATED_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".map")


class ScanError(Exception):
    """A problem with the repository path or scan that the user can understand."""

    def __init__(self, message: str, status_code: int = 400, code: str = "invalid_repository"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def is_ignored_dir(name: str) -> bool:
    low = name.lower()
    return low in IGNORED_DIR_NAMES or low.endswith(".egg-info")


def is_ignored_file(name: str) -> bool:
    low = name.lower()
    if low.startswith(".env"):
        return True
    if low in LOCKFILE_NAMES or low.endswith(".lock"):
        return True
    if low.endswith(SECRET_SUFFIXES) or low.endswith(GENERATED_SUFFIXES):
        return True
    return any(hint in low for hint in SECRET_NAME_HINTS)


# --------------------------------------------------------------------------
# Path validation
# --------------------------------------------------------------------------
def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_repo_path(raw: Optional[str], allowed_roots: Iterable[Path] = ()) -> Path:
    """Turn the user's repo_path into a safe, resolved directory Path."""
    if raw is None or not raw.strip():
        raise ScanError("repo_path is required.")
    raw = raw.strip()
    if "\x00" in raw or len(raw) > 1024:
        raise ScanError("repo_path is not a valid path.")
    try:
        root = Path(raw).expanduser().resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        raise ScanError("Repository path does not exist. Check the folder path and try again.")
    except (OSError, RuntimeError, ValueError):
        raise ScanError("repo_path could not be resolved.")
    if not root.is_dir():
        raise ScanError("repo_path must be a folder, not a file.")
    if root == Path(root.anchor):
        raise ScanError(
            "Refusing to scan the whole drive. Choose your project folder.",
            400,
            "repository_too_broad",
        )
    roots = list(allowed_roots)
    if roots and not any(_is_within(root, r) for r in roots):
        raise ScanError(
            "That folder is outside the locations this backend is allowed to read "
            "(see ALLOWED_REPO_ROOTS).",
            403,
            "repository_not_allowed",
        )
    return root


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------
@dataclass
class SourceFile:
    rel_path: str
    text: str
    size: int

    @property
    def line_count(self) -> int:
        return len(self.text.splitlines())


@dataclass
class RepoScan:
    root: Path
    files: list
    tree: str
    skipped: dict
    truncated: bool
    total_bytes: int


def scan_repository(root: Path, max_files: int, max_file_bytes: int, max_total_bytes: int) -> RepoScan:
    """Read supported source files under `root`, respecting all limits."""
    root = Path(root).resolve()
    skipped = {"ignored": 0, "too_large": 0, "binary_or_unreadable": 0, "unsafe": 0}
    files: list = []
    total = 0
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        kept = []
        for d in sorted(dirnames):
            if is_ignored_dir(d):
                skipped["ignored"] += 1
            elif os.path.islink(os.path.join(dirpath, d)):
                skipped["unsafe"] += 1
            else:
                kept.append(d)
        dirnames[:] = kept

        for name in sorted(filenames):
            if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            if is_ignored_file(name):
                skipped["ignored"] += 1
                continue
            full = Path(dirpath) / name
            if full.is_symlink():
                skipped["unsafe"] += 1
                continue
            try:
                full.resolve().relative_to(root)
            except (OSError, ValueError, RuntimeError):
                skipped["unsafe"] += 1
                continue
            try:
                size = full.stat().st_size
            except OSError:
                skipped["binary_or_unreadable"] += 1
                continue
            if size > max_file_bytes:
                skipped["too_large"] += 1
                continue
            if len(files) >= max_files or total + size > max_total_bytes:
                truncated = True
                break
            try:
                data = full.read_bytes()
            except OSError:
                skipped["binary_or_unreadable"] += 1
                continue
            if b"\x00" in data:
                skipped["binary_or_unreadable"] += 1
                continue
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped["binary_or_unreadable"] += 1
                continue
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            files.append(SourceFile(full.relative_to(root).as_posix(), text, size))
            total += size
        if truncated:
            break

    tree = build_tree(root.name or str(root), [f.rel_path for f in files])
    return RepoScan(root=root, files=files, tree=tree, skipped=skipped, truncated=truncated, total_bytes=total)


def build_tree(root_name: str, rel_paths: Iterable[str], max_lines: int = 200) -> str:
    """ASCII directory tree built from the files that were actually scanned."""
    tree: dict = {}
    for p in rel_paths:
        parts = p.split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    lines = [f"{root_name}/"]

    def walk(node: dict, prefix: str) -> None:
        items = sorted(node.items(), key=lambda kv: (kv[1] is None, kv[0].lower()))
        for idx, (name, child) in enumerate(items):
            last = idx == len(items) - 1
            lines.append(f"{prefix}{'`-- ' if last else '|-- '}{name}{'/' if child is not None else ''}")
            if child is not None:
                walk(child, prefix + ("    " if last else "|   "))

    walk(tree, "")
    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... ({extra} more entries not shown)"]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Smart file filtering
# --------------------------------------------------------------------------
_STOPWORDS = frozenset(
    """
    the and for with that this from are was were not but you your can has have its into there when then than
    them they their what which will would should could about above below over under also just only very more
    most some such each any all one two out off our his her she him who how why where while been being does did
    done get got use used using like looks look seems seem appears appear visible shown show shows displayed
    screenshot image picture page website site user interface text layout color colour colors colours contrast
    alignment aligned issue issues problem problems bug bugs button buttons element elements section likely
    possible possibly none heading headings label labels error errors message messages
    """.split()
)


def extract_keywords(*texts: Optional[str], max_tokens: int = 60) -> tuple:
    """Return (quoted phrases, single keywords), all lower-case."""
    phrases: list = []
    tokens: list = []
    seen: set = set()
    for text in texts:
        if not text:
            continue
        for m in re.finditer(r'"([^"\n]{3,60})"|\'([^\'\n]{3,60})\'|`([^`\n]{3,60})`', text):
            phrase = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text):
            low = tok.lower()
            if low in _STOPWORDS or low in seen:
                continue
            seen.add(low)
            tokens.append(low)
    return phrases[:30], tokens[:max_tokens]


def _ext(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def _score_file(f: SourceFile, phrases: list, tokens: list) -> float:
    low = f.text.lower()
    name = f.rel_path.lower()
    score = 0.0
    for p in phrases:
        if p in low:
            score += 4.0
        if p in name:
            score += 2.0
    for t in tokens:
        count = low.count(t)
        if count:
            score += 1.0 + 0.25 * min(count, 8)
        if t in name:
            score += 3.0
    if score > 0 and _ext(f.rel_path) in FRONTEND_EXTENSIONS:
        score += 0.5
    return score


_REF_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"'#?\s]+)["']"""
    r"""|(?:from|import)\s+["'](\.{1,2}/[^"']+)["']"""
    r"""|require\(\s*["'](\.{1,2}/[^"']+)["']\s*\)"""
    r"""|@import\s+(?:url\()?["'](\.{1,2}/[^"')]+)["']""",
    re.IGNORECASE,
)


def _local_references(f: SourceFile, by_path: dict) -> list:
    """Files that `f` links to (script/style tags, imports, requires)."""
    if _ext(f.rel_path) not in FRONTEND_EXTENSIONS:
        return []
    base = posixpath.dirname(f.rel_path)
    found = []
    for m in _REF_RE.finditer(f.text):
        ref = next((g for g in m.groups() if g), "")
        if not ref or re.match(r"^[a-z][a-z0-9+.-]*:|^//", ref, re.IGNORECASE):
            continue
        cand = posixpath.normpath(ref.lstrip("/") if ref.startswith("/") else posixpath.join(base, ref))
        options = [cand]
        if not posixpath.splitext(cand)[1]:
            options += [cand + e for e in (".js", ".jsx", ".ts", ".tsx", ".css")]
            options += [f"{cand}/index{e}" for e in (".js", ".jsx", ".ts", ".tsx")]
        for opt in options:
            if opt in by_path:
                found.append(by_path[opt])
                break
    return found


def _fallback_rank(f: SourceFile) -> int:
    stem = posixpath.splitext(posixpath.basename(f.rel_path))[0].lower()
    ext = _ext(f.rel_path)
    if stem in {"index", "main", "app", "style", "styles", "global", "globals", "home"}:
        return 0
    if ext in {".html", ".css"}:
        return 1
    if ext in {".js", ".jsx", ".ts", ".tsx"}:
        return 2
    return 3


@dataclass
class Selection:
    files: list
    mode: str  # "keyword-match" or "fallback"


def select_relevant_files(files: list, phrases: list, tokens: list, max_selected: int = 8) -> Selection:
    """Choose a small set of files worth sending to the model."""
    by_path = {f.rel_path: f for f in files}
    scored = []
    for f in files:
        s = _score_file(f, phrases, tokens)
        if s > 0:
            scored.append((s, f))
    scored.sort(key=lambda x: (-x[0], x[1].rel_path))

    if scored:
        chosen = [f for _, f in scored[: max(1, max_selected - 3)]]
        paths = {f.rel_path for f in chosen}
        for f in list(chosen):
            for ref in _local_references(f, by_path):
                if ref.rel_path not in paths and len(chosen) < max_selected:
                    chosen.append(ref)
                    paths.add(ref.rel_path)
        for _, f in scored:
            if len(chosen) >= max_selected:
                break
            if f.rel_path not in paths:
                chosen.append(f)
                paths.add(f.rel_path)
        return Selection(chosen, "keyword-match")

    pool = [f for f in files if _ext(f.rel_path) in FRONTEND_EXTENSIONS] or list(files)
    pool.sort(key=lambda f: (_fallback_rank(f), f.rel_path.count("/"), f.size, f.rel_path))
    return Selection(pool[:max_selected], "fallback")


# --------------------------------------------------------------------------
# Formatting code for the model
# --------------------------------------------------------------------------
def format_numbered_source(f: SourceFile, max_chars: Optional[int] = None) -> tuple:
    """Return (text block with line numbers, was_truncated)."""
    lines = f.text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    width = len(str(max(len(lines), 1)))
    header = f"===== FILE: {f.rel_path} ({len(lines)} lines) ====="
    out = [header]
    used = len(header) + 1
    truncated = False
    for i, line in enumerate(lines, 1):
        row = f"{i:>{width}}| {line}"
        if max_chars is not None and used + len(row) + 1 > max_chars:
            out.append(f"[... truncated: lines {i}-{len(lines)} not shown ...]")
            truncated = True
            break
        out.append(row)
        used += len(row) + 1
    out.append(f"===== END FILE: {f.rel_path} =====")
    return "\n".join(out), truncated


def build_code_context(files: list, max_chars: int) -> tuple:
    """Return (context text, included paths, paths that were cut short)."""
    parts, included, cut = [], [], []
    remaining = max_chars
    for f in files:
        if remaining < 400:
            break
        block, was_cut = format_numbered_source(f, remaining)
        parts.append(block)
        included.append(f.rel_path)
        if was_cut:
            cut.append(f.rel_path)
        remaining -= len(block) + 2
    return "\n\n".join(parts), included, cut
