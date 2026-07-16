"""Service for generating summary from static analysis findings."""

from typing import Dict, List

from ..models.finding import Finding
from ..core.logging_config import logger


class ReviewSummaryService:
    """Generate summary statistics from findings.
    
    Aggregates findings by severity level and provides summary counts.
    """

    @staticmethod
    def generate_summary(findings: List[Finding]) -> Dict[str, int]:
        """Generate severity summary from findings.
        
        Args:
            findings: List of findings from all analyzers
            
        Returns:
            Dictionary with counts per severity level:
            {
                "critical": int,
                "high": int,
                "medium": int,
                "low": int,
                "info": int,
            }
        """
        summary = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }

        for finding in findings:
            severity = finding.severity or "info"
            if severity in summary:
                summary[severity] += 1
            else:
                # Unknown severity defaults to 'info'
                logger.warning(
                    "Unknown severity level",
                    extra={"severity": severity, "rule_id": finding.rule_id},
                )
                summary["info"] += 1

        logger.info(
            "Review summary generated",
            extra={
                "total_findings": len(findings),
                "summary": summary,
            },
        )

        return summary
