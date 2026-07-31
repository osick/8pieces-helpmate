import json as _json
from ._helpmate import Tablebase as _Tablebase, generate, MissingTableError

class Tablebase(_Tablebase):
    def stats(self, material: str) -> dict:
        return _json.loads(self._stats_json(material))

    def mine_with_stats(self, material: str, dtm: int, count: int = -1, max: int = 100,
                        starts: int = -1, ends: int = -1) -> tuple[list, int]:
        """Like mine(), but also returns how many positions were skipped because
        their optimal-line count is saturated (255+) and therefore not enumerable."""
        return self._mine_with_stats(material, dtm, count, max, starts, ends)

__all__ = ["Tablebase", "generate", "MissingTableError"]
