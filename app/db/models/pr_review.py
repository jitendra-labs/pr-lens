"""Database models for PR reviews."""

from datetime import datetime
from sqlalchemy import Integer, String, BigInteger, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..config import Base


class PRReview(Base):    
    __tablename__ = "pr_reviews"

    __table_args__ = (
        UniqueConstraint(
            "owner", "repo", "pr_number",
            name="uq_pr_review"
        ),
    )
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    installation_id: Mapped[int] = mapped_column(BigInteger, index=True)

    owner: Mapped[str] = mapped_column(String(255))
    
    repo: Mapped[str] = mapped_column(String(255), index=True)
    pr_number: Mapped[int] = mapped_column(Integer, index=True)
    
    github_comment_id: Mapped[int] = mapped_column(BigInteger)
    last_commit_sha: Mapped[str | None] = mapped_column(String(100), nullable=True)
    findings_count: Mapped[int] = mapped_column(default=0)    
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Unique constraint on PR
    __table_args__ = (
        UniqueConstraint("owner", "repo", "pr_number", name="uq_pr_reviews_pr"),
    )

    def __repr__(self) -> str:
        return f"<PRReview(owner={self.owner}, repo={self.repo}, pr_number={self.pr_number})>"
