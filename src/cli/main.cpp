#include "format/table_file.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "probe/tablebase.h"
#include <climits>
#include <iostream>
#include <string>
#include <vector>

using namespace hm;

namespace {

void usage() {
    std::cerr <<
        "helpmate - build and query helpmate chess tablebases\n"
        "\n"
        "Usage:\n"
        "  helpmate gen <MATERIAL> [--tables DIR] [--threads N]\n"
        "  helpmate probe <FEN> [--tables DIR]\n"
        "  helpmate line <FEN> [--tables DIR] [--all] [--max N]\n"
        "  helpmate stats <MATERIAL> [--tables DIR]\n"
        "  helpmate mine <MATERIAL> --dtm D [--count C] [--max N] [--tables DIR]\n"
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
        "\n"
        "Options:\n"
        "  --tables DIR   table directory (default: \"tables\")\n"
        "  --threads N    worker threads for gen (default: 1)\n"
        "  --all          line: print every optimal line, not just one\n"
        "  --max N        cap on lines/FENs printed (default: 10)\n"
        "  --dtm D        mine: required, exact distance-to-mate to match\n"
        "  --count C      mine: optional, exact optimal-reply count to match\n"
        "\n"
        "Examples:\n"
        "  helpmate gen KQvk --tables tt\n"
        "  helpmate probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt\n"
        "  helpmate line  \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt --all\n"
        "  helpmate stats KQvk --tables tt\n"
        "  helpmate mine KQvk --dtm 2 --count 1 --max 5 --tables tt\n"
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

int cmd_gen(const std::vector<std::string>& pos, const std::string& tables, int threads) {
    if (pos.empty()) { std::cerr << "error: gen needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    GenOptions opt; opt.tables_dir = tables; opt.threads = threads;
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

int cmd_mine(const std::vector<std::string>& pos, const std::string& tables, int dtm, int count, int maxn) {
    if (pos.empty()) { std::cerr << "error: mine needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    if (dtm < 0) { std::cerr << "error: mine requires --dtm D\n\n"; usage(); return 3; }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    Tablebase tb(tables);
    int printed = 0;
    tb.mine(*m, dtm, count, [&](const std::string& fen) {
        if (printed >= maxn) return false;  // handles --max 0 (print none), matches `line --all`'s pre-check
        std::cout << fen << "\n";
        ++printed;
        return printed < maxn;
    });
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) { usage(); return 3; }
    std::string cmd = args[0];
    if (cmd == "--help" || cmd == "-h" || cmd == "help") { usage(); return 0; }

    std::string tables = "tables";
    int threads = 1, dtm = -1, count = -1, maxn = 10;
    bool all = false;
    std::vector<std::string> pos;  // positional args
    // Flags below all take a value; if one appears with nothing after it,
    // that's a usage error, not a stray positional argument (e.g. `probe FEN
    // --tables` with no directory should not silently treat "--tables" as
    // the FEN's replacement).
    auto needs_value = [](const std::string& a) {
        return a == "--tables" || a == "--threads" || a == "--dtm" || a == "--count" || a == "--max";
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
        else if (a == "--all") all = true;
        else pos.push_back(a);
    }
    if (bad_int) return 3;
    try {
        if (cmd == "gen")   return cmd_gen(pos, tables, threads);
        if (cmd == "probe") return cmd_probe(pos, tables);
        if (cmd == "line")  return cmd_line(pos, tables, all, maxn);
        if (cmd == "stats") return cmd_stats(pos, tables);
        if (cmd == "mine")  return cmd_mine(pos, tables, dtm, count, maxn);
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
