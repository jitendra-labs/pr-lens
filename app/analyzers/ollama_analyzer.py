"""Ollama code intelligence analyzer layer matching core pipeline patterns."""

import json
import os
from typing import Any, Dict, List
from ollama import AsyncClient

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger


class OllamaError(Exception):
    """Raised when local Ollama inference fails."""
    pass


class OllamaAnalyzer(Analyzer):
    """Run Ollama locally against a repository using Qwen2.5-Coder for logical reviews."""

    def __init__(self, model_name: str = "qwen2.5-coder:7b") -> None:
        self.model_name = model_name
        self.client = AsyncClient()
        
        # Enforce strict uniform output from the model
        self.system_prompt = (
            "You are an expert Senior Backend Engineer and Security Reviewer.\n"
            "Analyze the provided code changes carefully. Look for critical logic bugs, leaks, "
            "edge-cases, concurrency race conditions, or bad architectural patterns.\n"
            "Return your analysis ONLY as a raw JSON array of objects. Do not wrap it in markdown code blocks "
            "like ```json. Do not include introductory text.\n"
            "Each object must exactly match this structure:\n"
            "[\n"
            "  {\n"
            '    "file": "string (filename)",\n'
            '    "line": integer (specific line number containing the issue),\n'
            '    "severity": "string (either \'high\', \'medium\', or \'low\')",\n'
            '    "message": "string (concise explanation of the bug and how to refactor it)"\n'
            "  }\n"
            "]\n"
            "If the code looks perfect and has no logical issues, return an empty array: []"
        )

    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        repo_path = context.local_repo_path
        if not repo_path or not os.path.isdir(repo_path):
            raise OllamaError("Local repository path is missing or invalid")

        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        if not changed_lines_map:
            return {"tool": f"ollama-{self.model_name}", "raw": [], "findings": []}

        raw_payloads = []
        all_issues = []

        # Process each changed file sequentially just like Semgrep loops over targets
        for relative_path in changed_lines_map.keys():
            # Skip media or configuration lock noise
            if any(relative_path.endswith(ext) for ext in [".lock", ".json", ".md", ".png", ".jpg"]):
                continue

            full_file_path = os.path.join(repo_path, relative_path)
            if not os.path.exists(full_file_path):
                continue

            try:
                # Read the actual file contents to give the LLM clear context
                with open(full_file_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_content = f.read()

                user_prompt = (
                    f"Analyze the content of the file '{relative_path}' keeping mind the PR line diff limits.\n"
                    f"File Content:\n{file_content}"
                )

                # Fire async local inference loop
                response = await self.client.generate(
                    model=self.model_name,
                    system=self.system_prompt,
                    prompt=user_prompt,
                    options={
                        "temperature": 0.0,
                        "num_ctx": 8192
                    }
                )
                
                raw_output = response.get("response", "").strip()
                raw_payloads.append({"file": relative_path, "response": raw_output})

                # Sanitize potential code-block markdown wraps
                if raw_output.startswith("```json"):
                    raw_output = raw_output[7:].rstrip("```").strip()
                elif raw_output.startswith("```"):
                    raw_output = raw_output[3:].rstrip("```").strip()

                if not raw_output or raw_output == "[]":
                    continue

                parsed = json.loads(raw_output)
                if isinstance(parsed, list):
                    all_issues.extend(parsed)

            except json.JSONDecodeError:
                logger.warning("Ollama output failed to parse into valid JSON matrix format", extra={"file": relative_path})
            except Exception as e:
                logger.error("Ollama item file scanning error exception encountered", extra={"error": str(e), "file": relative_path})
                raise OllamaError(f"Ollama execution failed: {str(e)}") from e

        # Normalize and filter findings using your exact diff-line mapping rules
        findings = self._normalize(all_issues, context)
        
        logger.info(f"Ollama-{self.model_name} analyzer completed", extra={"findings_count": len(findings)})
        logger.info(
            f"Ollama-{self.model_name} findings",
            extra={"findings": [finding.model_dump() for finding in findings]}
        )

        return {"tool": f"ollama-{self.model_name}", "raw": raw_payloads, "findings": findings}

    def _normalize(self, raw_issues: List[Dict[str, Any]], context: PRContext) -> List[Finding]:
        changed_lines_map = getattr(context, "changed_lines_map", {}) or {}
        normalized: List[Finding] = []

        for issue in raw_issues:
            file_path = issue.get("file")
            if not file_path:
                continue

            # Clean path format matching Semgrep adjustments
            clean_relative_path = file_path.lstrip("./").strip()

            # Ensure the file belongs to the current PR change matrix
            if clean_relative_path not in changed_lines_map:
                continue

            target_line = issue.get("line")
            if target_line is None:
                continue

            # Strict hunk alignment filter: only include findings if they intersect lines changed in the PR
            changed_lines = changed_lines_map.get(clean_relative_path, set())
            if target_line not in changed_lines:
                continue

            normalized.append(
                Finding(
                    tool=f"ollama-{self.model_name}",
                    file=clean_relative_path,
                    start_line=target_line,
                    end_line=target_line,
                    message=issue.get("message"),
                    rule_id="cognitive-logic-flaw",
                    severity=issue.get("severity", "medium").lower(),
                )
            )

        return normalized