from __future__ import annotations

from pathlib import Path


class ValidationPolicy:
    DEFAULT_POLICY = (
        "(No policy file found. Evaluate against software engineering best practices.)"
    )

    def __init__(self, path: Path) -> None:
        self._path = path
        self._text: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> "ValidationPolicy":
        return cls(path)

    def load(self) -> str:
        if self._text is None:
            if self._path.exists():
                self._text = self._path.read_text(encoding="utf-8").strip()
            else:
                self._text = self.DEFAULT_POLICY
        return self._text

    def reload(self) -> str:
        self._text = None
        return self.load()
