import struct

import helpmate


def test_generate_compress_writes_a_block_compressed_table_and_reads_back(tmp_path):
    d = str(tmp_path)
    # A small block size so a 146 KB-ish KQvk table spans several blocks
    # (default kDefaultBlockSize is 16384, which is already several blocks
    # for a table this size, but an explicit small size makes the multi-block
    # path unambiguous regardless of future default changes).
    written = helpmate.generate("KQvk", tables=d, threads=1, compress=True, block_size=4096)
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
    # kDefaultBlockSize (table_file.h) -- 16 KiB as of v0.7.5's block-size
    # tuning; this test breaks loudly if that default ever drifts without the
    # binding's own default (py::arg("block_size") = kDefaultBlockSize)
    # being updated to match.
    assert block_size == 16384


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
