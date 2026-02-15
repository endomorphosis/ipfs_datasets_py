"""
Perfect Test Suite Template

This module demonstrates best practices for unit testing based on:
- Testing through public contracts only (e.g. no testing/accessing private callables, attributes, and properties)
- Testing behavior, not implementation details
- Following AAA (Arrange, Act, Assert) pattern
- Avoiding the following test smells:
    - Test methods longer than 10 lines, excluding docstrings.
    - Test methods with more than 1 assertion (e.g. multiple expectations).
    - Test methods with no assertions (e.g. unknown tests)
    - Test methods with conditional logic (e.g., if/else, for/while loops)
    - Test methods that fail/pass based on the test itself throwing an exception (e.g. try/except blocks)
    - Test methods with constructor initialization (.e.g __init__ method calls)
        (Should be moved to a setup method, fixture, or factory function)
    - Tests without executable statements (e.g. empty tests)
        (Should be deleted, fixed, or raise NotImplementedError)
    - Assertions that have either no or non-descriptive messages (i.e. Assertion Roulette)
        (Should be f-strings that contains the parameterized expected outcome and the parameterized actual outcome)
    - Duplicate assertions 
        (testing the same condition with multiple values should be parameterized)
    - Test methods that invoke multiple production methods (e.g. eager tests)
    - Test methods that invoke no production methods/functions (e.g. default/example tests)
    - Tests that mock the method/function being tested or its return value (e.g. fake tests)
    - Tests that only access parts of a fixture, instead of the whole fixture
    - Ignored/skipped tests (should be either deleted or fixed)
    - Numeric/string literals in assertions 
        (magic numbers and magic strings should be assigned to constants or fixtures, then asserted against)
    - Test methods that use real external resources (e.g. network, file system, database)
        (should be mocked, stubbed, faked, or controlled)
    - Tests methods that contain print/logging statements.
        (should be in the production code, not the test code)
    - Tests where assertions are either always true or always false (e.g. redundant assertions)
    - Tests that assume external resource availability without checking (e.g. resource optimism)
    - Tests that use 'str' or 'repr' in test methods (e.g. sensitive equality)
- Comprehensive unhappy path testing
- Clear, descriptive test naming in the 'test_when_x_then_y" format
- Test Method Docstrings that possess the following:
    - Written in the GIVEN/WHEN/THEN format that describes the test input (GIVEN), the action taken (WHEN), and the expected outcome (THEN)
    - Must include the name of the production method or function being tested.
    - Expected outcomes must be parameterizable (e.g. can be asserted against a predefined value or condition)
    - Expected outcomes must be a concrete behavior or outcome 
        (e.g. "returns X" instead of "completes successfully", "Y <= MAXIMUM_ALLOWED_TIME" instead of "completes in a reasonable time")
    - One and only one expected outcome per test stub (e.g. "returns X" instead of "returns X or Y")
- Class Docstrings that possess the following:
    - Short description of the group of scenarios being tested (e.g. error handling, input validation, etc.)
    - The production method or function being tested
    - Shared terminology and definitions (e.g. "valid input", "graceful failure")
"""
import unittest
from typing import List
from decimal import Decimal


# Example production classes to test
class Calculator:
    """A simple calculator with various mathematical operations."""
    
    def __init__(self, precision: int = 2):
        self._precision = precision
        self._history: List[str] = []
    
    def add(self, a: float, b: float) -> float:
        """Add two numbers and return the result."""
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            raise TypeError("Both arguments must be numbers")
        result = round(a + b, self._precision)
        self._history.append(f"{a} + {b} = {result}")
        return result
    
    def divide(self, dividend: float, divisor: float) -> float:
        """Divide dividend by divisor and return the result."""
        if not isinstance(dividend, (int, float)) or not isinstance(divisor, (int, float)):
            raise TypeError("Both arguments must be numbers")
        if divisor == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        result = round(dividend / divisor, self._precision)
        self._history.append(f"{dividend} / {divisor} = {result}")
        return result
    
    def get_history(self) -> List[str]:
        """Return a copy of the calculation history."""
        return self._history.copy()
    
    def clear_history(self) -> None:
        """Clear the calculation history."""
        self._history.clear()


class BankAccount:
    """A bank account with deposit, withdrawal, and transfer capabilities."""
    
    def __init__(self, account_id: str, initial_balance: Decimal = Decimal('0.00')):
        if not account_id or not isinstance(account_id, str):
            raise ValueError("Account ID must be a non-empty string")
        if initial_balance < 0:
            raise ValueError("Initial balance cannot be negative")
        
        self._account_id = account_id
        self._balance = initial_balance
        self._is_frozen = False
    
    def deposit(self, amount: Decimal) -> Decimal:
        """Deposit money into the account."""
        if self._is_frozen:
            raise RuntimeError("Account is frozen")
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        
        self._balance += amount
        return self._balance
    
    def withdraw(self, amount: Decimal) -> Decimal:
        """Withdraw money from the account."""
        if self._is_frozen:
            raise RuntimeError("Account is frozen")
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self._balance:
            raise ValueError("Insufficient funds")
        
        self._balance -= amount
        return self._balance
    
    def get_balance(self) -> Decimal:
        """Get the current account balance."""
        return self._balance
    
    def freeze_account(self) -> None:
        """Freeze the account to prevent transactions."""
        self._is_frozen = True
    
    def unfreeze_account(self) -> None:
        """Unfreeze the account to allow transactions."""
        self._is_frozen = False


class BaseTestCase(unittest.TestCase):
    """Base test case with common test constants and utilities."""
    
    def setUp(self) -> None:
        """Set up test constants used across test cases."""
        self.test_constants = {
            'VALID_NUMBER': 10.5,
            'ANOTHER_VALID_NUMBER': 5.25,
            'ZERO': 0,
            'NEGATIVE_NUMBER': -3.14,
            'LARGE_NUMBER': 999999.99,
            'VALID_ACCOUNT_ID': "ACC123456",
            'INITIAL_BALANCE': Decimal('100.00'),
            'DEPOSIT_AMOUNT': Decimal('50.00'),
            'WITHDRAWAL_AMOUNT': Decimal('25.00'),
            'PRECISION': 4,
            "INTEGER_ONE": 1,
            "INTEGER_TWO": 2,
            "VALID_FLOAT": 1.234567,
            "ANOTHER_VALID_FLOAT": 2.345678,
        }


class TestCalculatorAddition(BaseTestCase):
    """Test suite for Calculator addition functionality."""
    
    def setUp(self) -> None:
        """Set up Calculator instance and test constants for each test."""
        super().setUp()
        self.calculator = Calculator()
        self.calculator_with_precision = Calculator(precision=self.test_constants['PRECISION'])

    def test_when_adding_valid_number_and_another_valid_number_then_returns_correct_sum(self) -> None:
        """
        GIVEN Calculator instance and two valid positive float values
        WHEN add method is called with both values
        THEN expect float result equal to mathematical sum rounded to precision
        """
        # Arrange
        a = self.test_constants['VALID_NUMBER']
        b = self.test_constants['ANOTHER_VALID_NUMBER']
        expected = a + b

        # Act
        result = self.calculator.add(a, b)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected sum of {a} + {b} to equal {expected}, but got {result}")

    def test_when_adding_valid_number_and_negative_number_then_returns_correct_sum(self) -> None:
        """
        GIVEN Calculator instance, positive float value and negative float value
        WHEN add method is called with both values
        THEN expect float result equal to mathematical sum rounded to precision
        """
        # Arrange
        a = self.test_constants['VALID_NUMBER']
        b = self.test_constants['NEGATIVE_NUMBER']
        expected = a + b

        # Act
        result = self.calculator.add(a, b)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected sum of {a} + {b} to equal {expected}, but got {result}")

    def test_when_adding_valid_number_and_zero_then_returns_correct_sum(self) -> None:
        """
        GIVEN Calculator instance, positive float value and integer zero
        WHEN add method is called with both values
        THEN expect float result equal to mathematical sum rounded to precision
        """
        # Arrange
        a = self.test_constants['VALID_NUMBER']
        b = self.test_constants['ZERO']
        expected = a + b

        # Act
        result = self.calculator.add(a, b)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected sum of {a} + {b} to equal {expected}, but got {result}")

    def test_when_adding_large_numbers_then_returns_correct_sum(self) -> None:
        """
        GIVEN Calculator instance and two large float values
        WHEN add method is called with both values
        THEN expect float result equal to mathematical sum rounded to precision
        """
        # Arrange
        a = self.test_constants['LARGE_NUMBER']
        b = self.test_constants['LARGE_NUMBER']
        expected = a + b

        # Act
        result = self.calculator.add(a, b)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected sum of {a} + {b} to equal {expected}, but got {result}")

    def test_when_adding_with_custom_precision_then_rounds_to_specified_precision(self) -> None:
        """
        GIVEN Calculator instance with custom precision configuration and high-precision float inputs
        WHEN add method is called with both values
        THEN expect float result rounded to configured decimal places
        """
        # Arrange
        a = self.test_constants['VALID_FLOAT']
        b = self.test_constants['ANOTHER_VALID_FLOAT']
        expected = round(a + b, self.test_constants['PRECISION'])

        # Act
        result = self.calculator_with_precision.add(a, b)

        # Assert
        self.assertEqual(result, expected, 
                        f"Result should be rounded to {self.test_constants['PRECISION']} places, got {result} instead of {expected}")

    def test_when_adding_string_first_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, string first argument and numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_input = "not_a_number"
        valid_input = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(invalid_input, valid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_none_first_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, None first argument and numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_input = None
        valid_input = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(invalid_input, valid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_list_first_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, list first argument and numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_input = []
        valid_input = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(invalid_input, valid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_dict_first_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, dict first argument and numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_input = {}
        valid_input = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(invalid_input, valid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_string_second_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric first argument and string second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_input = 5.0
        invalid_input = "not_a_number"

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(valid_input, invalid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_none_second_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric first argument and None second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_input = 5.0
        invalid_input = None

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(valid_input, invalid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_list_second_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric first argument and list second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_input = 5.0
        invalid_input = []

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(valid_input, invalid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_adding_dict_second_argument_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric first argument and dict second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_input = 5.0
        invalid_input = {}

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.add(valid_input, invalid_input)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))


class TestCalculatorDivision(BaseTestCase):
    """Test suite for Calculator division functionality."""
    
    def setUp(self) -> None:
        """Set up Calculator instance and test constants for each test."""
        super().setUp()
        self.calculator = Calculator()

    def test_when_dividing_valid_number_by_another_valid_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance and two valid positive float values
        WHEN divide method is called with dividend and divisor
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['VALID_NUMBER']
        divisor = self.test_constants['ANOTHER_VALID_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_valid_number_by_large_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, smaller positive float dividend and larger positive float divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['VALID_NUMBER']
        divisor = self.test_constants['LARGE_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_large_number_by_valid_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, larger positive float dividend and smaller positive float divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['LARGE_NUMBER']
        divisor = self.test_constants['VALID_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_zero_by_valid_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, integer zero dividend and positive float divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['ZERO']
        divisor = self.test_constants['VALID_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_negative_number_by_valid_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, negative float dividend and positive float divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['NEGATIVE_NUMBER']
        divisor = self.test_constants['VALID_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_valid_number_by_negative_number_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, positive float dividend and negative float divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['VALID_NUMBER']
        divisor = self.test_constants['NEGATIVE_NUMBER']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_valid_number_by_integer_one_then_returns_correct_quotient(self) -> None:
        """
        GIVEN Calculator instance, positive float dividend and integer one divisor
        WHEN divide method is called with both values
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = self.test_constants['VALID_NUMBER']
        divisor = self.test_constants['INTEGER_ONE']
        expected = round(dividend / divisor, 2)
        
        # Act
        result = self.calculator.divide(dividend, divisor)
        
        # Assert
        self.assertEqual(result, expected, 
                        f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}")

    def test_when_dividing_negative_by_positive_then_returns_negative_quotient(self) -> None:
        """
        GIVEN Calculator instance, negative float dividend and positive float divisor
        WHEN divide method is called with both values
        THEN expect float result less than zero
        """
        # Arrange
        negative_num = self.test_constants['NEGATIVE_NUMBER']
        positive_num = self.test_constants['VALID_NUMBER']

        # Act
        result = self.calculator.divide(negative_num, positive_num)

        # Assert
        self.assertLess(result, 0, 
                       f"Expected quotient of {negative_num} / {positive_num} to be negative, but got {result}")

    def test_when_dividend_negative_by_negative_then_returns_positive_quotient(self) -> None:
        """
        GIVEN Calculator instance, negative float dividend and negative float divisor
        WHEN divide method is called with both values
        THEN expect float result greater than zero
        """
        # Arrange
        negative_num = self.test_constants['NEGATIVE_NUMBER']
        another_negative_num = -self.test_constants['ANOTHER_VALID_NUMBER']

        # Act
        result = self.calculator.divide(negative_num, another_negative_num)

        # Assert
        self.assertGreater(result, 0, 
                          f"Expected quotient of {negative_num} / {another_negative_num} to be positive, but got {result}")

    def test_when_dividing_by_zero_then_raises_zero_division_error(self) -> None:
        """
        GIVEN Calculator instance, valid float dividend and integer zero as divisor
        WHEN divide method is called with both values
        THEN expect ZeroDivisionError with message containing 'Cannot divide by zero'
        """
        # Arrange
        number = self.test_constants['VALID_NUMBER']
        zero = self.test_constants['ZERO']

        # Act & Assert
        with self.assertRaises(ZeroDivisionError) as context:
            self.calculator.divide(number, zero)
        
        self.assertIn("Cannot divide by zero", str(context.exception))

    def test_when_dividing_string_dividend_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, string dividend and numeric divisor
        WHEN divide method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_dividend = "not_a_number"
        valid_divisor = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.divide(invalid_dividend, valid_divisor)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_dividing_by_string_divisor_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric dividend and string divisor
        WHEN divide method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_dividend = 5.0
        invalid_divisor = "not_a_number"

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.divide(valid_dividend, invalid_divisor)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_dividing_none_dividend_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, None dividend and numeric divisor
        WHEN divide method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        invalid_dividend = None
        valid_divisor = 5.0

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.divide(invalid_dividend, valid_divisor)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))

    def test_when_dividing_by_none_divisor_then_raises_type_error(self) -> None:
        """
        GIVEN Calculator instance, numeric dividend and None divisor
        WHEN divide method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Arrange
        valid_dividend = 5.0
        invalid_divisor = None

        # Act & Assert
        with self.assertRaises(TypeError) as context:
            self.calculator.divide(valid_dividend, invalid_divisor)
        
        self.assertIn("Both arguments must be numbers", str(context.exception))


class TestCalculatorHistory(BaseTestCase):
    """Test suite for Calculator history functionality."""
    
    def setUp(self) -> None:
        """Set up Calculator instances with different history states for each test."""
        super().setUp()
        self.calculator = Calculator()
        
        # Calculator with one operation in history
        self.calculator_with_one_history = Calculator()
        self.calculator_with_one_history.add(
            self.test_constants['INTEGER_ONE'], 
            self.test_constants['INTEGER_ONE']
        )
        
        # Calculator with two operations in history
        self.calculator_with_two_history = Calculator()
        self.calculator_with_two_history.add(
            self.test_constants['INTEGER_ONE'], 
            self.test_constants['INTEGER_ONE']
        )
        self.calculator_with_two_history.add(
            self.test_constants['INTEGER_TWO'], 
            self.test_constants['INTEGER_TWO']
        )
        
        # Calculator with cleared history
        self.calculator_with_cleared_history = Calculator()
        self.calculator_with_cleared_history.add(
            self.test_constants['INTEGER_ONE'], 
            self.test_constants['INTEGER_ONE']
        )
        self.calculator_with_cleared_history.clear_history()
    
    def test_when_new_calculator_created_then_history_is_a_list(self) -> None:
        """
        GIVEN newly instantiated Calculator instance
        WHEN get_history method is called
        THEN expect method return to be a list type
        """
        # Act
        history = self.calculator.get_history()

        # Assert
        self.assertIsInstance(history, list, f"Expected history to be list type, but got {type(history)}")

    def test_when_new_calculator_created_then_history_is_empty(self) -> None:
        """
        GIVEN newly instantiated Calculator instance
        WHEN get_history method is called
        THEN expect method return to have a length of zero
        """
        # Act
        history = self.calculator.get_history()

        # Assert
        self.assertEqual(len(history), 0, f"Expected history length to be 0, but got {len(history)}")

    def test_when_add_performed_then_history_records_number_of_operations(self) -> None:
        """
        GIVEN Calculator instance with add method called in sequence
        WHEN get_history method is called
        THEN expect list length to match number of operations performed
        """
        # Arrange
        expected_len = 2

        # Act
        history = self.calculator_with_two_history.get_history()

        # Assert
        self.assertEqual(len(history), expected_len, 
                        f"Expected history length to be {expected_len}, but got {len(history)}")

    def test_when_operations_performed_then_history_records_order_of_operations(self) -> None:
        """
        GIVEN Calculator instance where add methods were called in sequence
        WHEN get_history method is called
        THEN expect list containing string representations of both operations in order
        """
        # Arrange
        add_a = self.test_constants['INTEGER_ONE']
        add_b = self.test_constants['INTEGER_ONE']
        add_c = self.test_constants['INTEGER_TWO']
        add_d = self.test_constants['INTEGER_TWO']
        expected_list = [f"{add_a} + {add_b} = {add_a + add_b}", f"{add_c} + {add_d} = {add_c + add_d}"]

        # Act
        history = self.calculator_with_two_history.get_history()

        # Assert
        self.assertEqual(history, expected_list, f"Expected history to be {expected_list}, but got {history}")

    def test_when_history_cleared_then_history_becomes_empty(self) -> None:
        """
        GIVEN Calculator instance with existing operations in history
        WHEN clear_history method is called
        THEN expect get_history to return empty list with length of zero
        """
        # Act
        history = self.calculator_with_cleared_history.get_history()

        # Assert
        self.assertEqual(len(history), 0, f"Expected history length to be 0 after clearing, but got {len(history)}")

    def test_when_getting_history_then_returns_copy_not_reference(self) -> None:
        """
        GIVEN Calculator instance with one operation in history
        WHEN get_history method is called multiple times and first returned list is modified
        THEN expect second returned list to not match the modified first list
        """
        # Act
        history1 = self.calculator_with_one_history.get_history()
        history2 = self.calculator_with_one_history.get_history()
        history1.append("modified")

        # Assert
        self.assertNotEqual(len(history1), len(history2), 
                           f"Expected modified history1 length {len(history1)} to differ from history2 length {len(history2)}")

    def test_when_getting_history_multiple_times_then_returns_are_decoupled(self) -> None:
        """
        GIVEN Calculator instance with one operation in history
        WHEN get_history method is called multiple times and first returned list is modified
        THEN expect second returned list to remain unchanged with original length
        """
        # Act
        history1 = self.calculator_with_one_history.get_history()
        history2 = self.calculator_with_one_history.get_history()
        original_length = len(history2)
        history1.append("modified")

        # Assert
        self.assertEqual(len(history2), original_length, 
                        f"Expected history2 length to remain {original_length}, but got {len(history2)}")


class TestBankAccountConstruction(BaseTestCase):
    """Test suite for BankAccount construction functionality."""
    
    def setUp(self) -> None:
        """Set up test constants for each test."""
        super().setUp()

    def test_when_creating_account_with_valid_id_and_zero_balance_then_succeeds(self) -> None:
        """
        GIVEN valid account ID string and zero initial balance Decimal
        WHEN BankAccount constructor is called with both values
        THEN expect successful instantiation without exceptions
        """
        # Arrange
        account_id = self.test_constants['VALID_ACCOUNT_ID']
        initial_balance = Decimal('0.00')

        # Act & Assert (no exception should be raised)
        account = BankAccount(account_id, initial_balance)
        self.assertIsInstance(account, BankAccount)

    def test_when_creating_account_with_empty_string_id_then_raises_value_error(self) -> None:
        """
        GIVEN empty string account ID and valid initial balance Decimal
        WHEN BankAccount constructor is called with both values
        THEN expect ValueError with message containing 'Account ID must be a non-empty string'
        """
        # Arrange
        account_id = ""
        initial_balance = self.test_constants['INITIAL_BALANCE']

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            BankAccount(account_id, initial_balance)
        
        self.assertIn("Account ID must be a non-empty string", str(context.exception))

    def test_when_creating_account_with_none_id_then_raises_value_error(self) -> None:
        """
        GIVEN None account ID and valid initial balance Decimal
        WHEN BankAccount constructor is called with both values
        THEN expect ValueError with message containing 'Account ID must be a non-empty string'
        """
        # Arrange
        account_id = None
        initial_balance = self.test_constants['INITIAL_BALANCE']

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            BankAccount(account_id, initial_balance)
        
        self.assertIn("Account ID must be a non-empty string", str(context.exception))

    def test_when_creating_account_with_negative_balance_then_raises_value_error(self) -> None:
        """
        GIVEN valid account ID string and negative initial balance Decimal
        WHEN BankAccount constructor is called with both values
        THEN expect ValueError with message containing 'Initial balance cannot be negative'
        """
        # Arrange
        account_id = self.test_constants['VALID_ACCOUNT_ID']
        initial_balance = Decimal('-10.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            BankAccount(account_id, initial_balance)
        
        self.assertIn("Initial balance cannot be negative", str(context.exception))


class TestBankAccountDeposit(BaseTestCase):
    """Test suite for BankAccount deposit functionality."""
    
    def setUp(self) -> None:
        """Set up BankAccount instances for each test."""
        super().setUp()
        self.bank_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.zero_balance_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            Decimal('0.00')
        )
        self.frozen_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.frozen_account.freeze_account()

    def test_when_depositing_positive_amount_then_returns_updated_balance(self) -> None:
        """
        GIVEN BankAccount instance with positive balance and positive deposit amount
        WHEN deposit method is called with amount
        THEN expect Decimal result equal to previous balance plus deposit amount
        """
        # Arrange
        amount = self.test_constants['DEPOSIT_AMOUNT']
        expected = self.test_constants['INITIAL_BALANCE'] + amount

        # Act
        result = self.bank_account.deposit(amount)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance after deposit to be {expected}, but got {result}")

    def test_when_depositing_to_zero_balance_then_returns_deposit_amount(self) -> None:
        """
        GIVEN BankAccount instance with zero balance and positive deposit amount
        WHEN deposit method is called with amount
        THEN expect Decimal result equal to deposit amount
        """
        # Arrange
        amount = self.test_constants['DEPOSIT_AMOUNT']
        expected = amount

        # Act
        result = self.zero_balance_account.deposit(amount)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance after deposit to be {expected}, but got {result}")

    def test_when_depositing_zero_amount_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance and zero deposit amount
        WHEN deposit method is called with zero amount
        THEN expect ValueError with message containing 'Deposit amount must be positive'
        """
        # Arrange
        amount = Decimal('0.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.bank_account.deposit(amount)
        
        self.assertIn("Deposit amount must be positive", str(context.exception))

    def test_when_depositing_negative_amount_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance and negative deposit amount
        WHEN deposit method is called with negative amount
        THEN expect ValueError with message containing 'Deposit amount must be positive'
        """
        # Arrange
        amount = Decimal('-10.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.bank_account.deposit(amount)
        
        self.assertIn("Deposit amount must be positive", str(context.exception))

    def test_when_depositing_to_frozen_account_then_raises_runtime_error(self) -> None:
        """
        GIVEN frozen BankAccount instance and positive deposit amount
        WHEN deposit method is called with amount
        THEN expect RuntimeError with message containing 'Account is frozen'
        """
        # Arrange
        amount = self.test_constants['DEPOSIT_AMOUNT']

        # Act & Assert
        with self.assertRaises(RuntimeError) as context:
            self.frozen_account.deposit(amount)
        
        self.assertIn("Account is frozen", str(context.exception))


class TestBankAccountWithdrawal(BaseTestCase):
    """Test suite for BankAccount withdrawal functionality."""
    
    def setUp(self) -> None:
        """Set up BankAccount instances for each test."""
        super().setUp()
        self.bank_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.zero_balance_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            Decimal('0.00')
        )
        self.frozen_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.frozen_account.freeze_account()

    def test_when_withdrawing_valid_amount_then_returns_updated_balance(self) -> None:
        """
        GIVEN BankAccount instance with sufficient balance and valid withdrawal amount
        WHEN withdraw method is called with amount
        THEN expect Decimal result equal to previous balance minus withdrawal amount
        """
        # Arrange
        amount = self.test_constants['WITHDRAWAL_AMOUNT']
        expected = self.test_constants['INITIAL_BALANCE'] - amount

        # Act
        result = self.bank_account.withdraw(amount)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance after withdrawal to be {expected}, but got {result}")

    def test_when_withdrawing_zero_amount_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance and zero withdrawal amount
        WHEN withdraw method is called with zero amount
        THEN expect ValueError with message containing 'Withdrawal amount must be positive'
        """
        # Arrange
        amount = Decimal('0.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.bank_account.withdraw(amount)
        
        self.assertIn("Withdrawal amount must be positive", str(context.exception))

    def test_when_withdrawing_negative_amount_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance and negative withdrawal amount
        WHEN withdraw method is called with negative amount
        THEN expect ValueError with message containing 'Withdrawal amount must be positive'
        """
        # Arrange
        amount = Decimal('-10.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.bank_account.withdraw(amount)
        
        self.assertIn("Withdrawal amount must be positive", str(context.exception))

    def test_when_withdrawing_more_than_balance_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance and withdrawal amount exceeding current balance
        WHEN withdraw method is called with excessive amount
        THEN expect ValueError with message containing 'Insufficient funds'
        """
        # Arrange
        amount = self.test_constants['INITIAL_BALANCE'] + Decimal('50.00')

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.bank_account.withdraw(amount)
        
        self.assertIn("Insufficient funds", str(context.exception))

    def test_when_withdrawing_from_zero_balance_then_raises_value_error(self) -> None:
        """
        GIVEN BankAccount instance with zero balance and positive withdrawal amount
        WHEN withdraw method is called with amount
        THEN expect ValueError with message containing 'Insufficient funds'
        """
        # Arrange
        amount = self.test_constants['WITHDRAWAL_AMOUNT']

        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.zero_balance_account.withdraw(amount)
        
        self.assertIn("Insufficient funds", str(context.exception))

    def test_when_withdrawing_from_frozen_account_then_raises_runtime_error(self) -> None:
        """
        GIVEN frozen BankAccount instance and valid withdrawal amount
        WHEN withdraw method is called with amount
        THEN expect RuntimeError with message containing 'Account is frozen'
        """
        # Arrange
        amount = self.test_constants['WITHDRAWAL_AMOUNT']

        # Act & Assert
        with self.assertRaises(RuntimeError) as context:
            self.frozen_account.withdraw(amount)
        
        self.assertIn("Account is frozen", str(context.exception))


class TestBankAccountBalance(BaseTestCase):
    """Test suite for BankAccount balance functionality."""
    
    def setUp(self) -> None:
        """Set up BankAccount instances for each test."""
        super().setUp()
        self.bank_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.zero_balance_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            Decimal('0.00')
        )

    def test_when_getting_balance_then_returns_current_balance(self) -> None:
        """
        GIVEN BankAccount instance with known initial balance
        WHEN get_balance method is called
        THEN expect Decimal result equal to initial balance
        """
        # Arrange
        expected = self.test_constants['INITIAL_BALANCE']

        # Act
        result = self.bank_account.get_balance()

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance to be {expected}, but got {result}")

    def test_when_getting_zero_balance_then_returns_zero(self) -> None:
        """
        GIVEN BankAccount instance with zero initial balance
        WHEN get_balance method is called
        THEN expect Decimal result equal to zero
        """
        # Arrange
        expected = Decimal('0.00')

        # Act
        result = self.zero_balance_account.get_balance()

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance to be {expected}, but got {result}")

    def test_when_creating_account_with_valid_id_and_balance_then_returns_account(self) -> None:
        """
        GIVEN valid account ID string and valid initial balance Decimal
        WHEN BankAccount constructor is called with both values
        THEN expect resulting instance to be of type BankAccount
        """
        # Arrange
        account_id = self.test_constants['VALID_ACCOUNT_ID']
        initial_balance = self.test_constants['INITIAL_BALANCE']
        # Act
        account = BankAccount(account_id, initial_balance)
        # Assert
        self.assertIsInstance(account, BankAccount, 
                              f"Expected account to be of type BankAccount, but got {type(account)}")


class TestBankAccountFreezing(BaseTestCase):
    """Test suite for BankAccount freezing functionality."""
    
    def setUp(self) -> None:
        """Set up BankAccount instances for each test."""
        super().setUp()
        self.bank_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.frozen_account = BankAccount(
            self.test_constants['VALID_ACCOUNT_ID'],
            self.test_constants['INITIAL_BALANCE']
        )
        self.frozen_account.freeze_account()


    def test_when_freezing_account_then_subsequent_deposit_raises_runtime_error(self) -> None:
        """
        GIVEN BankAccount instance that has been frozen
        WHEN deposit method is called with valid amount
        THEN expect RuntimeError with message containing 'Account is frozen'
        """
        # Arrange
        self.bank_account.freeze_account()
        amount = self.test_constants['DEPOSIT_AMOUNT']

        # Act & Assert
        with self.assertRaises(RuntimeError) as context:
            self.bank_account.deposit(amount)
        
        self.assertIn("Account is frozen", str(context.exception))

    def test_when_freezing_account_then_subsequent_withdrawal_raises_runtime_error(self) -> None:
        """
        GIVEN BankAccount instance that has been frozen
        WHEN withdraw method is called with valid amount
        THEN expect RuntimeError with message containing 'Account is frozen'
        """
        # Arrange
        self.bank_account.freeze_account()
        amount = self.test_constants['WITHDRAWAL_AMOUNT']

        # Act & Assert
        with self.assertRaises(RuntimeError) as context:
            self.bank_account.withdraw(amount)
        
        self.assertIn("Account is frozen", str(context.exception))

    def test_when_unfreezing_account_then_deposit_succeeds(self) -> None:
        """
        GIVEN frozen BankAccount instance that has been unfrozen
        WHEN deposit method is called with valid amount
        THEN expect successful deposit with updated balance returned
        """
        # Arrange
        self.frozen_account.unfreeze_account()
        amount = self.test_constants['DEPOSIT_AMOUNT']
        expected = self.test_constants['INITIAL_BALANCE'] + amount

        # Act
        result = self.frozen_account.deposit(amount)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance after deposit to be {expected}, but got {result}")

    def test_when_unfreezing_account_then_withdrawal_succeeds(self) -> None:
        """
        GIVEN frozen BankAccount instance that has been unfrozen
        WHEN withdraw method is called with valid amount
        THEN expect successful withdrawal with updated balance returned
        """
        # Arrange
        self.frozen_account.unfreeze_account()
        amount = self.test_constants['WITHDRAWAL_AMOUNT']
        expected = self.test_constants['INITIAL_BALANCE'] - amount

        # Act
        result = self.frozen_account.withdraw(amount)

        # Assert
        self.assertEqual(result, expected, 
                        f"Expected balance after withdrawal to be {expected}, but got {result}")


if __name__ == '__main__':
    unittest.main()

