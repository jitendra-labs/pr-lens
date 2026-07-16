import asyncio
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

import httpx

from ..core.logging_config import logger
from ..github.auth import generate_jwt


class GithubServiceError(Exception):
    pass


class GithubService:
    """Service encapsulating GitHub API operations needed by PRLens.

    Methods are async and designed to be dependency-injectable.
    """

    def __init__(self, github_api_url: str = "https://api.github.com") -> None:
        self.base_url = github_api_url.rstrip("/")

    async def get_installation_token(self, installation_id: int) -> str:
        """Exchange an app JWT for an installation access token.

        Args:
            installation_id: GitHub App installation id
            app_jwt: A signed JWT for the GitHub App (expiring short-lived)

        Returns:
            installation access token string
        """

        app_jwt = generate_jwt()
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {app_jwt}", 
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        async with httpx.AsyncClient() as client:
            # resp = await client.post(url, headers=headers, timeout=30.0)
            resp = await client.post(
                url,
                headers=headers,
            )

        # print('url: ', url)
        # print('installation_id: ', installation_id)

        # print('access_token resp : ', resp.status_code)
        # print('access_token resp : ', resp.text)

        if resp.status_code != 201:
            logger.error("Failed to get installation token", extra={"status": resp.status_code, "body": resp.text})
            raise GithubServiceError(f"Failed to get installation token: {resp.status_code}")
        
        data = resp.json()
        token = data.get("token")

        if not token:
            raise GithubServiceError("No token in installation response")
        
        return token

    async def get_pr_files(self, owner: str, repo: str, pr_number: int, installation_token: str) -> List[Dict[str, Any]]:
        """Fetch list of changed files for a pull request.

        Returns GitHub's file objects (filename, additions, deletions, patch...)
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        headers = {"Authorization": f"token {installation_token}", "Accept": "application/vnd.github+json"}
        files: List[Dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(url, headers=headers, params={"per_page": 100, "page": page}, timeout=30.0)
                if resp.status_code != 200:
                    logger.error("Failed to fetch PR files", extra={"status": resp.status_code, "body": resp.text})
                    raise GithubServiceError(f"Failed to fetch PR files: {resp.status_code}")
                part = resp.json()
                if not isinstance(part, list):
                    raise GithubServiceError("Unexpected response when fetching PR files")
                files.extend(part)
                if len(part) < 100:
                    break
                page += 1
        return files

    async def create_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        token: str,
    ) -> Dict[str, Any]:
        """Create a GitHub PR comment on the pull request issue thread."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"body": body}, timeout=30.0)

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to create PR comment",
                extra={"status": resp.status_code, "body": resp.text},
            )
            raise GithubServiceError(f"Failed to create PR comment: {resp.status_code}")

        return resp.json()

    async def edit_pr_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        body: str,
        token: str,
    ) -> Dict[str, Any]:
        """Edit an existing GitHub PR comment."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/comments/{comment_id}"
        headers = {
            # "Authorization": f"Bearer {token}",
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Cache-Control": "no-cache, no-store, must-revalidate", # Forces downstream cache clearance
            "Pragma": "no-cache"
        }

        async with httpx.AsyncClient() as client:
            resp = await client.patch(url, headers=headers, json={"body": body}, timeout=30.0)
            # logger.info(
            #     "Edit PR comment response -->",
            #     extra={"status": resp.status_code, "body": resp.text},
            # )

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to edit PR comment",
                extra={"status": resp.status_code, "body": resp.text},
            )
            raise GithubServiceError(f"Failed to edit PR comment: {resp.status_code}")

        return resp.json()

    async def delete_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        review_id: int,
        token: str,
    ) -> None:
        """Delete a pull request review."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=headers, timeout=30.0)

        if resp.status_code not in (200, 204):
            logger.error(
                "Failed to delete PR review",
                extra={"status": resp.status_code, "body": resp.text},
            )
            raise GithubServiceError(f"Failed to delete PR review: {resp.status_code}")

    async def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        comments: List[Dict[str, Any]],
        token: str,
    ) -> Dict[str, Any]:
        """Create a pull request review with inline comments.

        Each comment in `comments` should be a dict with `path`, `position`, and `body` fields.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        payload = {
            "body": "PRLens automated inline review",
            "event": "COMMENT",
            "comments": comments,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=30.0)

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to create pull request review",
                extra={"status": resp.status_code, "body": resp.text},
            )
            raise GithubServiceError(f"Failed to create pull request review: {resp.status_code}")

        return resp.json()

    async def clone_repository(self, owner: str, repo: str, pr_number: int, installation_token: str) -> str:
        """Clone repository into a temporary directory and checkout the PR ref.

        Returns the path to the checked out repository.
        """
        # Create a temporary directory that persists until cleanup by caller
        dest = tempfile.mkdtemp(prefix=f"prlens_{owner}_{repo}_")
        clone_url = f"https://x-access-token:{installation_token}@github.com/{owner}/{repo}.git"

        async def run_cmd(*cmd: str, cwd: Optional[str] = None) -> None:
            logger.debug("Running command: %s", " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            if proc.returncode != 0:
                logger.error("Command failed", extra={"cmd": cmd, "returncode": proc.returncode, "stdout": out.decode(errors="ignore"), "stderr": err.decode(errors="ignore")})
                raise GithubServiceError(f"Command {' '.join(cmd)} failed: {proc.returncode}\n{err.decode(errors='ignore')}")

        try:
            # Shallow clone default branch
            await run_cmd("git", "clone", "--depth", "1", clone_url, dest)
            # Fetch the pull request head and check it out
            await run_cmd("git", "fetch", "origin", f"pull/{pr_number}/head:pr-{pr_number}", cwd=dest)
            await run_cmd("git", "checkout", f"pr-{pr_number}", cwd=dest)
        except Exception:
            # Cleanup partial clone on failure
            try:
                shutil.rmtree(dest)
            except Exception:
                logger.exception("Failed to clean up temporary repo directory")
            raise

        return dest
