from collections.abc import AsyncIterator

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str
    provider: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)


class InferenceResponse(BaseModel):
    provider: str
    model: str
    output: str


class StreamChunk(BaseModel):
    provider: str
    model: str
    delta: str
    done: bool = False


StreamResult = AsyncIterator[StreamChunk]
