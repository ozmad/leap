"""Safely relocate a Claude Code session's on-disk state across cwds.

Claude Code stores each session under
``~/.claude/projects/<cwd-slug>/<uuid>.jsonl`` plus an *optional*
sidecar directory at ``~/.claude/projects/<cwd-slug>/<uuid>/`` that
holds sub-agent transcripts and overflow tool outputs.  Resuming a
session requires Claude to be invoked with ``cwd == src_cwd`` so it
can find the transcript by slug.

This module relocates the transcript (and sidecar, if present) so the
same session can be resumed under a different cwd::

  src = ~/.claude/projects/<slug(src_cwd)>/<uuid>.jsonl  [+ <uuid>/]
  dst = ~/.claude/projects/<slug(dst_cwd)>/<uuid>.jsonl  [+ <uuid>/]

Safety properties
-----------------
* **Source is never deleted until the destination is fully verified.**
  Copy → fsync → byte-size compare → SHA-256 compare → atomic rename
  into place, *only then* unlink the source.
* **Critical signals (SIGINT/SIGTERM/SIGHUP/SIGQUIT/SIGTSTP) are
  blocked** for the entire move via ``pthread_sigmask``.  The user
  cannot Ctrl+C the process out of a half-committed state — keys are
  queued and delivered when the move completes.  SIGKILL and power
  loss can't be blocked; in those cases the source is preserved
  through phases 1 and 2, and the worst observable state at phase 3
  (delete src) is a duplicate that the user can clean up by hand.
* **Rollback on commit-time failure.**  If the sidecar dir's atomic
  rename fails after the JSONL has already been committed, the
  committed JSONL is unlinked so the caller sees "nothing happened"
  and the source remains the only valid copy.
* **Bookkeeping order.**  The caller's ``on_committed`` callback is
  invoked *after* the destination is verified-in-place but *before*
  the source is deleted, so a crash between phase 2 (commit) and
  phase 3 (delete) leaves a recoverable duplicate state where the
  records already point at the new path.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
from pathlib import Path
from typing import Callable, Optional


CLAUDE_PROJECTS_ROOT: Path = Path.home() / ".claude" / "projects"

# Claude's per-cwd directory slug: every char *not* in ``[a-zA-Z0-9_-]``
# is replaced with ``-``, with no collapsing of consecutive dashes.
# Empirically derived from inspection of ``~/.claude/projects/``:
# ``Nevo.Mashiach`` → ``Nevo-Mashiach`` (single dot → single dash) and
# ``/Users/me/.claude`` → ``-Users-me--claude`` (slash + dot → two
# dashes preserved).  The pre-flight check in
# :func:`relocate_claude_session` validates that our computed slug for
# ``src_cwd`` matches the actual on-disk directory name — if Claude
# changes its encoding in a future version, the move aborts before
# touching any files.
_SLUG_REPLACE_RE: re.Pattern[str] = re.compile(r'[^a-zA-Z0-9_-]')

# Tail used for in-flight temp files at the destination.  Picked so it
# can never collide with a real Claude artifact (which is always a UUID
# or ``<uuid>.jsonl``).  The ``.<pid>`` segment is filled in at call
# time so two concurrent ``leap --resume`` processes targeting the same
# session don't share a tmp file (which would cause one to read the
# other's mid-write bytes and either hash-mismatch or — if the timing
# aligned exactly — silently consume each other's destination commit).
_TMP_SUFFIX = ".leap-relocate-tmp"

# Format we accept for ``session_id``.  Defense-in-depth — Claude's
# UUIDs are always hex+dashes and are extracted via ``os.path.basename``
# upstream, but a crafted hook payload could otherwise embed a path
# separator that escapes ``CLAUDE_PROJECTS_ROOT/<slug>/`` once we join.
_SAFE_SESSION_ID_RE: re.Pattern[str] = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class RelocationError(Exception):
    """Raised when a session can't be relocated.

    The source is *always* intact when this is raised — either we
    aborted before touching anything, or we rolled back the partial
    destination commit.
    """


def slugify(path: str) -> str:
    """Return Claude Code's per-cwd directory slug for ``path``."""
    return _SLUG_REPLACE_RE.sub('-', path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _fsync_file(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
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
                _fsync_file(p)


def _verify_files_match(a: Path, b: Path) -> None:
    """Assert two files are byte-identical via size + SHA-256."""
    a_size = a.stat().st_size
    b_size = b.stat().st_size
    if a_size != b_size:
        raise RelocationError(
            f"copy verification failed: size mismatch {a} ({a_size} B) "
            f"vs {b} ({b_size} B)"
        )
    a_hash = _sha256(a)
    b_hash = _sha256(b)
    if a_hash != b_hash:
        raise RelocationError(
            f"copy verification failed: checksum mismatch between {a} and {b}"
        )


def _verify_trees_match(src: Path, dst: Path) -> None:
    """Verify ``dst`` is a faithful copy of ``src``.

    Walks ``dst`` (which ``shutil.copytree(symlinks=False)`` has
    fully materialized — no symlinks remain) and for each file there,
    verifies the same relative path under ``src`` exists and has
    byte-identical content.  Reading via ``src / rel`` transparently
    follows any symlinks on the source side, matching what copytree
    did when resolving them.

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
            _verify_files_match(src_file, dst_file)


def _block_critical_signals() -> set[int]:
    """Block signals that would otherwise interrupt the move.

    Returns the previous mask so :func:`_restore_signal_mask` can put
    things back exactly the way they were.  ``pthread_sigmask`` is a
    Unix-only API; on platforms without it (theoretical — Leap is
    macOS-only today) we silently no-op rather than crash.
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


def _snapshot_tree(root: Path) -> dict[Path, tuple[int, int]]:
    """Return ``{relative_path: (size, mtime_ns)}`` for every regular
    file under ``root``.

    Used as the sidecar-side analogue of the ``src_jsonl.stat()``
    snapshot — captured right after ``_verify_trees_match`` succeeds
    and re-captured before the Phase 3 ``rmtree`` to detect a rogue
    writer (a Claude running directly, outside leap, with the same
    session id) that may have appended to an existing sub-agent
    transcript or written a new one.  Without this, ``rmtree`` would
    silently delete those bytes.

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


def _best_effort_remove(path: Path) -> None:
    """Remove ``path`` (file or directory) ignoring all errors."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(str(path))
    except OSError:
        pass


def relocate_claude_session(
    session_id: str,
    src_cwd: str,
    dst_cwd: str,
    *,
    on_committed: Optional[Callable[[str], None]] = None,
) -> str:
    """Move a Claude session's on-disk state from ``src_cwd`` to ``dst_cwd``.

    Args:
        session_id: The Claude session UUID (basename of the JSONL,
            without the ``.jsonl`` suffix).
        src_cwd: The directory the session was originally recorded in.
        dst_cwd: The directory we want Claude to find the session in
            on its next ``--resume=<id>`` launch.
        on_committed: Optional callback invoked *after* the destination
            is fully verified in-place but *before* the source is
            deleted.  Receives the new transcript path.  Called inside
            the signal-blocked critical section so any bookkeeping the
            caller does there is also atomic w.r.t. user interruption.
            If the callback raises, the source is *not* deleted (state
            stays recoverable) and the exception is re-raised wrapped
            in ``RelocationError``.

    Returns:
        Absolute path to the new transcript file on disk.

    Raises:
        RelocationError: on any failure.  The source is always intact;
            any half-written destination temp files are cleaned up.
    """
    if not session_id:
        raise RelocationError("missing session id")
    if not _SAFE_SESSION_ID_RE.match(session_id):
        # Defense-in-depth: a crafted session id with `/` would let us
        # escape ``CLAUDE_PROJECTS_ROOT/<slug>/`` once we join.  Real
        # Claude UUIDs always match this pattern.
        raise RelocationError(
            f"refusing to relocate: session id has unexpected format: "
            f"{session_id!r}"
        )
    if not src_cwd:
        raise RelocationError("missing source cwd")
    if not dst_cwd:
        raise RelocationError("missing destination cwd")

    src_slug = slugify(src_cwd)
    dst_slug = slugify(dst_cwd)

    src_proj = CLAUDE_PROJECTS_ROOT / src_slug
    dst_proj = CLAUDE_PROJECTS_ROOT / dst_slug

    src_jsonl = src_proj / f"{session_id}.jsonl"
    dst_jsonl = dst_proj / f"{session_id}.jsonl"
    src_dir = src_proj / session_id
    dst_dir = dst_proj / session_id

    # ---- Pre-flight (no mutations) ------------------------------------

    # Slug-encoding sanity check: Claude must already have this dir on
    # disk because we know a transcript lives there.  If our computed
    # slug for src_cwd doesn't match Claude's actual directory, our
    # encoding has drifted and we must abort *before* writing anything.
    if not src_proj.is_dir():
        raise RelocationError(
            f"source project directory not found: {src_proj}\n"
            f"  Computed slug for {src_cwd!r} doesn't match any directory "
            f"under {CLAUDE_PROJECTS_ROOT}.  Claude's path encoding may "
            f"have changed; refusing to relocate."
        )
    if not src_jsonl.is_file():
        raise RelocationError(
            f"source transcript not found: {src_jsonl}"
        )

    # Slug collision: different cwds can produce the same slug
    # (e.g. ``/a/b`` and ``/a-b`` both become ``-a-b``).  In that case
    # the move is a no-op — the file is already at the right path —
    # and we report success so the caller skips the chdir.
    if src_slug == dst_slug:
        return str(src_jsonl)

    # Case-insensitive filesystem defense (macOS APFS default): two
    # slugs that differ only in case (or by some other character that
    # the filesystem folds away) can resolve to the same on-disk inode.
    # If we proceeded, ``os.replace(jsonl_tmp, dst_jsonl)`` would
    # silently overwrite the source's bytes and the Phase 3 ``unlink``
    # would then delete the *only* copy on disk — actual data loss.
    # ``samefile`` catches this before we touch anything.
    try:
        if dst_proj.exists() and src_proj.samefile(dst_proj):
            return str(src_jsonl)
    except OSError:
        # Permission or stat failure here is rare; fall through and let
        # the explicit checks below surface a cleaner error.
        pass

    # Collision check on the destination — refuse to overwrite.
    if dst_jsonl.exists():
        raise RelocationError(
            f"destination transcript already exists: {dst_jsonl}\n"
            f"  Refusing to overwrite.  Move or delete it manually if you "
            f"want to proceed."
        )
    has_sidecar = src_dir.is_dir()
    if has_sidecar and dst_dir.exists():
        raise RelocationError(
            f"destination sidecar directory already exists: {dst_dir}\n"
            f"  Refusing to overwrite.  Move or delete it manually if you "
            f"want to proceed."
        )

    # Make sure the destination project dir is in place — also catches
    # permission errors before we start the expensive copy.
    try:
        dst_proj.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RelocationError(
            f"could not create destination project directory {dst_proj}: {e}"
        )

    # Per-process tmp paths so two concurrent ``leap --resume`` runs on
    # the same session never share a tmp file.  Sharing would let one
    # process read the other's mid-write bytes, fail verification, and
    # surface a confusing error even though no data is at risk.
    pid = os.getpid()
    jsonl_tmp = dst_proj / f"{session_id}.jsonl.{pid}{_TMP_SUFFIX}"
    dir_tmp = dst_proj / f"{session_id}.{pid}{_TMP_SUFFIX}"
    # If a previous, crashed run with the *same* PID (PIDs do recycle)
    # left these around, clear them now so ``shutil.copytree`` doesn't
    # trip on an existing directory.
    _best_effort_remove(jsonl_tmp)
    _best_effort_remove(dir_tmp)

    # ---- Critical section --------------------------------------------
    # ``prev_mask`` is initialized inside the try so that if a queued
    # SIGINT fires between ``_block_critical_signals`` returning and
    # the try-block being entered, we don't leak a permanently-blocked
    # signal mask on this process.  ``None`` sentinel tells the
    # ``finally`` whether the block actually happened.
    prev_mask: Optional[set[int]] = None
    # Snapshot of src_jsonl's stat captured at the moment we know its
    # bytes match our copy — used right before unlink to detect a
    # rogue writer (a Claude running directly, outside leap, with the
    # same session id) that may have appended after our verify.  We
    # would otherwise unlink src and lose those new bytes.
    src_stat_after_verify: Optional[os.stat_result] = None
    # Same idea for the sidecar dir: after verify we know every file
    # there matches dst, so we record sizes+mtimes; before ``rmtree``
    # we re-snapshot and refuse to delete if anything changed.
    src_dir_snapshot: Optional[dict[Path, tuple[int, int]]] = None
    try:
        prev_mask = _block_critical_signals()

        # Phase 1: copy + fsync + verify (source still untouched).
        try:
            shutil.copy2(str(src_jsonl), str(jsonl_tmp))
            _fsync_file(jsonl_tmp)
            _verify_files_match(src_jsonl, jsonl_tmp)
            # Capture src stat right after verify — this is the known
            # last moment at which src's bytes equal our committed
            # snapshot.  Any later mtime/size change means a rogue
            # writer modified src and we must NOT unlink.
            src_stat_after_verify = src_jsonl.stat()

            if has_sidecar:
                shutil.copytree(
                    str(src_dir),
                    str(dir_tmp),
                    copy_function=shutil.copy2,
                    symlinks=False,
                )
                _fsync_tree(dir_tmp)
                _verify_trees_match(src_dir, dir_tmp)
                # Capture the sidecar tree snapshot right after verify —
                # symmetric to ``src_stat_after_verify`` above.
                src_dir_snapshot = _snapshot_tree(src_dir)
        except RelocationError:
            _best_effort_remove(jsonl_tmp)
            _best_effort_remove(dir_tmp)
            raise
        except OSError as e:
            _best_effort_remove(jsonl_tmp)
            _best_effort_remove(dir_tmp)
            raise RelocationError(f"copy failed: {e}") from e

        # Phase 2: atomic commit.  os.replace is atomic on POSIX same-fs;
        # if dst and tmp aren't on the same fs, replace falls back to
        # copy+remove which is fine for our verification semantics.
        try:
            os.replace(str(jsonl_tmp), str(dst_jsonl))
        except OSError as e:
            _best_effort_remove(jsonl_tmp)
            _best_effort_remove(dir_tmp)
            raise RelocationError(f"failed to commit transcript to {dst_jsonl}: {e}") from e

        if has_sidecar:
            try:
                os.rename(str(dir_tmp), str(dst_dir))
            except OSError as e:
                # Roll back the JSONL placement so the caller sees a
                # clean "nothing happened" state.  Source is still the
                # only valid copy.
                _best_effort_remove(dst_jsonl)
                _best_effort_remove(dir_tmp)
                raise RelocationError(
                    f"failed to commit sidecar dir to {dst_dir}: {e}"
                ) from e

        # Caller bookkeeping happens here — *before* we delete the source —
        # so a crash mid-callback leaves a recoverable duplicate state
        # rather than orphaning the new files.
        if on_committed is not None:
            try:
                on_committed(str(dst_jsonl))
            except Exception as e:
                raise RelocationError(
                    f"destination committed but bookkeeping callback "
                    f"failed: {e}\n  Source files left intact at {src_jsonl}"
                    + (f" and {src_dir}" if has_sidecar else "") + "."
                ) from e

        # Phase 3: delete source.  Re-stat first to detect any rogue
        # writer that touched src after our verify; if so, refuse to
        # unlink and surface a clear error — the user keeps both
        # copies on disk and can reconcile manually.
        try:
            cur_src_stat = src_jsonl.stat()
        except OSError as e:
            raise RelocationError(
                f"source transcript disappeared during the move: {src_jsonl}: {e}\n"
                f"  Destination at {dst_jsonl} is intact."
            ) from e
        if (src_stat_after_verify is None
                or cur_src_stat.st_size != src_stat_after_verify.st_size
                or cur_src_stat.st_mtime_ns != src_stat_after_verify.st_mtime_ns):
            raise RelocationError(
                f"source transcript was modified after our copy was committed; "
                f"refusing to delete it to avoid losing those changes.\n"
                f"  Destination at {dst_jsonl} contains the verified snapshot.\n"
                f"  Source at {src_jsonl} still has whatever was appended.\n"
                f"  If a Claude session is currently running in {src_cwd}, "
                f"exit it before relocating."
            )
        try:
            src_jsonl.unlink()
        except OSError as e:
            raise RelocationError(
                f"destination committed but source transcript could not be "
                f"deleted: {src_jsonl}: {e}\n"
                f"  Both copies now exist; delete the source manually."
            ) from e
        if has_sidecar:
            # Symmetric to the src_jsonl stat re-check above: detect a
            # rogue writer that touched any sub-agent file (or added a
            # new one) after we copied the sidecar.  rmtree would
            # otherwise silently destroy those bytes.
            cur_dir_snapshot = _snapshot_tree(src_dir)
            if cur_dir_snapshot != src_dir_snapshot:
                added = sorted(set(cur_dir_snapshot) - set(src_dir_snapshot or {}))
                modified = sorted(
                    rel for rel, st in cur_dir_snapshot.items()
                    if (src_dir_snapshot or {}).get(rel) not in (None, st)
                    and rel not in added
                )
                raise RelocationError(
                    f"source sidecar dir was modified after our copy was "
                    f"committed; refusing to delete it to avoid losing "
                    f"those changes.\n"
                    f"  Destination at {dst_dir} contains the verified snapshot.\n"
                    f"  Source at {src_dir} has new/changed files: "
                    f"added={added[:5]} modified={modified[:5]}.\n"
                    f"  If a Claude session is currently running in {src_cwd}, "
                    f"exit it before relocating."
                )
            try:
                shutil.rmtree(str(src_dir))
            except OSError as e:
                raise RelocationError(
                    f"destination committed but source sidecar could not be "
                    f"deleted: {src_dir}: {e}\n"
                    f"  Both copies now exist; delete the source manually."
                ) from e

        return str(dst_jsonl)
    finally:
        if prev_mask is not None:
            _restore_signal_mask(prev_mask)
