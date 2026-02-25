"""
ClinicalTrials.gov Scraper Engine.

Canonical business logic for scraping clinical trial data from ClinicalTrials.gov.
This module is the authoritative location for the ClinicalTrialsScraper class.

Exposed in the ``ipfs_datasets_py.scrapers.medical`` package so the same class can be used
from package imports, CLI tools, and MCP server tools.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class ClinicalTrialsScraper:
    """Scraper for ClinicalTrials.gov database.

    Collects clinical trial data including outcomes, population demographics,
    and time-series data for supporting medical reasoning and theorem validation.

    Args:
        use_fallback: Enable fallback mechanisms if primary fails.
        cache_dir: Directory for caching scraped data.
        rate_limit_delay: Delay between requests in seconds.

    Example::

        scraper = ClinicalTrialsScraper()
        trials = scraper.search_trials("diabetes treatment")
        outcomes = scraper.get_trial_outcomes("NCT12345678")
        population_data = scraper.get_population_demographics("NCT12345678")
    """

    API_BASE = "https://clinicaltrials.gov/api/v2"
    QUERY_BASE = "https://clinicaltrials.gov/api/v2/studies"

    def __init__(
        self,
        use_fallback: bool = True,
        cache_dir: Optional[str] = None,
        rate_limit_delay: float = 1.0,
    ) -> None:
        self.use_fallback = use_fallback
        self.cache_dir = cache_dir
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.last_request_time: float = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def _parse_study_summary(self, study: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse study summary from API response."""
        try:
            protocol = study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})
            conditions_module = protocol.get("conditionsModule", {})
            arms_module = protocol.get("armsInterventionsModule", {})

            return {
                "nct_id": id_module.get("nctId", ""),
                "title": id_module.get("officialTitle", id_module.get("briefTitle", "")),
                "brief_summary": id_module.get("briefSummary", ""),
                "conditions": conditions_module.get("conditions", []),
                "interventions": [
                    i.get("name", "") for i in arms_module.get("interventions", [])
                ],
                "phase": (
                    design_module.get("phases", ["Unknown"])[0]
                    if design_module.get("phases")
                    else "Unknown"
                ),
                "status": status_module.get("overallStatus", "Unknown"),
                "enrollment": status_module.get("enrollmentInfo", {}).get("count", 0),
                "start_date": status_module.get("startDateStruct", {}).get("date", ""),
                "completion_date": status_module.get("completionDateStruct", {}).get("date", ""),
                "locations": self._extract_locations(
                    protocol.get("contactsLocationsModule", {})
                ),
                "source": "clinicaltrials_api",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Error parsing study summary: %s", exc)
            return None

    def _extract_locations(self, contacts_locations: Dict[str, Any]) -> List[str]:
        """Extract trial location information."""
        locations = []
        for loc in contacts_locations.get("locations", []):
            city = loc.get("city", "")
            country = loc.get("country", "")
            if city and country:
                locations.append(f"{city}, {country}")
        return locations

    def _parse_adverse_events(self, adverse_events: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse adverse events data."""
        events = []
        for event in (
            adverse_events.get("seriousEvents", []) + adverse_events.get("otherEvents", [])
        ):
            events.append(
                {
                    "term": event.get("term", ""),
                    "organ_system": event.get("organSystem", ""),
                    "assessment_type": event.get("assessmentType", ""),
                    "frequency": (
                        event.get("stats", [{}])[0].get("numEvents", 0)
                        if event.get("stats")
                        else 0
                    ),
                }
            )
        return events

    def _extract_age_data(self, baseline: Dict[str, Any]) -> Dict[str, Any]:
        """Extract age distribution from baseline characteristics."""
        return {"data": baseline.get("measures", []), "type": "age"}

    def _extract_sex_data(self, baseline: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sex distribution from baseline characteristics."""
        return {"data": baseline.get("measures", []), "type": "sex"}

    def _extract_ethnicity_data(self, baseline: Dict[str, Any]) -> Dict[str, Any]:
        """Extract ethnicity distribution from baseline characteristics."""
        return {"data": baseline.get("measures", []), "type": "ethnicity"}

    # ------------------------------------------------------------------
    # Fallback methods
    # ------------------------------------------------------------------

    def _search_fallback(self, query: str, max_results: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        """Fallback search mechanisms."""
        logger.warning("Fallback search not yet fully implemented")
        return []

    def _get_outcomes_fallback(self, nct_id: str) -> Dict[str, Any]:
        """Fallback for outcomes retrieval."""
        logger.warning("Outcomes fallback not yet implemented")
        return {"nct_id": nct_id, "outcomes": [], "source": "fallback"}

    def _get_demographics_fallback(self, nct_id: str) -> Dict[str, Any]:
        """Fallback for demographics retrieval."""
        logger.warning("Demographics fallback not yet implemented")
        return {"nct_id": nct_id, "demographics": {}, "source": "fallback"}

    # ------------------------------------------------------------------
    # Private API helper
    # ------------------------------------------------------------------

    def _search_via_api(
        self,
        query: str,
        condition: Optional[str],
        intervention: Optional[str],
        phase: Optional[str],
        status: Optional[str],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Search via ClinicalTrials.gov API v2."""
        self._rate_limit()

        params: Dict[str, Any] = {
            "format": "json",
            "pageSize": min(max_results, 1000),
        }

        query_parts = []
        if query:
            query_parts.append(query)
        if condition:
            query_parts.append(f"AREA[Condition]{condition}")
        if intervention:
            query_parts.append(f"AREA[Intervention]{intervention}")
        if phase:
            query_parts.append(f"AREA[Phase]{phase}")
        if status:
            query_parts.append(f"AREA[OverallStatus]{status}")

        if query_parts:
            params["query.term"] = " AND ".join(query_parts)

        response = self.session.get(self.QUERY_BASE, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        studies = data.get("studies", [])

        results = []
        for study in studies[:max_results]:
            parsed = self._parse_study_summary(study)
            if parsed:
                results.append(parsed)

        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_trials(
        self,
        query: str,
        condition: Optional[str] = None,
        intervention: Optional[str] = None,
        phase: Optional[str] = None,
        status: Optional[str] = None,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search for clinical trials matching criteria.

        Args:
            query: General search query.
            condition: Specific medical condition.
            intervention: Specific intervention/treatment.
            phase: Trial phase (e.g., ``"Phase 3"``).
            status: Trial status (e.g., ``"Completed"``).
            max_results: Maximum number of results to return.

        Returns:
            List of clinical trial summary dictionaries.

        Raises:
            requests.RequestException: If API request fails and fallback is disabled.
        """
        try:
            return self._search_via_api(
                query, condition, intervention, phase, status, max_results
            )
        except Exception as exc:
            logger.error("ClinicalTrials.gov API search failed: %s", exc)
            if self.use_fallback:
                logger.info("Attempting fallback mechanisms")
                return self._search_fallback(query, max_results)
            raise

    def get_trial_outcomes(self, nct_id: str) -> Dict[str, Any]:
        """Get detailed outcome data for a specific clinical trial.

        Args:
            nct_id: ClinicalTrials.gov identifier (e.g., ``"NCT12345678"``).

        Returns:
            Dictionary containing primary/secondary outcomes, adverse events,
            and baseline characteristics.

        Raises:
            requests.RequestException: If API request fails and fallback is disabled.
        """
        self._rate_limit()

        try:
            url = f"{self.QUERY_BASE}/{nct_id}"
            response = self.session.get(url, params={"format": "json"}, timeout=30)
            response.raise_for_status()

            data = response.json()
            study = data.get("protocolSection", {})
            results_section = data.get("resultsSection", {})

            outcomes_module = study.get("outcomesModule", {})
            primary_outcomes = outcomes_module.get("primaryOutcomes", [])
            secondary_outcomes = outcomes_module.get("secondaryOutcomes", [])

            outcome_measures = results_section.get("outcomeMeasuresModule", {})
            adverse_events = results_section.get("adverseEventsModule", {})
            baseline_chars = results_section.get("baselineCharacteristicsModule", {})

            return {
                "nct_id": nct_id,
                "primary_outcomes": [
                    {
                        "measure": o.get("measure", ""),
                        "description": o.get("description", ""),
                        "time_frame": o.get("timeFrame", ""),
                    }
                    for o in primary_outcomes
                ],
                "secondary_outcomes": [
                    {
                        "measure": o.get("measure", ""),
                        "description": o.get("description", ""),
                        "time_frame": o.get("timeFrame", ""),
                    }
                    for o in secondary_outcomes
                ],
                "outcome_results": outcome_measures.get("outcomeMeasures", []),
                "adverse_events": self._parse_adverse_events(adverse_events),
                "baseline_characteristics": baseline_chars,
                "source": "clinicaltrials_api",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Error getting trial outcomes for %s: %s", nct_id, exc)
            if self.use_fallback:
                return self._get_outcomes_fallback(nct_id)
            raise

    def get_population_demographics(self, nct_id: str) -> Dict[str, Any]:
        """Get population demographic data for a clinical trial.

        Args:
            nct_id: ClinicalTrials.gov identifier.

        Returns:
            Dictionary containing age, sex, ethnicity distributions and eligibility criteria.

        Raises:
            requests.RequestException: If API request fails and fallback is disabled.
        """
        self._rate_limit()

        try:
            url = f"{self.QUERY_BASE}/{nct_id}"
            response = self.session.get(url, params={"format": "json"}, timeout=30)
            response.raise_for_status()

            data = response.json()
            protocol = data.get("protocolSection", {})
            results = data.get("resultsSection", {})

            eligibility = protocol.get("eligibilityModule", {})
            baseline = results.get("baselineCharacteristicsModule", {})
            participant_flow = results.get("participantFlowModule", {})

            pre_assign = participant_flow.get("preAssignmentDetails", {})
            participants = pre_assign.get("participants", [{}]) if pre_assign else [{}]

            return {
                "nct_id": nct_id,
                "age_distribution": self._extract_age_data(baseline),
                "sex_distribution": self._extract_sex_data(baseline),
                "ethnicity_distribution": self._extract_ethnicity_data(baseline),
                "eligibility_criteria": {
                    "criteria": eligibility.get("eligibilityCriteria", ""),
                    "min_age": eligibility.get("minimumAge", ""),
                    "max_age": eligibility.get("maximumAge", ""),
                    "sex": eligibility.get("sex", "All"),
                    "healthy_volunteers": eligibility.get("healthyVolunteers", False),
                },
                "enrollment_count": participants[0].get("count", 0),
                "source": "clinicaltrials_api",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Error getting demographics for %s: %s", nct_id, exc)
            if self.use_fallback:
                return self._get_demographics_fallback(nct_id)
            raise

    def scrape_time_series_data(self, nct_id: str) -> Dict[str, Any]:
        """Scrape time-series data from a clinical trial for temporal reasoning.

        Args:
            nct_id: ClinicalTrials.gov identifier.

        Returns:
            Dictionary with time-series measurements and outcomes over time.
        """
        return {
            "nct_id": nct_id,
            "temporal_measurements": [],
            "outcome_timeline": [],
            "adverse_event_timeline": [],
            "message": "Time-series extraction requires detailed results data",
        }
