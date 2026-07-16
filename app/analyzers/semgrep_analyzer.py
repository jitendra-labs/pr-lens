import asyncio
import json
import os
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..core.logging_config import logger
from ..models.finding import Finding
from ..core.severity import normalize_semgrep_severity


class SemgrepError(Exception):
    pass


class SemgrepAnalyzer(Analyzer):
    """Run Semgrep against a local repository and return parsed JSON results.

    Requires the `semgrep` CLI to be installed and available on PATH.
    """

    def __init__(self, semgrep_cmd: str = "semgrep") -> None:
        self.cmd = semgrep_cmd

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise SemgrepError("Local repository path is missing or invalid")

        # Prepare semgrep command; use --json for machine-readable output
        cmd = [self.cmd, "--json", "--config", "auto", repo_path]
        # logger.info("Semgrep analyzer started", extra={"cmd": cmd, "path": repo_path})

        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()

        if proc.returncode not in (0, 1):
            # semgrep returns 1 when findings are present; treat other codes as errors
            logger.error("Semgrep failed", extra={"returncode": proc.returncode, "stderr": err.decode(errors="ignore")})
            raise SemgrepError(f"Semgrep execution failed: {err.decode(errors='ignore')}" )

        try:
            payload = json.loads(out.decode() or "{}")
        except Exception as e:
            logger.exception("Failed to parse semgrep JSON output")
            raise SemgrepError("Invalid JSON from semgrep") from e

        findings = self._normalize(payload, context)
        logger.info("Semgrep analyzer completed", extra={"findings_count": len(findings)})
        logger.info(
            "Semgrep findings",
            extra={
                "findings": [
                    finding.model_dump()
                    for finding in findings
                ]
            }
        )

        return {"tool": "semgrep", "raw": payload, "findings": findings}

    def _normalize(
        self,
        payload: Dict[str, Any],
        context: PRContext
    ) -> List[Finding]:
        # Semgrep emits {'results': [...]}        
        results = payload.get("results") or []
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: list[Finding] = []

        base_path = os.path.abspath(context.local_repo_path)

        for r in results:

            file_path = r.get("path")

            if not file_path:
                continue

            # Force absolute mapping before calculating the relative path difference
            abs_file_path = os.path.abspath(file_path)
            relative_path = os.path.relpath(abs_file_path, base_path)
            relative_path = relative_path.lstrip("./").strip()

            # If the PR did not touch this file at all, skip
            if relative_path not in changed_lines_map:
                continue

            start = r.get("start") or {}
            end = r.get("end") or {}

            start_line = start.get("line")
            end_line = end.get("line")

            # Only include findings that overlap with changed lines
            if start_line is None and end_line is None:
                # No location info — skip for inline-hunk reviews
                continue

            changed_lines = changed_lines_map.get(relative_path, set())
            # If any line in the finding range intersects the changed lines, include it
            overlap = False
            for ln in range(start_line or 0, (end_line or start_line or 0) + 1):
                if ln in changed_lines:
                    overlap = True
                    break
            if not overlap:
                continue

            normalized.append(
                Finding(
                    tool="semgrep",
                    file=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    message=r.get("extra", {}).get("message"),
                    rule_id=r.get("check_id"),
                    severity=normalize_semgrep_severity(r.get("extra", {}).get("severity")),
                )
            )

        return normalized
    
