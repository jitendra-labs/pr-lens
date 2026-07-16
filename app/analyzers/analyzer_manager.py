"""Manager for orchestrating multiple static analysis tools."""

from typing import List

from .analyzer import Analyzer
from ..models.pr_context import PRContext
from ..models.finding import Finding
from ..core.logging_config import logger


class AnalyzerManagerError(Exception):
    """Raised when analyzer manager fails."""
    pass


class AnalyzerManager:
    """Orchestrates execution of multiple analyzers.
    
    Responsibilities:
    - Register and execute analyzers sequentially
    - Aggregate findings from all analyzers
    - Continue execution if one analyzer fails
    - Log failures without stopping pipeline
    - Return unified list of findings
    """

    def __init__(self, analyzers: List[Analyzer]) -> None:
        """Initialize AnalyzerManager.
        
        Args:
            analyzers: List of analyzer instances to execute
        """
        self.analyzers = analyzers

    async def execute(self, context: PRContext) -> List[Finding]:
        """Execute all registered analyzers and aggregate findings.
        
        This method:
        1. Runs each analyzer sequentially
        2. Aggregates findings from all tools
        3. Continues execution if an analyzer fails
        4. Logs all failures for debugging
        
        Args:
            context: PR context with repository info and changed files
            
        Returns:
            Unified list of all findings from all analyzers
        """
        all_findings: List[Finding] = []
        failed_analyzers: List[str] = []

        for analyzer in self.analyzers:
            analyzer_name = analyzer.__class__.__name__
            
            try:
                logger.info(f"{analyzer_name} started")
                result = await analyzer.analyze(context)
                findings = result.get("findings", [])
                all_findings.extend(findings)
                logger.info(
                    f"{analyzer_name} completed successfully",
                    extra={"findings_count": len(findings)},
                )
            except Exception as e:
                failed_analyzers.append(analyzer_name)
                logger.error(
                    f"{analyzer_name} failed",
                    extra={"error": str(e), "error_type": type(e).__name__},
                )
                # Continue with next analyzer instead of failing
                continue

        if failed_analyzers:
            logger.warning(
                "Some analyzers failed",
                extra={"failed_analyzers": failed_analyzers},
            )

        logger.info(
            "All analyzers completed",
            extra={
                "total_findings": len(all_findings),
                "failed_count": len(failed_analyzers),
            },
        )

        return all_findings
