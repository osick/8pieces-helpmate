#include "generator/generator.h"
#include "indexing/material.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;

TEST_CASE("slice_has_any_mate finds mates only where they exist") {
    // KQvk: the queen mates the bare king cooperatively — mates exist.
    CHECK(slice_has_any_mate(*Material::parse("KQvk")));
    // Bare white king cannot even give check.
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvk")));
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvkq")));
    // King+bishop against king+queen: a queen on the blocking square can always
    // interpose or capture, so no mate position exists (user's KBvk[qr]* class).
    CHECK_FALSE(slice_has_any_mate(*Material::parse("KBvkq")));
    // King+knight against king+bishop does have mates (KNvkb is solvable).
    CHECK(slice_has_any_mate(*Material::parse("KNvkb")));
}
