"""Ruff linting analyzer implementation."""

import asyncio
import json
import os
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger
from ..core.severity import normalize_ruff_severity


class RuffError(Exception):
    """Raised when Ruff analysis fails."""
    pass


class RuffAnalyzer(Analyzer):
    """Run Ruff linting analysis against a local repository.
    
    Requires the `ruff` CLI to be installed and available on PATH.
    Ruff is a fast Python linter written in Rust that covers pycodestyle,
    pyflakes, isort, and many other linting rules.
    """

    def __init__(self, ruff_cmd: str = "ruff") -> None:
        """Initialize RuffAnalyzer.
        
        Args:
            ruff_cmd: Command name or path to ruff executable
        """
        self.cmd = ruff_cmd

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        """Run Ruff analysis on the repository.
        
        Args:
            context: PR context containing repository path and changed files
            
        Returns:
            Dictionary with tool name and findings list
            
        Raises:
            RuffError: If Ruff execution fails
        """
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise RuffError("Local repository path is missing or invalid")

        python_files = [f for f in context.changed_files if f.endswith(".py")]
        if not python_files:          
            return {"tool": "ruff", "raw": {}, "findings": []}

        # Prepare ruff command; use --output-format json for JSON output
        cmd = [
            self.cmd,
            "check",
            "--output-format",
            "json",
            repo_path,
        ]
        
        # logger.info("Ruff analyzer started", extra={"cmd": cmd, "path": repo_path})

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
        except Exception as e:
            logger.error("Ruff execution failed", extra={"error": str(e)})
            raise RuffError(f"Failed to execute Ruff: {str(e)}") from e

        # Ruff returns 0 (no issues) or 1 (issues found); other codes are errors
        if proc.returncode not in (0, 1):
            error_msg = err.decode(errors="ignore")
            logger.error(
                "Ruff failed with error",
                extra={"returncode": proc.returncode, "stderr": error_msg},
            )
            raise RuffError(f"Ruff execution failed: {error_msg}")

        try:
            payload = json.loads(out.decode() or "[]")
        except Exception as e:
            logger.exception("Failed to parse Ruff JSON output")
            raise RuffError("Invalid JSON from Ruff") from e

        findings = self._normalize(payload, context)
        logger.info(
            "Ruff analyzer completed",
            extra={"findings_count": len(findings)},
        )

        return {"tool": "ruff", "raw": payload, "findings": findings}

    def _normalize(
        self,
        payload: List[Dict[str, Any]],
        context: PRContext,
    ) -> List[Finding]:
        """Normalize Ruff JSON output to Finding objects.
        
        Args:
            payload: Raw JSON output from Ruff (array of findings)
            context: PR context containing changed files
            
        Returns:
            List of Finding objects filtered to changed files
        """
        # Ruff emits array of findings directly
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: List[Finding] = []

        base_path = os.path.abspath(context.local_repo_path)

        for result in payload:
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
            
            location = result.get("location", {})
            end_location = result.get("end_location", {})

            start_line = location.get("row")
            end_line = end_location.get("row")

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
                    tool="ruff",
                    file=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    message=result.get("message", ""),
                    rule_id=result.get("code", ""),
                    severity=normalize_ruff_severity(),
                )
            )

        return normalized
