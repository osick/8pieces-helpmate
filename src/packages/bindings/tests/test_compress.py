import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import helpmate

ROOT = Path(__file__).resolve().parents[4]


def _header_block_size(path):
    with open(path, "rb") as f:
        header = f.read(64)
    return struct.unpack_from("<I", header, 46)[0]


def test_block_size_unit_matches_cli(tmp_path):
    # v0.7.5 originally shipped a unit mismatch: the CLI's --block-size took
    # KiB but the Python binding's block_size took raw bytes, so
    # `--block-size 32` and `block_size=32` silently produced different
    # tables. The binding now converts KiB to bytes internally
    # (o.block_size = block_size * 1024 in pymodule.cpp), matching the CLI.
    # This test is the trap the mismatch would have caused, kept as a
    # regression guard so the two units can't drift apart again unnoticed.
    exe = shutil.which("helpmate") or str(ROOT / "build" / "helpmate")
    if not Path(exe).exists():
        pytest.skip("helpmate binary not built")

    cli_dir = tmp_path / "cli"
    py_dir = tmp_path / "py"
    cli_dir.mkdir()
    py_dir.mkdir()

    subprocess.run(
        [exe, "gen", "KQvk", "--tables", str(cli_dir), "--compress", "--block-size", "32"],
        capture_output=True, text=True, check=True,
    )
    helpmate.generate("KQvk", tables=str(py_dir), threads=1, compress=True, block_size=32)

    cli_block_size = _header_block_size(cli_dir / "KQvk.hm")
    py_block_size = _header_block_size(py_dir / "KQvk.hm")
    assert cli_block_size == py_block_size == 32 * 1024


def test_generate_compress_writes_a_block_compressed_table_and_reads_back(tmp_path):
    d = str(tmp_path)
    # A small block size so a 146 KB-ish KQvk table spans several blocks.
    # block_size is KiB here, matching the CLI's --block-size (see
    # test_block_size_unit_matches_cli below) -- 4 means 4 KiB (4096 bytes),
    # well under the ~146 KB table, making the multi-block path unambiguous
    # regardless of future default changes.
    written = helpmate.generate("KQvk", tables=d, threads=1, compress=True, block_size=4)
    assert any(w.endswith("KQvk.hm") for w in written)

    path = f"{d}/KQvk.hm"
    with open(path, "rb") as f:
        header = f.read(64)
    # TableHeader layout (table_file.h, #pragma pack(1), verified against
    # sizeof==64): magic[4]@0, version(u32)@4, encoding(u8)@8, symmetry(u8)@9,
    # material[26]@10, plane_size(u64)@36, max_dtm(u8)@44, flags(u8)@45,
    # block_size(u32)@46, codec(u8)@50, reserved[9]@51, json_len(u32)@60.
    magic = header[0:4]
    version = struct.unpack_from("<I", header, 4)[0]
    encoding = header[8]
    block_size = struct.unpack_from("<I", header, 46)[0]
    codec = header[50]
    assert magic == b"HM8P"
    assert version == 3          # block-compressed
    assert encoding == 2         # kEncodingBlocks
    assert codec == 1            # kCodecZstd
    assert block_size == 4096

    tb = helpmate.Tablebase(d)
    # Golden per test_smoke.py's test_probe_golden -- same material, same
    # position, just read through a compressed table this time.
    assert tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == (2, 4, False)
    assert tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == ["Kh6", "Qh2#"]


def test_generate_compress_default_block_size_matches_the_core_default(tmp_path):
    d = str(tmp_path)
    helpmate.generate("KQvk", tables=d, threads=1, compress=True)
    with open(f"{d}/KQvk.hm", "rb") as f:
        header = f.read(64)
    block_size = struct.unpack_from("<I", header, 46)[0]
    # kDefaultBlockSize (table_file.h) is 65536 bytes (64 KiB); the binding's
    # own default is py::arg("block_size") = kDefaultBlockSize / 1024, i.e.
    # 64 (KiB), converted back to bytes internally. This test breaks loudly
    # if either default drifts without the other being updated to match.
    assert block_size == 65536


def test_generate_without_compress_still_writes_a_raw_table(tmp_path):
    # compress defaults to False: omitting the new kwargs entirely must
    # reproduce the pre-existing behaviour byte for byte.
    d = str(tmp_path)
    helpmate.generate("KQvk", tables=d, threads=1)
    with open(f"{d}/KQvk.hm", "rb") as f:
        header = f.read(64)
    version = struct.unpack_from("<I", header, 4)[0]
    encoding = header[8]
    assert version == 1
    assert encoding == 1
