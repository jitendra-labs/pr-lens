"""Severity normalization utilities for different static analysis tools."""

from typing import Optional


# Bandit severity mapping
BANDIT_SEVERITY_MAP = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}

# Semgrep severity mapping
SEMGREP_SEVERITY_MAP = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "info",
}

# Ruff doesn't have severity levels, everything is "low" by default
RUFF_SEVERITY_MAP = {
    "DEFAULT": "low",
}


def normalize_bandit_severity(severity: Optional[str]) -> Optional[str]:
    """Convert Bandit severity to normalized form.
    
    Args:
        severity: Raw severity from Bandit output
        
    Returns:
        Normalized severity (high, medium, low) or None
    """
    if not severity:
        return None
    return BANDIT_SEVERITY_MAP.get(severity.upper(), "low")


def normalize_semgrep_severity(severity: Optional[str]) -> Optional[str]:
    """Convert Semgrep severity to normalized form.
    
    Args:
        severity: Raw severity from Semgrep output
        
    Returns:
        Normalized severity (high, medium, info) or None
    """
    if not severity:
        return None
    return SEMGREP_SEVERITY_MAP.get(severity.upper(), "info")


def normalize_ruff_severity(severity: Optional[str] = None) -> str:
    """Convert Ruff severity to normalized form.
    
    Ruff doesn't report severity levels, so everything defaults to 'low'.
    
    Args:
        severity: Unused, for API consistency
        
    Returns:
        Always returns 'low'
    """
    return "low"


def normalize_severity(tool: str, severity: Optional[str]) -> Optional[str]:
    """Normalize severity based on the analysis tool.
    
    Args:
        tool: Name of the analysis tool (bandit, semgrep, ruff)
        severity: Raw severity from tool output
        
    Returns:
        Normalized severity or None
    """
    if tool == "bandit":
        return normalize_bandit_severity(severity)
    elif tool == "semgrep":
        return normalize_semgrep_severity(severity)
    elif tool == "ruff":
        return normalize_ruff_severity(severity)
    else:
        return severity
