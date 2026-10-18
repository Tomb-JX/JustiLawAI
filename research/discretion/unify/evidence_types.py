"""Typed coordinate boundaries. Positions are Python characters, always [start,end)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re


@dataclass(frozen=True)
class SourceSpan:
    text_sha256: str
    start: int
    end: int
    quote: str

    def __post_init__(self):
        if (type(self.start) is not int or type(self.end) is not int
                or not 0 <= self.start < self.end or not isinstance(self.quote, str)
                or len(self.quote) != self.end - self.start or not isinstance(self.text_sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', self.text_sha256)):
            raise ValueError("invalid_original_span")

    @classmethod
    def from_text(cls, text: str, start: int, end: int):
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError("original_span_out_of_bounds")
        return cls(sha256(text.encode('utf-8')).hexdigest(), start, end, text[start:end])

    def verify(self, text: str):
        if (sha256(text.encode('utf-8')).hexdigest() != self.text_sha256
                or text[self.start:self.end] != self.quote):
            raise ValueError("original_span_source_mismatch")

    def to_dict(self):
        return {"coordinate_system": "original-python-char", **asdict(self)}


@dataclass(frozen=True)
class CleanSpan:
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError("invalid_clean_span")


@dataclass(frozen=True)
class SentenceRef:
    id: str
    span: SourceSpan

    def __post_init__(self):
        if not self.id or not isinstance(self.span, SourceSpan):
            raise ValueError("invalid_sentence_reference")
