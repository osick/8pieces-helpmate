#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include <string>

namespace hm {

// SAN for a legal move `m` of `b`, including check/mate suffix.
// `b` is restored to its original position before returning.
std::string san(Board& b, const Move& m);

}  // namespace hm
