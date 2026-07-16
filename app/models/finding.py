from pydantic import BaseModel


class Finding(BaseModel):
    """Unified finding schema across all analyzers."""
    
    tool: str  # semgrep, bandit, ruff
    file: str
    start_line: int | None = None
    end_line: int | None = None
    severity: str | None = None  # critical, high, medium, low, info
    rule_id: str | None = None
    message: str