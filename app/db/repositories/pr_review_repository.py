"""Service for managing PR reviews in database."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pr_review import PRReview
from ...core.logging_config import logger


class PRReviewRepositoryError(Exception):
    """Raised when database operation fails."""
    pass


class PRReviewRepository:
    """Service for managing PR review records in database."""

    @staticmethod
    async def get_review(
        session: AsyncSession,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> Optional[PRReview]:
        """Get existing PR review record.

        Args:
            session: AsyncSession instance
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number

        Returns:
            PRReview instance if exists, None otherwise
        """
        try:
            stmt = select(PRReview).where(
                (PRReview.owner == owner)
                & (PRReview.repo == repo)
                & (PRReview.pr_number == pr_number)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "Failed to fetch PR review from database",
                extra={"error": str(e), "owner": owner, "repo": repo, "pr_number": pr_number},
            )
            raise PRReviewRepositoryError(f"Failed to fetch PR review: {str(e)}") from e

    @staticmethod
    async def create_or_update_review(
        session: AsyncSession,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
        github_comment_id: int,
        findings_count: int,
        last_commit_sha: Optional[str] = None,
    ) -> PRReview:
        """Create or update PR review record and persist changes permanently to the database.

        Args:
            session: AsyncSession instance
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            installation_id: GitHub App installation ID
            github_comment_id: GitHub comment ID
            findings_count: Number of findings
            last_commit_sha: Last analyzed commit SHA

        Returns:
            Created or updated PRReview instance populated with DB attributes
        """
        try:
            # Check if review exists
            existing = await PRReviewRepository.get_review(
                session, owner, repo, pr_number
            )

            if existing:
                existing.github_comment_id = github_comment_id
                existing.findings_count = findings_count
                if last_commit_sha is not None:
                    existing.last_commit_sha = last_commit_sha
                
                # 💡 Commit updates to the database
                await session.commit()
                await session.refresh(existing)
                return existing
            else:
                new_review = PRReview(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    installation_id=installation_id,
                    github_comment_id=github_comment_id,
                    findings_count=findings_count,
                    last_commit_sha=last_commit_sha,
                )
                session.add(new_review)
                
                # 💡 Flush and lock down the records into PostgreSQL
                await session.commit()
                await session.refresh(new_review)
                return new_review

        except PRReviewRepositoryError:
            # If the error came from our inner get_review, bubble it up without double rollback
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                "Failed to create or update PR review record",
                extra={"error": str(e), "owner": owner, "repo": repo, "pr_number": pr_number},
            )
            raise PRReviewRepositoryError(f"Failed to create or update PR review: {str(e)}") from e