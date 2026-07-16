"""ESLint code quality analyzer implementation."""

import asyncio
import json
import os
import signal
from typing import Any, Dict, List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger


class EslintError(Exception):
    """Raised when ESLint analysis fails."""
    pass


class EslintAnalyzer(Analyzer):
    """Run ESLint code quality analysis against verified web source files."""

    def __init__(self, eslint_cmd: str = "npx") -> None:
        """Initialize EslintAnalyzer."""
        super().__init__()
        self.cmd = eslint_cmd
        self.name = "eslint"

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        """Run ESLint analysis on changed JS/TS files."""
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise EslintError("Local repository path is missing or invalid")

        target_files = [
            f for f in context.changed_files 
            if f.endswith((".js", ".jsx", ".ts", ".tsx"))
        ]
        if not target_files:
            return {"tool": "eslint", "raw": {}, "findings": []}

        config_files = ["eslint.config.js", "eslint.config.mjs", "eslint.config.cjs"]
        has_config = any(os.path.exists(os.path.join(repo_path, f)) for f in config_files)

        created_fallback = False
        fallback_path = os.path.join(repo_path, "eslint.config.js")

        if not has_config:
            logger.info("No flat configuration file found. Staging functional fallback baseline.")
            try:
                # Minimal working baseline configuration free of leading indentation margins
                baseline_config = """
                export default [
                    {
                        languageOptions: {
                            ecmaVersion: "latest",
                            sourceType: "module"
                        },
                        rules: {
                            "no-eval": "error",
                            "no-console": "warn",
                            "no-debugger": "error",
                            "no-unused-vars": "warn"
                        }
                    }
                ];
                """
                with open(fallback_path, "w", encoding="utf-8") as f:
                    f.write(baseline_config)
                created_fallback = True
            except Exception as e:
                logger.warning(f"Could not generate fallback ESLint config: {str(e)}")

        # Enforce automated confirmation flag
        cmd = [self.cmd, "--yes", "eslint", "-f", "json"] + target_files        

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid  # Assign a process group ID to cleanly kill all nested children
            )
            # Enforce a 30-second hard timeout wall
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError as e:
            try:
                # Terminate the entire process group session tree cleanly
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            logger.error("ESLint analyzer execution timed out after 30 seconds")
            raise EslintError("ESLint run timed out") from e
        except Exception as e:
            logger.error("ESLint execution failed", extra={"error": str(e)})
            raise EslintError(f"Failed to execute ESLint: {str(e)}") from e
        finally:
            # Guaranteed cleanup even if compilation exceptions are thrown or timed out
            if created_fallback and os.path.exists(fallback_path):
                try:
                    os.remove(fallback_path)
                    logger.info("Temporary fallback ESLint configuration cleaned up successfully.")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary config: {str(e)}")

        # ESLint exits with code 1 if lint errors are found; code 2 indicates configuration errors
        if proc.returncode not in (0, 1):
            error_msg = err.decode(errors="ignore")
            logger.error(
                "ESLint failed with error",
                extra={"returncode": proc.returncode, "stderr": error_msg},
            )
            raise EslintError(f"ESLint execution failed: {error_msg}")

        try:
            payload = json.loads(out.decode() or "[]")
        except Exception as e:
            logger.exception("Failed to parse ESLint JSON string payload")
            raise EslintError("Invalid JSON from ESLint") from e

        findings = self._normalize(payload, context)
        logger.info(
            "ESLint analyzer completed",
            extra={"findings_count": len(findings)},
        )

        return {"tool": "eslint", "raw": payload, "findings": findings}

    def _normalize(self, payload: List[Any], context: PRContext) -> List[Finding]:
        """Normalize ESLint raw arrays into unified Findings."""
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: List[Finding] = []
        base_path = os.path.abspath(context.local_repo_path)

        for file_entry in payload:
            file_path = file_entry.get("filePath")
            if not file_path:
                continue

            abs_file_path = os.path.abspath(os.path.join(base_path, file_path))
            relative_path = os.path.relpath(abs_file_path, base_path).lstrip("./").strip()

            if relative_path not in changed_lines_map:
                continue

            changed_lines = changed_lines_map.get(relative_path, set())

            for msg in file_entry.get("messages", []):
                start_line = msg.get("line")
                end_line = msg.get("endLine", start_line)

                if start_line is None:
                    continue

                overlap = any(ln in changed_lines for ln in range(start_line, (end_line or start_line) + 1))
                if not overlap:
                    continue

                # Map ESLint's numerical severity scales (2: error, 1: warning)
                severity = "high" if msg.get("severity") == 2 else "medium"

                normalized.append(
                    Finding(
                        tool="eslint",
                        file=relative_path,
                        start_line=start_line,
                        end_line=end_line or start_line,
                        message=msg.get("message", "Lint formatting anomaly discovered."),
                        rule_id=msg.get("ruleId", "eslint-unknown"),
                        severity=severity
                    )
                )

        return normalized