"""
Perfect Test Suite Template using pytest

This module demonstrates best practices for unit testing with pytest based on:
- Testing through public contracts only (e.g. no testing private callables, attributes, and properties)
- Testing behavior, not implementation details
- Following AAA (Arrange, Act, Assert) pattern
- Avoiding the following test smells:
    - Test methods longer than 10 lines, excluding docstrings.
    - Test methods with more than 1 assertion
    - Test methods with no assertions (e.g. unknown tests)
    - Test methods with conditional logic (e.g., if/else, for/while loops)
    - Test methods that fail/pass based on the test itself throwing an exception (e.g. try/except blocks)
    - Test methods with constructor initialization (.e.g __init__ method)
    - Tests without executable statements (e.g. empty tests)
    - Assertions with either no or non-descriptive messages (i.e. Assertion Roulette)
    - Default/example tests
    - Duplicate assertions (e.g. testing the same condition with multiple values)
    - Test methods that invoke multiple production methods (e.g. eager tests)
    - Tests that only access parts of a fixture, instead of the whole fixture
    - Ignored/skipped tests
    - Numeric/string literals in assertions (e.g. magic numbers, magic strings)
    - Test method uses external resources (e.g. network, file system, database)
    - Tests methods that contain print/logging statements.
    - Tests where assertions are either always true or always false (e.g. redundant assertions)
    - Tests that assume external resource availability without checking (e.g. resource optimism)
    - Tests that use 'str' or 'repr' in test methods (e.g. sensitive equality)
- Comprehensive unhappy path testing
- Clear, descriptive test naming in "test_when_XYZ_then_ABC" format
- Docstrings in the GIVEN/WHEN/THEN format
"""
import pytest
from typing import List, Optional, Dict, Any
from decimal import Decimal
import tempfile
import os


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


# Test Fixtures
@pytest.fixture
def test_constants():
    """Provide common test constants."""
    return {
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


@pytest.fixture
def calculator():
    """Create a Calculator instance for testing."""
    return Calculator()


@pytest.fixture
def calculator_with_precision(test_constants):
    """Create a Calculator instance with custom precision."""
    return Calculator(precision=test_constants['PRECISION'])


@pytest.fixture
def calculator_with_one_history(test_constants):
    """Create a Calculator instance with history enabled."""
    calculator = Calculator()
    # Add an initial operation to history
    calculator.add(test_constants['INTEGER_ONE'], test_constants['INTEGER_ONE']) 
    return calculator

@pytest.fixture
def calculator_with_two_history(calculator_with_one_history, test_constants):
    """Create a Calculator instance with two operations in history."""
    calculator_with_one_history.add(test_constants['INTEGER_TWO'], test_constants['INTEGER_TWO'])
    return calculator_with_one_history

@pytest.fixture
def  calculator_with_cleared_history(calculator_with_one_history):
    """Create a Calculator instance with cleared history."""
    calculator_with_one_history.clear_history()
    return calculator_with_one_history

@pytest.fixture
def bank_account(test_constants):
    """Create a BankAccount instance for testing."""
    return BankAccount(
        test_constants['VALID_ACCOUNT_ID'],
        test_constants['INITIAL_BALANCE']
    )


@pytest.fixture
def zero_balance_account(test_constants):
    """Create a BankAccount instance with zero balance."""
    return BankAccount(
        test_constants['VALID_ACCOUNT_ID'],
        Decimal('0.00')
    )


@pytest.fixture
def frozen_account(bank_account):
    """Create a frozen BankAccount instance."""
    bank_account.freeze_account()
    return bank_account


class TestCalculatorAddition:
    """Test suite for Calculator addition functionality."""


    @pytest.mark.parametrize("a,b", [
        ('VALID_NUMBER', 'ANOTHER_VALID_NUMBER'),
        ('VALID_NUMBER', 'NEGATIVE_NUMBER'),
        ('VALID_NUMBER', 'ZERO'),
        ('LARGE_NUMBER', 'LARGE_NUMBER'),
    ])
    def test_when_adding_two_numbers_then_returns_correct_sum(self, calculator, test_constants, a,b):
        """
        GIVEN Calculator instance and two valid values
        WHEN add method is called with both values
        THEN expect float result equal to mathematical sum rounded to precision
        """
        # Arrange
        a, b = test_constants[a], test_constants[b]
        expected = a + b

        # Act
        result = calculator.add(a, b)

        # Assert
        assert result == expected, f"Expected sum of {a} + {b} to equal {expected}, but got {result}"


    def test_when_adding_with_custom_precision_then_rounds_to_specified_precision(self, 
        calculator_with_precision, test_constants):
        """
        GIVEN Calculator instance with custom precision configuration and high-precision float inputs
        WHEN add method is called with both values
        THEN expect float result rounded to configured decimal places
        """
        # Arrange
        a, b = test_constants['VALID_FLOAT'], test_constants['ANOTHER_VALID_FLOAT']
        expected = round(a + b, test_constants['PRECISION'])

        # Act
        result = calculator_with_precision.add(a, b)

        # Assert
        assert result == expected, \
            f"Result should be rounded to {test_constants['PRECISION']} places, got {result} instead of {expected}"


    @pytest.mark.parametrize("invalid_input,valid_input", [
        ("not_a_number", 5.0),
        (None, 5.0),
        ([], 5.0),
        ({}, 5.0),
    ])
    def test_when_adding_non_numeric_first_argument_then_raises_type_error(self, 
        calculator, invalid_input, valid_input):
        """
        GIVEN Calculator instance, non-numeric first argument and numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Act & Assert
        with pytest.raises(TypeError, match="Both arguments must be numbers"):
            calculator.add(invalid_input, valid_input)


    @pytest.mark.parametrize("valid_input,invalid_input", [
        (5.0, "not_a_number"),
        (5.0, None),
        (5.0, []),
        (5.0, {}),
    ])
    def test_when_adding_non_numeric_second_argument_then_raises_type_error(self, calculator, valid_input, invalid_input):
        """
        GIVEN Calculator instance, numeric first argument and non-numeric second argument
        WHEN add method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Act & Assert
        with pytest.raises(TypeError, match="Both arguments must be numbers"):
            calculator.add(valid_input, invalid_input)


class TestCalculatorDivision:
    """Test suite for Calculator division functionality."""

    @pytest.mark.parametrize("dividend,divisor", [
        ('VALID_NUMBER', 'ANOTHER_VALID_NUMBER'),
        ('VALID_NUMBER', 'LARGE_NUMBER'),
        ('LARGE_NUMBER', 'VALID_NUMBER'),
        ('ZERO', 'VALID_NUMBER'),
        ('NEGATIVE_NUMBER', 'VALID_NUMBER'),
        ('VALID_NUMBER', 'NEGATIVE_NUMBER'),
        ('VALID_NUMBER', 'INTEGER_ONE'),
    ])
    def test_when_dividing_positive_numbers_then_returns_correct_quotient(self, 
        calculator, test_constants, dividend, divisor):
        """
        GIVEN Calculator instance and two valid float values
        WHEN divide method is called with dividend and divisor
        THEN expect float result equal to mathematical quotient rounded to precision
        """
        # Arrange
        dividend = test_constants[dividend]
        divisor = test_constants[dividend]
        expected = round(dividend / divisor, 2)
        
        # Act
        result = calculator.divide(dividend, divisor)
        
        # Assert
        assert result == expected, \
            f"Expected quotient of {dividend} / {divisor} to equal {expected}, but got {result}"


    def test_when_dividing_negative_by_positive_then_returns_negative_quotient(self, calculator, test_constants):
        """
        GIVEN Calculator instance, negative float dividend and positive float divisor
        WHEN divide method is called with both values
        THEN expect float result less than zero
        """
        # Arrange
        negative_num = test_constants['NEGATIVE_NUMBER']
        positive_num = test_constants['VALID_NUMBER']

        # Act
        result = calculator.divide(negative_num, positive_num)

        # Assert
        assert result < 0, \
            f"Expected quotient of {negative_num} / {positive_num} to be negative, but got {result}"


    def test_when_dividend_negative_by_negative_then_returns_positive_quotient(self, calculator, test_constants):
        """
        GIVEN Calculator instance, negative float dividend and negative float divisor
        WHEN divide method is called with both values
        THEN expect float result greater than zero
        """
        # Arrange
        negative_num = test_constants['NEGATIVE_NUMBER']
        another_negative_num = -test_constants['ANOTHER_VALID_NUMBER']

        # Act
        result = calculator.divide(negative_num, another_negative_num)

        # Assert
        assert result > 0, \
            f"Expected quotient of {negative_num} / {another_negative_num} to be positive, but got {result}"


    def test_when_dividing_by_zero_then_raises_zero_division_error(self, calculator, test_constants):
        """
        GIVEN Calculator instance, valid float dividend and integer zero as divisor
        WHEN divide method is called with both values
        THEN expect ZeroDivisionError with message containing 'Cannot divide by zero'
        """
        # Arrange
        number = test_constants['VALID_NUMBER']
        zero = test_constants['ZERO']

        # Act & Assert
        with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
            calculator.divide(number, zero)

    @pytest.mark.parametrize("invalid_dividend,invalid_divisor", [
        ("not_a_number", 5.0),
        (5.0, "not_a_number"),
        (None, 5.0),
        (5.0, None),
    ])
    def test_when_dividing_non_numeric_values_then_raises_type_error(self, calculator, invalid_dividend, invalid_divisor):
        """
        GIVEN Calculator instance and at least one non-numeric argument
        WHEN divide method is called with both arguments
        THEN expect TypeError with message containing 'Both arguments must be numbers'
        """
        # Act & Assert
        with pytest.raises(TypeError, match="Both arguments must be numbers"):
            calculator.divide(invalid_dividend, invalid_divisor)


class TestCalculatorHistory:
    """Test suite for Calculator history functionality."""
    
    def test_when_new_calculator_created_then_history_is_a_list(self, calculator):
        """
        GIVEN newly instantiated Calculator instance
        WHEN get_history method is called
        THEN expect method return to be a list type
        """
        # Act/Arrange
        history = calculator.get_history()

        # Assert
        assert isinstance(history, list), f"Expected history to be list type, but got {type(history)}"

    def test_when_new_calculator_created_then_history_is_empty(self, calculator):
        """
        GIVEN newly instantiated Calculator instance
        WHEN get_history method is called
        THEN expect method return to have a length of zero
        """
        # Act/Arrange
        history = calculator.get_history()

        # Assert
        assert len(history) == 0, f"Expected history length to be 0, but got {len(history)}"

    def test_when_add_performed_then_history_records_number_of_operations(self, calculator_with_two_history):
        """
        GIVEN Calculator instance with add method is called in sequence
        WHEN get_history method is called
        THEN expect list length to match number of operations performed
        """
        # Arrange
        expected_len = 2

        # Act
        history = calculator_with_two_history.get_history()

        # Assert
        assert len(history) == expected_len, \
            f"Expected history length to be {expected_len}, but got {len(history)}"

    def test_when_operations_performed_then_history_records_order_of_operations(self, 
        calculator_with_two_history, test_constants):
        """
        GIVEN Calculator instance where add methods were called in sequence
        WHEN get_history method is called
        THEN expect list containing string representations of both operations in order
        """
        # Arrange
        add_a, add_b = test_constants['INTEGER_ONE'], test_constants['INTEGER_ONE']
        add_c, add_d = test_constants['INTEGER_TWO'], test_constants['INTEGER_TWO']
        expected_list = [f"{add_a} + {add_b} = {add_a + add_b}", f"{add_c} + {add_d} = {add_c + add_d}"]

        # Act
        history = calculator_with_two_history.get_history()

        # Assert
        assert history == expected_list, f"Expected history to be {expected_list}, but got {history}"

    def test_when_history_cleared_then_history_becomes_empty(self, calculator_with_cleared_history):
        """
        GIVEN Calculator instance with existing operations in history
        WHEN clear_history method is called
        THEN expect get_history to return empty list with length of zero
        """
        # Arrange/Act
        history = calculator_with_cleared_history.get_history()

        # Assert
        assert len(history) == 0, f"Expected history length to be 0 after clearing, but got {len(history)}"

    def test_when_getting_history_then_returns_copy_not_reference(self, calculator_with_one_history):
        """
        GIVEN Calculator instance with one operation in history
        WHEN get_history method is called multiple times and first returned list is modified
        THEN expect second returned list to not match the modified first list
        """
        # Arrange/Act
        history1 = calculator_with_one_history.get_history()
        history2 = calculator_with_one_history.get_history()
        history1.append("modified")

        # Assert
        assert len(history1) != len(history2), \
            f"Expected modified history1 length {len(history1)} to differ from history2 length {len(history2)}"

    def test_when_getting_history_multiple_times_then_returns_are_decoupled(self, calculator_with_one_history):
        """
        GIVEN Calculator instance with one operation in history
        WHEN get_history method is called multiple times and first returned list is modified
        THEN expect second returned list to remain unchanged with original length
        """
        # Arrange/Act
        history1 = calculator_with_one_history.get_history()
        history2 = calculator_with_one_history.get_history()
        original_length = len(history2)
        history1.append("modified")

        # Assert
        assert len(history2) == original_length, \
            f"Expected history2 length to remain {original_length}, but got {len(history2)}"

