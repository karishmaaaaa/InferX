import hashlib
import math
import re


class HashingEmbedder:
    """Small local embedding model based on signed hashing over word and char n-grams."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _features(self, text: str) -> list[str]:
        normalized = text.lower().strip()
        words = re.findall(r"[a-z0-9]+", normalized)
        features = [f"w:{word}" for word in words]
        features.extend(f"b:{left}_{right}" for left, right in zip(words, words[1:], strict=False))
        compact = re.sub(r"\s+", " ", normalized)
        features.extend(
            f"c:{compact[index : index + 3]}" for index in range(max(0, len(compact) - 2))
        )
        return features


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vectors must have the same dimensions")
    return sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )
