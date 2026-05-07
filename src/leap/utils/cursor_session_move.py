"""Safely relocate a Cursor Agent session's on-disk state across cwds.

Cursor Agent stores each chat as a directory under
``~/.cursor/chats/<MD5(workspace)>/<chatId>/`` where ``workspace`` is
``--workspace <path>`` (if passed) or the cwd cursor-agent was
launched from (with cursor's own workspace-root walk).  Resuming a
chat with ``cursor-agent --resume <chatId>`` only finds it under the
``MD5`` of the *current* cwd, so a chat created in cwd A is invisible
when resuming from cwd B.

This module relocates the chat directory so the same chat can be
resumed under a different cwd::

  src = ~/.cursor/chats/<MD5(workspace_at_record_time)>/<chatId>/
  dst = ~/.cursor/chats/<MD5(dst_cwd)>/<chatId>/

Two complications vs Claude/Gemini:

* **The recorded cwd may not match cursor's actual hash dir.**  The
  hook captures the hook subprocess's cwd, which can differ from
  cursor's chosen workspace (cursor walks up from cwd looking for a
  ``.git`` etc.).  We compensate by *searching* — scan every
  ``~/.cursor/chats/<hash>/<chatId>/`` for a directory matching the
  chatId, regardless of which hash dir it's under.

* **The "session" is a whole directory tree**, not a single file.
  Phase 1 uses :func:`stage_copy_tree`; Phase 2 atomically renames
  the dir; Phase 3 deletes the source dir after a snapshot-based
  rogue-writer check (same semantics as Claude's sidecar logic).

Atomic-move primitives live in :mod:`leap.utils.relocation`; this
module is the Cursor-specific orchestrator.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional

from leap.utils.relocation import (
    RelocationError,
    best_effort_remove,
    commit_tree,
    is_safe_session_id,
    make_tmp_path,
    must_remove_tree,
    signals_blocked,
    snapshot_tree,
    stage_copy_tree,
)


__all__ = [
    'CURSOR_CHATS_ROOT',
    'cwd_hash',
    'find_chat_dir',
    'relocate_cursor_session',
]


CURSOR_HOME: Path = Path.home() / ".cursor"
CURSOR_CHATS_ROOT: Path = CURSOR_HOME / "chats"


def cwd_hash(cwd: str) -> str:
    """Return cursor-agent's per-cwd directory name for ``cwd``.

    Empirically MD5(cwd) hex-encoded — every entry under
    ``~/.cursor/chats/`` is a 32-char lowercase hex string and matches
    the MD5 of one of the user's workspace paths.  No salting, no
    normalization — bare bytes-in, bytes-out.
    """
    return hashlib.md5(cwd.encode('utf-8')).hexdigest()


def relocate_cursor_session(
    session_id: str,
    src_cwd: str,
    dst_cwd: str,
    *,
    on_committed: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Move a Cursor chat dir from its current hash dir to ``dst_cwd``'s.

    Returns the new chat-dir path on success, ``None`` when:

    * ``session_id`` fails the safety regex,
    * ``~/.cursor/chats/`` doesn't exist,
    * the chat dir can't be located under any project hash.

    The caller treats ``None`` as "couldn't relocate, fall through to
    chdir-to-recorded-cwd" — same contract as Claude/Gemini.

    Raises :class:`RelocationError` on disk-side failures (copy,
    verify, rename).  Source intact in those cases.
    """
    if not is_safe_session_id(session_id):
        return None
    if not src_cwd or not dst_cwd:
        return None
    if not CURSOR_CHATS_ROOT.is_dir():
        return None

    # ---- Locate src side ----------------------------------------------
    # Prefer the hash for the recorded cwd (fast common case); fall
    # back to scanning every hash dir under chats/ because cursor's
    # workspace-root walk may have hashed a parent dir of src_cwd.
    src_dir = find_chat_dir(session_id, prefer_cwd=src_cwd)
    if src_dir is None:
        return None

    # ---- Resolve dst slug ---------------------------------------------
    dst_hash = cwd_hash(dst_cwd)
    dst_proj = CURSOR_CHATS_ROOT / dst_hash
    dst_dir = dst_proj / session_id

    # Same-hash edge case: src already under dst_cwd's hash.
    if src_dir.parent.name == dst_hash:
        if on_committed is not None:
            on_committed(str(src_dir))
        return str(src_dir)

    # Refuse to overwrite an existing destination.
    if dst_dir.exists():
        raise RelocationError(
            f"destination chat directory already exists: {dst_dir}\n"
            f"  Refusing to overwrite.  Move or delete it manually if "
            f"you want to proceed."
        )

    try:
        dst_proj.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RelocationError(
            f"could not create destination project dir {dst_proj}: {e}"
        ) from e

    tmp = make_tmp_path(dst_dir)
    best_effort_remove(tmp)

    # Snapshot of source tree at the moment we know the copy is good
    # — used to detect a rogue cursor-agent process that wrote new
    # files into the source dir between our verify and our rmtree.
    src_snapshot: Optional[dict[Path, tuple[int, int]]] = None

    with signals_blocked():
        # Phase 1: copytree + fsync + verify (source still untouched).
        stage_copy_tree(src_dir, tmp)
        src_snapshot = snapshot_tree(src_dir)

        # Phase 2: atomic commit of the directory.
        commit_tree(tmp, dst_dir)

        # Caller bookkeeping — runs after the move is durable but
        # before src is removed, so a crash mid-callback leaves a
        # recoverable duplicate state.
        if on_committed is not None:
            try:
                on_committed(str(dst_dir))
            except Exception as e:
                raise RelocationError(
                    f"destination committed but bookkeeping callback "
                    f"failed: {e}\n  Source dir left intact at {src_dir}."
                ) from e

        # Phase 3: delete source dir, with a rogue-writer check.
        cur_snapshot = snapshot_tree(src_dir)
        if cur_snapshot != src_snapshot:
            added = sorted(set(cur_snapshot) - set(src_snapshot or {}))
            modified = sorted(
                rel for rel, st in cur_snapshot.items()
                if (src_snapshot or {}).get(rel) not in (None, st)
                and rel not in added
            )
            raise RelocationError(
                f"source chat dir was modified after our copy was "
                f"committed; refusing to delete it to avoid losing "
                f"those changes.\n"
                f"  Destination at {dst_dir} contains the verified snapshot.\n"
                f"  Source at {src_dir} has new/changed files: "
                f"added={added[:5]} modified={modified[:5]}.\n"
                f"  If a Cursor session is currently running for this "
                f"chat, exit it before relocating."
            )
        must_remove_tree(src_dir, dst_for_message=dst_dir)

        # If the source's project dir is now empty, prune it too — leaves
        # ``~/.cursor/chats/`` tidy.  Best-effort: if cursor races and
        # creates a sibling chat, the rmdir fails harmlessly.
        try:
            src_proj = src_dir.parent
            if src_proj.is_dir() and not any(src_proj.iterdir()):
                src_proj.rmdir()
        except OSError:
            pass

        return str(dst_dir)


# ---- Internals -------------------------------------------------------


def find_chat_dir(session_id: str, *, prefer_cwd: str) -> Optional[Path]:
    """Locate ``<chats_root>/<hash>/<session_id>`` across project dirs.

    Tries ``MD5(prefer_cwd)`` first (the cheap common case where the
    record was accurate); falls back to scanning every project hash
    dir for a child named ``session_id``.  This handles the case where
    cursor-agent's workspace-root walk hashed a parent of the recorded
    cwd, so the chat doesn't actually live under MD5(prefer_cwd).

    Returns ``None`` when the chat dir doesn't exist anywhere under
    ``~/.cursor/chats/`` — used both by :func:`relocate_cursor_session`
    (give up the move) and by ``CursorAgentProvider.session_exists``
    (hide stale records from the picker).
    """
    preferred = CURSOR_CHATS_ROOT / cwd_hash(prefer_cwd) / session_id
    if preferred.is_dir():
        return preferred
    if not CURSOR_CHATS_ROOT.is_dir():
        return None
    try:
        projects = list(CURSOR_CHATS_ROOT.iterdir())
    except OSError:
        return None
    for proj in projects:
        if not proj.is_dir():
            continue
        candidate = proj / session_id
        if candidate.is_dir():
            return candidate
    return None
