Feature: TestWorkflowDefinition class from tests/test_p2p_workflow_scheduler.py
  This class tests WorkflowDefinition class

  Scenario: test_workflow_creation method
    Given workflow parameters with id "wf1", name "Test Workflow", tags P2P_ELIGIBLE and CODE_GEN, priority 2.0
    When creating WorkflowDefinition
    Then workflow_id equals "wf1"

  Scenario: test_workflow_creation method - assertion 2
    Given workflow parameters with id "wf1", name "Test Workflow", tags P2P_ELIGIBLE and CODE_GEN, priority 2.0
    When creating WorkflowDefinition
    Then name equals "Test Workflow"

  Scenario: test_workflow_creation method - assertion 3
    Given workflow parameters with id "wf1", name "Test Workflow", tags P2P_ELIGIBLE and CODE_GEN, priority 2.0
    When creating WorkflowDefinition
    Then tags contain P2P_ELIGIBLE

  Scenario: test_workflow_creation method - assertion 4
    Given workflow parameters with id "wf1", name "Test Workflow", tags P2P_ELIGIBLE and CODE_GEN, priority 2.0
    When creating WorkflowDefinition
    Then priority equals 2.0

  Scenario: test_workflow_is_p2p_eligible method with P2P_ELIGIBLE tag
    Given workflow with P2P_ELIGIBLE tag
    When calling is_p2p_eligible
    Then result is true

  Scenario: test_workflow_is_p2p_eligible method with P2P_ONLY tag
    Given workflow with P2P_ONLY tag
    When calling is_p2p_eligible
    Then result is true

  Scenario: test_workflow_is_p2p_eligible method with GITHUB_API tag
    Given workflow with GITHUB_API tag
    When calling is_p2p_eligible
    Then result is false

  Scenario: test_workflow_requires_github_api method with UNIT_TEST tag
    Given workflow with UNIT_TEST tag
    When calling requires_github_api
    Then result is true

  Scenario: test_workflow_requires_github_api method with P2P_ONLY tag
    Given workflow with P2P_ONLY tag
    When calling requires_github_api
    Then result is false

  Scenario: test_workflow_to_dict method
    Given WorkflowDefinition with id "wf1", name "Test", tags P2P_ELIGIBLE, priority 1.5
    When converting to dictionary
    Then dict workflow_id equals "wf1"

  Scenario: test_workflow_to_dict method - assertion 2
    Given WorkflowDefinition with id "wf1", name "Test", tags P2P_ELIGIBLE, priority 1.5
    When converting to dictionary
    Then dict name equals "Test"

  Scenario: test_workflow_to_dict method - assertion 3
    Given WorkflowDefinition with id "wf1", name "Test", tags P2P_ELIGIBLE, priority 1.5
    When converting to dictionary
    Then dict tags contain "p2p_eligible"

  Scenario: test_workflow_to_dict method - assertion 4
    Given WorkflowDefinition with id "wf1", name "Test", tags P2P_ELIGIBLE, priority 1.5
    When converting to dictionary
    Then dict priority equals 1.5
