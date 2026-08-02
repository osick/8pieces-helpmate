#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "chess/board.h"
#include "version.h"
namespace py = pybind11;
using namespace hm;
static Material mat_or_throw(const std::string& s) {
    auto m = Material::parse(s);
    if (!m) throw std::invalid_argument("bad material string: " + s);
    return *m;
}
// Mirrors the validation in src/packages/cli/main.cpp's cmd_mine. Unlike the CLI, this
// binding has no "was the flag given" distinction: -1 is the documented wire
// value for "unset" (the HTTP API converts None -> -1 before calling), so -1
// must always be accepted here, even though the CLI treats a user-typed -1
// as an error. Do not "fix" that into matching the CLI.
static void validate_mine_shape(int count, int starts, int ends) {
    if (starts != -1 && starts < 1)
        throw std::invalid_argument("starts must be at least 1");
    if (ends != -1 && ends < 1)
        throw std::invalid_argument("ends must be at least 1");
    if (count >= 0 && starts > count)
        throw std::invalid_argument(
            "starts=" + std::to_string(starts) + " cannot exceed count=" + std::to_string(count));
    if (count >= 0 && ends > count)
        throw std::invalid_argument(
            "ends=" + std::to_string(ends) + " cannot exceed count=" + std::to_string(count));
}
PYBIND11_MODULE(_helpmate, mod) {
    mod.attr("__version__") = hm::HELPMATE_VERSION;
    py::register_exception<MissingTableError>(mod, "MissingTableError", PyExc_RuntimeError);
    mod.def(
        "generate",
        [](const std::string& mat, const std::string& tables, int threads, bool verbose, bool progress,
           bool force_ram, bool compress, unsigned int block_size) {
            GenOptions o;
            o.tables_dir = tables;
            o.threads = threads;
            o.verbose = verbose;
            o.progress = progress;
            o.force_ram = force_ram;
            o.compress = compress;
            o.block_size = block_size;
            return generate(mat_or_throw(mat), o);
        },
        py::arg("material"), py::arg("tables") = "tables", py::arg("threads") = 1, py::arg("verbose") = false,
        py::arg("progress") = false, py::arg("force_ram") = false,
        // compress/block_size mirror the CLI's `gen --compress`/`--block-size`
        // (see docs/USAGE.md's Table format section). Unlike the CLI flag
        // (which takes KiB), block_size here is raw BYTES, matching
        // GenOptions::block_size and every other block_size in this codebase.
        py::arg("compress") = false, py::arg("block_size") = kDefaultBlockSize);
    py::class_<Tablebase>(mod, "Tablebase")
        .def(py::init<std::string>())
        .def("probe", [](const Tablebase& t, const std::string& fen) -> py::object {
            auto p = t.probe(fen);
            if (!p) return py::none();
            return py::make_tuple(p->dtm, p->count, p->flipped);
        })
        .def("line", &Tablebase::line)
        .def("lines", &Tablebase::lines, py::arg("fen"), py::arg("max") = 100)
        .def("moves", [](const Tablebase& t, const std::string& fen) {
            py::list out;
            for (const auto& m : t.moves(fen)) {
                py::dict d;
                d["uci"] = m.uci;  d["san"] = m.san;  d["fen"] = m.fen;
                d["dtm"] = m.solvable ? py::cast(m.dtm) : py::none();
                d["count"] = m.count;
                d["solvable"] = m.solvable;
                d["optimal"] = m.optimal;
                out.append(std::move(d));
            }
            return out;
        }, py::arg("fen"))
        .def("mine", [](const Tablebase& t, const std::string& mat, int dtm, int count,
                        int max, int starts, int ends) {
            validate_mine_shape(count, starts, ends);
            std::vector<std::string> out;
            t.mine(mat_or_throw(mat),
                   MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; });
            return out;
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
           py::arg("starts") = -1, py::arg("ends") = -1)
        .def("_mine_with_stats", [](const Tablebase& t, const std::string& mat, int dtm,
                                    int count, int max, int starts, int ends) {
            validate_mine_shape(count, starts, ends);
            std::vector<std::string> out;
            uint64_t skipped = 0;
            t.mine(mat_or_throw(mat),
                   MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; },
                   &skipped);
            return std::make_pair(out, skipped);      // -> (list[str], int) in Python
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
           py::arg("starts") = -1, py::arg("ends") = -1)
        .def("_stats_json", [](const Tablebase& t, const std::string& mat) {
            return t.stats_json(mat_or_throw(mat)); });
    mod.def("_perft", [](const std::string& fen, int depth) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        return b->perft(depth);
    });
    mod.def("_legal_moves", [](const std::string& fen) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        std::vector<std::string> out;
        for (auto& m : b->legal_moves()) out.push_back(m.uci());
        return out;
    });
}
