from fastapi import APIRouter, Request

router = APIRouter(prefix="/github", tags=["GitHub"])

@router.post('/webhook')
async def github_webhook(request: Request):
    payload = await request.json()

    print("=" * 50)
    # print("payload: ", payload)

    event = request.headers.get("X-GitHub-Event")

    print("Event:", event)

    print("Action:", payload.get("action"))

    installation = payload.get("installation")

    if installation:
        print("Installation ID:", installation["id"])
    
    repository = payload.get("repository")

    if repository:
        print("Repo:", repository["full_name"])

    # publish_to_queue()
    return {"ok": True}

@router.get('/')
async def test_github():
    return { "sucess": True, "message": "Github route" }