"""Atomic update metadata, with a private temporary file for every writer."""

import json
import os
import threading
import time
import uuid
import weakref

_locks = weakref.WeakValueDictionary()
_registry_lock = threading.Lock()


def state_lock(path):
    key = os.path.normcase(str(path.absolute()))
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def write_state(path, value):
    with state_lock(path):
        _write(path, value)


def _write(path, value):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
        for attempt in range(3):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.03)
    finally:
        temporary.unlink(missing_ok=True)
