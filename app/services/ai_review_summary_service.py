"""AI-powered executive summary generation."""

from typing import List

from ollama import AsyncClient

from ..core.logging_config import logger
from ..models.finding import Finding


SUMMARY_SYSTEM_PROMPT = """
You are PRLens, a professional Pull Request review assistant.

You receive findings from static analysis tools.

Your job is to produce an executive review for engineering teams.

Rules:
- Do NOT speculate about product functionality.
- Do NOT describe features added by the PR.
- Do NOT repeat finding messages verbatim.
- Do NOT copy analyzer output.
- Group related findings into themes.
- Focus on overall risk posture.
- Focus on security, reliability, maintainability, and code quality.
- Prioritize Critical, High, and Medium findings.
- Never mention analyzer names.
- Never mention rule IDs.
- Keep response under 120 words.
- Sound concise, professional, and actionable.

Return markdown using EXACTLY this structure:

## 📑 PRLens Executive Summary

### Overall Risk
(2-3 concise sentences)

### Key Risk Themes
- Theme 1
- Theme 2
- Theme 3

### Recommended Priorities
1. Priority 1
2. Priority 2
3. Priority 3
"""


class AISummaryService:
    """Generate executive summaries from analyzer findings."""

    MAX_FINDINGS_FOR_LLM = 25

    def __init__(
        self,
        model_name: str = "qwen2.5:3b",
    ) -> None:
        self.model_name = model_name
        self.client = AsyncClient()

    def _calculate_risk_rating(
        self,
        severity_counts: dict,
    ) -> str:

        if severity_counts.get("critical", 0) > 0:
            return "🚨 Critical"

        if severity_counts.get("high", 0) > 0:
            return "🔴 High"

        if severity_counts.get("medium", 0) > 0:
            return "🟠 Medium"

        return "🟢 Low"

    async def generate_executive_summary(
        self,
        findings: List[Finding],
    ) -> str:
        """
        Generate an executive summary
        from static analysis findings.
        """

        if not findings:
            return (
                "## 📑 PRLens Executive Summary\n\n"
                "### Overall Risk\n"
                "No significant security, reliability, or code quality "
                "risks were identified by the configured analyzers.\n\n"
                "### Key Risk Themes\n"
                "- No major risks detected.\n\n"
                "### Recommended Priorities\n"
                "1. Proceed with normal code review.\n"
                "2. Validate functionality through testing.\n"
                "3. Merge after reviewer approval."
            )

        severity_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }

        for finding in findings:
            severity = (
                finding.severity or "info"
            ).lower()

            if severity in severity_counts:
                severity_counts[severity] += 1

        risk_rating = self._calculate_risk_rating(
            severity_counts
        )

        findings_for_prompt = findings[
            : self.MAX_FINDINGS_FOR_LLM
        ]

        serialized_findings = []

        for finding in findings_for_prompt:
            serialized_findings.append(
                (
                    f"- Severity={finding.severity} "
                    f"File={finding.file} "
                    f"Line={finding.start_line} "
                    f"Rule={finding.rule_id} "
                    f"Issue={finding.message}"
                )
            )

        findings_payload = "\n".join(
            serialized_findings
        )

        user_prompt = f"""
            Risk Rating: {risk_rating}

            Finding Counts

            Critical: {severity_counts["critical"]}
            High: {severity_counts["high"]}
            Medium: {severity_counts["medium"]}
            Low: {severity_counts["low"]}
            Info: {severity_counts["info"]}

            Static Analysis Findings

            {findings_payload}

            Generate the executive summary using ONLY these findings.

            Focus on:
            - root causes
            - recurring risk themes
            - remediation priorities

            Do not repeat finding messages.
            """

        try:
            response = await self.client.generate(
                model=self.model_name,
                system=SUMMARY_SYSTEM_PROMPT,
                prompt=user_prompt,
                options={
                    "temperature": 0.1,
                    "num_predict": 220,
                },
            )

            summary = (
                response.get("response", "")
                .strip()
            )

            if summary:
                return summary

            raise ValueError(
                "Empty response returned from model."
            )

        except Exception as exc:
            logger.error(
                "Failed to generate AI executive summary",
                extra={
                    "error": str(exc),
                },
            )

            return (
                "## 📑 PRLens Executive Summary\n\n"
                "### Overall Risk\n"
                f"Static analysis identified {len(findings)} "
                f"findings requiring review.\n\n"
                "### Key Risk Themes\n"
                "- Security concerns detected.\n"
                "- Code quality issues present.\n"
                "- Additional review recommended.\n\n"
                "### Recommended Priorities\n"
                "1. Resolve High severity findings.\n"
                "2. Review Medium severity findings.\n"
                "3. Re-run analysis before merge."
            )