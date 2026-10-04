Feature: Advanced Analytics Dashboard
  Analytics and insights visualization

  Scenario: Display key metrics
    Given analytics data exists
    When the dashboard is accessed
    Then key metrics are displayed

  Scenario: Visualize trends over time
    Given time-series data
    When trend visualization is requested
    Then a trend chart is displayed

  Scenario: Generate statistical summaries
    Given dataset statistics
    When summary is requested
    Then statistical summary is displayed

  Scenario: Create custom visualizations
    Given data and visualization type
    When custom visualization is requested
    Then the specified chart is displayed

  Scenario: Filter data by dimensions
    Given dimensional filters
    When filters are applied
    Then filtered data is visualized

  Scenario: Export dashboard data
    Given dashboard data
    When export is requested
    Then data is exported in specified format

  Scenario: Set alert thresholds
    Given metric thresholds
    When thresholds are configured
    Then alerts trigger when thresholds are exceeded

  Scenario: Compare metrics across periods
    Given multiple time periods
    When comparison is requested
    Then period-over-period comparison is displayed
