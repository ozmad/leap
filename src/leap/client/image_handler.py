"""
Image handling for Leap client.

Handles clipboard image detection and saving (macOS and Linux).
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from leap.utils.constants import IMAGE_EXTENSIONS, QUEUE_IMAGES_DIR


def check_clipboard_has_image() -> bool:
    """Check if clipboard contains an image (macOS and Linux)."""
    if sys.platform == 'darwin':
        try:
            result = subprocess.run(
                ['osascript', '-e', 'clipboard info'],
                capture_output=True,
                text=True,
                timeout=1,
            )
            return 'picture' in result.stdout.lower()
        except (subprocess.SubprocessError, OSError):
            return False
    # Linux: try xclip TARGETS, then xsel raw-bytes magic check
    if shutil.which('xclip'):
        try:
            r = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-t', 'TARGETS', '-o'],
                capture_output=True,
                timeout=2,
            )
            return b'image/png' in r.stdout or b'image/jpeg' in r.stdout
        except (subprocess.SubprocessError, OSError):
            pass
    if shutil.which('xsel'):
        try:
            r = subprocess.run(
                ['xsel', '--clipboard', '--output'],
                capture_output=True,
                timeout=2,
            )
            return r.stdout[:4] == b'\x89PNG'
        except (subprocess.SubprocessError, OSError):
            pass
    return False


def save_clipboard_image() -> Optional[str]:
    """Save clipboard image to .storage/queue_images/ (macOS and Linux).

    Uses an MD5 hash of the file content as the filename so that
    saving the same image twice produces the same file (natural dedup).

    Returns:
        Path to the saved image file, or None on failure.
    """
    QUEUE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == 'darwin':
        try:
            fd, tmp_path = tempfile.mkstemp(suffix='.png', dir=str(QUEUE_IMAGES_DIR))
            os.close(fd)
            script = f'''
            set png_data to the clipboard as «class PNGf»
            set the_file to open for access POSIX file "{tmp_path}" with write permission
            write png_data to the_file
            close access the_file
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0 or not os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return None
            raw_bytes: Optional[bytes] = None
            with open(tmp_path, 'rb') as fh:
                raw_bytes = fh.read()
            os.unlink(tmp_path)
        except (subprocess.SubprocessError, OSError):
            return None
    else:
        # Linux: try xclip → xsel → give up
        raw_bytes = None
        if shutil.which('xclip'):
            try:
                r = subprocess.run(
                    ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'],
                    capture_output=True,
                    timeout=5,
                )
                if r.returncode == 0 and r.stdout:
                    raw_bytes = r.stdout
            except (subprocess.SubprocessError, OSError):
                pass
        if raw_bytes is None and shutil.which('xsel'):
            try:
                r = subprocess.run(
                    ['xsel', '--clipboard', '--output'],
                    capture_output=True,
                    timeout=5,
                )
                if r.returncode == 0 and r.stdout[:4] == b'\x89PNG':
                    raw_bytes = r.stdout
            except (subprocess.SubprocessError, OSError):
                pass
        if not raw_bytes:
            return None

    if raw_bytes is None:
        return None
    content_hash = hashlib.md5(raw_bytes).hexdigest()[:12]
    final_path = str(QUEUE_IMAGES_DIR / f'{content_hash}.png')
    if os.path.isfile(final_path):
        return final_path
    try:
        with open(final_path, 'wb') as fh:
            fh.write(raw_bytes)
    except OSError:
        return None
    return final_path


def is_image_file(path: str) -> bool:
    """
    Check if path points to an image file.

    Args:
        path: File path to check.

    Returns:
        True if path exists and is an image file.
    """
    if not os.path.exists(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in IMAGE_EXTENSIONS
