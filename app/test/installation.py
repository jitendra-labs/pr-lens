import asyncio

from app.github.client import (get_installation_token, get_repo, get_pr_files )


async def main():
    token = await get_installation_token(
        140377078
    )

    print('token: ', token)

    repo = await get_repo(
        "Jitendra-cx",
        "zoma-ai-assistant",
        token,
    )

    print('repo: ', repo["full_name"])

    files = await get_pr_files(
        "Jitendra-cx",
        "zoma-ai-assistant",
        3,  # replace with actual PR number
        token,
    )

    print('pr files: ')
    for file in files:
        print(file["filename"])
        print(file.get("patch"))


asyncio.run(main())