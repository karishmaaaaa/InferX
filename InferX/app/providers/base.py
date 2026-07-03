from abc import ABC, abstractmethod

from app.schemas.inference import InferenceRequest, InferenceResponse, StreamResult
from app.schemas.providers import ProviderHealth


class Provider(ABC):
    name: str

    @abstractmethod
    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: InferenceRequest) -> StreamResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        raise NotImplementedError
