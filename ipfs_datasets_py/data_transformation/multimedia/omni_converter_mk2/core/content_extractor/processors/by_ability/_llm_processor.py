"""
LLM processor module for enhancing document processing with language models.
Provides text summarization, metadata extraction, and content analysis capabilities.
"""
import os
import asyncio
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from configs import Configs
from logger import logger
from utils.llm._async_interface import AsyncLLMInterface
from utils.llm.refactored_prompt_loader import load_prompt_by_name, PromptTemplate
from utils.llm.factory import make_llm_interface


class LLMOptions(BaseModel):
    """
    Options for LLM processing.
    
    Attributes:
        model: The model to use for generation
        summarize: Whether to generate a summary
        extract_metadata: Whether to extract metadata
        analyze_sentiment: Whether to analyze sentiment
        summary_max_length: Maximum length of summary in characters
        summary_format: Format of the summary (bullet, paragraph)
        prompt_name: Name of the prompt template to use
        custom_system_prompt: Custom system prompt to use
        custom_user_prompt: Custom user prompt to use
    """
    model: Optional[str] = None
    summarize: bool = False
    extract_metadata: bool = False
    summary_max_length: Optional[int] = None
    summary_format: Optional[str] = None
    prompt_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    custom_user_prompt: Optional[str] = None


class LLMResult(BaseModel):
    """
    Result of LLM processing.
    
    Attributes:
        summary: Generated summary of the content
        metadata: Extracted metadata from the content
        sentiment: Sentiment analysis of the content
        raw_responses: Raw responses from the LLM
    """
    summary: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sentiment: Optional[dict[str, Any]] = None
    raw_responses: dict[str, Any] = Field(default_factory=dict)


class LLMProcessor:
    """
    Processor for enhancing document processing with language models.
    """
    def __init__(
        self,
        resources: dict[str, Any] = None,
        configs: Configs = None
    ):
        """
        Initialize the LLM processor with dependency injection.
        
        Args:
            resources: Dictionary of resources including LLM interface
            configs: Configuration parameters
        """
        self.resources = resources
        self.configs = configs
        
        # Extract required resources
        self.llm_interface = self.resources["llm_interface"]
        self.async_llm_interface = self.resources["async_llm_interface"]
        
        # Initialize configuration
        self.default_model = self.configs["model"]
        self.prompts_dir = self.configs["prompts_dir"]

        logger.info("Initialized LLMProcessor")
    
    def process_content(
        self,
        content: str,
        options: Union[dict[str, Any], LLMOptions] = None
    ) -> LLMResult:
        """
        Process content using language models.
        
        Args:
            content: Text content to process
            options: Processing options
            
        Returns:
            LLMResult containing processing results
        """
        # Convert options to LLMOptions if needed
        if isinstance(options, dict):
            options = LLMOptions(**options)
        elif options is None:
            options = LLMOptions()
        
        # Run processing in an async loop
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(self._process_content_async(content, options))
        return result
    
    async def _process_content_async(
        self,
        content: str,
        options: LLMOptions
    ) -> LLMResult:
        """
        Process content asynchronously using language models.
        
        Args:
            content: Text content to process
            options: Processing options
            
        Returns:
            LLMResult containing processing results
        """
        result = LLMResult()
        tasks = []
        
        # Use specified model or default
        model = options.model or self.default_model
        
        # Generate summary if requested
        if options.summarize:
            tasks.append(self._generate_summary(content, options, model, result))
        
        # Extract metadata if requested
        if options.extract_metadata:
            tasks.append(self._extract_metadata(content, options, model, result))

        # Wait for all tasks to complete
        if tasks:
            await asyncio.gather(*tasks)
        
        return result
    
    async def _generate_summary(
        self,
        content: str,
        options: LLMOptions,
        model: str,
        result: LLMResult
    ) -> None:
        """
        Generate a summary of the content.
        
        Args:
            content: Text content to summarize
            options: Processing options
            model: Model to use for generation
            result: Result object to update
        """
        logger.debug("Generating summary with LLM")
        
        try:
            # Load prompt template if specified
            prompt_template = None
            if options.prompt_name and self.prompts_dir:
                prompt_path = os.path.join(self.prompts_dir, f"{options.prompt_name}.yaml")
                if os.path.exists(prompt_path):
                    prompt_template = load_prompt_by_name(options.prompt_name, self.prompts_dir)
            
            # Use custom prompts if provided
            system_prompt = options.custom_system_prompt
            if system_prompt is None and prompt_template:
                system_prompt = prompt_template.system_prompt
            if system_prompt is None:
                system_prompt = (
                    "You are a document summarization assistant. "
                    "Create a concise summary that captures the key information. "
                )
                
                # Add format instruction
                if options.summary_format == "bullet":
                    system_prompt += "Format the summary as bullet points."
                elif options.summary_format == "paragraph":
                    system_prompt += "Format the summary as a single paragraph."
                
                # Add length instruction
                if options.summary_max_length:
                    system_prompt += f" Keep the summary under {options.summary_max_length} characters."
            
            # Use custom user prompt or create one
            user_prompt = options.custom_user_prompt
            if user_prompt is None and prompt_template:
                user_prompt = prompt_template.user_prompt.format(content=content)
            if user_prompt is None:
                user_prompt = f"Summarize the following content:\n\n{content}"
            
            # Generate summary
            response = await self.llm_interface.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.3,  # Lower temperature for more focused summary
                max_tokens=500  # Summaries should be concise
            )
            
            # Update result
            result.summary = response.get("response")
            result.raw_responses["summary"] = response
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            result.raw_responses["summary_error"] = str(e)
    
    async def _generate_image_description(
        self,
        content: bytes,
        options: LLMOptions,
        model: str,
        result: LLMResult
    ):
        """
        Generate a summary of an image using VLLM.
        
        Args:
            content (bytes): Image data in bytes.
            options: Processing options
            model: Model to use for generation
            result: Result object to update
        """
        logger.debug("Generating image summary with LLM")
        
        # TODO Implement image summary generation logic here
        pass

    async def _ocr_with_vllm(
        self,
        content: bytes,
        options: LLMOptions,
        model: str,
        result: LLMResult
    ):
        """Extract text from an image using a VLLM.

        Args:
            content: Image content to summarize
            options: Processing options
            model: Model to use for generation
            result: Result object to update
        """
        logger.debug("Generating image summary with LLM")
        # TODO Implement image summary generation logic here
        pass

    async def _extract_metadata(
        self,
        content: str,
        options: LLMOptions,
        model: str,
        result: LLMResult
    ) -> None:
        """
        Extract metadata from the content.
        
        Args:
            content: Text content to extract metadata from
            options: Processing options
            model: Model to use for generation
            result: Result object to update
        """
        logger.debug("Extracting metadata with LLM")
        
        try:
            # Use metadata extraction prompt
            system_prompt = (
                "You are a metadata extraction assistant. Extract the requested metadata "
                "fields from the provided text. Return ONLY the extracted information in "
                "a clear key: value format. If a field cannot be determined, use 'Unknown' "
                "as the value."
            )
            
            # Create field list for common metadata fields
            fields = [
                "title", "author", "date", "subject", "keywords", 
                "language", "source", "document_type"
            ]
            field_list = "\n".join([f"- {field}" for field in fields])
            
            # Create user prompt
            user_prompt = (
                f"Extract the following metadata fields from the text:\n{field_list}\n\n"
                f"Text:\n{content}"
            )

            # Generate extraction
            response = await self.llm_interface.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.1,  # Very low temperature for consistent formatting # TODO Make this configurable.
                max_tokens=500  # Metadata should be concise # TODO Make this configurable.
            )
            
            # Process the response into a dictionary
            metadata = {}
            if response.get("response"):
                lines = response["response"].strip().split("\n")
                for line in lines:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip().lower()] = value.strip()
            
            # Update result
            result.metadata = metadata
            result.raw_responses["metadata"] = response
            
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")
            result.raw_responses["metadata_error"] = str(e)
    
    async def _analyze_sentiment(
        self,
        content: str,
        options: LLMOptions,
        model: str,
        result: LLMResult
    ) -> None:
        """
        Analyze sentiment of the content.
        
        Args:
            content: Text content to analyze
            options: Processing options
            model: Model to use for generation
            result: Result object to update
        """
        logger.debug("Analyzing sentiment with LLM")
        
        try:
            # Use sentiment analysis prompt
            system_prompt = (
                "You are a sentiment analysis assistant. Analyze the sentiment of the provided text "
                "and return ONLY a JSON object with the following fields: "
                "- 'overall': overall sentiment as 'positive', 'neutral', or 'negative' "
                "- 'score': a score from -1 (very negative) to 1 (very positive) "
                "- 'confidence': your confidence in the assessment from 0 to 1 "
                "- 'keywords': list of 3-5 keywords that influenced your assessment"
            )
            
            # Create user prompt
            user_prompt = f"Analyze the sentiment of the following text:\n\n{content[:2000]}..."
            
            # Generate analysis
            response = await self.llm_interface.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.1,  # Very low temperature for consistent formatting
                max_tokens=500  # Sentiment analysis should be concise
            )
            
            # Process the response - try to parse as JSON, but fallback to text
            sentiment = {}
            if response.get("response"):
                response_text = response["response"].strip()
                
                # Try to parse as JSON
                try:
                    import json
                    # Find JSON within the response if needed
                    json_start = response_text.find("{")
                    json_end = response_text.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_text = response_text[json_start:json_end]
                        sentiment = json.loads(json_text)
                except Exception:
                    # Fallback to simple text processing
                    lines = response_text.split("\n")
                    for line in lines:
                        if ":" in line:
                            key, value = line.split(":", 1)
                            sentiment[key.strip().lower()] = value.strip()
            
            # Update result
            result.sentiment = sentiment
            result.raw_responses["sentiment"] = response
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {e}")
            result.raw_responses["sentiment_error"] = str(e)


