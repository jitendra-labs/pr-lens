"""TypeScript Compiler validation analyzer implementation."""

import asyncio
import os
import re
import signal
import json
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger


class TypeScriptError(Exception):
    """Raised when TypeScript compilation parsing fails."""
    pass


class TypeScriptAnalyzer(Analyzer):
    """Run `tsc` structural compilation checks against verified workspace scopes."""

    def __init__(self, tsc_cmd: str = "npx") -> None:
        """Initialize TypeScriptAnalyzer."""
        super().__init__()
        self.cmd = tsc_cmd
        self.name = "tsc"
        # Regular expression matching classic unformatted tsc terminal logs
        self.line_pattern = re.compile(r"^(.*?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.*)$")

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        """Run type diagnostics parsing loop pipelines."""
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise TypeScriptError("Local repository path is missing or invalid")

        ts_files = [f for f in context.changed_files if f.endswith((".ts", ".tsx"))]
        if not ts_files:
            return {"tool": "tsc", "raw": {}, "findings": []}

        # Check for existing tsconfig.json
        tsconfig_path = os.path.join(repo_path, "tsconfig.json")
        has_config = os.path.exists(tsconfig_path)
        created_fallback = False

        if not has_config:
            logger.info("No tsconfig.json found. Creating temporary standard fallback baseline.")
            try:            
                fallback_config = {
                    "compilerOptions": {
                        "target": "es2022",
                        "module": "commonjs",
                        "strict": True,
                        "noEmit": True,
                        "esModuleInterop": True,
                        "skipLibCheck": True
                    },
                    "files": ts_files
                }
                with open(tsconfig_path, "w", encoding="utf-8") as f:
                    json.dump(fallback_config, f, indent=4)
                created_fallback = True
            except Exception as e:
                logger.warning(f"Failed to write temporary tsconfig.json: {str(e)}")

        # Run with --noEmit so we don't dump temporary validation builds into the workspace
        # We drop direct file targets (*ts_files) here because tsc ignores project configuration structures when explicitly targeted
        cmd = [
            self.cmd, 
            "--yes", 
            "-p", "typescript",
            "tsc", 
            "--project", tsconfig_path,
            "--noEmit", 
            "--pretty", "false"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid  # Group subprocesses for uniform handling on timeouts
            )
            # Enforce a 30-second hard timeout wall
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError as e:
            try:
                # Send SIGKILL to the entire process group instead of just the parent PID
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            logger.error("TypeScript compilation diagnostics timed out after 30 seconds")
            raise TypeScriptError("TypeScript validation timed out") from e
        except Exception as e:
            logger.error("TypeScript compilation diagnostics execution failed", extra={"error": str(e)})
            raise TypeScriptError(f"Failed to execute tsc: {str(e)}") from e
        finally:
            # Guaranteed workspace state preservation
            if created_fallback and os.path.exists(tsconfig_path):
                try:
                    os.remove(tsconfig_path)
                    logger.info("Temporary fallback tsconfig.json cleaned up successfully.")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary tsconfig: {str(e)}")

        # Combine streams for complete line-by-line normalization scans
        raw_output = out.decode(errors="ignore") + "\n" + err.decode(errors="ignore")
        payload = {"stdout": raw_output, "exit_code": proc.returncode}

        # Combine streams for complete line-by-line normalization scans
        # raw_output = out.decode(errors="ignore") + "\n" + err.decode(errors="ignore")
        # payload = {"stdout": raw_output, "exit_code": proc.returncode}

        # # 💡 ADD THIS TEMPORARY DEBUG LOG HERE:
        # logger.info(f"🚨 RAW TSC OUTPUT START:\n{raw_output}\n🚨 RAW TSC OUTPUT END")

        findings = self._normalize(payload, context)
        logger.info(
            "TypeScript compiler diagnostics complete",
            extra={"findings_count": len(findings)},
        )

        return {"tool": "tsc", "raw": payload, "findings": findings}

    def _normalize(self, payload: Dict[str, Any], context: PRContext) -> List[Finding]:
        """Normalize parsed tsc terminal logs line-by-line into structural entities."""
        normalized: List[Finding] = []
        
        # 💡 FIX: Safe check for missing or empty stdout strings
        stdout_str = payload.get("stdout")
        if not stdout_str or not stdout_str.strip():
            return normalized

        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        base_path = os.path.abspath(context.local_repo_path)
        
        for line in stdout_str.splitlines():
            match = self.line_pattern.match(line.strip())
            if not match:
                continue

            file_path = match.group(1).strip()
            line_num = int(match.group(2))
            rule_code = match.group(5).strip()
            message_text = match.group(6).strip()

            abs_file_path = os.path.abspath(os.path.join(base_path, file_path))
            relative_path = os.path.relpath(abs_file_path, base_path).lstrip("./").strip()

            if relative_path not in changed_lines_map:
                continue

            changed_lines = changed_lines_map.get(relative_path, set())
            if line_num not in changed_lines:
                continue

            normalized.append(
                Finding(
                    tool="tsc",
                    file=relative_path,
                    start_line=line_num,
                    end_line=line_num,
                    message=message_text,
                    rule_id=rule_code,
                    severity="high"
                )
            )

        return normalized