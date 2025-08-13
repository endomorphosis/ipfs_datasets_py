import pytest
import asyncio
import math
from unittest.mock import AsyncMock, Mock, patch
from ipfs_datasets_py.pdf_processing.classify_with_llm import (
    classify_with_llm, ClassificationResult, _classify_with_openai_llm, WIKIPEDIA_CLASSIFICATIONS
)
from tests._test_utils import has_good_callable_metadata
import openai

@pytest.fixture
def mock_client():
    return AsyncMock(spec_set=openai.AsyncOpenAI)


@pytest.fixture
def basic_classifications():
    return {"Technology", "Science"}


@pytest.fixture
def large_classifications():
    return {f"Category{i}" for i in range(37)}


@pytest.fixture
def single_classification():
    return {"Technology"}


class TestClassifyWithLLM:
    """Test classify_with_llm main function behavior and edge cases."""

    @pytest.mark.asyncio
    async def test_successful_single_iteration_classification(self, mock_client, single_classification):
        """
        GIVEN text and classifications resulting in single category
        WHEN classify_with_llm is called
        THEN expect single ClassificationResult
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Technology", -0.5)]
            result = await classify_with_llm(text="AI research", classifications=single_classification, client=mock_client)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_single_result_entity_matches_input(self, mock_client, single_classification):
        """
        GIVEN text input
        WHEN classify_with_llm returns single result
        THEN expect result entity matches input text
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Technology", -0.5)]
            result = await classify_with_llm(text="test input", classifications=single_classification, client=mock_client)
            assert result[0].entity == "test input"

    @pytest.mark.asyncio
    async def test_single_result_category_correct(self, mock_client):
        """
        GIVEN LLM returns specific category token
        WHEN classify_with_llm is called
        THEN expect result category matches returned token
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Science", -0.3)]
            result = await classify_with_llm(text="test", classifications={"Science"}, client=mock_client)
            assert result[0].category == "Science"

    @pytest.mark.asyncio
    async def test_single_result_confidence_calculation(self, mock_client, single_classification):
        """
        GIVEN LLM returns specific log probability
        WHEN classify_with_llm is called
        THEN expect confidence calculated as exp(log_prob)
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Technology", -0.693)]
            result = await classify_with_llm(text="test", classifications=single_classification, client=mock_client)
            assert abs(result[0].confidence - 0.5) < 0.01

    @pytest.mark.asyncio
    async def test_winnowing_multiple_iterations_calls_llm_multiple_times(self, mock_client, basic_classifications):
        """
        GIVEN classification set requiring winnowing
        WHEN classify_with_llm is called
        THEN expect multiple LLM calls
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = [
                [("Tech", -0.5), ("Science", -0.6)],
                [("Tech", -0.3)]
            ]
            await classify_with_llm(text="test", classifications={"Technology", "Science", "Art", "History"}, client=mock_client, retries=3)
            assert mock_llm.call_count >= 2

    @pytest.mark.asyncio
    async def test_winnowing_returns_single_result(self, mock_client):
        """
        GIVEN winnowing process that converges
        WHEN classify_with_llm is called
        THEN expect single final result
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = [
                [("Tech", -0.5), ("Science", -0.6)],
                [("Tech", -0.3)]
            ]
            result = await classify_with_llm(text="test", classifications={"Technology", "Science", "Art"}, client=mock_client)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_multiple_categories(self, mock_client, basic_classifications):
        """
        GIVEN text consistently returning multiple categories
        WHEN maximum retries is reached
        THEN expect list of multiple ClassificationResult objects
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Tech", -0.5), ("Science", -0.7)]
            result = await classify_with_llm(text="test", classifications=basic_classifications, client=mock_client, retries=2)
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_max_retries_results_sorted_by_confidence(self, mock_client, basic_classifications):
        """
        GIVEN multiple results after max retries
        WHEN classify_with_llm returns results
        THEN expect results sorted by confidence
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Tech", -0.7), ("Science", -0.3)]
            result = await classify_with_llm(text="test", classifications=basic_classifications, client=mock_client, retries=1)
            assert result[0].confidence <= result[1].confidence

    @pytest.mark.asyncio
    async def test_no_categories_above_threshold(self, mock_client, basic_classifications):
        """
        GIVEN LLM returns no categories above threshold
        WHEN classify_with_llm is called
        THEN expect empty list
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = []
            result = await classify_with_llm(text="test", classifications=basic_classifications, client=mock_client)
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_classification_set(self, mock_client):
        """
        GIVEN empty classifications set
        WHEN classify_with_llm is called
        THEN expect ValueError
        """
        with pytest.raises(ValueError):
            await classify_with_llm(text="test", classifications=set(), client=mock_client)

    @pytest.mark.asyncio
    async def test_single_category_classification_set(self, mock_client, single_classification):
        """
        GIVEN classifications set with only one category
        WHEN classify_with_llm is called
        THEN expect single classification attempt
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Technology", -0.5)]
            await classify_with_llm(text="test", classifications=single_classification, client=mock_client)
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_text_input_creates_result_with_empty_entity(self, mock_client, single_classification):
        """
        GIVEN empty string as text input
        WHEN classify_with_llm is called
        THEN expect result with empty entity string
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Technology", -0.5)]
            result = await classify_with_llm(text="", classifications=single_classification, client=mock_client)
            assert result[0].entity == ""

    @pytest.mark.asyncio
    async def test_zero_retries_parameter(self, mock_client, basic_classifications):
        """
        GIVEN retries parameter set to 0
        WHEN classify_with_llm is called
        THEN expect single attempt only
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Tech", -0.5), ("Science", -0.6)]
            await classify_with_llm(text="test", classifications=basic_classifications, client=mock_client, retries=0)
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_zero_threshold_raises_value_error(self, mock_client, single_classification):
        """
        GIVEN threshold parameter of 0.0
        WHEN classify_with_llm is called
        THEN expected to raise ValueError
        """
        with pytest.raises(ValueError):
            await classify_with_llm(text="test", classifications=single_classification, client=mock_client, threshold=0.0)

    @pytest.mark.asyncio
    async def test_threshold_greater_than_one_filters_all(self, mock_client, single_classification):
        """
        GIVEN threshold parameter greater than 1.0
        WHEN classify_with_llm is called
        THEN expect raise ValueError
        """
        with pytest.raises(ValueError):
            await classify_with_llm(text="test", classifications=single_classification, client=mock_client, threshold=1.5)

    @pytest.mark.asyncio
    async def test_connection_error_on_first_attempt(self, mock_client, single_classification):
        """
        GIVEN first LLM call raises ConnectionError
        WHEN classify_with_llm is called
        THEN expect ConnectionError to be propagated
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = ConnectionError("Network error")
            with pytest.raises(ConnectionError):
                await classify_with_llm(text="test", classifications=single_classification, client=mock_client)

    @pytest.mark.asyncio
    async def test_timeout_error_on_all_attempts(self, mock_client, single_classification):
        """
        GIVEN timeout error on all retry attempts
        WHEN classify_with_llm is called
        THEN expect TimeoutError after max retries
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = asyncio.TimeoutError("Request timeout")
            with pytest.raises(asyncio.TimeoutError):
                await classify_with_llm(text="test", classifications=single_classification, client=mock_client, retries=2)

    @pytest.mark.asyncio
    async def test_runtime_error_on_final_attempt(self, mock_client, single_classification):
        """
        GIVEN unexpected errors on all attempts
        WHEN classify_with_llm is called
        THEN expect RuntimeError with wrapped exception
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = ValueError("Unexpected error")
            with pytest.raises(RuntimeError):
                await classify_with_llm(text="test", classifications=single_classification, client=mock_client, retries=1)

    @pytest.mark.asyncio
    async def test_case_sensitivity_in_token_matching(self, mock_client):
        """
        GIVEN mixed case categories and lowercase LLM tokens
        WHEN token matching occurs
        THEN expect case-insensitive matching to work
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("tech", -0.5)]
            result = await classify_with_llm(text="test", classifications={"Technology"}, client=mock_client)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_partial_token_matching_startswith_logic(self, mock_client):
        """
        GIVEN categories where token prefix matching works
        WHEN winnowing occurs
        THEN expect correct category matching based on startswith
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Art", -0.5)]
            result = await classify_with_llm(text="test", classifications={"Art", "Artificial Intelligence"}, client=mock_client)
            assert result[0].category == "Art"


@pytest.fixture
def exact_multiple_categories():
    return {f"Category{i}" for i in range(20)}


@pytest.fixture
def remainder_categories():
    return {f"Category{i}" for i in range(37)}


@pytest.fixture
def small_category_set():
    return {f"Category{i}" for i in range(5)}


@pytest.fixture
def medium_category_set():
    return {f"Category{i}" for i in range(25)}


class TestBatchingLogic:
    """Test batching functionality and edge cases."""

    @pytest.mark.asyncio
    async def test_category_batching_with_exact_multiples(self, mock_client, exact_multiple_categories):
        """
        GIVEN 20 categories and batch processing
        WHEN batching occurs
        THEN expect multiple LLM calls for batches
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Category1", -0.5)]
            await classify_with_llm(text="test", classifications=exact_multiple_categories, client=mock_client)
            assert mock_llm.call_count >= 2

    @pytest.mark.asyncio
    async def test_category_batching_with_remainder(self, mock_client, remainder_categories):
        """
        GIVEN 37 categories requiring batching
        WHEN batching occurs
        THEN expect multiple LLM calls for all batches
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Category1", -0.5)]
            await classify_with_llm(text="test", classifications=remainder_categories, client=mock_client)
            assert mock_llm.call_count >= 2

    @pytest.mark.asyncio
    async def test_batch_size_larger_than_category_count(self, mock_client, small_category_set):
        """
        GIVEN 5 categories with large batch size
        WHEN batching occurs
        THEN expect single batch containing all categories
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Category1", -0.5)]
            await classify_with_llm(text="test", classifications=small_category_set, client=mock_client)
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_parallel_batch_processing_multiple_calls(self, mock_client, medium_category_set):
        """
        GIVEN multiple batches of categories
        WHEN parallel processing occurs
        THEN expect multiple concurrent LLM calls
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Category1", -0.5)]
            await classify_with_llm(text="test", classifications=medium_category_set, client=mock_client)
            assert mock_llm.call_count > 1

    @pytest.mark.asyncio
    async def test_parallel_batch_processing_aggregates_results(self, mock_client, medium_category_set):
        """
        GIVEN multiple batches returning different results
        WHEN parallel processing occurs
        THEN expect aggregated results from all batches
        """
        categories = {"Hitler", "Staling", "Don Cheedle"}
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.side_effect = [
                [("Hitler", -0.5)],
                [("Stalin", -0.6)]
            ]
            result = await classify_with_llm(text="test", classifications=categories, client=mock_client, retries=1)
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_batch_size_determines_llm_function_type(self, mock_client):
        """
        GIVEN specific LLM function type
        WHEN batch processing occurs
        THEN expect batch size determined by function type
        """
        categories = {"Category1", "Category2", "Category3"}
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Category1", -0.5)]
            await classify_with_llm(text="test", classifications=categories, client=mock_client, llm_func=_classify_with_openai_llm)
            assert mock_llm.call_count >= 1

    @pytest.mark.asyncio
    async def test_batch_processing_preserves_category_integrity(self, mock_client):
        """
        GIVEN multiple categories across batches
        WHEN batching processes all categories
        THEN expect matching category found despite batching
        """
        categories = {"Technology", "Science", "Art", "History", "Sports"}
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Tech", -0.5)]
            result = await classify_with_llm(text="test", classifications=categories, client=mock_client)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_batch_results_handling(self, mock_client, medium_category_set):
        """
        GIVEN all batches return empty results
        WHEN batch processing occurs
        THEN expect empty final result
        """
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = []
            result = await classify_with_llm(text="test", classifications=medium_category_set, client=mock_client)
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_single_category_no_batching_needed(self, mock_client):
        """
        GIVEN single category input
        WHEN classify_with_llm is called
        THEN expect no batching logic triggered
        """
        categories = {"Technology"}
        with patch('ipfs_datasets_py.pdf_processing.classify_with_llm._classify_with_openai_llm') as mock_llm:
            mock_llm.return_value = [("Tech", -0.5)]
            await classify_with_llm(text="test", classifications=categories, client=mock_client)
            assert mock_llm.call_count == 1



class TestClassifyWithLLMActualCategories:

    @property
    def openai_client(self):
        """
        Create an OpenAI client for testing.
        """
        import os
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return openai.AsyncOpenAI(api_key=api_key)

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brother Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect classify_with_llm to return a list
        """
        result = await classify_with_llm(
            text="The Brother Karamazov", 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=self.openai_client
        )
        assert isinstance(result, list), f"Expected list but got {type(result)}"

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brother Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect the list returned by classify_with_llm to only be ClassificationResult objects
        """
        result = await classify_with_llm(
            text="The Brother Karamazov", 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=self.openai_client
        )
        for item in result:
            assert isinstance(item, ClassificationResult), \
                f"Expected ClassificationResult but got {type(item)}"

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brother Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect the classification in ClassificationResult to be one of the WIKIPEDIA_CLASSIFICATIONS
        """
        result = await classify_with_llm(
            text="The Brother Karamazov", 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=self.openai_client
        )
        for item in result:
            assert item.category in WIKIPEDIA_CLASSIFICATIONS, \
                f"Expected category to be one of WIKIPEDIA_CLASSIFICATIONS but got {item.category}"







if __name__ == "__main__":
    pytest.main([__file__, "-v"])
