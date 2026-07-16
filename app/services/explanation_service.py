import os
import asyncio
import inspect
from ollama import AsyncClient
from google import genai
from google.genai import types

from ..config import GEMINI_API_KEY
from ..models.finding import Finding
from ..core.logging_config import logger


EXPLANATION_SYSTEM_PROMPT = """
You are a Senior Security Engineer reviewing a pull request.

You are explaining a static-analysis finding to the author of the code.

Rules:

- Do NOT repeat the tool message.
- Explain the real-world risk.
- Explain why this specific pattern is dangerous.
- Give a concrete remediation.
- Provide a short example fix when possible.
- Use professional engineering language.
- Keep under 180 words.
- Avoid mentioning the analyzer itself.

Return markdown:

### Why This Matters
(impact)

### Recommended Fix
(remediation)

### Example
(code example if applicable)
"""


class AIExplanationService:
    def __init__(
        self,
        ollama_model: str = "qwen2.5:3b",
        gemini_model: str = "gemini-2.5-flash",
    ) -> None:
        self.ollama_model = ollama_model
        self.gemini_model = gemini_model
        self.client = AsyncClient()        

        self.gemini_api_key = GEMINI_API_KEY

        self.ollama_client = AsyncClient()
        self.gemini_client = genai.Client(api_key=self.gemini_api_key) if self.gemini_api_key else None

        # Bound parallel execution blocks to 3 to prevent GPU/CPU thrashing
        self._semaphore = asyncio.BoundedSemaphore(1)

    async def explain_finding(
        self,
        finding: Finding,
        code_context: str,
    ) -> str:
        """Generate finding explanations using tiered strategy: Gemini -> Ollama -> Static Fallback."""

        language = self._detect_language(finding.file or "")

        # Format clean markdown code-blocks for optimized context token parsing
        user_prompt = inspect.cleandoc(f"""
            Tool: {finding.tool}
            Rule: {finding.rule_id}
            Severity: {finding.severity}

            Finding:
            {finding.message}

            File:
            {finding.file}

            Code Context:
            ```{language}
            {code_context}
            ```
        """)

        # Execute inside the resource-controlled semaphore block
        async with self._semaphore:
            # --- Layer 1: GEMINI ENGINE ---
            if self.gemini_client:
                try:
                    return await self._explain_with_gemini(user_prompt)
                except Exception as e:
                    logger.warning(
                        "Gemini explanation failed",
                        extra={"error": str(e), "file": finding.file, "rule": finding.rule_id}
                    )
            
            # --- Layer 2: OLLAMA LOCAL ENGINE ---
            try:
                return await self._explain_with_ollama(user_prompt)
            except Exception as e:
                logger.warning(
                    "Ollama explanation failed",
                    extra={"error": str(e), "file": finding.file, "rule": finding.rule_id}
                )

            # --- Layer 3: STATIC DOCUMENTATION FALLBACK ---
            return self._generate_static_explanation(finding, code_context, language)

            # try:
            #     response = await asyncio.wait_for(
            #         self.client.generate(
            #             model=self.model_name,
            #             system=EXPLANATION_SYSTEM_PROMPT,
            #             prompt=user_prompt,
            #             options={
            #                 "temperature": 0.1,
            #             },
            #         ),
            #         timeout=30,
            #     )

            #     return (
            #         response.get("response")
            #         or "Explanation unavailable."
            #     )

            # except asyncio.TimeoutError:
            #     logger.warning(
            #         "AI explanation timeout",
            #         extra={
            #             "file": finding.file,
            #             "rule": finding.rule_id,
            #         },
            #     )
            #     return f"({finding.tool}) Error ({finding.rule_id}): {finding.message}"

            # except Exception as e:
            #     logger.error(
            #         "Failed to generate AI explanation",
            #         extra={
            #             "error": str(e),
            #             "file": finding.file,
            #             "rule": finding.rule_id,
            #         },
            #     )
            #     return f"*AI explanation generation omitted: {finding.message}*"

    async def _explain_with_gemini(self, user_prompt: str) -> str:
        """Execute async inference inside the Gemini engine block."""
        # Wrap the synchronous SDK client generation call within an async executor thread
        loop = asyncio.get_running_loop()
        
        config = types.GenerateContentConfig(
            system_instruction=EXPLANATION_SYSTEM_PROMPT,
            temperature=0.1,
        )
        
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self.gemini_client.models.generate_content(
                    model=self.gemini_model,
                    contents=user_prompt,
                    config=config
                )
            ),
            timeout=20.0, # Isolated 20s execution wall for API calls
        )
        if response.text:
            return response.text
        raise ValueError("Empty generation text response returned from Gemini API.")


    async def _explain_with_ollama(self, user_prompt: str) -> str:
        """Execute async inference through the local Ollama daemon pipeline."""
        response = await asyncio.wait_for(
            self.ollama_client.generate(
                model=self.ollama_model,
                system=EXPLANATION_SYSTEM_PROMPT,
                prompt=user_prompt,
                options={"temperature": 0.1},
            ),
            timeout=60.0, # Isolated 30s execution wall for local GPU/CPU cycles
        )
        output = response.get("response")
        if output:
            return output
        raise ValueError("Empty execution payload returned from Ollama daemon context.")


    def _generate_static_explanation(self, finding: Finding, code_context: str, language: str) -> str:
        """Generate structured markdown context blocks if all remote/local AI models fail."""
        logger.info(f"Serving static fallback metadata documentation for {finding.file}")
        return inspect.cleandoc(f"""
            ### Why This Matters
            The automated static code analysis engine identified a **{finding.severity}** rule violation path inside your code changes. 
            
            * **Tool Source:** `{finding.tool}`
            * **Rule Violation Identifier:** `{finding.rule_id}`

            ### Recommended Fix
            Review the code surrounding line positions flagged by the analyzer. Ensure inputs are correctly validated, data types are explicitly cast, and standard security boundaries are observed.

            ### Context Reference
            ```{language}
            {code_context}
            ```
            
            *Original finding rule notification:* `{finding.message}`
        """)


    def _detect_language(self, filename: str) -> str:
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx"
        }
        _, ext = os.path.splitext(filename.lower())
        return ext_map.get(ext, "text")
