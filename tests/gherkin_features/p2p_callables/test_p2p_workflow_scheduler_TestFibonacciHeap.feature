Feature: TestFibonacciHeap class from tests/test_p2p_workflow_scheduler.py
  This class tests Fibonacci Heap implementation

  Scenario: test_heap_initialization method
    When creating FibonacciHeap
    Then heap is_empty is true
    And heap size equals 0

  Scenario: test_heap_insert method
    Given empty FibonacciHeap
    When inserting element with key 5.0 and value "workflow1"
    Then heap is_empty is false
    And heap size equals 1

  Scenario: test_heap_find_min method
    Given heap with elements 5.0, 2.0, 8.0
    When calling find_min
    Then min element key equals 2.0
    And min element value equals "workflow2"
    And heap size equals 3

  Scenario: test_heap_extract_min method
    Given heap with elements 5.0, 2.0, 8.0
    When calling extract_min
    Then min element key equals 2.0
    And min element value equals "workflow2"
    And heap size equals 2

  Scenario: test_heap_priority_order method
    Given heap with priorities 5.0, 2.0, 8.0, 1.0, 9.0, 3.0
    When extracting all elements
    Then extracted list equals sorted priorities

  Scenario: test_heap_empty_extract method
    Given empty heap
    When calling extract_min
    Then result is None
