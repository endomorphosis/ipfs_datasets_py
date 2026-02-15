"""
A Monad is a design pattern in functional programming focused on chaining functions.
Simply put, a Monad is a box that a function runs inside of, and returns a new box with that function's result.
```python
>>> def add_one(x):
...     return x + 1
>>> the_results = Monad(add_one(5))
>>> print(the_results.value)
'6'
```
The key operations in a Monad are:
- `unit`: Wrap a value in a monad. This can also be done directly by calling the constructor.
- `bind` (or flatmap): Apply a function to the value inside the monad, and return a new monad with the result.
```python
>>> the_results = Monad(5)
>>> print(type(the_results))
'Monad'
# unit
>>> units_results = Monad.unit(5)
>>> print(type(units_results))
'Monad'
# bind
>>> the_results = Monad.unit(5).bind(add_one(5))
>>> print(the_results.value)
'6'
```
Because the result of `bind` is another Monad, we can chain functions using it.
```python
>>> def multiply_by_two(x):
...     return x * 2
>>> the_results = Monad(5).bind(add_one).bind(multiply_by_two)
>>> print(the_results.value)
'12'
```
As Python allows for operators to be re-assigned in classes, we can bind the `bind` method to the `>>` operator.
This allows for a more natural syntax when chaining functions.
```python
>>> the_results = Monad(5).bind(add_one).bind(multiply_by_two)
>>> print(the_results.value)
'12'
>>> the_results = Monad(5) >> add_one >> multiply_by_two
>>> print(the_results.value)
'12'
```
Monads can be sub-typed that attach side-effects to them, such as logging, error handling, and logic.
For example, the IO Monad logs the inputs and outputs of each function in the chain.
```python
>>> def add_one(x):
...     return x + 1
>>> def multiply_by_two(x):
...     return x * 2
>>> result = IOMonad(5) >> add_one >> multiply_by_two
'add_one input is 5', 'add_one output is 6', 'multiply_by_two input is 6', 'multiply_by_two output is 12'
>>> print(result.value)
'12'
```
Note how the original functions are unmodified.
A more useful example is when you want to use or test a badly documented third-party libraries or legacy code.
```python
>>> from badly_documented_library import pi_it

>>> result = IOMonad(5) >> add_one >> pi_it >> multiply_by_two
'Input is 5', 'Output is 6', 'Input is 6', 'output is 18.84', 'Input is 18.84', 'output is 37.68'
>>> print(result.value)
'37.68'
```
Error handling is another use case. For example, the Error Monad can log, catch and propagate errors.
```python
>>> def divide_by_zero(x):
...     return x / 0
result = ErrorMonad(5) >> add_one >> divide_by_zero >> multiply_by_two
print(result.value)
'DivideByZeroError'
print(result.errored)
'True'
>>> print(isinstance(result.value, Exception))
'True'
```
Pipelines of arbitrary length and order are another use case.
```python
>>> def add_one(x):
...     return x + 1
>>> def multiply_by_two(x):
...     return x * 2
>>> result = ErrorMonad(5) >> add_one >> multiply_by_two >> add_one >> multiply_by_two >> add_one >> multiply_by_two
Whereas in regular python code it would be:
>>> def add_one(x):
...     try:
...         return x + 1
...     except Exception as e:
...         return e
>>> def multiply_by_two(x):
...     try:
...         return x * 2
...     except Exception as e:
...         return e
>>> result = multiply_by_two(add_one(multiply_by_two(add_one(multiply_by_two(add_one(5))))))
```
or
```python
>>> def result(x):
    result = add_one(x)
    result = multiply_by_two(result)
    result = add_one(result)
    result = multiply_by_two(result)
    result = add_one(result)
    result = multiply_by_two(result)
    return result
>>> result(5)
"""

