#pragma once
#include "chess/types.h"
#include <memory>
#include <vector>

namespace hm {

class Board {  // pimpl over surge Position; copyable
public:
    Board();
    Board(const Board&);
    Board& operator=(const Board&);
    ~Board();

    static std::optional<Board> from_fen(const std::string&);  // nullopt on parse error or castling rights
    static Board from_pieces(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);
    void reset(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);  // reuse allocation

    std::string fen() const;
    Color stm() const;
    int ep_square() const;  // -1 if none
    std::vector<PlacedPiece> pieces() const;
    bool in_check() const;             // side to move
    bool opponent_in_check() const;    // true => position illegal
    PosState state() const;            // for side to move
    std::vector<Move> legal_moves() const;
    void make(const Move&);
    void unmake(const Move&);
    uint64_t perft(int depth);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hm
