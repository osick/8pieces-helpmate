#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <algorithm>

namespace hm {

enum class Color : uint8_t { White = 0, Black = 1 };
enum class PieceType : uint8_t { King = 0, Queen = 1, Rook = 2, Bishop = 3, Knight = 4, Pawn = 5 };

struct Piece {
    Color color;
    PieceType type;
    bool operator==(const Piece&) const = default;
};

struct PlacedPiece {
    Piece piece;
    uint8_t square;
};

enum class PosState : uint8_t { Open, Check, Checkmate, Stalemate };

struct ValuePair {
    uint8_t dtm;
    uint8_t count;
};

constexpr uint8_t DTM_UNSET = 253, DTM_INVALID = 254, DTM_UNSOLVABLE = 255;
constexpr uint8_t DTM_MAX = 252, COUNT_SAT = 255;

inline uint8_t sat_add(unsigned a, unsigned b) { return (uint8_t)std::min(255u, a + b); }

inline int sq_file(int sq) { return sq & 7; }
inline int sq_rank(int sq) { return sq >> 3; }
std::string sq_name(int sq);  // "e4"

struct Move {  // flags byte uses ChessMG/surge encoding, opaque outside board.cpp
    uint8_t from, to, flags;
    bool is_capture() const;
    bool is_double_push() const;
    bool is_ep() const;
    std::optional<PieceType> promotion() const;
    std::string uci() const;  // "e2e4", "e7e8q"
};

}  // namespace hm
