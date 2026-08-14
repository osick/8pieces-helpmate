from math import comb
KK_PAWNLESS, KK_PAWNS = 462, 1806
BYTES_PER_CELL = 4          # 4 planes x 1 byte: dtm_wtm, dtm_btm, cnt_wtm, cnt_btm
NONKING = 4                 # 6 pieces = 2 kings + 4 others
KINDS, PAWN_KINDS = 10, 2   # {Q,R,B,N,P} x {white,black}; P and p are the pawns

rows, total, tables = [], 0, 0
for k in range(NONKING + 1):                       # k = number of pawns
    n = (k + 1) * comb(NONKING - k + (KINDS - PAWN_KINDS) - 1, KINDS - PAWN_KINDS - 1)
    kk = KK_PAWNS if k else KK_PAWNLESS
    cells = kk * (48 ** k) * (64 ** (NONKING - k))
    size = cells * BYTES_PER_CELL
    rows.append((k, n, size, n * size))
    total += n * size; tables += n

print(f"{'pawns':>5} {'tables':>7} {'per table':>12} {'subtotal':>12}  share")
for k, n, size, sub in rows:
    print(f"{k:>5} {n:>7} {size/1e9:>9.1f} GB {sub/1e12:>9.2f} TB  {100*sub/total:5.1f}%")
print(f"\n{tables} tables, {total/1e12:.1f} TB raw ({total/2**40:.1f} TiB)")
for name, r in (("measured KBvkqrb", 9.27), ("corpus avg", 8.51), ("worst measured", 6.53)):
    print(f"  compressed at {r:>5.2f}x ({name:<16}): {total/r/1e12:6.2f} TB")
print(f"\nsanity: pawnless 6-piece = {rows[0][2]/2**30:.2f} GiB/table vs 29G measured on disk")
