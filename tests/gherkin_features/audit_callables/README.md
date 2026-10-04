# Audit Module Gherkin Feature Files

This directory contains Gherkin feature files documenting the behavior of public callables in the `ipfs_datasets_py/audit` module.

## Overview

The audit module provides comprehensive audit logging, compliance reporting, intrusion detection, and adaptive security response capabilities. These Gherkin files serve as executable documentation and test specifications.

## File Organization

Each Gherkin file corresponds to a specific public callable from the audit module:

### AuditLogger Class (7 files)
- `AuditLogger_log.feature` - Core logging method with 24 scenarios
- `AuditLogger_add_handler.feature` - Handler registration
- `AuditLogger_remove_handler.feature` - Handler removal
- `AuditLogger_set_context.feature` - Thread-local context management
- `AuditLogger_clear_context.feature` - Context clearing
- `AuditLogger_add_event_listener.feature` - Event listener registration
- `AuditLogger_remove_event_listener.feature` - Event listener removal

### AuditEvent Class (4 files)
- `AuditEvent_to_dict.feature` - Dictionary conversion
- `AuditEvent_to_json.feature` - JSON serialization
- `AuditEvent_from_dict.feature` - Dictionary deserialization
- `AuditEvent_from_json.feature` - JSON deserialization

### Handler Classes (2 files)
- `AuditHandler_handle.feature` - Base handler processing
- `FileAuditHandler__handle_event.feature` - File-based event handling

### Compliance Classes (3 files)
- `ComplianceReporter_generate_report.feature` - Report generation with 21 scenarios
- `ComplianceReport_save_json.feature` - JSON export functionality
- `GDPRComplianceReporter_init.feature` - GDPR-specific reporter

### Intrusion Detection Classes (3 files)
- `IntrusionDetection_process_events.feature` - Threat detection with 17 scenarios
- `AnomalyDetector_process_event.feature` - Anomaly detection with 13 scenarios
- `SecurityAlertManager_add_alert.feature` - Alert management

### Adaptive Security Classes (2 files)
- `AdaptiveSecurityManager_add_rule.feature` - Response rule management
- `ResponseRule_matches_alert.feature` - Rule matching logic

### Reporting Classes (1 file)
- `AuditReportGenerator_generate_security_report.feature` - Security report generation

## File Format

All feature files follow this structure:

```gherkin
Feature: ClassName.method_name()
  Tests the method_name() method of ClassName.
  This callable [description of what it does].

  Background:
    Given [common preconditions]
    And [setup state]

  Scenario: [Specific behavior description]
    Given [specific preconditions]
    When [action is performed]
    Then [expected outcome]
    And [additional assertions]
```

## Key Characteristics

1. **Explicit Callable Reference**: Each feature explicitly mentions the callable it documents
2. **Concrete Scenarios**: Uses specific values (e.g., "user='alice'") rather than vague terms
3. **Comprehensive Coverage**: Includes success cases, edge cases, and error conditions
4. **No Examples Tables**: Each scenario is self-contained with concrete values
5. **Minimal Adjectives/Adverbs**: Focuses on specific, measurable behaviors

## Usage

These Gherkin files serve multiple purposes:

1. **Documentation**: Readable specification of expected behavior
2. **Test Cases**: Can be used with BDD testing frameworks (e.g., behave, pytest-bdd)
3. **Requirements**: Clear definition of functional requirements
4. **Onboarding**: Help new developers understand module behavior

## Statistics

- **Total Files**: 22
- **Total Lines**: 1,594
- **Coverage**: Core audit logging, compliance reporting, intrusion detection, and adaptive security

## Related Modules

The audit module integrates with:
- `ipfs_datasets_py/security` - Security management
- `ipfs_datasets_py/provenance` - Data provenance tracking
- External systems - Elasticsearch, Syslog, etc.

## Testing

To use these feature files with pytest-bdd:

```bash
pytest tests/gherkin_features/audit_callables/
```

## Contributing

When adding new public callables to the audit module:

1. Create a corresponding `.feature` file in this directory
2. Follow the naming convention: `ClassName_method_name.feature`
3. Include comprehensive scenarios covering all behavior
4. Use concrete values and avoid vague descriptions
5. Explicitly mention the callable in the feature description
