"""Gitleaks security analyzer implementation."""

import asyncio
import json
import os
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger


class GitleaksError(Exception):
    """Raised when Gitleaks analysis fails."""
    pass


class GitleaksAnalyzer(Analyzer):
    """Run Gitleaks security analysis against a local repository.
    
    Requires the `gitleaks` CLI to be installed and available on PATH.
    Finds secrets, API keys, and hardcoded passwords.
    """

    def __init__(self, gitleaks_cmd: str = "gitleaks") -> None:
        """Initialize GitleaksAnalyzer.
        
        Args:
            gitleaks_cmd: Command name or path to gitleaks executable
        """
        self.cmd = gitleaks_cmd

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        """Run Gitleaks analysis on the repository."""
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise GitleaksError("Local repository path is missing or invalid")

        # Gitleaks scans everything, but if no files changed in the PR, skip early
        if not context.changed_files:
            return {"tool": "gitleaks", "raw": {}, "findings": []}

        report_path = os.path.join(repo_path, "gitleaks_report.json")
        
        cmd = [
            self.cmd,
            "detect",
            "--source", repo_path,
            "--report-format", "json",
            "--report-path", report_path,
            "--no-git"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
        except Exception as e:
            logger.error("Gitleaks execution failed", extra={"error": str(e)})
            raise GitleaksError(f"Failed to execute Gitleaks: {str(e)}") from e

        # Gitleaks exits with code 0 (no leaks) or 1 (leaks found). Others are true errors.
        if proc.returncode not in (0, 1):
            error_msg = err.decode(errors="ignore")
            logger.error(
                "Gitleaks failed with error",
                extra={"returncode": proc.returncode, "stderr": error_msg},
            )
            raise GitleaksError(f"Gitleaks execution failed: {error_msg}")

        payload = []
        if os.path.exists(report_path) and os.path.getsize(report_path) > 0:
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:
                logger.exception("Failed to parse Gitleaks JSON report")
                raise GitleaksError("Invalid JSON from Gitleaks") from e

        findings = self._normalize(payload, context)
        logger.info(
            "Gitleaks analyzer completed",
            extra={"findings_count": len(findings)},
        )

        return {"tool": "gitleaks", "raw": payload, "findings": findings}

    def _normalize(self, payload: List[Any], context: PRContext) -> List[Finding]:
        """Normalize Gitleaks JSON arrays to Finding objects."""
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: List[Finding] = []
        base_path = os.path.abspath(context.local_repo_path)

        for result in payload:
            file_path = result.get("File")
            if not file_path:
                continue

            abs_file_path = os.path.abspath(file_path)
            relative_path = os.path.relpath(abs_file_path, base_path).lstrip("./").strip()

            if relative_path not in changed_lines_map:
                continue

            start_line = result.get("StartLine", 1)
            end_line = result.get("EndLine", start_line)

            changed_lines = changed_lines_map.get(relative_path, set())
            overlap = any(ln in changed_lines for ln in range(start_line, end_line + 1))
            if not overlap:
                continue

            normalized.append(
                Finding(
                    tool="gitleaks",
                    file=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    message=f"Secret detected: {result.get('Description', 'Sensitive rule match')}.",
                    rule_id=result.get("RuleID", "secret-leak"),
                    severity="critical"  # Secrets are universally treated as critical
                )
            )

        return normalized