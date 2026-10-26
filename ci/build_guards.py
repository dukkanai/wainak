"""Small shared guards for the two manual build drivers; no tool/network access."""
import errno
import os
from pathlib import Path
import stat
import subprocess
import time

def tree_size(root, attempts=3):
    """Count payload and metadata without following links or hiding scan errors.

    ENOENT can be ordinary compiler-cache churn: retry the WHOLE snapshot a
    bounded number of times. EACCES, EIO and every other error fail immediately.
    This is periodic accounting, not an atomic snapshot or an OS quota.
    """
    root = Path(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    def scan(fd, depth=0):
        if depth > 128:
            raise OSError(errno.EOVERFLOW, 'budget_tree_depth')
        total = os.fstat(fd).st_size
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, flags, dir_fd=fd)
                    try:
                        actual = os.fstat(child)
                        if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
                            raise FileNotFoundError(errno.ENOENT, 'budget_snapshot_changed')
                        total += scan(child, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    total += info.st_size
                else:
                    raise OSError(errno.EINVAL, 'budget_special_file')
        return total
    for attempt in range(attempts):
        try:
            try:
                fd = os.open(root, flags)
            except FileNotFoundError:
                return 0  # Optional build roots need not have been created yet.
            try:
                return scan(fd)
            finally:
                os.close(fd)
        except FileNotFoundError:
            if attempt + 1 == attempts:
                raise
            time.sleep(.01)
    raise ValueError('invalid_budget_attempts')

def wait_until(process, deadline, guard, expired):
    """EOF is not exit: retain cancellation/resource checks until real exit."""
    while True:
        guard()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise expired()
        try:
            return process.wait(timeout=min(.2, remaining))
        except subprocess.TimeoutExpired:
            pass
