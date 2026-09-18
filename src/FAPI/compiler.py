import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path

import zstandard

parent = Path(__file__).resolve().parent
COMPILER_PATH = parent / "luau" / "compile.exe"
MAX_DECOMPRESSED_BYTECODE = 50 * 1024 * 1024
COMPILE_TIMEOUT_SECONDS = 20


class BytecodeError(Exception):
    pass


WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_chunkname(chunkname: str) -> str:
    name = (chunkname or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(" .") or "chunk"
    if name.upper() in WINDOWS_RESERVED:
        name = "_" + name
    return name[:120]


class Luau:
    @staticmethod
    def _normalize_source(source: str | bytes) -> str | bytes:
        if not isinstance(source, (str, bytes)):
            raise TypeError("source must be str or bytes")
        return source

    @staticmethod
    def _run_compiler(source_path: Path, cwd: Path | None = None) -> bytes:
        if not COMPILER_PATH.is_file():
            raise BytecodeError(f"Luau compiler not found: {COMPILER_PATH}")

        try:
            result = subprocess.run(
                [str(COMPILER_PATH), str(source_path.name) if cwd else str(source_path), "--binary"],
                capture_output=True,
                cwd=str(cwd) if cwd else None,
                timeout=COMPILE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise BytecodeError("Luau compilation timed out")
        except OSError as exc:
            raise BytecodeError(f"Failed to start Luau compiler: {exc}") from exc

        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
            stdout = (result.stdout or b"").decode("utf-8", "replace").strip()
            detail = stderr or stdout or f"compiler exited with code {result.returncode}"
            raise BytecodeError(f"Luau compile error:\n{detail}")

        return result.stdout

    @staticmethod
    def compile(source: str | bytes, chunkname: str = "") -> bytes:
        source = Luau._normalize_source(source)

        with tempfile.TemporaryDirectory(prefix="AkazExecutor-Chunk-") as tmpdir:
            tmp_path = Path(tmpdir)
            safe_name = safe_chunkname(chunkname) if chunkname else "source.luau"
            source_path = tmp_path / safe_name

            Luau._write_source(source_path, source)
            return Luau._run_compiler(source_path, cwd=tmp_path)

    @staticmethod
    def decrypt_bytecode(encrypted: bytes) -> bytes:
        if not isinstance(encrypted, (bytes, bytearray)):
            raise TypeError("encrypted bytecode must be bytes-like")
        if len(encrypted) < 8:
            raise BytecodeError("bytecode too short")

        sign = b"RSB1"
        hash_mul = 41

        buffer = bytearray(encrypted)
        key = [((buffer[i] ^ sign[i]) - i * hash_mul) & 0xFF for i in range(4)]

        for i in range(len(buffer)):
            buffer[i] ^= (key[i % 4] + i * hash_mul) & 0xFF

        if not buffer.startswith(sign):
            raise BytecodeError("decryption failed")

        decomp_size = struct.unpack_from("<I", buffer, 4)[0]
        if decomp_size <= 0 or decomp_size > MAX_DECOMPRESSED_BYTECODE:
            raise BytecodeError("invalid decompressed bytecode size")

        try:
            result = zstandard.ZstdDecompressor().decompress(bytes(buffer[8:]), decomp_size)
        except zstandard.ZstdError as exc:
            raise BytecodeError("decompression failed") from exc

        if len(result) != decomp_size:
            raise BytecodeError("decompression produced an unexpected size")

        return result

    @staticmethod
    def _write_source(path: Path, source: str | bytes) -> None:
        if isinstance(source, str):
            path.write_text(source, encoding="utf-8")
        else:
            path.write_bytes(source)
