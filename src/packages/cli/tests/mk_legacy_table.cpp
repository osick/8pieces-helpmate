// Test-support tool (not installed): writes a full-size, ordinary
// (version 1) table file whose every cell reads DTM_UNSOLVABLE. This stands
// in for a real pre-v0.6.1 table on disk -- one written before generation
// started pruning provably-unsolvable slices at source (see
// generator.cpp's opt.prune path) -- so `helpmate compact`'s ctest coverage
// exercises the actual rewrite path instead of only the "nothing to do"
// path (every slice `helpmate gen` produces today is already pruned to a
// marker at generation time when it is fully unsolvable, so gen output
// alone can no longer create this fixture).
//
// Optional 4th arg `--future` additionally bumps the header's version field
// to a value no build understands, after the ordinary write -- fabricating
// a table written by a newer helpmate, for `compact`'s UnsupportedVersion
// ctest coverage (see test_table_file.cpp for the same version-byte-patch
// idiom used against TableReader::open directly).
#include "format/table_file.h"
#include "indexing/material.h"
#include <cstddef>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "usage: mk_legacy_table <path> <material> [--future]\n";
        return 2;
    }
    using namespace hm;
    auto m = Material::parse(argv[2]);
    if (!m) { std::cerr << "bad material: " << argv[2] << "\n"; return 2; }
    const uint64_t n = 1000;
    std::vector<uint8_t> dw(n, DTM_UNSOLVABLE), db(n, DTM_UNSOLVABLE), cw(n, 0), cb(n, 0);
    TableWriter::write(argv[1], *m, n, DTM_UNSOLVABLE, "{\"legacy_fixture\":true}",
                       dw.data(), db.data(), cw.data(), cb.data());
    if (argc == 4 && std::strcmp(argv[3], "--future") == 0) {
        std::fstream f(argv[1], std::ios::in | std::ios::out | std::ios::binary);
        uint32_t v = 99;
        f.seekp(offsetof(TableHeader, version));
        f.write(reinterpret_cast<const char*>(&v), sizeof(v));
    }
    return 0;
}
