# Table format v4 — measured recommendation

Date: 2026-08-07
Status: **recommendation, measured but not approved.** Backward compatibility
is explicitly not a constraint (a migration script converts the corpus), so
this is free to propose a clean break.
Origin: format review of 2026-08-07. Supersedes the "out of scope" list in
`2026-08-02-block-compression-design.md` where the numbers below contradict it.

## Method

`KRvkbn` (full file, 484.5 MB, 5 pieces) and `KBvkqrb` (4 × 48 MiB samples
per plane at 10/35/60/85% depth, 6 pieces), read-only from `~/tb/raw`. Every
candidate compressed **block-independently at 64 KiB / zstd level 3**, exactly
as the v3 writer does — a single stream would overstate every result.

## The finding that reorders everything

**The count planes are 72–82% of the compressed file. The DTM planes are
18–28%.**

| plane | `KRvkbn` | `KBvkqrb` |
|---|---|---|
| `dtm_wtm` | 6.60 MB (8.9%) | 16.07 MB (17.5%) |
| `dtm_btm` | 6.73 MB (9.1%) | 10.00 MB (10.9%) |
| `cnt_wtm` | **30.63 MB (41.3%)** | **40.86 MB (44.4%)** |
| `cnt_btm` | **30.12 MB (40.7%)** | **25.04 MB (27.2%)** |
| total | 74.08 MB (6.54×) | 91.96 MB (8.76×) |

DTM compresses 12–20×; counts only 4–8×. Every optimisation aimed at the DTM
byte — bit-packing it, halving its alphabet, filling its sentinels — is
working on a fifth of the file. **The solution count is the format's
expensive field, and nobody has been optimising it.**

## Recommended: format v4

### 1. `COUNT_SAT` 255 → 63 (or 15). The whole ballgame.

Measured sweep, effect on the **whole file**:

| `COUNT_SAT` | `KRvkbn` | `KBvkqrb` |
|---|---|---|
| 127 | −19.1% | −13.0% |
| **63** | **−34.5%** | **−24.3%** |
| 31 | −46.1% | −34.2% |
| **15** | **−54.5%** | **−42.7%** |
| 7 | −60.6% | −49.7% |
| 3 | −65.1% | −56.0% |

Context: the field is *already* lossy for most of the corpus — across all 98
sidecars, 48–97% of solvable cells are saturated at 255 today (`KBvkqrb`
65.2%, `KBvkqrn` 85.5%, `KBvkp` 94.8%). Lowering the ceiling moves a
threshold that is already there.

**This is the one genuinely semantic decision in the whole proposal, and it
is the user's call**, because the saturation value is also what
`Tablebase::mine` uses to decide a position's solutions cannot be enumerated
exhaustively (`tablebase.cpp:225,238,282`). At `SAT=63`, positions with 64+
optimal solutions become non-enumerable where today the bar is 255. That is
almost certainly harmless — nobody enumerates 64 optimal solutions of a
helpmate by hand — but at `SAT=15` it starts to bite, and the theme-mining
scan would skip visibly more positions.

**Recommendation: `SAT=63`.** −24% to −35% of the corpus for a limit no
composition query realistically reaches. `SAT=15` is on the table if the
extra ~20 points matter more than enumerability between 16 and 63.

### 2. Merge `DTM_INVALID` into `DTM_UNSOLVABLE` on write. Free.

Grep confirms **no on-disk reader distinguishes 254 from 255** — only
`src/packages/cli/main.cpp:542` reads them and it treats both identically;
`tablebase.cpp:96` maps `dtm > DTM_MAX` to `nullopt`; the sidecar's
invalid/unsolvable split is computed in RAM during generation, never read
back. Writing one sentinel instead of two costs nothing and measures −0.0%
(`KRvkbn`, which has almost no unsolvable cells) to **−4.3%** (`KBvkqrb`,
34% unsolvable).

The one consumer to fix: `helpmate compact`'s retroactive marker path
(`main.cpp:566-590`) re-synthesises stats by scanning and would need to
recompute the split rather than read it off the bytes.

### 3. Split the count planes into a companion file.

Not a byte saving — a *distribution* saving. With counts at 72–82% of the
payload, a DTM-only table is roughly a fifth the size. `mine --dtm`,
`--theme` and the whole probe path for mate distance need no count bytes at
all. Publishing `<Material>.hm` + optional `<Material>.cnt` lets a user pull
2.5 GB instead of 14 GB of corpus when they do not need solution counts.

This also removes the two-block cold probe (§6).

### 4. Optionally: a "slim" btm-only distribution variant.

`dtm_wtm(p) = 1 + min over White's legal moves of dtm_btm(child)`, counts
summed over the minimising branches — the wtm planes are a one-ply minimax
away, and they are the *expensive* ones (`cnt_wtm` alone is 44% of
`KBvkqrb`'s compressed bytes). Dropping them measures **5.0× (`KBvkqrb`) to
5.6× (`KRvkbn`) smaller than today**, combined with §1 and §2.

The cost is real and lands exactly where the goal was speed: a wtm probe
becomes move-gen plus up to ~40 child probes, and `mine` over wtm positions
becomes impractical. So **not the default** — but the right shape for the
Hugging Face dataset, in the way Syzygy ships WDL separately from DTZ. Keep
full tables locally, publish slim ones, and let `helpmate-tables pull`
choose.

## Recommended against — all measured, not argued

### Bit-packing the four fields. It loses.

The intuition is sound — `max_dtm` across all 98 tables never exceeds 34
against a reserved `DTM_MAX` of 252, and parity is implicit, so the real DTM
alphabet is `d/2 ∈ 0..17`, five bits. But compressed:

| layout | `KRvkbn` | `KBvkqrb` |
|---|---|---|
| four separate byte planes (recommended) | baseline | baseline |
| interleaved `(dtm,count)` pairs | **+22.5%** | **+16.0%** |
| packed 4×6 bits = 3 B/cell | **+41.0%** | **+27.6%** |
| packed 4×7 bits = 3.5 B/cell | **+63.0%** | **+53.7%** |

Raw shrinks 25% (or 12.5%); compressed *grows* by more. Packing interleaves
four different distributions into one record and destroys the homogeneous
runs zstd lives on. The 3.5-byte variant is worse still because two cells per
seven bytes breaks the alignment period.

Where it *is* right: **generation RAM**, which has no compressor. 3 bytes per
cell takes a 7-piece resident plane from 1.98 TB to 1.49 TB. That belongs to
v0.9's out-of-core work, not to the on-disk format.

### Halving the DTM alphabet (`d/2`). Zero effect.

−0.0% to −0.1%. zstd already models the parity structure; there is nothing
left to extract by hand.

### Don't-care filling of invalid cells. Not worth what it breaks.

This was my headline candidate before measuring, on the Syzygy analogy. It
delivers −50.5% of the DTM planes on `KRvkbn` but only −1.5% on `KBvkqrb`,
which is −9.1% and −0.4% of the whole file respectively — because the DTM
planes are the cheap fifth.

And it is not free: `mine` currently skips invalid cells by reading one byte.
Filling them means the scan must decode the cell and run a legality test
instead, on every one of 7.75e9 cells. Trading `mine`'s cheap skip for a
single-digit size gain is a bad deal. **Rejected.**

### Falling-factorial / combinatorial indexing. Confirmed dead for disk.

Recomputed: 7,751,073,792 → 6,185,385,360 cells for `KBvkqrb` (**1.25×**),
1.55× at 8 pieces. The cells it removes are constant sentinel bytes that
compress to nothing, which is why the 2026-08-02 spike measured 3.5%. It is a
generation-RAM question for v0.9, not a disk one.

## Projected effect

Measured multipliers, applied to a corpus of 253.8 GB raw (~29.8 GB at
today's 8.51×):

| | multiplier vs v3 | corpus |
|---|---|---|
| today (v3) | 1.00× | ~29.8 GB |
| **v4: merge + `SAT=63`** | **1.40–1.53×** | **~20 GB** |
| v4 with `SAT=15` | 1.89–2.20× | ~14 GB |
| slim variant (btm only, `SAT=15`) | 5.04–5.55× | ~6 GB |

## Separately: the `mine --count` 6.5× is not a format problem

Two structural suspects the existing notes do not name:

1. DTM and count live `2·plane_size` apart, so a cold probe costs **two**
   block decompressions. §3's file split removes this.
2. `--count` triggers *random* enumeration probing where every byte goes
   through `BlockCache::byte_at` — a mutex acquire plus a memcpy **per byte**.
   `mine` without `--count` is only +14%; single `probe` is +9%. The
   asymmetry points here, not at block size.

`TableReader::read_range` (`table_file.cpp:596-636`) already exists and is
the fix shape. This should be tried before any format change, since it is
independent of all of the above.

## Header hygiene to fold into v4

- `symmetry` (offset 9) is written by all four writers and **read by nobody**.
  Either validate it against the material name or drop it.
- A marker is defined by `flags` bit 0, **not** by `version` — a `version==1`
  file with the flag set is accepted as a marker. Tighten or drop v2.
- `reserved[9]` is zeroed on write but never verified on read, so it cannot
  serve as a forward-compat guard. Check it.
- v3 tolerates trailing bytes after the last block; v1 demands an exact size.
- `codec`/`block_size` are unvalidated on v1/v2.
- v1 raw tables have **no corruption detection at all**; only v3 gets zstd's
  per-block XXH64. If v4 is compressed-only, this resolves itself.
- `max_dtm` is a `uint8` using 255 as a sentinel, so it can never record a
  genuine max of 253–255. Harmless given `DTM_MAX = 252`, but the corpus
  maximum is 34 — the field has 7× more headroom than has ever been used.

## Reproducing

`spike.py` / `spike2.py` in the session scratchpad. Read-only against
`~/tb/raw`; nothing was written outside `/tmp`. Both run under
`taskset -c 0-3`.
