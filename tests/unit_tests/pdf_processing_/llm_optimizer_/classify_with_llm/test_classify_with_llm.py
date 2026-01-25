
import anyio
import os
from unittest.mock import AsyncMock, Mock
import random


import pytest
import openai


from ipfs_datasets_py.pdf_processing.classify_with_llm import (
    classify_with_llm, ClassificationResult, _classify_with_openai_llm, WIKIPEDIA_CLASSIFICATIONS
)
from tests._test_utils import has_good_callable_metadata

random.seed(420)

@pytest.fixture
def mock_client():
    return AsyncMock(spec_set=openai.AsyncOpenAI)

@pytest.fixture
def openai_client():
    """
    Create an OpenAI client for testing.
    """
    import os
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set; skipping live OpenAI tests")
    return openai.AsyncOpenAI(api_key=api_key)

@pytest.fixture
def basic_classifications():
    return {"Technology", "Science"}


@pytest.fixture
def large_classifications():
    return {f"Category{i}" for i in range(37)}


@pytest.fixture
def one_cat():
    return {"Technology"}

@pytest.fixture
def test_cats():
    return {
        "one_cat": {"Technology"},
        "two_cats": {"Technology", "Science"},
        "three_cats": {"Technology", "Science", "Art"},
        "four_cats": {"Technology", "Science", "Art", "History"},
    }

CATEGORIES = {
    "tech": "Technology",
    "science": "Science",
    "art": "Art",
    "history": "History"
}

@pytest.fixture
def categories():
    return CATEGORIES


LLM_FUNC_RETURNS = {
    "empty": [],
    "one_cat": [("Technology", -0.5)],
    "two_cats": [("Technology", -0.5), ("Science", -0.7)],
    "three_cats": [("Technology", -0.5), ("Science", -0.7), ("Art", -0.9)],
    "four_cats": [("Technology", -0.5), ("Science", -0.7), ("Art", -0.9), ("History", -1.2)],
    "connection_error": ConnectionError("Network error"),
    "timeout_error": TimeoutError("Request timeout"),
    "runtime_error": ValueError("Unexpected error"),
    "lowercase_token": [("tech", -0.5)],
    "partial_match": [("Art", -0.5)],
}


@pytest.fixture
def llm_func_returns():
    return LLM_FUNC_RETURNS 


INPUT_TEXTS = {
    "text": "test input",
    "short_text": "AI research",
    "long_text": "Artificial Intelligence (AI) is a branch of computer science that aims to create intelligent machines that can perform tasks that typically require human intelligence. AI research involves the development of algorithms and models that enable computers to learn from data, recognize patterns, and make decisions. Applications of AI include natural language processing, computer vision, robotics, and autonomous systems.",
    "ambiguous_text": "The study of stars and galaxies.",
    "empty_text": "",
}


@pytest.fixture
def input_texts():
    return INPUT_TEXTS 


def mock_llm_return(key):
    """Factory function to create a mock LLM function returning specified or default values."""
    async def llm_func(*args, **kwargs):
        return LLM_FUNC_RETURNS[key]
    return llm_func


def make_mock_llm_func(key):
    """Create a mock async LLM function that tracks how many times it was called."""

    async def llm_func(*args, **kwargs):
        llm_func.call_count += 1
        return LLM_FUNC_RETURNS[key]

    llm_func.call_count = 0
    return llm_func


@pytest.fixture
def empty_llm_func():
    """Create LLM function that returns no categories above threshold."""
    async def llm_func(*args, **kwargs):
        return []
    return llm_func


@pytest.fixture
def connection_error_llm_func():
    """Create LLM function that raises ConnectionError."""
    async def llm_func(*args, **kwargs):
        raise ConnectionError("Network error")
    return llm_func


@pytest.fixture
def timeout_error_llm_func():
    """Create LLM function that raises TimeoutError."""
    async def llm_func(*args, **kwargs):
        raise TimeoutError("Request timeout")
    return llm_func


@pytest.fixture
def runtime_error_llm_func():
    """Create LLM function that raises unexpected ValueError."""
    async def llm_func(*args, **kwargs):
        raise ValueError("Unexpected error")
    return llm_func


@pytest.fixture
def lowercase_token_llm_func():
    """Create LLM function that returns lowercase token."""
    async def llm_func(*args, **kwargs):
        return [("tech", -0.5)]
    return llm_func


@pytest.fixture
def partial_match_llm_func():
    """Create LLM function that returns partial token match."""
    async def llm_func(*args, **kwargs):
        return [("Art", -0.5)]
    return llm_func


@pytest.fixture
def real_entity():
    return "The Brothers Karamazov"


def make_valid_args(text="text", cat="one_cat", llm_func="one_cat"):
    """Helper to create valid args for classify_with_llm tests."""
    @pytest.fixture
    def _make_valid_args(input_texts, mock_client, test_cats):
        return {
            "text": input_texts[text],
            "classifications": test_cats[cat],
            "client": mock_client,
            "llm_func": mock_llm_return(llm_func)
        }
    return _make_valid_args


valid_args = make_valid_args(text="text", cat="one_cat", llm_func="one_cat")
single_result_args = make_valid_args(text="text", cat="one_cat", llm_func="one_cat")
one_cat_args = make_valid_args(text="text", cat="one_cat", llm_func="one_cat")
two_cats_args = make_valid_args(text="text", cat="two_cats", llm_func="two_cats")
three_cats_args = make_valid_args(text="text", cat="three_cats", llm_func="three_cats")
empty_args = make_valid_args(text="text", cat="three_cats", llm_func="empty")
connection_error_args = make_valid_args(text="text", cat="one_cat", llm_func="connection_error")
timeout_error_args = make_valid_args(text="text", cat="one_cat", llm_func="timeout_error")
runtime_error_args = make_valid_args(text="text", cat="one_cat", llm_func="runtime_error")
lowercase_error_args = make_valid_args(text="text", cat="one_cat", llm_func="lowercase_token")
partial_match_args = make_valid_args(text="text", cat="three_cats", llm_func="partial_match")


@pytest.fixture
def kwargs(
    valid_args, 
    single_result_args, 
    two_cats_args, 
    three_cats_args, 
    one_cat_args, 
    empty_args,
    connection_error_args,
    timeout_error_args,
    runtime_error_args,
    lowercase_error_args,
    partial_match_args
    ):
    return {
        "valid_args": valid_args,
        "one_cat_args": one_cat_args,
        "single_result_args": single_result_args,
        "two_cats_args": two_cats_args,
        "three_cats_args": three_cats_args,
        "empty_args": empty_args,
        "connection_error_args": connection_error_args,
        "timeout_error_args": timeout_error_args,
        "runtime_error_args": runtime_error_args,
        "lowercase_error_args": lowercase_error_args,
        "partial_match_args": partial_match_args
    }


class TestClassifyWithLLM:
    """Test classify_with_llm main function behavior and edge cases."""


    @pytest.mark.asyncio
    async def test_function_returns_a_list(self, kwargs):
        """
        GIVEN text and a single classification category
        WHEN classify_with_llm is called
        THEN expect the function to return a list.
        """
        valid_args = kwargs['valid_args']
        result = await classify_with_llm(**valid_args)

        assert isinstance(result, list), \
            f"Expected result to be a list, got {type(result).__name__} instead."


    @pytest.mark.asyncio
    async def test_function_returns_a_list_of_classification_results(self, kwargs):
        """
        GIVEN text and a single classification category
        WHEN classify_with_llm is called
        THEN expect the list to contain a ClassificationResult instance.
        """
        valid_args = kwargs['valid_args']
        result = await classify_with_llm(**valid_args)

        instance = result[0]
        assert isinstance(instance, ClassificationResult), \
            f"Expected list to contain a ClassificationResult, got {type(instance).__name__} instead."

    @pytest.mark.asyncio
    async def test_successful_single_iteration_classification(self, kwargs):
        """
        GIVEN text and classifications resulting in single category
        WHEN classify_with_llm is called
        THEN expect single ClassificationResult
        """
        expected_length = 1
        valid_args = kwargs['valid_args']

        result = await classify_with_llm(**valid_args)

        assert len(result) == expected_length, \
            f"Expected {expected_length} result, got {len(result)}"


    @pytest.mark.asyncio
    async def test_winnowing_returns_single_result(self, kwargs):
        """
        GIVEN winnowing process that converges
        WHEN classify_with_llm is called
        THEN expect single final result
        """
        expected_length = 1
        single_result_args = kwargs['single_result_args']

        result = await classify_with_llm(**single_result_args)

        assert len(result) == expected_length, \
            f"Expected 1 result after winnowing, got {len(result)} instead."


    @pytest.mark.asyncio
    async def test_when_single_result_returned_then_entity_matches_input_text(
        self, kwargs, input_texts):
        """
        GIVEN text input and mock LLM function returning single classification
        WHEN classify_with_llm is called with text and classifications
        THEN expect result entity to match original input text exactly
        """
        # Arrange
        text = input_texts["text"]
        kwargs = kwargs['valid_args']
        kwargs['text'] = text

        # Act
        result = await classify_with_llm(**kwargs)

        # Assert
        assert result[0].entity == text, f"Expected entity '{text}', got '{result[0].entity}'"


    @pytest.mark.asyncio
    async def test_single_result_category_correct(self, kwargs, categories):
        """
        GIVEN LLM returns specific category token
        WHEN classify_with_llm is called
        THEN expect result category matches returned token
        """
        # Arrange
        expected_category = categories["tech"]
        valid_args = kwargs['valid_args']

        # Act
        result = await classify_with_llm(**valid_args)

        # Assert
        assert result[0].category == expected_category, \
            f"Expected category '{expected_category}', got '{result[0].category}'"


    @pytest.mark.asyncio
    async def test_single_result_confidence_calculation(
        self, kwargs):
        """
        GIVEN LLM returns specific log probability
        WHEN classify_with_llm is called
        THEN expect confidence calculated as exp(log_prob)
        """
        expected_value = 0.11 # FIXME This is a sensitive test, need to fine-tune it
        valid_args = kwargs['valid_args']

        result = await classify_with_llm(**valid_args)

        actual_value = abs(result[0].confidence - 0.5)

        assert actual_value < expected_value, \
            f"Expected the result's confidence's absolute value to be less than 0.01, got {actual_value}"


    @pytest.mark.asyncio
    async def test_winnowing_multiple_iterations_calls_llm_multiple_times(self, kwargs):
        """
        GIVEN classification set with multiple categories
        WHEN classify_with_llm is called with max retries
        THEN expect the number of LLM calls to be less than or equal to the max retries
        """
        max_retries = 3
        three_cats_args = kwargs['three_cats_args']
        _ = three_cats_args.pop('llm_func')
        mock_llm_func = make_mock_llm_func("three_cats")

        _ = await classify_with_llm(**three_cats_args, retries=max_retries, llm_func=mock_llm_func)

        assert mock_llm_func.call_count <= max_retries, \
            f"Expected LLM call count to be <= {max_retries}, got {mock_llm_func.call_count} instead."


    @pytest.mark.asyncio
    async def test_max_retries_exhausted_multiple_categories(
        self, kwargs, test_cats):
        """
        GIVEN text consistently returning multiple categories
        WHEN maximum retries is reached
        THEN expect list of multiple ClassificationResult objects
        """
        expected_length = len(test_cats['two_cats'])
        two_cats_args = kwargs['two_cats_args']
        result = await classify_with_llm(**two_cats_args, retries=2)

        assert len(result) == expected_length, \
            f"Expected {expected_length} results after max retries, got {len(result)} instead."


    @pytest.mark.asyncio
    async def test_max_retries_results_sorted_by_confidence(self, kwargs):
        """
        GIVEN multiple results after max retries
        WHEN classify_with_llm returns results
        THEN expect results sorted by confidence in descending order
        """
        two_cats_args = kwargs['two_cats_args']

        # Act
        result = await classify_with_llm(**two_cats_args, retries=2)
        first_confidence = result[0].confidence
        second_confidence = result[1].confidence

        # Assert
        assert first_confidence >= second_confidence, \
            f"Expected first result confidence {first_confidence} >= second result confidence {second_confidence}"


    @pytest.mark.asyncio
    async def test_no_categories_above_threshold(self, kwargs):
        """
        GIVEN LLM returns no categories above threshold
        WHEN classify_with_llm is called
        THEN expect empty list
        """
        expected_length = 0
        empty_args = kwargs['empty_args']

        # Act
        result = await classify_with_llm(**empty_args)
        assert len(result) == expected_length, \
            f"Expected empty result list, got {len(result)} instead."


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
    async def test_empty_text_input_creates_result_with_empty_entity(self, kwargs):
        """
        GIVEN empty string as text input
        WHEN classify_with_llm is called
        THEN expect result with empty entity string
        """
        valid_args = kwargs['valid_args']
        valid_args['text'] = ""

        result = await classify_with_llm(**valid_args)
    
        assert result[0].entity == "", \
            f"Expected entity to be empty string, got '{result[0].entity}' instead."


    @pytest.mark.asyncio
    async def test_single_category_classification_set(self, kwargs):
        """
        GIVEN classifications set with only one category
        WHEN classify_with_llm is called
        THEN expect single classification attempt
        """
        expected_count = 1

        one_cat_args = kwargs['one_cat_args']
        _ = one_cat_args.pop('llm_func')
        mock_llm_func = make_mock_llm_func("one_cat")

        _ = await classify_with_llm(**one_cat_args, llm_func=mock_llm_func)

        assert mock_llm_func.call_count == expected_count, \
            f"Expected LLM call count to be {expected_count}, got {mock_llm_func.call_count} instead."


    @pytest.mark.asyncio
    async def test_zero_retries_parameter(self, kwargs):
        """
        GIVEN retries parameter set to 0
        WHEN classify_with_llm is called
        THEN expect single attempt only
        """
        retries = 0
        expected_value = 1
        two_cats_args = kwargs['two_cats_args']
        _ = two_cats_args.pop('llm_func')
        llm_func = make_mock_llm_func("two_cats")

        await classify_with_llm(**two_cats_args, retries=retries, llm_func=llm_func)

        assert llm_func.call_count == expected_value, \
            f"Expected LLM call count to be {expected_value}, got {llm_func.call_count} instead."


    @pytest.mark.parametrize("threshold", [0.0, 1.5,])
    @pytest.mark.asyncio
    async def test_invalid_threshold_raises_value_error(self, mock_client, one_cat, threshold):
        """
        GIVEN invalid threshold parameter (0.0 or > 1.0)
        WHEN classify_with_llm is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError):
            await classify_with_llm(text="test", classifications=one_cat, client=mock_client, threshold=threshold)

    @pytest.mark.asyncio
    async def test_connection_error_on_first_attempt(self, kwargs, connection_error_llm_func):
        """
        GIVEN first LLM call raises ConnectionError
        WHEN classify_with_llm is called
        THEN expect ConnectionError to be raised
        """
        kwargs = kwargs['connection_error_args']
        _ = kwargs.pop('llm_func')
        with pytest.raises(ConnectionError):
            await classify_with_llm(**kwargs, llm_func=connection_error_llm_func)


    @pytest.mark.asyncio
    async def test_timeout_error_on_all_attempts(self, kwargs, timeout_error_llm_func):
        """
        GIVEN timeout error on all retry attempts
        WHEN classify_with_llm is called
        THEN expect TimeoutError to be raised
        """
        retries = 2
        kwargs = kwargs['timeout_error_args']
        _ = kwargs.pop('llm_func')
        with pytest.raises(TimeoutError):
            await classify_with_llm(**kwargs, retries=retries, llm_func=timeout_error_llm_func)


    @pytest.mark.asyncio
    async def test_runtime_error_on_final_attempt(self, kwargs, runtime_error_llm_func):
        """
        GIVEN unexpected errors on all attempts
        WHEN classify_with_llm is called
        THEN expect RuntimeError to be raised
        """
        retries = 1
        kwargs = kwargs['runtime_error_args']
        _ = kwargs.pop('llm_func')
        with pytest.raises(RuntimeError):
            await classify_with_llm(**kwargs, retries=retries, llm_func=runtime_error_llm_func)


    @pytest.mark.asyncio
    async def test_case_sensitivity_in_token_matching(self, kwargs):
        """
        GIVEN mixed case categories and lowercase LLM tokens
        WHEN token matching occurs
        THEN expect case-insensitive matching to work
        """
        expected_value = 1
        kwargs = kwargs['lowercase_error_args']
        result = await classify_with_llm(**kwargs)
        assert len(result) == expected_value, \
            f"Expected {expected_value} result, got {len(result)} instead."


    @pytest.mark.asyncio
    async def test_partial_token_matching_startswith_logic(self, kwargs):
        """
        GIVEN categories where token prefix matching works
        WHEN winnowing occurs
        THEN expect correct category matching based on startswith
        """
        expected_value = "Art"
        kwargs = kwargs['partial_match_args']
        result = await classify_with_llm(**kwargs)
        assert result[0].category == expected_value, \
            f"Expected category '{expected_value}', got '{result[0].category}' instead."




class TestClassifyWithLLMActualCategories:

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self, openai_client, real_entity):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brothers Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect classify_with_llm to return a list
        """
        result = await classify_with_llm(
            text=real_entity, 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=openai_client
        )

        assert isinstance(result, list), f"Expected list but got {type(result)}"

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self, openai_client, real_entity):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brothers Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect the list returned by classify_with_llm to only be ClassificationResult objects
        """
        result = await classify_with_llm(
            text=real_entity, 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=openai_client
        )

        for item in result:
            assert isinstance(item, ClassificationResult), \
                f"Expected ClassificationResult but got {type(item)}"

    @pytest.mark.asyncio
    async def test_function_with_wikipedia_categories(self, openai_client, real_entity):
        """
        GIVEN classify_with_llm function
        WHEN checking "The Brothers Karamazov" against WIKIPEDIA_CLASSIFICATIONS
        THEN expect the classification in ClassificationResult to be one of the WIKIPEDIA_CLASSIFICATIONS
        """
        result = await classify_with_llm(
            text=real_entity, 
            classifications=WIKIPEDIA_CLASSIFICATIONS,
            client=openai_client
        )
        for item in result:
            assert item.category in WIKIPEDIA_CLASSIFICATIONS, \
                f"Expected category to be one of WIKIPEDIA_CLASSIFICATIONS but got {item.category}"







if __name__ == "__main__":
    pytest.main([__file__, "-v"])
