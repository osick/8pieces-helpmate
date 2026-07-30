#pragma once
#include "chess/types.h"
#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace hm {

struct Material {
    std::array<uint8_t, 6> white{}, black{};        // counts indexed by PieceType

    static std::optional<Material> parse(const std::string&);  // "KBkqrbp" or "KBvkqrbp"
    static Material of(const std::vector<PlacedPiece>&);

    std::string name() const;                       // canonical "KBvkqrbp"
    bool operator==(const Material&) const = default;

    bool has_pawns() const;
    int total() const;
    int pawn_count() const;
    // True iff the white (mating) side holds only its king. Such a side can
    // never give check, so the material can contain no mate — and since only
    // black owns pawns here, no promotion can change that.
    bool mating_side_is_bare_king() const;

    std::vector<Material> successors() const;       // capture / promotion / promotion-capture results
    static std::vector<Material> closure_topo(const Material& root); // build order, root last
};

}  // namespace hm
