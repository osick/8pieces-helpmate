#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "chess/board.h"
namespace py = pybind11;
using namespace hm;
static Material mat_or_throw(const std::string& s) {
    auto m = Material::parse(s);
    if (!m) throw std::invalid_argument("bad material string: " + s);
    return *m;
}
PYBIND11_MODULE(_helpmate, mod) {
    py::register_exception<MissingTableError>(mod, "MissingTableError", PyExc_RuntimeError);
    mod.def("generate", [](const std::string& mat, const std::string& tables, int threads,
                           bool verbose, bool progress, bool force_ram) {
        GenOptions o; o.tables_dir = tables; o.threads = threads;
        o.verbose = verbose; o.progress = progress; o.force_ram = force_ram;
        return generate(mat_or_throw(mat), o);
    }, py::arg("material"), py::arg("tables") = "tables", py::arg("threads") = 1,
       py::arg("verbose") = false, py::arg("progress") = false, py::arg("force_ram") = false);
    py::class_<Tablebase>(mod, "Tablebase")
        .def(py::init<std::string>())
        .def("probe", [](const Tablebase& t, const std::string& fen) -> py::object {
            auto p = t.probe(fen);
            if (!p) return py::none();
            return py::make_tuple(p->dtm, p->count, p->flipped);
        })
        .def("line", &Tablebase::line)
        .def("lines", &Tablebase::lines, py::arg("fen"), py::arg("max") = 100)
        .def("mine", [](const Tablebase& t, const std::string& mat, int dtm, int count, int max) {
            std::vector<std::string> out;
            t.mine(mat_or_throw(mat), dtm, count, [&](const std::string& f) {
                out.push_back(f); return (int)out.size() < max; });
            return out;
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100)
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
