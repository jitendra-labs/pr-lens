import os
import shutil
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from ..github.github_service import GithubService, GithubServiceError
from ..analyzers.analyzer_manager import AnalyzerManager, AnalyzerManagerError
from ..analyzers.semgrep_analyzer import SemgrepAnalyzer
from ..analyzers.bandit_analyzer import BanditAnalyzer
from ..analyzers.ruff_analyzer import RuffAnalyzer
from ..analyzers.gitleaks_analyzer import GitleaksAnalyzer
from ..analyzers.eslint_analyzer import EslintAnalyzer
from ..analyzers.typescript_analyzer import TypeScriptAnalyzer
from ..models.pr_context import PRContext
from ..core.logging_config import logger
from ..services.review_formatter import ReviewFormatter
from ..services.review_summary_service import ReviewSummaryService
from ..services.ai_review_summary_service import AISummaryService
from ..db.repositories.pr_review_repository import PRReviewRepository, PRReviewRepositoryError
from .explanation_service import AIExplanationService


class ReviewServiceError(Exception):
    pass


class ReviewService:
    def __init__(self, github_service: GithubService, db_session: AsyncSession) -> None:
        self.github = github_service
        self.db_session = db_session
        # Initialize analyzer manager with all supported analyzers
        self.analyzer_manager = AnalyzerManager(
            analyzers=[
                SemgrepAnalyzer(),
                BanditAnalyzer(),
                RuffAnalyzer(),
                GitleaksAnalyzer(),
                EslintAnalyzer(),
                TypeScriptAnalyzer(),
            ]
        )
        self.summary_service = ReviewSummaryService()
        self.ai_summary_service = AISummaryService(model_name="qwen2.5:3b")
        self.explanation_service = AIExplanationService(
            ollama_model="qwen2.5:3b",
            gemini_model="gemini-2.5-flash",
        )
        self.formatter = ReviewFormatter()
        self.pr_review_repository = PRReviewRepository()

    async def run_review(self, owner: str, repo: str, pr_number: int, installation_id: int) -> dict:
        """Run the full review pipeline for a PR and return unified findings.

        Steps:
        - Exchange app JWT for installation token
        - Fetch changed files
        - Clone repo and checkout PR
        - Run all analyzers concurrently
        - Generate automated markdown report summaries
        - Return normalized findings and summary metrics
        """
        ctx = PRContext(owner=owner, repo=repo, pr_number=pr_number, installation_id=installation_id)

        comment_id = None
        comment_url = None
        comment_posted = False
        findings = []
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        
        try:
            existing_review = await self.pr_review_repository.get_review(
                session=self.db_session,
                owner=owner,
                repo=repo,
                pr_number=pr_number
            )
            if existing_review:
                logger.info(
                    "Found existing historical review record for PR", 
                    extra={"github_comment_id": existing_review.github_comment_id}
                )
        except PRReviewRepositoryError:
            logger.warning("Failed to look up historical PR review records")
            await self.db_session.rollback()

        try:
            token = await self.github.get_installation_token(installation_id)
        except GithubServiceError as e:
            logger.exception("Failed to get installation token")
            raise ReviewServiceError("Failed to get installation token") from e

        try:
            files = await self.github.get_pr_files(owner, repo, pr_number, token)
        except GithubServiceError as e:
            logger.exception("Failed to fetch PR files")
            raise ReviewServiceError("Failed to fetch PR files") from e

        ctx.changed_files = [f.get("filename") for f in files if f.get("filename")]
        
        # Parse patch hunks to compute changed line numbers and diff positions
        changed_lines_map = {}
        line_position_map = {}

        for f in files:
            filename = f.get("filename")
            patch = f.get("patch")
            if not filename or not patch:
                continue

            pos = 0
            cur_new = None
            changed_lines = set()
            pos_map = {}

            for raw in patch.splitlines():
                if raw.startswith("@@"):
                    try:
                        header = raw.split("@@")[1].strip()
                        parts = header.split(" ")
                        new_part = [p for p in parts if p.startswith("+")][0]
                        if "," in new_part:
                            start = int(new_part.lstrip("+").split(",")[0])
                        else:
                            start = int(new_part.lstrip("+"))
                        cur_new = start
                    except Exception:
                        cur_new = None
                    continue

                if raw.startswith("+"):
                    pos += 1
                    if cur_new is not None:
                        pos_map[cur_new] = pos
                        changed_lines.add(cur_new)
                        cur_new += 1
                    continue
                if raw.startswith("-"):
                    pos += 1
                    continue
                if raw.startswith(" "):
                    pos += 1
                    if cur_new is not None:
                        pos_map[cur_new] = pos
                        cur_new += 1
                    continue

            if changed_lines:
                changed_lines_map[filename] = changed_lines
            if pos_map:
                line_position_map[filename] = pos_map

        ctx.changed_lines_map = changed_lines_map
        ctx.line_position_map = line_position_map

        logger.info("Files detected in PR", extra={"changed_files": ctx.changed_files})

        try:
            path = await self.github.clone_repository(owner, repo, pr_number, token)
            ctx.local_repo_path = path
        except Exception as e:
            logger.exception("Failed to clone repository")
            raise ReviewServiceError("Failed to clone repository") from e

        try:
            # Run all static code analyzers concurrently
            raw_results = await self.analyzer_manager.execute(ctx)

            # Defensive fallback programming to guarantee an iterable list
            if isinstance(raw_results, dict):
                findings = raw_results.get("findings") or []
            elif isinstance(raw_results, list):
                # If your manager directly aggregates a flat list of findings objects
                findings = raw_results
            else:
                findings = []

            # Filter out findings that sit outside line patches modified in this PR
            filtered_findings = []
            for finding in findings:
                if not finding.file:
                    continue

                changed_lines = ctx.changed_lines_map.get(finding.file)
                if not changed_lines:
                    continue

                target_line = finding.start_line or finding.end_line
                if target_line in changed_lines:
                    filtered_findings.append(finding)

            findings = filtered_findings
            logger.info("Analysis complete", extra={"total_findings": len(findings)})

            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            findings.sort(key=lambda x: severity_order.get((x.severity or "info").lower(), 99))

            # Deduplicate findings sharing identical file coordinates and tool messages
            unique = {}
            for finding in findings:
                key = (finding.file, finding.start_line, str(finding.message))
                if key not in unique:
                    unique[key] = finding

            findings = list(unique.values())

            # Generate statistical summary from the unique findings array
            summary = self.summary_service.generate_summary(findings)

            priority_findings = [
                f for f in findings
                if (f.severity or "").lower() in ["critical", "high", "medium"]
            ][:5]

            # Generate the Architectural Executive Summary using local LLM infrastructure
            executive_summary = await self.ai_summary_service.generate_executive_summary(priority_findings)

            markdown = self.formatter.generate_markdown(
                findings=findings,
                summary=summary,
                executive_summary=executive_summary,
            )

            try:
                if existing_review:
                    comment_response = await self.github.edit_pr_comment(
                        owner=owner,
                        repo=repo,
                        comment_id=existing_review.github_comment_id,
                        body=markdown,
                        token=token
                    )
                else:
                    comment_response = await self.github.create_pr_comment(
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        body=markdown,
                        token=token,
                    )

                comment_url = comment_response.get("html_url")
                comment_id = comment_response.get("id")
                comment_posted = True
                logger.info("GitHub comment posted", extra={"comment_url": comment_url})
            except GithubServiceError as e:
                logger.error("GitHub comment failed", extra={"error": str(e)})
                comment_posted = False

            # Determine commit SHA from the checked-out workspace safely using an explicit execution timeout
            commit_id = None
            if ctx.local_repo_path and os.path.exists(ctx.local_repo_path):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        'git', 'rev-parse', 'HEAD', 
                        cwd=ctx.local_repo_path, 
                        stdout=asyncio.subprocess.PIPE, 
                        stderr=asyncio.subprocess.PIPE
                    )
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                    if proc.returncode == 0:
                        commit_id = out.decode().strip()
                except Exception:
                    logger.warning("Failed to resolve HEAD commit SHA within checkout path")
                    commit_id = None

            # Generate Deep AI Explanations for touched lines
            inline_comments = []
            max_inline = 10
            MAX_AI_EXPLANATIONS = 5
            
            # Filter valid inline findings and deduplicate by file + line mapping
            unique_line_findings = {}
            for f in findings:
                if len(unique_line_findings) >= max_inline:
                    break
                if not f.file or not (f.start_line or f.end_line):
                    continue
                    
                pos_map = ctx.line_position_map.get(f.file)
                if not pos_map:
                    continue
                    
                target_line = f.start_line or f.end_line
                position = pos_map.get(target_line)
                if not position:
                    continue

                key = f"{f.file}:{target_line}"
                if key not in unique_line_findings:
                    unique_line_findings[key] = {
                        "finding": f,
                        "position": position,
                        "file": f.file,
                        "line": target_line
                    }

            # Batch request explanations concurrently to eliminate Head-of-Line processing bottlenecks
            if unique_line_findings:
                logger.info(f"Batching AI explanations for {len(unique_line_findings)} unique locations.")
                
                tasks = []
                target_metadata = []
                ai_count = 0
                
                for key, target in unique_line_findings.items():
                    f = target["finding"]
                    severity = (f.severity or "").lower()
                    
                    # Extract target contextual source snapshot window
                    code_context = "Context snippet unavailable."
                    full_file_path = os.path.join(ctx.local_repo_path, target["file"])
                    if os.path.exists(full_file_path):
                        try:
                            with open(full_file_path, "r", encoding="utf-8", errors="ignore") as src_file:
                                src_lines = src_file.readlines()
                                start_idx = max(0, target["line"] - 4)
                                end_idx = min(len(src_lines), target["line"] + 4)
                                code_context = "".join(src_lines[start_idx:end_idx])
                        except Exception as err:
                            logger.warning(f"Could not read source context: {str(err)}")

                    if severity in ["critical", "high"] and ai_count < MAX_AI_EXPLANATIONS:
                        # Append the async task execution into the parallel orchestration pool
                        tasks.append(self.explanation_service.explain_finding(finding=f, code_context=code_context))
                        target_metadata.append((target, True))
                        ai_count += 1
                    else:
                        target_metadata.append((target, False))

                # Fire and resolve scheduled inference executions concurrently
                ai_responses = await asyncio.gather(*tasks, return_exceptions=True)
                
                ai_idx = 0
                for target, was_ai in target_metadata:
                    f = target["finding"]
                    severity = (f.severity or "").lower()
                    
                    if was_ai:
                        response_text = ai_responses[ai_idx]
                        ai_idx += 1
                        if isinstance(response_text, Exception):
                            logger.error(f"AI generation failed for inline coordinate: {str(response_text)}")
                            body = f"### {severity.upper()}\n\n{f.message}"
                        else:
                            body = response_text
                    else:
                        body = (
                            f"### {severity.upper()}\n\n"
                            f"{f.message}\n\n"
                            f"**Rule:** `{f.rule_id}`\n\n"
                            f"_Generated by PRLens_"
                        )

                    inline_comments.append({
                        "path": target["file"],
                        "position": target["position"],
                        "body": body
                    })

            # If inline review findings are present, publish them in a single batch API call
            if inline_comments and commit_id:
                try:
                    review_resp = await self.github.create_pull_request_review(
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        commit_id=commit_id,
                        comments=inline_comments,
                        token=token,
                    )
                    logger.info("Inline review posted", extra={"review_id": review_resp.get("id")})
                except GithubServiceError as e:
                    logger.error("Failed to post inline review", extra={"error": str(e)})

            # Persist comprehensive structural execution metrics and tracking comment metrics to the database
            if comment_id:
                try:
                    review_record = await self.pr_review_repository.create_or_update_review(
                        session=self.db_session,
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        installation_id=installation_id,
                        github_comment_id=comment_id,
                        findings_count=len(findings),
                        last_commit_sha=commit_id
                    )
                    # Production Fix: Explicitly commit connection states to maintain relational integrity
                    await self.db_session.commit()
                    logger.info("PR review metrics staged to database successfully", extra={"record_id": review_record.id})
                except PRReviewRepositoryError as e:
                    await self.db_session.rollback()
                    logger.error("Failed to save review metrics to database", extra={"error": str(e)})

        except AnalyzerManagerError as e:
            logger.exception("Analyzer manager failed")
            findings = []
            summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        finally:
            # Production Fix: Offload disk unlinking to separate worker thread pool to prevent blocking the event loop
            if ctx.local_repo_path and os.path.exists(ctx.local_repo_path):
                logger.info(f"Cleaning up temporary directory: {ctx.local_repo_path}")
                try:
                    await asyncio.to_thread(shutil.rmtree, ctx.local_repo_path)
                except Exception as e:
                    logger.error(f"Failed to clean up temporary workspace path {ctx.local_repo_path}: {str(e)}")

        logger.info(
            "Review completed",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "findings": len(findings),
                "critical": summary["critical"],
                "high": summary["high"],
                "medium": summary["medium"],
                "low": summary["low"],
                "info": summary["info"],
                "comment_posted": comment_posted,
            }
        )

        return {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "findings_count": len(findings),
            "summary": summary,
            "comment_posted": comment_posted,
            "comment_url": comment_url,
        }