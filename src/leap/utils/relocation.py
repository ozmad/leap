"""Shared primitives for cross-cwd CLI session relocation.

Each CLI provider that's cwd-bound for resume (Claude, Gemini, Cursor)
needs to physically move on-disk session state from the slug/hash dir
of one cwd to the slug/hash dir of another so the CLI's
``<cli> --resume <id>`` command finds it under the new cwd.  All the
movers share the same safety guarantees:

* **Source is never deleted until destination is fully verified.**
  Copy → fsync → SHA-256 verify → atomic rename, *only then* unlink.
* **Critical signals blocked** for the whole critical section
  (``signals_blocked`` context manager) so Ctrl+C can't interrupt
  mid-commit.
* **Atomic per-piece commit.**  Multi-piece moves (Claude's JSONL +
  sidecar dir, Cursor's chat dir + future metadata files) commit each
  piece independently and roll back the prior pieces on a later
  failure.
* **Rogue-writer detection** via stat snapshots — if the source was
  modified after our verify but before our unlink, we refuse to
  delete it (keeps both copies on disk for the user to reconcile).

This module exposes the building blocks; per-CLI movers
(``claude_session_move.py``, ``gemini_session_move.py``,
``cursor_session_move.py``) compose them into the file-layout-specific
relocation flow.

Usage sketch::

    from leap.utils.relocation import (
        RelocationError, signals_blocked,
        stage_copy_file, commit_file,
        verify_files_match, snapshot_tree,
    )

    with signals_blocked():
        stage_copy_file(src, tmp)        # phase 1: copy + fsync + verify
        commit_file(tmp, dst)            # phase 2: atomic rename
        on_committed(dst)                # bookkeeping inside critical section
        # phase 3: delete src (with rogue-writer check)
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Iterator, Optional


# ── Errors ────────────────────────────────────────────────────────────


class RelocationError(Exception):
    """Raised when a session relocation fails.

    Contract: when this is raised, the *source* is always intact.
    Either we aborted before touching anything, or we rolled back any
    partial destination commits.  The user keeps the original copy and
    can retry.
    """


# ── Validation ────────────────────────────────────────────────────────


# Used by every mover to validate session ids before joining them into
# filesystem paths — guards against a crafted hook payload escaping the
# CLI's storage root via ``..`` or ``/`` segments.  Real CLI session ids
# (UUIDs, chat ids, etc.) all match this pattern.
SAFE_SESSION_ID_RE: re.Pattern[str] = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
)


def is_safe_session_id(session_id: str) -> bool:
    """Cheap path-injection guard for session ids."""
    return bool(session_id) and bool(SAFE_SESSION_ID_RE.match(session_id))


# ── Tmp paths ─────────────────────────────────────────────────────────


# Tail used for in-flight temp files at the destination.  Picked so it
# can never collide with a real CLI artifact (which is always a UUID,
# slug-named file, or similar).  The ``.<pid>`` segment is added at
# call time so two concurrent ``leap --resume`` processes targeting the
# same session don't share a tmp file (which would cause one to read
# the other's mid-write bytes and either hash-mismatch or — if the
# timing aligned exactly — silently consume each other's destination
# commit).
TMP_SUFFIX: str = ".leap-relocate-tmp"


def make_tmp_path(dst: Path) -> Path:
    """Per-pid tmp path next to ``dst`` for in-flight Phase 1 copies.

    The destination's extension (if any) is preserved so any tooling
    that watches the destination dir for ``.jsonl`` doesn't pick the
    tmp file up as a real session.
    """
    return dst.parent / f"{dst.name}.{os.getpid()}{TMP_SUFFIX}"


# ── Signal handling ───────────────────────────────────────────────────


def _block_critical_signals() -> set[int]:
    """Block signals that would otherwise interrupt the move.

    Returns the previous mask so :func:`_restore_signal_mask` can put
    things back exactly the way they were.  ``pthread_sigmask`` is a
    Unix-only API; on platforms without it (theoretical — Leap is
    macOS/Linux today) we silently no-op rather than crash.
    """
    sigs = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT}
    if hasattr(signal, 'SIGTSTP'):
        sigs.add(signal.SIGTSTP)
    if not hasattr(signal, 'pthread_sigmask'):
        return set()
    return set(signal.pthread_sigmask(signal.SIG_BLOCK, sigs))


def _restore_signal_mask(prev: set[int]) -> None:
    if hasattr(signal, 'pthread_sigmask'):
        signal.pthread_sigmask(signal.SIG_SETMASK, prev)


@contextlib.contextmanager
def signals_blocked() -> Iterator[None]:
    """Block SIGINT/SIGTERM/SIGHUP/SIGQUIT/SIGTSTP for the duration of
    the ``with`` block.

    Queued signals are delivered after the block exits.  The ``try`` /
    ``finally`` order matters: if a signal fires between ``yield`` and
    the unblock call, the OS would deliver it inside ``finally`` —
    which is fine, the move is already complete by then.
    """
    prev_mask: Optional[set[int]] = None
    try:
        prev_mask = _block_critical_signals()
        yield
    finally:
        if prev_mask is not None:
            _restore_signal_mask(prev_mask)


# ── Verification ──────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    """Hash the entire contents of ``path``.

    Streams in 1 MiB chunks so very large transcripts don't blow up
    memory.  Caller is responsible for catching ``OSError``.
    """
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_files_match(a: Path, b: Path) -> None:
    """Assert two files are byte-identical via size + SHA-256.

    Size first (cheap, catches the common copy-was-truncated case
    instantly); hash second (catches silent bit-rot or any byte-level
    mismatch the size check missed).
    """
    a_size = a.stat().st_size
    b_size = b.stat().st_size
    if a_size != b_size:
        raise RelocationError(
            f"copy verification failed: size mismatch {a} ({a_size} B) "
            f"vs {b} ({b_size} B)"
        )
    if sha256_file(a) != sha256_file(b):
        raise RelocationError(
            f"copy verification failed: checksum mismatch between {a} and {b}"
        )


def verify_trees_match(src: Path, dst: Path) -> None:
    """Verify ``dst`` is a faithful copy of ``src`` (file-tree variant).

    Walks ``dst`` and for each file there, verifies the same relative
    path under ``src`` exists and has byte-identical content.  Reading
    via ``src / rel`` transparently follows any symlinks on the source
    side, matching what ``shutil.copytree(symlinks=False)`` did when
    resolving them.

    We deliberately don't *also* enumerate src to look for files that
    didn't make it to dst.  ``rglob`` doesn't recurse into
    symlinks-to-directories (whereas ``copytree(symlinks=False)``
    does), so a symmetric enumeration would falsely flag a sidecar
    that contains a symlinked subdir as a "tree mismatch" even though
    copytree faithfully copied the contents.  The asymmetry is safe
    to ignore because ``copytree`` raises ``shutil.Error`` if it
    couldn't copy any source entry — if it returned successfully,
    every src entry is reachable on dst.
    """
    for cur, _dirs, files in os.walk(str(dst)):
        for f in files:
            dst_file = Path(cur) / f
            rel = dst_file.relative_to(dst)
            src_file = src / rel
            if not src_file.is_file():
                raise RelocationError(
                    f"copy verification failed: {dst_file} has no "
                    f"counterpart at {src_file}"
                )
            verify_files_match(src_file, dst_file)


# ── fsync ─────────────────────────────────────────────────────────────


def fsync_file(path: Path) -> None:
    """Force-flush ``path`` to disk so a crash post-rename can't lose
    its committed bytes.

    macOS ``fsync`` on a regular fd may return without flushing the
    drive cache; that's a tradeoff we accept — the alternative
    ``fcntl(F_FULLFSYNC)`` is much slower and the leap relocation
    path isn't a database commit.  We just need ordering: the bytes
    must be on the OS-side device buffer before ``os.replace``
    publishes the new path.
    """
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_tree(root: Path) -> None:
    """fsync every regular file under ``root``.

    ``Path.is_file()`` is True for both regular files and symlinks
    pointing at files, which is exactly what we want — at the
    destination tree (where this is called), ``shutil.copytree`` with
    ``symlinks=False`` has already materialized any source symlinks
    into regular files, so we want to fsync them too.
    """
    for cur, _dirs, files in os.walk(str(root)):
        for f in files:
            p = Path(cur) / f
            if p.is_file():
                fsync_file(p)


# ── Atomic copy primitives ────────────────────────────────────────────


def stage_copy_file(src: Path, dst_tmp: Path) -> None:
    """Phase 1 for a single file: copy → fsync → verify.

    ``dst_tmp`` must be a fresh path next to the final destination
    (use :func:`make_tmp_path`).  Cleans up ``dst_tmp`` on failure so
    a retry won't trip on stale bytes.

    Wraps low-level errors in :class:`RelocationError` so callers only
    need one ``except`` clause.
    """
    try:
        shutil.copy2(str(src), str(dst_tmp))
        fsync_file(dst_tmp)
        verify_files_match(src, dst_tmp)
    except RelocationError:
        best_effort_remove(dst_tmp)
        raise
    except OSError as e:
        best_effort_remove(dst_tmp)
        raise RelocationError(f"copy failed for {src} → {dst_tmp}: {e}") from e


def stage_copy_tree(src: Path, dst_tmp: Path) -> None:
    """Phase 1 for a directory tree: copytree → fsync → verify.

    Uses ``symlinks=False`` so the destination is a self-contained
    copy with all source-side symlinks resolved.  Cleans up
    ``dst_tmp`` on failure.
    """
    try:
        shutil.copytree(
            str(src), str(dst_tmp),
            copy_function=shutil.copy2, symlinks=False,
        )
        fsync_tree(dst_tmp)
        verify_trees_match(src, dst_tmp)
    except RelocationError:
        best_effort_remove(dst_tmp)
        raise
    except (OSError, shutil.Error) as e:
        best_effort_remove(dst_tmp)
        raise RelocationError(f"tree copy failed for {src} → {dst_tmp}: {e}") from e


def commit_file(tmp: Path, dst: Path) -> None:
    """Phase 2 for a single file: atomic rename ``tmp`` over ``dst``.

    On POSIX same-fs this is a true atomic rename; cross-fs falls
    back to copy+remove which is fine for our verification semantics
    (the verified bytes from Phase 1 are what reach ``dst``).
    """
    try:
        os.replace(str(tmp), str(dst))
    except OSError as e:
        best_effort_remove(tmp)
        raise RelocationError(
            f"failed to commit {tmp} → {dst}: {e}"
        ) from e


def commit_tree(tmp: Path, dst: Path) -> None:
    """Phase 2 for a directory: atomic rename ``tmp`` to ``dst``.

    ``os.rename`` on a directory is atomic on the same filesystem and
    fails (rather than half-merging) if ``dst`` already exists.
    """
    try:
        os.rename(str(tmp), str(dst))
    except OSError as e:
        best_effort_remove(tmp)
        raise RelocationError(
            f"failed to commit dir {tmp} → {dst}: {e}"
        ) from e


# ── Rogue-writer detection ────────────────────────────────────────────
#
# After Phase 2 commits the verified bytes, we want to delete the
# source.  But between our Phase 1 verify and the Phase 3 unlink, a
# concurrent CLI process could have appended to / modified the source.
# The snapshot helpers let callers compare before/after and refuse the
# delete if anything changed.


def stat_snapshot(path: Path) -> tuple[int, int]:
    """Return ``(size, mtime_ns)`` for a single file.

    Caller compares against a fresh snapshot before unlinking — if it
    differs, abort and surface a "source modified during move" error.
    """
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


def snapshot_tree(root: Path) -> dict[Path, tuple[int, int]]:
    """Return ``{relative_path: (size, mtime_ns)}`` for every regular
    file under ``root``.

    Errors statting individual files are swallowed (the file may have
    been deleted mid-walk) — the snapshot just won't include them,
    which the comparison treats as a change.
    """
    snap: dict[Path, tuple[int, int]] = {}
    for cur, _dirs, files in os.walk(str(root)):
        for f in files:
            p = Path(cur) / f
            try:
                st = p.stat()
            except OSError:
                continue
            snap[p.relative_to(root)] = (st.st_size, st.st_mtime_ns)
    return snap


# ── Cleanup ───────────────────────────────────────────────────────────


def best_effort_remove(path: Path) -> None:
    """Remove ``path`` (file or directory) ignoring all errors.

    Used to clean up half-written tmp paths on failure paths.  Never
    raises — the caller is already in an error path and a follow-up
    cleanup error would just mask the real cause.
    """
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(str(path))
    except OSError:
        pass


def must_remove_tree(path: Path, *, dst_for_message: Path) -> None:
    """Phase 3 source-tree cleanup: ``rmtree`` and raise on failure.

    Used after the destination is committed, when the caller wants
    the user to know if the source couldn't be deleted (so they can
    reconcile the duplicate manually).  Distinct from
    :func:`best_effort_remove` which is for *cleanup* paths where a
    follow-up failure would mask the real cause.

    ``dst_for_message`` is woven into the error so the user knows
    which committed copy is the canonical one.
    """
    try:
        shutil.rmtree(str(path))
    except OSError as e:
        raise RelocationError(
            f"destination committed but source could not be deleted: "
            f"{path}: {e}\n"
            f"  Destination at {dst_for_message} is intact.\n"
            f"  Both copies now exist; delete the source manually."
        ) from e
