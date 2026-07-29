import json as _json
from ._helpmate import Tablebase as _Tablebase, generate, MissingTableError

class Tablebase(_Tablebase):
    def stats(self, material: str) -> dict:
        return _json.loads(self._stats_json(material))

__all__ = ["Tablebase", "generate", "MissingTableError"]
