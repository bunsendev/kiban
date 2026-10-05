"""Current-user Windows DPAPI storage outside portable data and distribution files."""

import ctypes
import os
import tempfile
from pathlib import Path


class CredentialError(ValueError):
    pass


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise CredentialError("キーの保存はWindowsで利用できます")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    # UI_FORBIDDEN only: deliberately omit LOCAL_MACHINE (other users cannot decrypt).
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(Blob),
    ]
    fn.restype = ctypes.c_int
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise CredentialError(
            "保存したキーを利用できません。このWindowsユーザーで再設定してください"
        )
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def validate(key):
    if (
        not isinstance(key, str)
        or not 0 < len(key) <= 256
        or any(ord(c) < 33 or ord(c) > 126 for c in key)
    ):
        raise CredentialError("APIキーを入力してください（空白・改行は含めないでください）")
    return key


class ApiCredentials:
    def __init__(self, path=None):
        base = os.environ.get("LOCALAPPDATA")
        self.path = (
            Path(path)
            if path
            else (
                Path(base) / "Bunsen" / "Portable" / "Credentials" / "openai.dpapi"
                if base
                else None
            )
        )

    def status(self):
        if not self.path or not self.path.exists():
            return {"saved": False, "available": False}
        try:
            self.load()
            return {"saved": True, "available": True}
        except CredentialError:
            return {"saved": True, "available": False}

    def load(self):
        try:
            if not self.path or self.path.stat().st_size > 16384:
                raise CredentialError("APIキーを設定してください")
            return validate(protect(self.path.read_bytes(), decrypt=True).decode("ascii"))
        except (OSError, UnicodeError) as exc:
            raise CredentialError("保存したAPIキーを読み込めません。再設定してください") from exc

    def save(self, key):
        encrypted = protect(validate(key).encode("ascii"))
        if not self.path:
            raise CredentialError("Windowsユーザーの保存先が見つかりません")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        return self.status()

    def delete(self):
        if self.path:
            self.path.unlink(missing_ok=True)
        return self.status()
