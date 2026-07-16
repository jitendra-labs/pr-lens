import httpx

from app.github.auth import generate_jwt

# ----- get installation token ----
async def get_installation_token(installation_id: int):
    jwt_token = generate_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }

    # https://api.github.com/app/installations/140377078/access_tokens
    url = (
        f"https://api.github.com/app/installations/"
        f"{installation_id}/access_tokens"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=headers,
        )

    print(response.status_code)
    print(response.text)

    response.raise_for_status()

    return response.json()["token"]


# ----- get repo ----
async def get_repo(
    owner: str,
    repo: str,
    token: str,
):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
        )

    response.raise_for_status()

    return response.json()


# ---- get pr files -----
async def get_pr_files(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/pulls/{pr_number}/files"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
        )

    response.raise_for_status()

    return response.json()