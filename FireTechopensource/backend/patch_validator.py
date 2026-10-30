"""
patch_validator.py - Checks (and tidies) the unified diff suggested by Gemma.

What it does
------------
* Parses the diff and checks it has a sane unified-diff structure.
* Rejects unsafe paths: absolute paths, "..", ignored folders (.git,
  node_modules ...), secret/.env files, unsupported file types, and anything
  that resolves outside the selected repository (including via symlinks).
* Rejects file deletions, renames, mode changes and binary patches.
* Compares each hunk with the REAL file contents. Small models often get line
  numbers wrong, so when the hunk's context/removed lines are found in the
  file we rebuild the "@@ -a,b +c,d @@" headers correctly. If a hunk cannot be
  found, the patch is flagged as "not verified".
* NEVER runs commands and NEVER writes to the repository. The patch is only
  returned for a human to review and apply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from scanner import ALLOWED_EXTENSIONS, is_ignored_dir, is_ignored_file

MAX_PATCH_CHARS = 200_000
MAX_PATCH_FILES = 5

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@dataclass
class PatchReport:
    valid: bool        # safe + well-formed
    verified: bool     # every hunk matched the real file contents
    patch: str         # normalised patch text ("" when not valid)
    files: list        # repo-relative files the patch touches
    warnings: list
    errors: list


@dataclass
class _Hunk:
    old_start: int
    new_start: int
    ops: list  # list of (tag, text) with tag in " ", "-", "+"


@dataclass
class _Section:
    old_raw: str
    new_raw: str
    hunks: list


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _clean_patch_text(raw: Optional[str]) -> str:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    # Models often add a sentence before/after a ```diff block: keep only the block.
    fence = re.search(r"```[A-Za-z]*[ \t]*\n(.*?)\n?```", text, re.S)
    if fence and ("@@" in fence.group(1) or "--- " in fence.group(1)):
        text = fence.group(1)
    return text.strip("\n")


def _strip_header_path(raw: str) -> str:
    raw = raw.split("\t")[0].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1]
    return raw


def _is_boundary(lines: list, j: int) -> bool:
    line = lines[j]
    if _HUNK_RE.match(line) or line.startswith("diff --git ") or line.startswith("```"):
        return True
    return line.startswith("--- ") and j + 1 < len(lines) and lines[j + 1].startswith("+++ ")


def _parse_body(body: list, warnings: list) -> list:
    ops = []
    flagged_blank = False
    flagged_prefix = False
    for line in body:
        if line.startswith("\\"):  # "\ No newline at end of file"
            continue
        if line == "":
            ops.append((" ", ""))
            if not flagged_blank:
                warnings.append("Some blank context lines had no leading space; they were treated as context.")
                flagged_blank = True
        elif line[0] in " +-":
            ops.append((line[0], line[1:]))
        else:
            ops.append((" ", line))
            if not flagged_prefix:
                warnings.append("Some diff lines had no +, - or space prefix; they were treated as context.")
                flagged_prefix = True
    return ops


def _parse(lines: list, errors: list, warnings: list) -> list:
    sections: list = []
    current: Optional[_Section] = None
    ignored = 0
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
            current = _Section(_strip_header_path(line[4:]), _strip_header_path(lines[i + 1][4:]), [])
            sections.append(current)
            i += 2
            continue
        m = _HUNK_RE.match(line)
        if m:
            if current is None:
                errors.append("Found a hunk before any '--- a/file' / '+++ b/file' header.")
                i += 1
                continue
            j = i + 1
            body = []
            while j < n and not _is_boundary(lines, j):
                body.append(lines[j])
                j += 1
            while body and body[-1] == "":
                body.pop()
            ops = _parse_body(body, warnings)
            if not any(tag in "+-" for tag, _ in ops):
                errors.append("A hunk contains no added or removed lines.")
            else:
                current.hunks.append(_Hunk(int(m.group(1)), int(m.group(3)), ops))
            i = j
            continue
        if line.startswith(("deleted file mode", "rename ", "copy ", "GIT binary patch", "Binary files",
                            "old mode", "new mode")):
            errors.append("Patch contains a deletion, rename, copy, mode change or binary change, which is not allowed.")
        elif line.startswith(("diff --git", "index ", "new file mode", "similarity index")):
            pass
        else:
            ignored += 1
        i += 1
    if ignored:
        warnings.append(f"Ignored {ignored} line(s) outside the diff (for example explanatory text).")
    return sections


# --------------------------------------------------------------------------
# Path safety
# --------------------------------------------------------------------------
def _exists(root: Path, rel: str) -> bool:
    try:
        return (root / rel).is_file()
    except (OSError, ValueError):
        return False


def _normalise_header_path(raw: str, root: Path) -> Optional[str]:
    """Return repo-relative path text, or None for /dev/null."""
    if raw == "/dev/null":
        return None
    raw = raw.replace("\\", "/")
    stripped = raw[2:] if raw[:2] in ("a/", "b/") else raw
    if stripped != raw and not _exists(root, stripped) and _exists(root, raw):
        return raw
    return stripped


def _check_path(rel: str, root: Path) -> Optional[str]:
    """Return an error message if `rel` is unsafe, else None."""
    shown = repr(rel[:80])
    if not rel or "\x00" in rel:
        return f"Unsafe patch path {shown}: empty or invalid."
    if rel.startswith(("/", "~")) or _DRIVE_RE.match(rel):
        return f"Unsafe patch path {shown}: absolute paths are not allowed."
    parts = PurePosixPath(rel).parts
    if any(p == ".." for p in parts):
        return f"Unsafe patch path {shown}: path traversal ('..') is not allowed."
    if any(is_ignored_dir(p) for p in parts[:-1]):
        return f"Unsafe patch path {shown}: it points into an ignored folder."
    if is_ignored_file(parts[-1]):
        return f"Unsafe patch path {shown}: secret, lock or generated files cannot be patched."
    if PurePosixPath(parts[-1]).suffix.lower() not in ALLOWED_EXTENSIONS:
        return f"Unsafe patch path {shown}: unsupported file type."
    try:
        (root / rel).resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return f"Unsafe patch path {shown}: it resolves outside the repository."
    return None


# --------------------------------------------------------------------------
# Verification against the real file
# --------------------------------------------------------------------------
def _read_lines(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines, crlf


_NORMALISERS = (
    lambda s: s,
    lambda s: s.rstrip(),
    lambda s: s.strip(),
    lambda s: " ".join(s.split()),
)


def _locate(file_lines: list, old_seq: list, hint_idx: int) -> Optional[tuple]:
    """Find old_seq inside file_lines. Returns (index, exact_match) or None."""
    n = len(old_seq)
    if n == 0 or n > len(file_lines):
        return None
    for level, norm in enumerate(_NORMALISERS):
        wanted = [norm(s) for s in old_seq]
        found = []
        for k in range(len(file_lines) - n + 1):
            if norm(file_lines[k]) != wanted[0]:
                continue
            if all(norm(file_lines[k + t]) == wanted[t] for t in range(1, n)):
                found.append(k)
        if found:
            return min(found, key=lambda k: abs(k - hint_idx)), level == 0
    return None


def _rewrite_old_side(ops: list, file_lines: list, pos: int) -> list:
    out, k = [], 0
    for tag, text in ops:
        if tag in " -":
            out.append((tag, file_lines[pos + k]))
            k += 1
        else:
            out.append((tag, text))
    return out


def _rebuild_section(path: str, is_new: bool, hunks: list, file_lines: list, warnings: list, errors: list) -> tuple:
    if not hunks:
        errors.append(f"The patch for '{path}' has no hunks.")
        return "", False
    out = [f"diff --git a/{path} b/{path}"]
    if is_new:
        out += ["new file mode 100644", "--- /dev/null", f"+++ b/{path}"]
    else:
        out += [f"--- a/{path}", f"+++ b/{path}"]

    verified = True
    delta = 0
    prev_end = 0
    for n, h in enumerate(hunks, 1):
        ops = list(h.ops)
        old_seq = [t for tag, t in ops if tag in " -"]
        old_count = len(old_seq)
        new_count = sum(1 for tag, _ in ops if tag in " +")
        if is_new:
            if any(tag != "+" for tag, _ in ops):
                errors.append(f"The patch creates '{path}' but contains context or removed lines.")
                return "", False
            old_start, new_start = 0, 1
        else:
            located = _locate(file_lines, old_seq, h.old_start - 1)
            if located is None:
                verified = False
                warnings.append(
                    f"Hunk {n} for '{path}' could not be matched to the file's real contents; "
                    "review it manually before applying."
                )
                old_start, new_start = h.old_start, h.new_start
            else:
                pos, exact = located
                if not exact:
                    ops = _rewrite_old_side(ops, file_lines, pos)
                    warnings.append(f"Hunk {n} for '{path}': whitespace in context lines was corrected to match the file.")
                if pos < prev_end:
                    warnings.append(f"Hunk {n} for '{path}' overlaps the previous hunk.")
                old_start = pos + 1
                new_start = pos + 1 + delta if new_count else pos + delta
                prev_end = pos + old_count
                delta += new_count - old_count
        out.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")
        out.extend(tag + text for tag, text in ops)
    return "\n".join(out), verified


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def validate_patch(diff_text: Optional[str], repo_root: Path) -> PatchReport:
    """Validate a model-written diff against the repository. Never modifies files."""
    root = Path(repo_root).resolve()
    errors: list = []
    warnings: list = []

    text = _clean_patch_text(diff_text)
    if not text.strip():
        return PatchReport(False, False, "", [], [], ["The model did not provide a patch."])
    if len(text) > MAX_PATCH_CHARS:
        return PatchReport(False, False, "", [], [], ["The suggested patch is too large to review safely."])

    sections = _parse(text.split("\n"), errors, warnings)
    if not sections and not errors:
        errors.append("No file sections ('--- a/file' and '+++ b/file') were found in the patch.")
    if len(sections) > MAX_PATCH_FILES:
        errors.append(f"The patch touches more than {MAX_PATCH_FILES} files.")
    if errors:
        return PatchReport(False, False, "", [], warnings, errors)

    blocks: list = []
    files: list = []
    all_verified = True
    for sec in sections:
        old = _normalise_header_path(sec.old_raw, root)
        new = _normalise_header_path(sec.new_raw, root)
        if new is None:
            errors.append("The patch tries to delete a file, which is not allowed.")
            continue
        if old is not None and old != new:
            errors.append("The patch tries to rename a file, which is not allowed.")
            continue
        problem = _check_path(new, root)
        if problem:
            errors.append(problem)
            continue
        target = root / new
        is_new = old is None
        if is_new:
            if target.exists():
                errors.append(f"The patch says '{new}' is a new file, but it already exists.")
                continue
            file_lines: list = []
        else:
            if not target.is_file():
                errors.append(f"The patch targets '{new}', which does not exist in the repository.")
                continue
            try:
                file_lines, crlf = _read_lines(target)
            except OSError:
                errors.append(f"Could not read '{new}' to verify the patch.")
                continue
            if crlf:
                warnings.append(f"'{new}' uses Windows (CRLF) line endings; use 'git apply --ignore-whitespace' if applying fails.")
        block, verified = _rebuild_section(new, is_new, sec.hunks, file_lines, warnings, errors)
        if not block:
            continue
        blocks.append(block)
        files.append(new)
        all_verified = all_verified and verified

    if errors:
        return PatchReport(False, False, "", files, warnings, errors)
    if not all_verified:
        warnings.append("The patch is well-formed, but at least one hunk could not be verified against the real file.")
    return PatchReport(True, all_verified, "\n".join(blocks) + "\n", files, warnings, [])
