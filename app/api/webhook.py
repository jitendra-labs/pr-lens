from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging_config import logger
from ..db.config import get_db_session
from ..github.github_service import GithubService
from ..services.review_service import ReviewService

router = APIRouter(prefix="/webhook", tags=["Webhook"])


def get_github_service() -> GithubService:
    return GithubService()


def get_review_service(
    db_session: AsyncSession = Depends(get_db_session),
    github: GithubService = Depends(get_github_service)
) -> ReviewService:
    return ReviewService(github, db_session)

# Simple signature validation helper placeholder
def verify_github_signature(payload: bytes, signature: str) -> bool:
    # TODO: Implement hmac verification using your GITHUB_WEBHOOK_SECRET
    return True

@router.post("/github")
async def handle_github(
    request: Request, 
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"), 
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    review_service: ReviewService = Depends(get_review_service)
) -> Dict[str, Any]:
    
    raw_body = await request.body()
    payload = await request.json()
    
    if not x_github_event:
        x_github_event = request.headers.get("X-GitHub-Event")
        
    logger.info("Received webhook", extra={"event": x_github_event})

    # Validate webhook origin
    if not verify_github_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Validate Event Type
    if x_github_event != "pull_request":
        raise HTTPException(status_code=400, detail="Unsupported event")

    # Filter relevant actions (Opened or Updated with new code)
    action = payload.get("action")
    if action not in ["opened", "synchronize"]:
        return {"status": "ignored", "action": action}

    # Extract safely with fallbacks
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    owner = repo.get("owner", {}).get("login")

    repo_name = repo.get("name")
    pr_number = pr.get("number")

    installation_id = payload.get("installation", {}).get("id")

    if not all([owner, repo_name, pr_number]):
        raise HTTPException(status_code=422, detail="Missing essential repository or PR payload data")

    # print('headers: ', request.headers)

    # Execute Review Service
    try:
        result = await review_service.run_review(owner, repo_name, pr_number, installation_id)
    except Exception as e:
        logger.exception("Review orchestration failed internally")
        raise HTTPException(status_code=500, detail=str(e))

    logger.info("Handle github success: ", result)
    return {"status": "ok", "result": result}
