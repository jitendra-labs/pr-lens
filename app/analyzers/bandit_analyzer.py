"""Bandit security analyzer implementation."""

import asyncio
import json
import os
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger
from ..core.severity import normalize_bandit_severity


class BanditError(Exception):
    """Raised when Bandit analysis fails."""
    pass


class BanditAnalyzer(Analyzer):
    """Run Bandit security analysis against a local repository.
    
    Requires the `bandit` CLI to be installed and available on PATH.
    Bandit is a security linter for Python that finds common security issues.
    """

    def __init__(self, bandit_cmd: str = "bandit") -> None:
        """Initialize BanditAnalyzer.
        
        Args:
            bandit_cmd: Command name or path to bandit executable
        """
        self.cmd = bandit_cmd

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        """Run Bandit analysis on the repository.
        
        Args:
            context: PR context containing repository path and changed files
            
        Returns:
            Dictionary with tool name and findings list
            
        Raises:
            BanditError: If Bandit execution fails
        """
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise BanditError("Local repository path is missing or invalid")

        python_files = [f for f in context.changed_files if f.endswith(".py")]
        if not python_files:           
            return {"tool": "bandit", "raw": {}, "findings": []}

        # Prepare bandit command; use -f json for JSON output
        # -r for recursive, skip .git and venv directories
        cmd = [
            self.cmd,
            "-r",
            "-f",
            "json",
            "-x",
            ".git,venv,.venv,node_modules",
            repo_path,
        ]
        
        # logger.info("Bandit analyzer started", extra={"cmd": cmd, "path": repo_path})

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
        except Exception as e:
            logger.error("Bandit execution failed", extra={"error": str(e)})
            raise BanditError(f"Failed to execute Bandit: {str(e)}") from e

        # Bandit returns 0 or 1 regardless of findings; only treat other codes as errors
        if proc.returncode not in (0, 1):
            error_msg = err.decode(errors="ignore")
            logger.error(
                "Bandit failed with error",
                extra={"returncode": proc.returncode, "stderr": error_msg},
            )
            raise BanditError(f"Bandit execution failed: {error_msg}")

        try:
            payload = json.loads(out.decode() or "{}")
        except Exception as e:
            logger.exception("Failed to parse Bandit JSON output")
            raise BanditError("Invalid JSON from Bandit") from e

        findings = self._normalize(payload, context)
        logger.info(
            "Bandit analyzer completed",
            extra={"findings_count": len(findings)},
        )

        return {"tool": "bandit", "raw": payload, "findings": findings}

    def _normalize(
        self,
        payload: Dict[str, Any],
        context: PRContext,
    ) -> List[Finding]:
        """Normalize Bandit JSON output to Finding objects.
        
        Args:
            payload: Raw JSON output from Bandit
            context: PR context containing changed files
            
        Returns:
            List of Finding objects filtered to changed files
        """
        # Bandit emits {'results': [...], 'metrics': {...}}
        results = payload.get("results") or []
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: List[Finding] = []

        base_path = os.path.abspath(context.local_repo_path)

        for result in results:
            file_path = result.get("filename")

            if not file_path:
                continue

            # Normalize path to match PR changed files
            abs_file_path = os.path.abspath(file_path)
            relative_path = os.path.relpath(abs_file_path, base_path)
            relative_path = relative_path.lstrip("./").strip()

            # Skip findings for files not touched in the PR
            if relative_path not in changed_lines_map:
                continue

            line_range = result.get("line_range", [])
            start_line = result.get("line_number")
            end_line = line_range[-1] if line_range else start_line

            # Only include findings that overlap with changed lines
            if start_line is None and end_line is None:
                continue

            changed_lines = changed_lines_map.get(relative_path, set())
            overlap = False
            for ln in range(start_line or 0, (end_line or start_line or 0) + 1):
                if ln in changed_lines:
                    overlap = True
                    break
            if not overlap:
                continue

            normalized.append(
                Finding(
                    tool="bandit",
                    file=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    message=result.get("issue_text", ""),
                    rule_id=result.get("test_id", ""),
                    severity=normalize_bandit_severity(result.get("issue_severity")),
                )
            )

        return normalized
