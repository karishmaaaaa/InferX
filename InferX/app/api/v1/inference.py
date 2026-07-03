from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.routing.queue import PriorityRequestQueue
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.auth import AuthenticatedAccount, require_api_key

router = APIRouter(prefix="/v1", tags=["inference"])


def get_request_queue(request: Request) -> PriorityRequestQueue:
    return request.app.state.request_queue


@router.post("/generate", response_model=InferenceResponse)
async def generate(
    inference_request: InferenceRequest,
    account: Annotated[AuthenticatedAccount, Depends(require_api_key)],
    queue: Annotated[PriorityRequestQueue, Depends(get_request_queue)],
) -> InferenceResponse:
    return await queue.submit(inference_request, account)
