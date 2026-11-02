#!/usr/bin/env python3
"""patchctl - the Graphite patch engine.

Graphite = GrapheneOS + a stack of local patches. Every patch lives in
patches/<id>/ with a patch.toml (metadata) and one or more patch files, each
targeting one repo project (e.g. frameworks/base). See patches/README.md.

Subcommands (normally driven by build.sh / update.sh, but usable directly):
  list                      show all patches and their state
  info ID                   show metadata of one patch
  new ID                    scaffold a new patch directory
  apply                     reset patched projects and apply all patches to src/
  reset                     restore all patched projects to their manifest revision
  validate --tag TAG        dry-run all patches against another GrapheneOS tag
                            (no checkout; writes an agent-ready report)
  export ID --project P     write commits from src/P into patches/ID
  fix start|continue|finish|abort ID --tag TAG
                            fix workspace to rebase a broken patch onto TAG
  refresh ID --tag TAG      regenerate a patch that only applies with 3-way merge
  latest-tag                print the newest GrapheneOS release tag

Only the Python standard library is used (needs Python >= 3.11 for tomllib).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCHES_DIR = Path(os.environ.get("GRAPHITE_PATCHES_DIR", ROOT / "patches"))
STATE_DIR = ROOT / "state"
CACHE_DIR = STATE_DIR / "cache"
REPORTS_DIR = ROOT / "reports"
WORK_DIR = ROOT / "work"
LOCAL_MANIFESTS_DIR = ROOT / "manifests"
SKIP_LIST = PATCHES_DIR / "skip.list"
APPLIED_STATE = STATE_DIR / "applied.json"
ALLOWED_SIGNERS = ROOT / "keys" / "trust" / "grapheneos_allowed_signers"
MANIFEST_URL = os.environ.get(
    "GRAPHITE_MANIFEST_URL", "https://github.com/GrapheneOS/platform_manifest.git")
TRAILER = "Graphite-Patch"
IDENT_ENV = {
    "GIT_AUTHOR_NAME": "Graphite", "GIT_AUTHOR_EMAIL": "graphite@localhost",
    "GIT_COMMITTER_NAME": "Graphite Patcher", "GIT_COMMITTER_EMAIL": "graphite@localhost",
}

# Piece / patch statuses, ordered roughly by severity.
OK = "OK"                          # applies cleanly
ALREADY_APPLIED = "ALREADY_APPLIED"  # upstream already contains this change
OK_3WAY = "OK_3WAY"                # applies, but only via 3-way merge (refresh it)
NEEDS_REFRESH = "NEEDS_REFRESH"    # patch-level: works, but some pieces fuzzy/upstreamed
CONFLICT = "CONFLICT"              # 3-way merge conflicts
FAILED = "FAILED"                  # cannot apply at all (file gone, no base blob, ...)
PROJECT_MISSING = "PROJECT_MISSING"  # project no longer in the manifest
SKIPPED_DEP = "SKIPPED_DEP"        # a dependency failed or is disabled
DISABLED = "DISABLED"              # disabled in patch.toml or skip.list
BROKEN = {CONFLICT, FAILED, PROJECT_MISSING}
GOOD = {OK, OK_3WAY, NEEDS_REFRESH, ALREADY_APPLIED}

# ----------------------------------------------------------------------------
# small helpers

_tty = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _tty else s


def info(msg: str) -> None:
    print(c("1;34", "==>"), msg, flush=True)


def warn(msg: str) -> None:
    print(c("1;33", "WARNING:"), msg, flush=True)


def err(msg: str) -> None:
    print(c("1;31", "ERROR:"), msg, file=sys.stderr, flush=True)


class Fatal(Exception):
    pass


STATUS_COLOR = {OK: "32", ALREADY_APPLIED: "36", OK_3WAY: "33", NEEDS_REFRESH: "33",
                CONFLICT: "31", FAILED: "31", PROJECT_MISSING: "31",
                SKIPPED_DEP: "35", DISABLED: "90"}


def cs(status: str) -> str:
    return c(STATUS_COLOR.get(status, "0"), status)


def run(args, cwd=None, env=None, input=None, check=True) -> subprocess.CompletedProcess:
    full_env = None
    if env:
        full_env = os.environ.copy()
        full_env.update(env)
    r = subprocess.run(args, cwd=cwd, env=full_env, input=input,
                       capture_output=True, text=True, errors="replace")
    if check and r.returncode != 0:
        raise Fatal(f"command failed ({r.returncode}): {' '.join(map(str, args))}\n"
                    f"{r.stdout}{r.stderr}".rstrip())
    return r


def git(gitdir, *args, env=None, input=None, check=True) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(gitdir), *map(str, args)], env=env, input=input, check=check)


def rel(path: Path) -> str:
    """Path relative to the Graphite root when possible (reports stay portable)."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def truncate_lines(text: str, limit: int) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n... [{len(lines) - limit} more lines truncated]"


def fence_lang(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {".java": "java", ".kt": "kotlin", ".c": "c", ".h": "c", ".cpp": "cpp",
            ".cc": "cpp", ".rs": "rust", ".py": "python", ".xml": "xml", ".mk": "make",
            ".bp": "", ".sh": "bash", ".te": "", ".json": "json", ".go": "go",
            ".aidl": "java", ".rc": ""}.get(ext, "")


# ----------------------------------------------------------------------------
# patch model

@dataclasses.dataclass
class Change:
    project: str
    file: Path


@dataclasses.dataclass
class Patch:
    id: str
    dir: Path
    title: str
    description: str
    required: bool
    skip_impact: str
    category: str
    depends: list[str]
    enabled: bool
    notes: str
    changes: list[Change]

    @property
    def projects(self) -> list[str]:
        out = []
        for ch in self.changes:
            if ch.project not in out:
                out.append(ch.project)
        return out


def load_patches() -> list[Patch]:
    patches = []
    if not PATCHES_DIR.is_dir():
        return patches
    for d in sorted(p for p in PATCHES_DIR.iterdir() if p.is_dir()):
        meta = d / "patch.toml"
        if not meta.exists():
            continue
        try:
            data = tomllib.loads(meta.read_text())
        except tomllib.TOMLDecodeError as e:
            raise Fatal(f"{meta}: invalid TOML: {e}")
        changes = []
        for ch in data.get("change", []):
            f = d / ch["file"]
            if not f.exists():
                raise Fatal(f"{meta}: change file {ch['file']} does not exist")
            changes.append(Change(project=ch["project"].strip("/"), file=f))
        patches.append(Patch(
            id=d.name, dir=d,
            title=data.get("title", d.name),
            description=data.get("description", "").strip(),
            required=bool(data.get("required", True)),
            skip_impact=data.get("skip_impact", "").strip(),
            category=data.get("category", "misc"),
            depends=list(data.get("depends", [])),
            enabled=bool(data.get("enabled", True)),
            notes=data.get("notes", "").strip(),
            changes=changes,
        ))
    ids = {p.id for p in patches}
    for p in patches:
        for dep in p.depends:
            if dep not in ids:
                raise Fatal(f"patch {p.id} depends on unknown patch {dep}")
            if dep >= p.id:
                raise Fatal(f"patch {p.id} depends on {dep}, which sorts after it; "
                            "rename so dependencies come first")
    return patches


def load_skip_list() -> dict[str, str]:
    out = {}
    if SKIP_LIST.exists():
        for line in SKIP_LIST.read_text().splitlines():
            body, _, reason = line.partition("#")
            pid = body.strip()
            if pid:
                out[pid] = reason.strip()
    return out


def add_to_skip_list(pid: str, reason: str) -> None:
    current = load_skip_list()
    if pid in current:
        return
    with SKIP_LIST.open("a") as f:
        f.write(f"{pid}  # {reason}\n")


def remove_from_skip_list(pid: str) -> None:
    if not SKIP_LIST.exists():
        return
    keep = [l for l in SKIP_LIST.read_text().splitlines()
            if l.partition("#")[0].strip() != pid]
    SKIP_LIST.write_text("\n".join(keep) + ("\n" if keep else ""))


def find_patch(patches: list[Patch], pid: str) -> Patch:
    for p in patches:
        if p.id == pid:
            return p
    matches = [p for p in patches if pid in p.id]
    if len(matches) == 1:
        return matches[0]
    raise Fatal(f"no such patch: {pid}")


# ----------------------------------------------------------------------------
# patch file parsing

@dataclasses.dataclass
class Hunk:
    header: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[str]

    @property
    def preimage(self) -> list[str]:
        return [l[1:] for l in self.lines if l[:1] in (" ", "-")]


@dataclasses.dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    hunks: list[Hunk]
    text: str

    @property
    def path(self) -> str:
        return self.old_path or self.new_path or "?"


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    cur_lines: list[str] = []
    hunk: Hunk | None = None

    def flush():
        nonlocal cur, cur_lines
        if cur is not None:
            cur.text = "\n".join(cur_lines)
            files.append(cur)
        cur, cur_lines = None, []

    for line in text.splitlines():
        if line.startswith("diff --git "):
            flush()
            m = re.match(r"diff --git a/(.*) b/(.*)", line)
            cur = FileDiff(m.group(1) if m else None, m.group(2) if m else None, [], "")
            hunk = None
        elif cur is None and line.startswith("--- "):
            flush()
            cur = FileDiff(None, None, [], "")
            hunk = None
        if cur is None:
            continue
        cur_lines.append(line)
        if line.startswith("--- ") and hunk is None:
            p = line[4:].split("\t")[0]
            cur.old_path = None if p == "/dev/null" else re.sub(r"^a/", "", p)
        elif line.startswith("+++ ") and hunk is None:
            p = line[4:].split("\t")[0]
            cur.new_path = None if p == "/dev/null" else re.sub(r"^b/", "", p)
        elif m := HUNK_RE.match(line):
            hunk = Hunk(line, int(m.group(1)), int(m.group(2) or 1),
                        int(m.group(3)), int(m.group(4) or 1), [])
            cur.hunks.append(hunk)
        elif hunk is not None and line[:1] in (" ", "-", "+", "\\"):
            hunk.lines.append(line)
    flush()
    return files


@dataclasses.dataclass
class Piece:
    """One commit/diff out of a patch file."""
    patch: Patch
    change: Change
    index: int
    total: int
    subject: str
    author: str
    email: str
    date: str
    body: str
    diff_path: Path
    diff: str
    mbox_path: Path

    @property
    def project(self) -> str:
        return self.change.project

    @property
    def label(self) -> str:
        return f"{self.change.file.name} [{self.index}/{self.total}] {self.subject}"

    def commit_message(self) -> str:
        body = "\n".join(l for l in self.body.splitlines()
                         if not l.startswith(f"{TRAILER}:")).strip()
        msg = self.subject + ("\n\n" + body if body else "")
        return msg + f"\n\n{TRAILER}: {self.patch.id}\n"


class PieceCache:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="graphite-pieces-"))
        self._cache: dict[tuple[str, str], list[Piece]] = {}

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pieces(self, patch: Patch, change: Change) -> list[Piece]:
        key = (patch.id, str(change.file))
        if key in self._cache:
            return self._cache[key]
        out_dir = self.tmp / f"{patch.id}-{len(self._cache)}"
        out_dir.mkdir()
        r = run(["git", "mailsplit", "-b", "-o" + str(out_dir), str(change.file)], check=False)
        if r.returncode != 0:
            raise Fatal(f"cannot split {change.file}: {r.stderr.strip()}")
        mails = sorted(p for p in out_dir.iterdir() if p.name.isdigit())
        pieces = []
        for i, mail in enumerate(mails, 1):
            msg, dif = mail.with_suffix(".msg"), mail.with_suffix(".diff")
            r = run(["git", "mailinfo", "-b", str(msg), str(dif)],
                    input=mail.read_text(errors="replace"), check=False)
            hdr = dict(re.findall(r"^(\w+): ?(.*)$", r.stdout, re.M))
            diff_text = dif.read_text(errors="replace") if dif.exists() else ""
            if not diff_text.strip():
                continue
            subject = hdr.get("Subject") or patch.title
            pieces.append(Piece(
                patch=patch, change=change, index=i, total=len(mails), subject=subject,
                author=hdr.get("Author", ""), email=hdr.get("Email", ""),
                date=hdr.get("Date", ""), body=msg.read_text(errors="replace") if msg.exists() else "",
                diff_path=dif, diff=diff_text, mbox_path=mail))
        for p in pieces:
            p.total = len(pieces)
        for i, p in enumerate(pieces, 1):
            p.index = i
        if not pieces:
            raise Fatal(f"{change.file}: no diff found in patch file")
        self._cache[key] = pieces
        return pieces

    def mbox_for(self, piece: Piece) -> Path:
        """A clean, git-am compatible mbox for one piece (also for plain diffs)."""
        out = piece.diff_path.with_suffix(".mbox")
        author = piece.author or "Graphite"
        email = piece.email or "graphite@localhost"
        date = piece.date or "Thu, 1 Jan 1970 00:00:00 +0000"
        body = "\n".join(l for l in piece.body.splitlines()
                         if not l.startswith(f"{TRAILER}:")).strip()
        out.write_text(f"From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
                       f"From: {author} <{email}>\nDate: {date}\nSubject: {piece.subject}\n\n"
                       f"{body}\n---\n{piece.diff}")
        return out


# ----------------------------------------------------------------------------
# manifests

@dataclasses.dataclass
class Project:
    name: str
    path: str
    remote: str
    url: str
    revision: str


def _resolve_fetch(fetch: str) -> str:
    if fetch.startswith(".."):
        base = MANIFEST_URL.rsplit("/", 1)[0]
        while fetch.startswith(".."):
            base = base.rsplit("/", 1)[0]
            fetch = fetch[2:].lstrip("/")
        fetch = base + ("/" + fetch if fetch else "")
    return fetch.rstrip("/")


def parse_manifest(loader, entry: str, projects=None, remotes=None, default=None):
    """loader(name) -> xml text. Returns {path: Project}."""
    projects = {} if projects is None else projects
    remotes = {} if remotes is None else remotes
    default = {} if default is None else default
    root = ET.fromstring(loader(entry))
    for el in root:
        if el.tag == "remote":
            remotes[el.get("name")] = {"fetch": _resolve_fetch(el.get("fetch", "")),
                                       "revision": el.get("revision")}
        elif el.tag == "default":
            default.update(el.attrib)
        elif el.tag == "include":
            parse_manifest(loader, el.get("name"), projects, remotes, default)
        elif el.tag == "remove-project":
            for path, p in list(projects.items()):
                if el.get("name") in (p.name, None) and el.get("path") in (p.path, None):
                    del projects[path]
        elif el.tag == "extend-project":
            for p in projects.values():
                if p.name == el.get("name") and el.get("path") in (p.path, None):
                    if el.get("revision"):
                        p.revision = el.get("revision")
        elif el.tag == "project":
            name = el.get("name")
            path = el.get("path", name)
            remote = el.get("remote", default.get("remote"))
            rinfo = remotes.get(remote, {"fetch": "", "revision": None})
            rev = el.get("revision") or rinfo.get("revision") or default.get("revision")
            projects[path] = Project(name=name, path=path, remote=remote,
                                     url=f"{rinfo['fetch']}/{name}", revision=rev)
    return projects


class ManifestStore:
    """Fetches GrapheneOS platform_manifest tags into a private bare cache."""

    def __init__(self):
        self.gitdir = CACHE_DIR / "platform_manifest.git"

    def _ensure(self):
        if not (self.gitdir / "HEAD").exists():
            self.gitdir.mkdir(parents=True, exist_ok=True)
            git(self.gitdir, "init", "-q", "--bare")

    def fetch_tag(self, tag: str) -> None:
        self._ensure()
        if git(self.gitdir, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
            return
        info(f"fetching manifest for tag {tag}")
        git(self.gitdir, "fetch", "-q", "--depth=1", MANIFEST_URL,
            f"+refs/tags/{tag}:refs/tags/{tag}")

    def verify_tag(self, tag: str) -> tuple[bool, str]:
        self.fetch_tag(tag)
        if not ALLOWED_SIGNERS.exists():
            return False, f"allowed signers file missing: {ALLOWED_SIGNERS}"
        r = git(self.gitdir, "-c", f"gpg.ssh.allowedSignersFile={ALLOWED_SIGNERS}",
                "verify-tag", tag, check=False)
        return r.returncode == 0, (r.stdout + r.stderr).strip()

    def projects(self, tag: str, local_manifests: bool = True) -> dict[str, Project]:
        self.fetch_tag(tag)

        def loader(name):
            return git(self.gitdir, "show", f"refs/tags/{tag}:{name}").stdout

        projects = parse_manifest(loader, "default.xml")
        if local_manifests:
            add_local_manifests(projects)
        return projects

    def file(self, tag: str, name: str) -> str:
        self.fetch_tag(tag)
        return git(self.gitdir, "show", f"refs/tags/{tag}:{name}").stdout


def add_local_manifests(projects: dict[str, Project]) -> None:
    if not LOCAL_MANIFESTS_DIR.is_dir():
        return
    for xml in sorted(LOCAL_MANIFESTS_DIR.glob("*.xml")):
        remotes = {"aosp": {"fetch": "https://android.googlesource.com", "revision": None},
                   "grapheneos": {"fetch": "https://github.com/GrapheneOS", "revision": None}}
        parse_manifest(lambda n, x=xml: (LOCAL_MANIFESTS_DIR / n).read_text() if n != xml.name
                       else x.read_text(), xml.name, projects, remotes, {})


def tree_projects(src: Path) -> dict[str, Project]:
    """Projects as currently synced in src/ (from .repo/manifests on disk)."""
    mdir = src / ".repo" / "manifests"
    if not mdir.is_dir():
        raise Fatal(f"{src} is not a synced repo tree (no .repo/manifests)")
    projects = parse_manifest(lambda n: (mdir / n).read_text(), "default.xml")
    add_local_manifests(projects)
    return projects


def tree_tag(src: Path) -> str | None:
    mdir = src / ".repo" / "manifests"
    r = git(mdir, "describe", "--tags", "--exact-match", check=False)
    return r.stdout.strip() or None


def latest_tag() -> str:
    r = run(["git", "ls-remote", "--tags", MANIFEST_URL])
    tags = sorted({m for m in re.findall(r"refs/tags/(\d{10})$", r.stdout, re.M)}, key=int)
    if not tags:
        raise Fatal("no release tags found")
    return tags[-1]


# ----------------------------------------------------------------------------
# object access for projects (src tree if present, else a bare cache)

class Objects:
    def __init__(self, src: Path | None):
        self.src = src

    def gitdir(self, proj: Project) -> Path:
        if self.src:
            wt = self.src / proj.path
            if (wt / ".git").exists():
                return wt
        bare = CACHE_DIR / "projects" / (proj.name.replace("/", "_") + ".git")
        if not (bare / "HEAD").exists():
            bare.mkdir(parents=True, exist_ok=True)
            git(bare, "init", "-q", "--bare")
        return bare

    def ensure(self, gitdir: Path, proj: Project, rev: str | None = None) -> str:
        rev = rev or proj.revision
        r = git(gitdir, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}", check=False)
        if r.returncode == 0:
            return r.stdout.strip()
        info(f"fetching {proj.path} @ {rev[:12]}")
        r = git(gitdir, "fetch", "-q", "--depth=1", "--no-tags", proj.url, rev, check=False)
        if r.returncode != 0:
            # some servers refuse a sha with --depth; retry as ref / full
            r = git(gitdir, "fetch", "-q", "--no-tags", proj.url, rev, check=False)
        if r.returncode != 0:
            raise Fatal(f"cannot fetch {proj.url} {rev}: {r.stderr.strip()}")
        return git(gitdir, "rev-parse", f"{rev}^{{commit}}" if not rev.startswith("refs/")
                   else "FETCH_HEAD^{commit}").stdout.strip()


def compare_url(proj: Project, old: str, new: str) -> str:
    if "github.com" in proj.url:
        return f"{proj.url}/compare/{old}...{new}"
    if "googlesource.com" in proj.url:
        return f"{proj.url}/+log/{old}..{new}"
    if "gitlab.com" in proj.url:
        return f"{proj.url}/-/compare/{old}...{new}"
    return f"{proj.url} ({old}..{new})"


# ----------------------------------------------------------------------------
# diagnostics: everything a human / agent needs to fix a broken piece

APPLY_ERR_RES = [
    (re.compile(r"error: patch failed: (.+?):(\d+)"), "hunk_failed"),
    (re.compile(r"error: (.+?): does not exist in (?:index|working directory)"), "missing"),
    (re.compile(r"error: (.+?): No such file or directory"), "missing"),
    (re.compile(r"error: (.+?): already exists in (?:index|working directory)"), "exists"),
    (re.compile(r"error: (.+?): patch does not apply"), "does_not_apply"),
    (re.compile(r"error: (.+?): does not match index"), "dirty"),
]


def parse_apply_errors(output: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rx, kind in APPLY_ERR_RES:
        for m in rx.finditer(output):
            path = m.group(1)
            detail = kind + (f"@{m.group(2)}" if kind == "hunk_failed" else "")
            out.setdefault(path, [])
            if detail not in out[path]:
                out[path].append(detail)
    return out


def locate_hunk(hunk: Hunk, content: list[str]) -> tuple[int | None, float]:
    """Find where a hunk's pre-image best matches in content. Returns (1-based line, score)."""
    pre = [l.strip() for l in hunk.preimage]
    if not pre or not content:
        return None, 0.0
    stripped = [l.strip() for l in content]
    anchors = [i for i, l in enumerate(pre) if len(l) > 6] or list(range(len(pre)))
    best, best_score = None, 0.0
    for a in anchors[:6]:
        for pos, line in enumerate(stripped):
            if line != pre[a]:
                continue
            start = pos - a
            score = sum(1 for k, p in enumerate(pre)
                        if 0 <= start + k < len(stripped) and stripped[start + k] == p)
            s = score / len(pre)
            if s > best_score:
                best, best_score = start + 1, s
    return best, best_score


def snippet(content: list[str], center: int, radius: int = 25) -> tuple[int, int, str]:
    lo = max(1, center - radius)
    hi = min(len(content), center + radius)
    width = len(str(hi))
    body = "\n".join(f"{n:>{width}}| {content[n - 1]}" for n in range(lo, hi + 1))
    return lo, hi, body


def conflict_regions(text: str, context: int = 8) -> str:
    lines = text.splitlines()
    marks = [i for i, l in enumerate(lines) if l.startswith(("<<<<<<<", "=======", ">>>>>>>", "|||||||"))]
    if not marks:
        return ""
    keep = set()
    i = 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            j = i
            while j < len(lines) and not lines[j].startswith(">>>>>>>"):
                j += 1
            keep.update(range(max(0, i - context), min(len(lines), j + context + 1)))
            i = j
        i += 1
    out, prev = [], -2
    for n in sorted(keep):
        if n != prev + 1:
            out.append(f"--- (line {n + 1}) ---")
        out.append(lines[n])
        prev = n
    return "\n".join(out)


def diagnose_piece(gitdir: Path, piece: Piece, *, index_env: dict | None,
                   worktree: bool, target_rev: str | None, old_rev: str | None,
                   proj: Project | None, apply_output: str,
                   conflicts: dict[str, str]) -> dict:
    d: dict = {"git_apply_output": apply_output.strip()[-8000:], "files": []}
    errors = parse_apply_errors(apply_output)
    files = parse_diff(piece.diff)
    for fd in files:
        if errors and fd.path not in errors and (fd.new_path not in errors):
            continue
        entry: dict = {"path": fd.path, "errors": errors.get(fd.path, errors.get(fd.new_path or "", [])),
                       "hunks": []}
        # current content of the target file
        content: list[str] | None = None
        if worktree:
            f = Path(gitdir) / fd.path
            if f.is_file():
                content = f.read_text(errors="replace").splitlines()
        else:
            r = git(gitdir, "cat-file", "-p", f":{fd.path}", env=index_env, check=False)
            if r.returncode == 0:
                content = r.stdout.splitlines()
        entry["exists_in_target"] = content is not None
        if content is None and old_rev and target_rev and old_rev != target_rev:
            r = git(gitdir, "diff", "-M", "--name-status", old_rev, target_rev, "--", fd.path, check=False)
            ren = git(gitdir, "diff", "-M", "--name-status", "--diff-filter=R", old_rev, target_rev, check=False)
            moved = [l.split("\t")[2] for l in ren.stdout.splitlines()
                     if l.count("\t") == 2 and l.split("\t")[1] == fd.path]
            entry["upstream_status"] = r.stdout.strip() or "file not found in old or new revision"
            if moved:
                entry["renamed_to"] = moved[0]
        for h in fd.hunks:
            he: dict = {"header": h.header, "text": "\n".join([h.header, *h.lines])}
            failed_here = any(e == f"hunk_failed@{h.old_start}" for e in entry["errors"])
            he["reported_failing"] = failed_here
            if content is not None:
                line, score = locate_hunk(h, content)
                he["expected_line"] = h.old_start
                he["best_match_line"] = line
                he["best_match_score"] = round(score, 2)
                center = line if (line and score >= 0.3) else h.old_start
                lo, hi, body = snippet(content, center)
                he["target_snippet"] = {"from": lo, "to": hi, "text": body}
            entry["hunks"].append(he)
        if old_rev and target_rev and old_rev != target_rev and content is not None:
            r = git(gitdir, "diff", old_rev, target_rev, "--", fd.path, check=False)
            if r.returncode == 0 and r.stdout.strip():
                entry["upstream_diff"] = truncate_lines(r.stdout, 400)
            elif r.returncode == 0:
                entry["upstream_diff"] = "(file unchanged upstream between the two revisions)"
        if fd.path in conflicts:
            entry["conflict"] = conflicts[fd.path]
        d["files"].append(entry)
    if proj and old_rev and target_rev:
        d["compare_url"] = compare_url(proj, old_rev, target_rev)
    return d


# ----------------------------------------------------------------------------
# results

@dataclasses.dataclass
class PieceResult:
    piece: Piece
    status: str
    detail: str = ""
    diagnostics: dict | None = None


@dataclasses.dataclass
class PatchResult:
    patch: Patch
    status: str
    pieces: list[PieceResult]
    note: str = ""


def patch_status(pieces: list[PieceResult]) -> str:
    sts = {p.status for p in pieces}
    for bad in (PROJECT_MISSING, FAILED, CONFLICT):
        if bad in sts:
            return bad
    if sts == {ALREADY_APPLIED}:
        return ALREADY_APPLIED
    if sts & {OK_3WAY, ALREADY_APPLIED}:
        return NEEDS_REFRESH
    return OK


def selected_patches(patches, only, skip_list, respect_skip=True):
    """Yield (patch, disabled_reason|None) in order."""
    for p in patches:
        if only and p.id not in only:
            continue
        if not p.enabled:
            yield p, "disabled in patch.toml"
        elif respect_skip and p.id in skip_list:
            yield p, f"listed in patches/skip.list ({skip_list[p.id] or 'no reason given'})"
        else:
            yield p, None


# ----------------------------------------------------------------------------
# validate (no checkout): apply into temporary indexes of the target revisions

def cmd_validate(args) -> int:
    src = Path(args.src) if args.src else None
    if src and not (src / ".repo").is_dir():
        src = None
    store = ManifestStore()
    tag = args.tag if args.tag != "latest" else latest_tag()
    base_tag = args.base_tag
    patches = load_patches()
    skip = load_skip_list()
    only = set(args.only.split(",")) if args.only else None

    sig_ok, sig_msg = store.verify_tag(tag)
    new_projects = store.projects(tag)
    old_projects = store.projects(base_tag) if base_tag else (tree_projects(src) if src else {})
    objs = Objects(src)
    tmp = Path(tempfile.mkdtemp(prefix="graphite-validate-"))
    cache = PieceCache()
    indexes: dict[str, tuple[Path, dict, Path, str]] = {}  # path -> (idxfile, env, gitdir, rev)
    results: list[PatchResult] = []
    failed_ids: set[str] = set()

    def index_for(path: str):
        if path in indexes:
            return indexes[path]
        proj = new_projects[path]
        gd = objs.gitdir(proj)
        rev = objs.ensure(gd, proj)
        if path in old_projects:
            try:
                objs.ensure(gd, old_projects[path])
            except Fatal as e:
                warn(f"could not fetch old revision of {path}: {e}")
        idx = tmp / (path.replace("/", "_") + ".index")
        env = {"GIT_INDEX_FILE": str(idx)}
        git(gd, "read-tree", rev, env=env)
        indexes[path] = (idx, env, gd, rev)
        return indexes[path]

    try:
        info(f"validating {len(patches)} patch(es) against {tag}"
             + (f" (base {base_tag})" if base_tag else ""))
        for p, disabled in selected_patches(patches, only, skip, respect_skip=not args.ignore_skip_list):
            if disabled:
                failed_ids.add(p.id)
                results.append(PatchResult(p, DISABLED, [], disabled))
                print(f"  {cs(DISABLED):<26} {p.id}  ({disabled})")
                continue
            bad_deps = [d for d in p.depends if d in failed_ids]
            if bad_deps:
                failed_ids.add(p.id)
                results.append(PatchResult(p, SKIPPED_DEP, [], f"depends on broken/disabled {', '.join(bad_deps)}"))
                print(f"  {cs(SKIPPED_DEP):<26} {p.id}  (needs {', '.join(bad_deps)})")
                continue
            backups = {}
            piece_results: list[PieceResult] = []
            for ch in p.changes:
                pieces = cache.pieces(p, ch)
                if ch.project not in new_projects:
                    for pc in pieces:
                        piece_results.append(PieceResult(pc, PROJECT_MISSING,
                                             f"project {ch.project} is not in the manifest of {tag}"))
                    continue
                idx, env, gd, rev = index_for(ch.project)
                if ch.project not in backups:
                    backups[ch.project] = idx.read_bytes()
                old = old_projects.get(ch.project)
                old_rev = None
                if old:
                    rr = git(gd, "rev-parse", "-q", "--verify", f"{old.revision}^{{commit}}", check=False)
                    old_rev = rr.stdout.strip() or None
                for pc in pieces:
                    piece_results.append(validate_piece(gd, env, idx, pc, rev, old_rev, new_projects[ch.project]))
                    if piece_results[-1].status in BROKEN:
                        break
            st = patch_status(piece_results)
            if st in BROKEN:
                failed_ids.add(p.id)
                for path, data in backups.items():
                    indexes[path][0].write_bytes(data)
            results.append(PatchResult(p, st, piece_results))
            print(f"  {cs(st):<26} {p.id}" + ("" if p.required else c("90", "  (optional)")))
        sanity = sanity_checks(args, store, tag, base_tag, new_projects, old_projects, objs, sig_ok, sig_msg)
        report_dir = Path(args.report_dir) if args.report_dir else REPORTS_DIR / f"validate-{tag}"
        write_report(report_dir, mode="validate", tag=tag, base_tag=base_tag,
                     results=results, sanity=sanity)
        return summarize(results, report_dir, sanity)
    finally:
        cache.close()
        shutil.rmtree(tmp, ignore_errors=True)


def validate_piece(gd, env, idx: Path, pc: Piece, rev: str, old_rev: str | None, proj: Project) -> PieceResult:
    r = git(gd, "apply", "--cached", "--check", pc.diff_path, env=env, check=False)
    if r.returncode == 0:
        git(gd, "apply", "--cached", pc.diff_path, env=env)
        return PieceResult(pc, OK)
    plain_out = r.stdout + r.stderr
    if git(gd, "apply", "--cached", "--check", "-R", pc.diff_path, env=env, check=False).returncode == 0:
        return PieceResult(pc, ALREADY_APPLIED, "reverse-applies cleanly: upstream already contains this change")
    backup = idx.read_bytes()
    r3 = git(gd, "apply", "--cached", "--3way", pc.diff_path, env=env, check=False)
    if r3.returncode == 0:
        return PieceResult(pc, OK_3WAY, "applies only via 3-way merge; context changed upstream")
    conflicts = {}
    unmerged = git(gd, "ls-files", "-u", env=env, check=False).stdout
    stages: dict[str, dict[int, str]] = {}
    for line in unmerged.splitlines():
        meta, path = line.split("\t", 1)
        _, sha, stage = meta.split()
        stages.setdefault(path, {})[int(stage)] = sha
    with tempfile.TemporaryDirectory() as td:
        for path, st in stages.items():
            files = []
            for s in (2, 1, 3):
                f = Path(td) / f"{s}"
                f.write_text(git(gd, "cat-file", "-p", st[s]).stdout if s in st else "")
                files.append(str(f))
            m = run(["git", "merge-file", "-p", "--diff3", "-L", "upstream (new)", "-L", "base (patch was made against)",
                     "-L", "graphite patch", *files], check=False)
            conflicts[path] = conflict_regions(m.stdout)
    idx.write_bytes(backup)
    diag = diagnose_piece(gd, pc, index_env=env, worktree=False, target_rev=rev, old_rev=old_rev,
                          proj=proj, apply_output=plain_out + "\n--- 3-way attempt ---\n" + r3.stdout + r3.stderr,
                          conflicts=conflicts)
    return PieceResult(pc, CONFLICT if stages else FAILED, "", diag)


def device_build_ids(objs: Objects, proj: Project, rev: str, device: str) -> list[str]:
    gd = objs.gitdir(proj)
    seen, out = set(), []

    def visit(rel: str):
        if rel in seen:
            return
        seen.add(rel)
        r = git(gd, "show", f"{rev}:config/device/{rel}", check=False)
        if r.returncode != 0:
            return
        out.extend(re.findall(r"^\s*build_id:\s*(\S+)", r.stdout, re.M))
        inc = re.search(r"^includes:\s*\n((?:\s+-\s*.+\n?)+)", r.stdout, re.M)
        if inc:
            base = str(Path(rel).parent)
            for item in re.findall(r"-\s*(\S+)", inc.group(1)):
                visit(str(Path(base) / item) if base != "." else item)

    visit(f"{device}.yml")
    return out


def sanity_checks(args, store, tag, base_tag, new_projects, old_projects, objs, sig_ok, sig_msg) -> list[dict]:
    checks = [{"name": "manifest tag signature", "ok": sig_ok, "detail": sig_msg}]
    device = args.device
    if args.kernel_project:
        checks.append({"name": f"kernel prebuilts project {args.kernel_project} present",
                       "ok": args.kernel_project in new_projects, "detail": ""})
    adev = new_projects.get("vendor/adevtool")
    if adev and device:
        gd = objs.gitdir(adev)
        rev = objs.ensure(gd, adev)
        has = git(gd, "cat-file", "-e", f"{rev}:config/device/{device}.yml", check=False).returncode == 0
        checks.append({"name": f"adevtool supports {device}", "ok": has, "detail": ""})
        new_ids = device_build_ids(objs, adev, rev, device)
        detail = f"stock build id(s) in {tag}: {', '.join(new_ids) or '?'}"
        old_adev = old_projects.get("vendor/adevtool")
        if old_adev:
            try:
                orev = objs.ensure(gd, old_adev)
                old_ids = device_build_ids(objs, old_adev, orev, device)
                detail += f"; before: {', '.join(old_ids) or '?'}"
                if old_ids != new_ids:
                    detail += " -> vendor files change, adevtool will download a new factory image"
            except Fatal:
                pass
        checks.append({"name": "stock vendor build", "ok": True, "detail": detail})
    if base_tag and tag.isdigit() and base_tag.isdigit() and int(tag) < int(base_tag):
        checks.append({"name": "target is older than current pin", "ok": True,
                       "detail": f"{tag} < {base_tag}: this is a downgrade"})
    return checks


# ----------------------------------------------------------------------------
# apply (real): reset patched projects, then commit every piece in src/

def git_clean_state(wt: Path) -> tuple[bool, str]:
    st = git(wt, "status", "--porcelain", "--untracked-files=normal", check=False).stdout.strip()
    gd = Path(git(wt, "rev-parse", "--git-dir").stdout.strip())
    if not gd.is_absolute():
        gd = wt / gd
    for marker in ("rebase-apply", "rebase-merge", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        if (gd / marker).exists():
            return False, f"{marker} in progress"
    return (not st), st


def foreign_commits(wt: Path, base: str) -> list[str]:
    """Commits between base and HEAD that were not created by patchctl."""
    r = git(wt, "log", "--format=%H%x00%s%x00%(trailers:key=" + TRAILER + ",valueonly)%x1e",
            f"{base}..HEAD", check=False)
    out = []
    for rec in r.stdout.split("\x1e"):
        rec = rec.strip()
        if not rec:
            continue
        sha, subj, trailer = (rec.split("\x00") + ["", ""])[:3]
        if not trailer.strip():
            out.append(f"{sha[:12]} {subj}")
    return out


def touched_projects(patches: list[Patch]) -> set[str]:
    out = set()
    for p in patches:
        out.update(p.projects)
    if APPLIED_STATE.exists():
        try:
            out.update(json.loads(APPLIED_STATE.read_text()).get("projects", {}).keys())
        except json.JSONDecodeError:
            pass
    return out


def reset_projects(src: Path, force: bool) -> None:
    projects = tree_projects(src)
    patches = load_patches()
    problems = []
    todo = []
    for path in sorted(touched_projects(patches)):
        wt = src / path
        if not (wt / ".git").exists() or path not in projects:
            continue
        base = projects[path].revision
        if git(wt, "rev-parse", "-q", "--verify", f"{base}^{{commit}}", check=False).returncode != 0:
            # tree not synced to this revision yet; repo sync will handle it
            todo.append((wt, None))
            continue
        clean, why = git_clean_state(wt)
        foreign = foreign_commits(wt, base)
        if not clean:
            problems.append(f"{path}: uncommitted changes / operation in progress:\n      {why}")
        if foreign:
            problems.append(f"{path}: commits not created by patchctl (export them first with "
                            f"'patchctl export <id> --project {path} --new'):\n      " + "\n      ".join(foreign))
        todo.append((wt, base))
    if problems and not force:
        raise Fatal("refusing to reset patched projects, your work would be lost:\n  "
                    + "\n  ".join(problems) + "\nUse --force to discard.")
    for wt, base in todo:
        gd = Path(git(wt, "rev-parse", "--git-dir").stdout.strip())
        gd = gd if gd.is_absolute() else wt / gd
        if (gd / "rebase-apply").exists():
            git(wt, "am", "--abort", check=False)
        if base:
            git(wt, "checkout", "-q", "--force", "--detach", base)
        git(wt, "reset", "-q", "--hard")
        git(wt, "clean", "-q", "-fd")
    if APPLIED_STATE.exists():
        APPLIED_STATE.unlink()


def cmd_reset(args) -> int:
    reset_projects(Path(args.src), args.force)
    info("patched projects restored to their manifest revisions")
    return 0


def commit_piece(wt: Path, pc: Piece) -> None:
    env = dict(IDENT_ENV)
    if pc.author:
        env["GIT_AUTHOR_NAME"] = pc.author
    if pc.email:
        env["GIT_AUTHOR_EMAIL"] = pc.email
    if pc.date:
        env["GIT_AUTHOR_DATE"] = pc.date
    git(wt, "commit", "-q", "--no-verify", "--allow-empty", "-F", "-", env=env, input=pc.commit_message())


def apply_piece_worktree(wt: Path, pc: Piece, proj: Project, last_good_rev: str | None) -> PieceResult:
    r = git(wt, "apply", "--index", "--check", pc.diff_path, check=False)
    if r.returncode == 0:
        git(wt, "apply", "--index", pc.diff_path)
        commit_piece(wt, pc)
        return PieceResult(pc, OK)
    plain_out = r.stdout + r.stderr
    if git(wt, "apply", "--check", "-R", pc.diff_path, check=False).returncode == 0:
        return PieceResult(pc, ALREADY_APPLIED, "already present upstream; skipped")
    r3 = git(wt, "apply", "--index", "--3way", pc.diff_path, check=False)
    if r3.returncode == 0 and not git(wt, "ls-files", "-u").stdout.strip():
        commit_piece(wt, pc)
        return PieceResult(pc, OK_3WAY, "applied via 3-way merge")
    conflicts = {}
    for path in sorted({l.split("\t", 1)[1] for l in git(wt, "ls-files", "-u").stdout.splitlines()}):
        f = wt / path
        if f.is_file():
            conflicts[path] = conflict_regions(f.read_text(errors="replace"))
    head = git(wt, "rev-parse", "HEAD").stdout.strip()
    old = None
    if last_good_rev and git(wt, "rev-parse", "-q", "--verify", f"{last_good_rev}^{{commit}}",
                             check=False).returncode == 0:
        old = last_good_rev
    git(wt, "reset", "-q", "--hard", head)
    diag = diagnose_piece(wt, pc, index_env=None, worktree=True, target_rev=proj.revision, old_rev=old,
                          proj=proj, apply_output=plain_out + "\n--- 3-way attempt ---\n" + r3.stdout + r3.stderr,
                          conflicts=conflicts)
    git(wt, "clean", "-q", "-fd")
    return PieceResult(pc, CONFLICT if conflicts else FAILED, "", diag)


def ask(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def explain_failure(p: Patch, st: str, report_dir: Path) -> None:
    print()
    print(c("1;31", f"Patch failed: {p.id} ({st})"))
    print(f"  {c('1', p.title)}")
    for line in (p.description or "(no description)").splitlines():
        print(f"    {line}")
    print(f"  Required: {c('1;31', 'YES - the build cannot continue without it') if p.required else c('1;32', 'no - it can be skipped')}")
    if p.skip_impact:
        print(f"  If skipped: {p.skip_impact}")
    dependents = [q.id for q in load_patches() if p.id in q.depends]
    if dependents:
        print(f"  Patches that depend on it (will be skipped too): {', '.join(dependents)}")
    print(f"  Details for fixing: {report_dir / 'failures' / (p.id + '.md')}")
    print()


def cmd_apply(args) -> int:
    src = Path(args.src)
    projects = tree_projects(src)
    tag = tree_tag(src) or "unknown"
    patches = load_patches()
    skip = load_skip_list()
    only = set(args.only.split(",")) if args.only else None
    last_good = {}
    if APPLIED_STATE.exists():
        try:
            last_good = json.loads(APPLIED_STATE.read_text()).get("last_good_revisions", {})
        except json.JSONDecodeError:
            pass
    prev_good_file = STATE_DIR / "last_good_revisions.json"
    if prev_good_file.exists():
        last_good = {**json.loads(prev_good_file.read_text()), **last_good}
    reset_projects(src, args.force)
    cache = PieceCache()
    results: list[PatchResult] = []
    failed_ids: set[str] = set()
    report_dir = REPORTS_DIR / f"build-{tag}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    applied_projects: dict[str, str] = {}
    aborted = False
    try:
        info(f"applying patches to tree at {tag}")
        for p, disabled in selected_patches(patches, only, skip):
            if disabled:
                results.append(PatchResult(p, DISABLED, [], disabled))
                print(f"  {cs(DISABLED):<26} {p.id}  ({disabled})")
                failed_ids.add(p.id)
                continue
            bad_deps = [d for d in p.depends if d in failed_ids]
            if bad_deps:
                failed_ids.add(p.id)
                note = f"depends on skipped/broken {', '.join(bad_deps)}"
                results.append(PatchResult(p, SKIPPED_DEP, [], note))
                print(f"  {cs(SKIPPED_DEP):<26} {p.id}  ({note})")
                if p.required:
                    err(f"required patch {p.id} cannot be applied because {note}")
                    aborted = True
                    break
                continue
            heads: dict[str, str] = {}
            piece_results: list[PieceResult] = []
            for ch in p.changes:
                if ch.project not in projects or not (src / ch.project / ".git").exists():
                    piece_results.append(PieceResult(cache.pieces(p, ch)[0], PROJECT_MISSING,
                                                     f"project {ch.project} not in tree"))
                    break
                wt = src / ch.project
                heads.setdefault(ch.project, git(wt, "rev-parse", "HEAD").stdout.strip())
                for pc in cache.pieces(p, ch):
                    res = apply_piece_worktree(wt, pc, projects[ch.project], last_good.get(ch.project))
                    piece_results.append(res)
                    if res.status in BROKEN:
                        break
                if piece_results and piece_results[-1].status in BROKEN:
                    break
            st = patch_status(piece_results)
            results.append(PatchResult(p, st, piece_results))
            print(f"  {cs(st):<26} {p.id}" + ("" if p.required else c("90", "  (optional)")))
            if st in BROKEN:
                for path, h in heads.items():  # roll back partial application of this patch
                    git(src / path, "reset", "-q", "--hard", h)
                    git(src / path, "clean", "-q", "-fd")
                failed_ids.add(p.id)
                write_report(report_dir, mode="build", tag=tag, base_tag=None, results=results, sanity=[])
                explain_failure(p, st, report_dir)
                if p.required:
                    err("a required patch failed; aborting. Fix it (see report) or mark it optional.")
                    aborted = True
                    break
                if args.skip_optional or ask(f"Skip optional patch {p.id} and continue?"):
                    warn(f"skipping {p.id} for this build")
                    continue
                err("aborting (re-run with --skip-optional to skip failed optional patches automatically)")
                aborted = True
                break
            for path in p.projects:
                applied_projects[path] = projects[path].revision
    finally:
        cache.close()
    write_report(report_dir, mode="build", tag=tag, base_tag=None, results=results, sanity=[])
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    good = [r.patch.id for r in results if r.status in GOOD]
    APPLIED_STATE.write_text(json.dumps({
        "tag": tag, "time": now_iso(), "applied": good,
        "skipped": [r.patch.id for r in results if r.status not in GOOD],
        "projects": applied_projects,
        "complete": not aborted,
    }, indent=2))
    if not aborted:
        prev_good_file.write_text(json.dumps({path: projects[path].revision
                                              for path in touched_projects(patches) if path in projects}, indent=2))
    summarize(results, report_dir, [])
    return 1 if aborted else 0


# ----------------------------------------------------------------------------
# reporting

def write_report(report_dir: Path, *, mode: str, tag: str, base_tag: str | None,
                 results: list[PatchResult], sanity: list[dict]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    fail_dir = report_dir / "failures"
    if fail_dir.exists():
        shutil.rmtree(fail_dir)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    data = {
        "tool": "graphite patchctl", "mode": mode, "generated": now_iso(),
        "target_tag": tag, "base_tag": base_tag, "counts": counts, "sanity": sanity,
        "patches": [{
            "id": r.patch.id, "title": r.patch.title, "status": r.status,
            "required": r.patch.required, "category": r.patch.category,
            "description": r.patch.description, "skip_impact": r.patch.skip_impact,
            "depends": r.patch.depends, "note": r.note,
            "patch_dir": rel(r.patch.dir),
            "pieces": [{"project": pr.piece.project, "file": rel(pr.piece.change.file),
                        "index": pr.piece.index, "total": pr.piece.total, "subject": pr.piece.subject,
                        "status": pr.status, "detail": pr.detail, "diagnostics": pr.diagnostics}
                       for pr in r.pieces],
        } for r in results],
    }
    (report_dir / "report.json").write_text(json.dumps(data, indent=2))

    broken = [r for r in results if r.status in BROKEN]
    md = [f"# Graphite patch report ({mode})", "",
          f"- Target GrapheneOS tag: `{tag}`" + (f" (current pin: `{base_tag}`)" if base_tag else ""),
          f"- Generated: {data['generated']}",
          "- Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), ""]
    if sanity:
        md += ["## Sanity checks", ""]
        md += [f"- {'✅' if s['ok'] else '❌'} {s['name']}" + (f" — {s['detail']}" if s["detail"] else "")
               for s in sanity]
        md.append("")
    md += ["## Patches", "", "| Patch | Status | Required | Title |", "|---|---|---|---|"]
    for r in results:
        md.append(f"| `{r.patch.id}` | {r.status} | {'yes' if r.patch.required else 'no'} | {r.patch.title} |")
    md.append("")
    legend = {
        OK: "applies cleanly", NEEDS_REFRESH: "applies, but via 3-way merge or partly upstreamed — run `tools/patchctl refresh <id>`",
        ALREADY_APPLIED: "upstream already contains the change — the patch can be dropped",
        CONFLICT: "3-way merge conflict — needs manual fix", FAILED: "cannot apply (file moved/removed, no common base)",
        PROJECT_MISSING: "project vanished from the manifest", SKIPPED_DEP: "not tried, a dependency failed",
        DISABLED: "not tried (disabled / skip.list)"}
    md += ["Status legend: " + "; ".join(f"**{k}** {v}" for k, v in legend.items()), ""]
    if broken:
        md += ["## Broken patches", ""]
        for r in broken:
            md.append(f"- [`{r.patch.id}`](failures/{r.patch.id}.md) — {r.status} — "
                      + ("**required**" if r.patch.required else f"optional, skipping loses: {r.patch.skip_impact or 'n/a'}"))
        md += ["", "Each linked file is a self-contained fix request (usable as a prompt for an agent or a plain LLM).",
               "See also [FIX_PROMPT.md](FIX_PROMPT.md).", ""]
    (report_dir / "REPORT.md").write_text("\n".join(md))

    if broken:
        fail_dir.mkdir()
        for r in broken:
            (fail_dir / f"{r.patch.id}.md").write_text(failure_doc(r, tag, base_tag, mode))
        (report_dir / "FIX_PROMPT.md").write_text(fix_prompt(broken, tag, base_tag, mode, report_dir))
    elif (report_dir / "FIX_PROMPT.md").exists():
        (report_dir / "FIX_PROMPT.md").unlink()


def failure_doc(r: PatchResult, tag: str, base_tag: str | None, mode: str) -> str:
    p = r.patch
    ctx = (f"Graphite (a GrapheneOS derivative) is being moved from GrapheneOS tag `{base_tag}` to `{tag}`."
           if base_tag else f"Graphite (a GrapheneOS derivative) is building GrapheneOS tag `{tag}`.")
    out = [f"# Fix request: patch `{p.id}` — {p.title}", "",
           "## Situation", "", ctx + " This patch no longer applies to the new upstream code.", "",
           f"- Status: **{r.status}**",
           f"- Required: **{'yes' if p.required else 'no (optional)'}**",
           f"- Patch directory: `{rel(p.dir)}/` (metadata in `patch.toml`)",
           f"- Projects touched: {', '.join(f'`{x}`' for x in p.projects)}",
           ]
    if p.skip_impact:
        out.append(f"- Effect of skipping it: {p.skip_impact}")
    out += ["", "## What the patch is supposed to do", "", p.description or "(no description in patch.toml)", ""]
    if p.notes:
        out += ["## Maintainer notes", "", p.notes, ""]
    for pr in r.pieces:
        if pr.status not in BROKEN:
            out.append(f"- piece `{pr.piece.label}` in `{pr.piece.project}`: {pr.status}")
    out.append("")
    for pr in r.pieces:
        if pr.status not in BROKEN:
            continue
        pc = pr.piece
        out += [f"## Failing piece: `{pc.change.file.name}` [{pc.index}/{pc.total}] — \"{pc.subject}\"", "",
                f"- Project (path in source tree): `{pc.project}`", f"- Result: **{pr.status}** {pr.detail}"]
        d = pr.diagnostics or {}
        if d.get("compare_url"):
            out.append(f"- Upstream changes in this project: {d['compare_url']}")
        out.append("")
        if d.get("git_apply_output"):
            out += ["### `git apply` output", "", "```", truncate_lines(d["git_apply_output"], 60), "```", ""]
        for fe in d.get("files", []):
            out += [f"### File `{fe['path']}`", ""]
            if fe.get("errors"):
                out.append(f"- errors: {', '.join(fe['errors'])}")
            if not fe.get("exists_in_target", True):
                out.append("- **The file does not exist in the new upstream revision.**")
                if fe.get("renamed_to"):
                    out.append(f"- It was renamed/moved to `{fe['renamed_to']}`.")
                if fe.get("upstream_status"):
                    out.append(f"- `git diff --name-status`: `{fe['upstream_status']}`")
            out.append("")
            lang = fence_lang(fe["path"])
            for h in fe.get("hunks", []):
                flag = " ← reported as failing" if h.get("reported_failing") else ""
                out += [f"#### Hunk `{h['header']}`{flag}", "", "```diff", h["text"], "```", ""]
                if "best_match_line" in h:
                    if h["best_match_line"]:
                        out.append(f"Pre-image expected at line {h['expected_line']}; best match in new code "
                                   f"at line {h['best_match_line']} ({int(h['best_match_score'] * 100)}% of lines match).")
                    else:
                        out.append(f"Pre-image expected at line {h['expected_line']}; **no match found** in new code "
                                   "(the code was rewritten or moved to another file).")
                    sn = h.get("target_snippet")
                    if sn:
                        out += ["", f"New upstream code, lines {sn['from']}–{sn['to']}:", "",
                                f"```{lang}", sn["text"], "```", ""]
            if fe.get("conflict"):
                out += ["#### 3-way merge conflict", "",
                        "`upstream (new)` = new GrapheneOS code, `base` = code the patch was written against, "
                        "`graphite patch` = what the patch wants.", "", "```", truncate_lines(fe["conflict"], 200), "```", ""]
            if fe.get("upstream_diff"):
                out += ["#### What upstream changed in this file (old pin → new tag)", "",
                        "```diff", fe["upstream_diff"], "```", ""]
        out += ["### Full original piece", "", "```diff", truncate_lines(pc.diff, 600), "```", ""]
    tag_arg = tag
    out += ["## How to fix", "",
            "**Goal:** produce an updated version of the patch that applies to the new upstream code and keeps "
            "the behaviour described above. Keep the change minimal; adapt to renamed APIs/moved code.", "",
            "**With shell access (agent):**", "",
            "```bash",
            f"tools/patchctl fix start {p.id} --tag {tag_arg}   # worktrees at work/fix-{p.id}/ with the patch applied / conflicts marked",
            f"# resolve conflicts in the listed worktree, then: git -C <worktree> add -A && tools/patchctl fix continue {p.id}",
            f"tools/patchctl fix finish {p.id}                  # writes the updated patch files back to {rel(p.dir)}/",
            f"./update.sh validate {tag_arg} --only {p.id}       # must report OK",
            "```", "",
            "**Text-only model:** answer with one updated patch per failing piece, in `git format-patch` / unified diff "
            "format with `a/` and `b/` prefixes, paths relative to the project root shown above, and correct hunk "
            f"line numbers for the new code. The result is saved over the corresponding file in `{rel(p.dir)}/`.",
            "",
            "If the feature is now obsolete (upstream implemented it) say so; the patch can be removed or added to "
            "`patches/skip.list`.", ""]
    return "\n".join(out)


def fix_prompt(broken: list[PatchResult], tag, base_tag, mode, report_dir: Path) -> str:
    lines = ["# Task: repair broken Graphite patches", "",
             "You are maintaining **Graphite**, a GrapheneOS derivative built from GrapheneOS release tags plus a "
             "stack of patches in `patches/`. "
             + (f"The pin is being updated from `{base_tag}` to `{tag}`." if base_tag else f"The build of `{tag}` failed."),
             "", "Read `AGENTS.md` at the repository root for the workflow. Broken patches:", ""]
    for r in broken:
        lines.append(f"- `{r.patch.id}` ({r.status}, {'required' if r.patch.required else 'optional'}): "
                     f"{r.patch.title} → `{rel(report_dir / 'failures' / (r.patch.id + '.md'))}`")
    lines += ["", "For each patch: read its failure file, run `tools/patchctl fix start <id> --tag " + tag + "`, "
              "resolve, `tools/patchctl fix finish <id>`, then `./update.sh validate " + tag + " --only <id>`. "
              "Fix patches in the listed order (later patches may depend on earlier ones). Do not change patch "
              "behaviour beyond what is needed to port it. Report anything that could not be ported.", ""]
    return "\n".join(lines)


def summarize(results: list[PatchResult], report_dir: Path, sanity: list[dict]) -> int:
    broken_req = [r for r in results if r.status in BROKEN and r.patch.required]
    broken_opt = [r for r in results if r.status in BROKEN and not r.patch.required]
    refresh = [r for r in results if r.status in (NEEDS_REFRESH, OK_3WAY)]
    upstreamed = [r for r in results if r.status == ALREADY_APPLIED]
    bad_sanity = [s for s in sanity if not s["ok"]]
    print()
    info(f"report: {report_dir / 'REPORT.md'}")
    for s in bad_sanity:
        err(f"sanity check failed: {s['name']} {s['detail']}")
    if refresh:
        warn("applies only with 3-way merge (refresh recommended): " + ", ".join(r.patch.id for r in refresh))
    if upstreamed:
        warn("already contained upstream (can be dropped): " + ", ".join(r.patch.id for r in upstreamed))
    if broken_opt:
        warn("broken OPTIONAL patches: " + ", ".join(r.patch.id for r in broken_opt))
    if broken_req:
        err("broken REQUIRED patches: " + ", ".join(r.patch.id for r in broken_req))
    if broken_req or bad_sanity:
        return 2
    if broken_opt:
        return 3
    return 0


# ----------------------------------------------------------------------------
# authoring: new / export / fix / refresh

def project_file_name(project: str) -> str:
    return project.replace("/", "_") + ".patch"


def cmd_new(args) -> int:
    d = PATCHES_DIR / args.id
    if d.exists():
        raise Fatal(f"{d} already exists")
    if not re.match(r"^\d{4}-[a-z0-9][a-z0-9-]*$", args.id):
        raise Fatal("patch id must look like NNNN-short-name (e.g. 0200-root-support); the number sets the order")
    d.mkdir(parents=True)
    (d / "patch.toml").write_text(f'''title = "{args.title or args.id}"
description = """
Describe what this patch does and why. Readers of build/update failure reports
(and AI agents fixing the patch) only know what you write here.
"""
# false = the ROM still builds and works without it; build.sh may skip it on failure
required = {"true" if args.required else "false"}
skip_impact = "What is lost if this patch is skipped."
category = "{args.category}"
depends = []
enabled = true
notes = ""

# One [[change]] per patched project. Add them with:
#   tools/patchctl export {args.id} --project <path> --new
''')
    info(f"created {d}/patch.toml — commit your changes in src/<project>, then run "
         f"'tools/patchctl export {args.id} --project <project> --new'")
    return 0


def add_change_entry(patch_dir: Path, project: str, fname: str) -> None:
    meta = patch_dir / "patch.toml"
    data = tomllib.loads(meta.read_text())
    if any(ch["project"] == project and ch["file"] == fname for ch in data.get("change", [])):
        return
    with meta.open("a") as f:
        f.write(f'\n[[change]]\nproject = "{project}"\nfile = "{fname}"\n')


def format_patch(wt: Path, shas: list[str]) -> str:
    out = []
    for sha in shas:
        r = git(wt, "format-patch", "-1", "--stdout", "--zero-commit", "--no-signature",
                "--no-numbered", "--full-index", sha)
        out.append(re.sub(rf"^{TRAILER}: .*\n", "", r.stdout, flags=re.M))
    return "".join(out)


def cmd_export(args) -> int:
    src = Path(args.src)
    patches = load_patches()
    p = find_patch(patches, args.id)
    projects = tree_projects(src)
    if args.project not in projects:
        raise Fatal(f"{args.project} is not a project in the tree")
    wt = src / args.project
    base = projects[args.project].revision
    r = git(wt, "log", "--reverse", "--format=%H%x00%(trailers:key=" + TRAILER + ",valueonly)%x1e", f"{base}..HEAD")
    shas = []
    for rec in r.stdout.split("\x1e"):
        rec = rec.strip()
        if not rec:
            continue
        sha, trailer = (rec.split("\x00") + [""])[:2]
        trailer = trailer.strip()
        if trailer == p.id or (args.new and not trailer):
            shas.append(sha)
    if not shas:
        raise Fatal(f"no commits for {p.id} in {args.project} (commits since {base[:12]}"
                    + (" tagged with this patch id" if not args.new else " without a Graphite-Patch trailer") + ")")
    fname = project_file_name(args.project)
    (p.dir / fname).write_text(format_patch(wt, shas))
    add_change_entry(p.dir, args.project, fname)
    if args.new:  # tag the commits so later exports / resets know who owns them
        warn("the exported commits have no Graphite-Patch trailer; re-run './build.sh --only patch' "
             "to re-apply them as tracked commits")
    info(f"wrote {len(shas)} commit(s) to {p.dir / fname}")
    return 0


def fix_state_file(pid: str) -> Path:
    return WORK_DIR / f"fix-{pid}" / "fix-state.json"


def cmd_fix(args) -> int:
    patches = load_patches()
    p = find_patch(patches, args.id)
    wdir = WORK_DIR / f"fix-{p.id}"
    src = Path(args.src) if args.src and (Path(args.src) / ".repo").is_dir() else None
    objs = Objects(src)
    if args.action == "start":
        if wdir.exists():
            raise Fatal(f"{wdir} exists; use 'fix continue/finish/abort {p.id}'")
        store = ManifestStore()
        tag = args.tag if args.tag != "latest" else latest_tag()
        projects = store.projects(tag)
        skip = load_skip_list()
        state = {"patch": p.id, "tag": tag, "projects": {}}
        cache = PieceCache()
        try:
            for path in p.projects:
                if path not in projects:
                    raise Fatal(f"{path} is not in the manifest of {tag}; the patch must be retargeted manually")
                proj = projects[path]
                gd = objs.gitdir(proj)
                rev = objs.ensure(gd, proj)
                wt = wdir / path
                wt.parent.mkdir(parents=True, exist_ok=True)
                git(gd, "worktree", "add", "-q", "--detach", wt, rev)
                # earlier patches touching this project are applied first (they define the base)
                for q, disabled in selected_patches(patches, None, skip):
                    if q.id == p.id:
                        break
                    if disabled or path not in q.projects:
                        continue
                    for ch in q.changes:
                        if ch.project != path:
                            continue
                        for pc in cache.pieces(q, ch):
                            r = git(wt, "-c", "user.name=Graphite", "-c", "user.email=graphite@localhost",
                                    "am", "-q", "--3way", cache.mbox_for(pc), check=False)
                            if r.returncode != 0:
                                git(wt, "am", "--abort", check=False)
                                warn(f"earlier patch {q.id} does not apply in {path}; fix it first. Continuing without it.")
                                break
                base = git(wt, "rev-parse", "HEAD").stdout.strip()
                state["projects"][path] = {"gitdir": str(gd), "worktree": str(wt), "base": base,
                                           "files": [], "pending": []}
                for ch in p.changes:
                    if ch.project == path:
                        state["projects"][path]["files"].append(ch.file.name)
                        state["projects"][path]["pending"] += [str(cache.mbox_for(pc)) for pc in cache.pieces(p, ch)]
            # keep the normalized mboxes around for 'continue'
            keep = wdir / ".mbox"
            keep.mkdir(parents=True, exist_ok=True)
            for path, ps in state["projects"].items():
                new_pending = []
                for m in ps["pending"]:
                    dest = keep / f"{len(list(keep.iterdir())):04d}.mbox"
                    shutil.copy(m, dest)
                    new_pending.append(str(dest))
                ps["pending"] = new_pending
        finally:
            cache.close()
        fix_state_file(p.id).write_text(json.dumps(state, indent=2))
        return fix_continue(p, wdir)
    if args.action == "abort":
        return fix_cleanup(p, wdir)
    if not fix_state_file(p.id).exists():
        raise Fatal(f"no fix in progress for {p.id}")
    if args.action == "continue":
        return fix_continue(p, wdir)
    if args.action == "finish":
        state = json.loads(fix_state_file(p.id).read_text())
        for path, ps in state["projects"].items():
            wt = Path(ps["worktree"])
            gd = Path(git(wt, "rev-parse", "--git-dir").stdout.strip())
            gd = gd if gd.is_absolute() else wt / gd
            if (gd / "rebase-apply").exists() or ps["pending"]:
                raise Fatal(f"{path}: patch application not finished; run 'fix continue {p.id}' "
                            f"(or 'git am --continue' in {wt})")
            if not git_clean_state(wt)[0]:
                raise Fatal(f"{wt} has uncommitted changes; commit (git commit --amend) or discard them first")
            shas = git(wt, "rev-list", "--reverse", f"{ps['base']}..HEAD").stdout.split()
            if not shas:
                warn(f"{path}: no commits left (patch is empty / upstreamed?) - leaving patch file untouched")
                continue
            fname = ps["files"][0]
            if len(ps["files"]) > 1:
                for extra in ps["files"][1:]:
                    (p.dir / extra).unlink(missing_ok=True)
                rewrite_changes(p, path, fname)
            (p.dir / fname).write_text(format_patch(wt, shas))
            info(f"updated {p.dir / fname} ({len(shas)} commit(s))")
        fix_cleanup(p, wdir)
        info(f"now validate: ./update.sh validate {state['tag']} --only {p.id}")
        return 0
    return 1


def rewrite_changes(p: Patch, project: str, keep_file: str) -> None:
    meta = p.dir / "patch.toml"
    text = meta.read_text()
    blocks = re.split(r"(?=^\[\[change\]\])", text, flags=re.M)
    out = [blocks[0]]
    for b in blocks[1:]:
        if f'project = "{project}"' in b and f'file = "{keep_file}"' not in b:
            continue
        out.append(b)
    meta.write_text("".join(out))


def fix_continue(p: Patch, wdir: Path) -> int:
    state = json.loads(fix_state_file(p.id).read_text())
    for path, ps in state["projects"].items():
        wt = Path(ps["worktree"])
        gd = Path(git(wt, "rev-parse", "--git-dir").stdout.strip())
        gd = gd if gd.is_absolute() else wt / gd
        if (gd / "rebase-apply").exists():
            r = git(wt, "-c", "user.name=Graphite", "-c", "user.email=graphite@localhost",
                    "am", "--continue", check=False)
            if r.returncode != 0:
                print(r.stdout + r.stderr)
                err(f"still conflicted in {wt}; resolve, 'git add -A', then 'tools/patchctl fix continue {p.id}'")
                return 1
        while ps["pending"]:
            mbox = ps["pending"][0]
            r = git(wt, "-c", "user.name=Graphite", "-c", "user.email=graphite@localhost",
                    "am", "--3way", mbox, check=False)
            ps["pending"].pop(0)
            fix_state_file(p.id).write_text(json.dumps(state, indent=2))
            if r.returncode != 0:
                unmerged = git(wt, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
                print(r.stdout + r.stderr)
                info(f"conflict in {wt}")
                for u in unmerged:
                    print(f"    {wt / u}")
                print(f"  Resolve the conflict markers (or apply the rejected change by hand), then:\n"
                      f"    git -C {wt} add -A\n    tools/patchctl fix continue {p.id}\n"
                      f"  Finally: tools/patchctl fix finish {p.id}")
                return 1
    info(f"all pieces applied in work/fix-{p.id}/. Review/build-test, amend commits if needed, then "
         f"'tools/patchctl fix finish {p.id}'")
    return 0


def fix_cleanup(p: Patch, wdir: Path) -> int:
    gitdirs = set()
    if fix_state_file(p.id).exists():
        state = json.loads(fix_state_file(p.id).read_text())
        for path, ps in state["projects"].items():
            git(ps["gitdir"], "worktree", "remove", "--force", ps["worktree"], check=False)
            gitdirs.add(ps["gitdir"])
    shutil.rmtree(wdir, ignore_errors=True)
    for gd in gitdirs:
        git(gd, "worktree", "prune", check=False)
    info(f"removed {wdir}")
    return 0


def cmd_refresh(args) -> int:
    args.action = "start"
    rc = cmd_fix(args)
    if rc != 0:
        err("refresh hit a real conflict; finish it manually as described above")
        return rc
    args.action = "finish"
    return cmd_fix(args)


# ----------------------------------------------------------------------------
# list / info

def cmd_list(args) -> int:
    patches = load_patches()
    skip = load_skip_list()
    applied = {}
    if APPLIED_STATE.exists():
        try:
            applied = json.loads(APPLIED_STATE.read_text())
        except json.JSONDecodeError:
            pass
    if args.json:
        print(json.dumps([{"id": p.id, "title": p.title, "required": p.required, "category": p.category,
                           "enabled": p.enabled and p.id not in skip, "projects": p.projects,
                           "depends": p.depends} for p in patches], indent=2))
        return 0
    if not patches:
        print("no patches yet (create one with: tools/patchctl new NNNN-name --title '...')")
        return 0
    for p in patches:
        state = "disabled" if not p.enabled else ("skip.list" if p.id in skip else
                ("applied" if p.id in applied.get("applied", []) else "-"))
        req = c("1", "required") if p.required else "optional"
        print(f"{p.id:<36} {req:<10} {state:<10} {p.title}")
        print(c("90", f"{'':<36} {', '.join(p.projects)}"))
    if applied:
        print(c("90", f"\nlast apply: tag {applied.get('tag')} at {applied.get('time')}"
                f"{'' if applied.get('complete', True) else ' (INCOMPLETE)'}"))
    return 0


def cmd_info(args) -> int:
    p = find_patch(load_patches(), args.id)
    skip = load_skip_list()
    print(c("1", f"{p.id}: {p.title}"))
    print(f"category: {p.category}   required: {p.required}   enabled: {p.enabled}"
          + (f"   SKIPPED via skip.list: {skip[p.id]}" if p.id in skip else ""))
    if p.depends:
        print(f"depends on: {', '.join(p.depends)}")
    print(f"\n{p.description}\n")
    if p.skip_impact:
        print(f"if skipped: {p.skip_impact}")
    if p.notes:
        print(f"notes: {p.notes}")
    for ch in p.changes:
        print(f"  {ch.project:<40} {rel(ch.file)}")
    return 0


def cmd_latest(args) -> int:
    print(latest_tag())
    return 0


# ----------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="patchctl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=os.environ.get("GRAPHITE_SRC", str(ROOT / "src")))
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("info")
    s.add_argument("id")
    s.set_defaults(fn=cmd_info)
    s = sub.add_parser("new")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--category", default="feature")
    s.add_argument("--required", action="store_true")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("apply")
    s.add_argument("--skip-optional", action="store_true", help="skip failing optional patches without asking")
    s.add_argument("--only", help="comma separated patch ids")
    s.add_argument("--force", action="store_true", help="discard local changes in patched projects")
    s.set_defaults(fn=cmd_apply)
    s = sub.add_parser("reset")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_reset)
    s = sub.add_parser("validate")
    s.add_argument("--tag", required=True, help="GrapheneOS tag or 'latest'")
    s.add_argument("--base-tag", help="currently pinned tag (for upstream diffs)")
    s.add_argument("--only", help="comma separated patch ids")
    s.add_argument("--report-dir")
    s.add_argument("--device", default=os.environ.get("GRAPHITE_DEVICE"))
    s.add_argument("--kernel-project", default=os.environ.get("GRAPHITE_KERNEL_PROJECT"))
    s.add_argument("--ignore-skip-list", action="store_true", help="also test patches listed in skip.list")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("export")
    s.add_argument("id")
    s.add_argument("--project", required=True)
    s.add_argument("--new", action="store_true", help="also take commits without a Graphite-Patch trailer")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("fix")
    s.add_argument("action", choices=["start", "continue", "finish", "abort"])
    s.add_argument("id")
    s.add_argument("--tag", default="latest")
    s.set_defaults(fn=cmd_fix)
    s = sub.add_parser("refresh")
    s.add_argument("id")
    s.add_argument("--tag", required=True)
    s.set_defaults(fn=cmd_refresh)
    s = sub.add_parser("latest-tag")
    s.set_defaults(fn=cmd_latest)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except Fatal as e:
        err(str(e))
        return 1
    except KeyboardInterrupt:
        err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
