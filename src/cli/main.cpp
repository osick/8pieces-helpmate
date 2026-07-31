#include "format/table_file.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "probe/tablebase.h"
#include "version.h"
#include <algorithm>
#include <climits>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

using namespace hm;

namespace {

void usage() {
    std::cerr <<
        "helpmate - build and query helpmate chess tablebases\n"
        "\n"
        "Usage:\n"
        "  helpmate gen <MATERIAL> [--tables DIR] [--threads N] [--verbose]\n"
        "               [--progress] [--force-ram]\n"
        "  helpmate probe <FEN> [--tables DIR]\n"
        "  helpmate line <FEN> [--tables DIR] [--all] [--max N]\n"
        "  helpmate stats <MATERIAL> [--tables DIR]\n"
        "  helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N]\n"
        "               [--max N] [--tables DIR]\n"
        "  helpmate compact <DIR> [--dry-run]\n"
        "  helpmate --version\n"
        "\n"
        "MATERIAL is a canonical piece string, e.g. \"KQvk\" (White king+queen vs\n"
        "black king) or \"KBNvkq\". FEN is standard 6-field notation; castling\n"
        "rights must be \"-\" (this engine has no castling).\n"
        "\n"
        "Commands:\n"
        "  gen    Generate every table needed to answer queries about MATERIAL\n"
        "         (including sub-slices reached by captures/promotions), writing\n"
        "         one <name>.hm file plus a <name>.stats.json sidecar per slice\n"
        "         into --tables DIR. Existing files are left alone (re-run is\n"
        "         cheap after adding a new root material).\n"
        "  probe  Look up one position: distance-to-mate (dtm), helpmate notation\n"
        "         (h#N / h#N.5), and how many optimal replies tie for best.\n"
        "  line   Print one optimal mating line from FEN as SAN moves. With\n"
        "         --all, print every optimal line (one per output line), capped\n"
        "         at --max.\n"
        "  stats  Print the generation-time statistics JSON for MATERIAL (cell\n"
        "         counts, dtm histogram, deepest positions, ...).\n"
        "  mine   Print FENs of positions in MATERIAL matching --dtm exactly (and,\n"
        "         if given, --count exactly), up to --max, one per line.\n"
        "  compact Rewrite every .hm table in DIR whose cells are all\n"
        "         unsolvable (or invalid) as a tiny marker file, reclaiming\n"
        "         disk space. Tables with any solvable cell are left\n"
        "         untouched. --dry-run reports what would be rewritten\n"
        "         without writing anything.\n"
        "\n"
        "Options:\n"
        "  --tables DIR   table directory (default: \"tables\")\n"
        "  --threads N    worker threads for gen (default: 1)\n"
        "  --verbose      gen: per-slice lifecycle lines on stderr (closure\n"
        "                 summary, generating/cached/done per slice); implies\n"
        "                 --progress. stdout stays scriptable.\n"
        "  --progress     gen: per-pass progress lines on stderr while a slice\n"
        "                 is being generated (init pass, each scan pass with\n"
        "                 cells resolved, each count-sweep depth, with timings)\n"
        "  --force-ram    gen: skip the RAM guard (which refuses to start a\n"
        "                 slice whose planes exceed available memory)\n"
        "  --all          line: print every optimal line, not just one\n"
        "  --max N        cap on lines/FENs printed (default: 10)\n"
        "  --dtm D        mine: required, exact distance-to-mate to match\n"
        "  --count C      mine: optional, exact optimal-reply count to match\n"
        "  --starts N     mine: optional, exact number of distinct first moves across\n"
        "                 the optimal solutions (must be >= 1, and <= --count if given)\n"
        "  --ends N       mine: optional, exact number of distinct mating moves\n"
        "  --dry-run      compact: report what would be rewritten, write nothing\n"
        "  --version      print version (\"helpmate " << HELPMATE_VERSION << "\") and exit\n"
        "\n"
        "Examples:\n"
        "  helpmate gen KQvk --tables tt\n"
        "  helpmate probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt\n"
        "  helpmate line  \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt --all\n"
        "  helpmate stats KQvk --tables tt\n"
        "  helpmate mine KQvk --dtm 2 --count 1 --max 5 --tables tt\n"
        "  helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --tables tt\n"
        "\n"
        "Exit codes: 0 success (an \"unsolvable\" answer is still success), 2 a\n"
        "table needed to answer the query is missing (message says which one and\n"
        "how to build it), 3 bad usage or unparseable input.\n";
}

// Side to move, read straight from the FEN's 2nd field ("w"/"b"); only called
// after the FEN has already been accepted by the API, so it is well-formed.
Color stm_of(const std::string& fen) {
    auto sp1 = fen.find(' ');
    if (sp1 == std::string::npos) return Color::White;
    return fen[sp1 + 1] == 'b' ? Color::Black : Color::White;
}

void print_line(const std::vector<std::string>& moves) {
    for (size_t i = 0; i < moves.size(); ++i) std::cout << (i ? " " : "") << moves[i];
    std::cout << "\n";
}

// Parses `value` as an integer; never throws -- malformed input ("abc") and
// out-of-range input (overflowing int) both just return false, so the caller
// can print one clear, actionable message instead of an uncaught
// std::invalid_argument/std::out_of_range crashing the process.
bool parse_int(const std::string& value, int& out) {
    try {
        size_t used = 0;
        long v = std::stol(value, &used);
        if (used != value.size() || v < INT_MIN || v > INT_MAX) return false;
        out = (int)v;
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

int cmd_gen(const std::vector<std::string>& pos, const std::string& tables, int threads,
            bool verbose, bool progress, bool force_ram) {
    if (pos.empty()) { std::cerr << "error: gen needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    GenOptions opt; opt.tables_dir = tables; opt.threads = threads;
    opt.verbose = verbose; opt.progress = progress; opt.force_ram = force_ram;
    auto written = generate(*m, opt);
    if (written.empty())
        std::cout << "nothing to do: all tables for " << m->name() << " already exist in " << tables << "\n";
    for (auto& path : written) {
        std::cout << path;
        if (auto r = TableReader::open(path)) std::cout << " max_dtm=" << (int)r->max_dtm();
        std::cout << "\n";
    }
    return 0;
}

int cmd_probe(const std::vector<std::string>& pos, const std::string& tables) {
    if (pos.empty()) { std::cerr << "error: probe needs a FEN argument\n\n"; usage(); return 3; }
    Tablebase tb(tables);
    auto p = tb.probe(pos[0]);
    if (!p) { std::cout << "unsolvable\n"; return 0; }
    std::cout << "dtm=" << p->dtm << " (" << Tablebase::h_notation(p->dtm, stm_of(pos[0]))
               << (p->flipped ? ", colors flipped" : "") << ") count=" << p->count << "\n";
    return 0;
}

int cmd_line(const std::vector<std::string>& pos, const std::string& tables, bool all, int maxn) {
    if (pos.empty()) { std::cerr << "error: line needs a FEN argument\n\n"; usage(); return 3; }
    Tablebase tb(tables);
    if (all) {
        auto ls = tb.lines(pos[0], maxn);
        // ls == {} means unsolvable; ls == {{}} (one *empty* line) means the
        // position is already checkmate (dtm==0) -- both print nothing
        // useful move-wise, so give the same message the non---all branch
        // gives instead of silently printing a blank line.
        if (ls.empty() || ls[0].empty()) { std::cout << "unsolvable (or already mate: no line to print)\n"; return 0; }
        for (auto& l : ls) print_line(l);
    } else {
        auto l = tb.line(pos[0]);
        if (l.empty()) { std::cout << "unsolvable (or already mate: no line to print)\n"; return 0; }
        print_line(l);
    }
    return 0;
}

int cmd_stats(const std::vector<std::string>& pos, const std::string& tables) {
    if (pos.empty()) { std::cerr << "error: stats needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    Tablebase tb(tables);
    std::cout << tb.stats_json(*m) << "\n";
    return 0;
}

int cmd_mine(const std::vector<std::string>& pos, const std::string& tables, int dtm, int count,
             int maxn, int starts, int ends) {
    if (pos.empty()) { std::cerr << "error: mine needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    if (dtm < 0) { std::cerr << "error: mine requires --dtm D\n\n"; usage(); return 3; }
    for (auto [flag, val] : {std::pair{"--starts", starts}, std::pair{"--ends", ends}}) {
        if (val == -1) continue;                       // not given
        if (val < 1) {
            std::cerr << "error: " << flag << " must be at least 1\n"; return 3;
        }
        if (count >= 0 && val > count) {
            std::cerr << "error: " << flag << " " << val << " cannot exceed --count " << count
                      << " (a position with " << count << " solution(s) has at most "
                      << count << " distinct starting/mating moves)\n";
            return 3;
        }
    }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    Tablebase tb(tables);
    int printed = 0;
    uint64_t skipped = 0;
    tb.mine(*m, MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
            [&](const std::string& fen) {
                if (printed >= maxn) return false;  // handles --max 0 (print none), matches `line --all`'s pre-check
                std::cout << fen << "\n";
                ++printed;
                return printed < maxn;
            }, &skipped);
    if (skipped)
        std::cerr << "note: skipped " << skipped
                  << " position(s) whose solution count is saturated (255+): their"
                     " solutions cannot be enumerated exhaustively\n";
    return 0;
}

// helpmate compact <DIR> [--dry-run]
// Rewrites every .hm in DIR whose cells are all unsolvable as a marker table.
int cmd_compact(const std::vector<std::string>& args) {
    if (args.empty()) { std::cerr << "error: compact needs a tables directory\n"; return 3; }
    std::string dir = args[0];
    bool dry = std::find(args.begin(), args.end(), "--dry-run") != args.end();
    if (!std::filesystem::is_directory(dir)) {
        std::cerr << "error: not a directory: " << dir << "\n"; return 3;
    }
    uint64_t reclaimed = 0; int rewritten = 0, skipped = 0;
    for (auto& e : std::filesystem::directory_iterator(dir)) {
        if (e.path().extension() != ".hm") continue;
        auto r = TableReader::open(e.path().string());
        if (!r) { std::cerr << "error: unreadable table " << e.path() << "\n"; return 3; }
        if (r->all_unsolvable()) { ++skipped; continue; }          // already compact
        bool any_solvable = false;
        for (uint64_t c = 0; c < r->plane_size() && !any_solvable; ++c)
            for (Color stm : {Color::White, Color::Black}) {
                uint8_t d = r->get(stm, c).dtm;
                if (d != DTM_UNSOLVABLE && d != DTM_INVALID) { any_solvable = true; break; }
            }
        if (any_solvable) { ++skipped; continue; }
        uint64_t size = std::filesystem::file_size(e.path());
        std::string name = r->material_name();
        std::string stem = e.path().stem().string();
        uint64_t ps = r->plane_size();
        // Identity check: the sidecar and the rewrite must be keyed off the file's own
        // name, not the header's self-reported material -- otherwise a name/header
        // mismatch would rewrite the right .hm but clobber a DIFFERENT material's
        // .stats.json (or write a marker table under the wrong identity).
        if (name != stem) {
            std::cerr << "error: table " << e.path() << " is for material '" << name
                      << "', expected '" << stem << "' from filename; refusing to touch it\n";
            return 3;
        }
        std::cout << (dry ? "would rewrite " : "rewrote ") << name
                  << " (" << size / (1024 * 1024) << " MiB)\n";
        reclaimed += size;
        if (!dry) {
            auto mat = Material::parse(name);
            if (!mat) { std::cerr << "error: bad material in header: " << name << "\n"; return 3; }
            // Synthesize fresh marker metadata -- same shape as the generator's
            // opt.prune path (generator.cpp), not the original table's stale
            // meta_json -- so tooling that inspects metadata recognises a
            // compact-produced marker the same way it recognises a
            // generator-produced one.
            nlohmann::json j;
            j["material"] = name;
            j["plane_size"] = ps;
            j["max_dtm"] = (int)DTM_UNSOLVABLE;
            j["cells"] = {{"invalid", {{"wtm", 0}, {"btm", 0}}},
                          {"unsolvable", {{"wtm", ps}, {"btm", ps}}}};
            j["dtm_histogram"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
            j["uniqueness"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
            j["deepest"] = nlohmann::json::array();
            j["deepest_unique"] = nlohmann::json::array();
            j["generator_version"] = HELPMATE_VERSION;
            j["all_unsolvable"] = true;
            std::string meta = j.dump(2);
            r.reset();                                   // unmap before replacing
            TableWriter::write_unsolvable(e.path().string(), *mat, ps, meta);
            std::ofstream(dir + "/" + stem + ".stats.json", std::ios::trunc) << meta;
        }
        ++rewritten;
    }
    std::cout << (dry ? "would reclaim " : "reclaimed ") << reclaimed / (1024 * 1024)
              << " MiB from " << rewritten << " table(s); " << skipped
              << " left unchanged (solvable or already compact)\n";
    if (rewritten == 0) std::cout << "already compact\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) { usage(); return 3; }
    std::string cmd = args[0];
    if (cmd == "--help" || cmd == "-h" || cmd == "help") { usage(); return 0; }
    if (cmd == "--version" || cmd == "-V" || cmd == "version") {
        std::cout << "helpmate " << HELPMATE_VERSION << "\n";
        return 0;
    }

    std::string tables = "tables";
    int threads = 1, dtm = -1, count = -1, maxn = 10, starts = -1, ends = -1;
    bool all = false, verbose = false, progress = false, force_ram = false;
    std::vector<std::string> pos;  // positional args
    // Flags below all take a value; if one appears with nothing after it,
    // that's a usage error, not a stray positional argument (e.g. `probe FEN
    // --tables` with no directory should not silently treat "--tables" as
    // the FEN's replacement).
    auto needs_value = [](const std::string& a) {
        return a == "--tables" || a == "--threads" || a == "--dtm" || a == "--count" ||
               a == "--max" || a == "--starts" || a == "--ends";
    };
    // Consumes the value following flag `a` (already known to exist) into
    // `target`; on malformed/out-of-range input prints one clear message +
    // usage and signals the caller to exit 3, instead of ever calling
    // std::stoi directly where an exception would escape uncaught.
    bool bad_int = false;
    auto set_int = [&](const std::string& a, size_t& i, int& target) {
        if (!parse_int(args[++i], target)) {
            std::cerr << "error: " << a << " expects an integer, got \"" << args[i] << "\"\n\n";
            usage();
            bad_int = true;
        }
    };
    for (size_t i = 1; i < args.size() && !bad_int; ++i) {
        const std::string& a = args[i];
        if (needs_value(a) && i + 1 >= args.size()) {
            std::cerr << "error: " << a << " requires a value\n\n"; usage(); return 3;
        }
        if      (a == "--tables")  tables = args[++i];
        else if (a == "--threads") set_int(a, i, threads);
        else if (a == "--dtm")     set_int(a, i, dtm);
        else if (a == "--count")   set_int(a, i, count);
        else if (a == "--max")     set_int(a, i, maxn);
        else if (a == "--starts")  set_int(a, i, starts);
        else if (a == "--ends")    set_int(a, i, ends);
        else if (a == "--all") all = true;
        else if (a == "--verbose")   verbose = true;
        else if (a == "--progress")  progress = true;
        else if (a == "--force-ram") force_ram = true;
        else pos.push_back(a);
    }
    if (bad_int) return 3;
    try {
        if (cmd == "gen")   return cmd_gen(pos, tables, threads, verbose, progress, force_ram);
        if (cmd == "probe") return cmd_probe(pos, tables);
        if (cmd == "line")  return cmd_line(pos, tables, all, maxn);
        if (cmd == "stats") return cmd_stats(pos, tables);
        if (cmd == "mine")  return cmd_mine(pos, tables, dtm, count, maxn, starts, ends);
        if (cmd == "compact") return cmd_compact(pos);
        std::cerr << "error: unknown command \"" << cmd << "\"\n\n";
        usage();
        return 3;
    } catch (const MissingTableError& e) {
        std::cerr << "error: " << e.what() << "\nrun: helpmate gen <MATERIAL> --tables " << tables << "\n";
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 3;
    }
}
