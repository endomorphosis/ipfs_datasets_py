Feature: Unified Monitoring Dashboard
  Centralized system monitoring interface

  Scenario: Display system overview
    Given monitoring data is collected
    When the dashboard is accessed
    Then system overview is displayed

  Scenario: Monitor multiple services
    Given multiple services are running
    When service monitoring is viewed
    Then all service statuses are displayed

  Scenario: Aggregate metrics across services
    Given metrics from multiple services
    When aggregation is requested
    Then aggregated metrics are displayed

  Scenario: View service dependencies
    Given service dependency information
    When dependency view is accessed
    Then service dependency graph is displayed

  Scenario: Set up monitoring alerts
    Given alert configuration
    When alerts are configured
    Then alerts trigger on conditions

  Scenario: View historical metrics
    Given historical monitoring data
    When historical view is accessed
    Then metrics over time are displayed

  Scenario: Customize dashboard layout
    Given dashboard customization options
    When layout is customized
    Then the custom layout is displayed

  Scenario: Export monitoring data
    Given monitoring data
    When export is requested
    Then data is exported in specified format
