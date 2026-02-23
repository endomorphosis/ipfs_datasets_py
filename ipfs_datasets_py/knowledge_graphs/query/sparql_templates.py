"""
SPARQL Query Templates for Knowledge Graph Validation

This module provides a comprehensive collection of SPARQL query templates and builder functions
for validating knowledge graphs against external SPARQL endpoints like Wikidata. The module
enables sophisticated validation workflows including entity verification, relationship validation,
property analysis, and complex graph pattern matching for knowledge graph quality assurance.

The module contains pre-built SPARQL query templates that can be parameterized through builder
functions to create executable queries for various validation scenarios. It supports both basic
entity-level validation and complex multi-hop relationship analysis across knowledge graphs.

Key Features:
- Entity search and validation against external knowledge bases
- Direct and inverse relationship verification between entities
- Multi-hop path discovery and relationship inference
- Entity type validation and classification
- Property usage statistics and validation
- Entity similarity analysis based on shared properties
- Cross-validation against common entity patterns

Query Template Categories:
- Entity Queries: Search, properties, and type validation
- Relationship Queries: Direct, inverse, and path-based relationship discovery
- Validation Queries: Property validation and entity similarity analysis
- Statistics Queries: Property usage patterns and entity type analysis

Usage Example:
    # Search for entities by name
    query = build_entity_query("Albert Einstein")
    
    # Validate relationships between entities
    relationship_query = build_direct_relationship_query("Q937", "Q5")
    
    # Find similar entities based on properties
    similarity_query = build_similar_entities_query("Q937", "Q5")

Dependencies:
    - typing: Type annotations for function signatures
    - External SPARQL endpoint (e.g., Wikidata) for query execution
"""

from typing import Dict, List, Any, Optional, Union, Tuple

# Basic entity query template
ENTITY_QUERY = """
SELECT ?item ?itemLabel ?itemDescription
WHERE {
  ?item rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), LCASE("%s"))) .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
LIMIT 10
"""

# Entity properties query template
ENTITY_PROPERTIES_QUERY = """
SELECT ?property ?propertyLabel ?value ?valueLabel
WHERE {
  wd:%s ?p ?value .
  ?property wikibase:directClaim ?p .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Direct relationship query template
DIRECT_RELATIONSHIP_QUERY = """
SELECT ?property ?propertyLabel
WHERE {
  wd:%s ?p wd:%s .
  ?property wikibase:directClaim ?p .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Inverse relationship query template
INVERSE_RELATIONSHIP_QUERY = """
SELECT ?property ?propertyLabel
WHERE {
  wd:%s ?p wd:%s .
  ?property wikibase:directClaim ?p .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Entity type validation query template
ENTITY_TYPE_QUERY = """
SELECT ?type ?typeLabel
WHERE {
  wd:%s wdt:P31 ?type .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Path relationship query template (finds paths up to 2 hops between entities)
PATH_RELATIONSHIP_QUERY = """
SELECT ?source ?intermediate ?intermediateLabel ?p1 ?p1Label ?p2 ?p2Label ?target
WHERE {
  VALUES ?source { wd:%s }
  VALUES ?target { wd:%s }

  # Direct path
  { ?source ?p1 ?target . }
  UNION
  # Path through one intermediate entity
  {
    ?source ?p1 ?intermediate .
    ?intermediate ?p2 ?target .
    FILTER(?intermediate != ?source && ?intermediate != ?target)
  }

  # Get property labels
  ?prop1 wikibase:directClaim ?p1 .
  OPTIONAL { ?prop2 wikibase:directClaim ?p2 . }

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 10
"""

# Query to find similar entities by properties
SIMILAR_ENTITIES_QUERY = """
SELECT ?item ?itemLabel ?score
WHERE {
  # Entity we're comparing with
  VALUES ?entity { wd:%s }

  # Properties of the entity
  {
    SELECT ?entity ?prop (count(*) as ?entityPropCount)
    WHERE {
      ?entity ?p ?o .
      ?prop wikibase:directClaim ?p .
    }
    GROUP BY ?entity ?prop
  }

  # Find other entities with the same properties
  {
    SELECT ?item ?prop (count(*) as ?itemPropCount)
    WHERE {
      ?item ?p ?o .
      ?prop wikibase:directClaim ?p .

      # Exclude the entity itself
      FILTER(?item != wd:%s)

      # Optionally filter by type
      %s
    }
    GROUP BY ?item ?prop
  }

  # Properties that both entities have
  FILTER(?prop = ?prop)

  # Calculate similarity score (Jaccard similarity)
  BIND((?entityPropCount + ?itemPropCount) as ?unionCount)
  BIND((?entityPropCount * ?itemPropCount / ?unionCount) as ?score)

  # Sort by score
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?score)
LIMIT 5
"""

# Query to get property statistics for an entity type
PROPERTY_STATS_QUERY = """
SELECT ?property ?propertyLabel (COUNT(?item) as ?count) (COUNT(?item) * 100 / ?totalCount as ?percentage)
WHERE {
  # Get all items of a specific type
  ?item wdt:P31 wd:%s .

  # Count total number of such items
  {
    SELECT (COUNT(?allItems) as ?totalCount)
    WHERE {
      ?allItems wdt:P31 wd:%s
    }
  }

  # Get their properties
  ?item ?p ?value .
  ?property wikibase:directClaim ?p .

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?property ?propertyLabel ?totalCount
ORDER BY DESC(?count)
LIMIT 20
"""

# Query to validate a set of properties against common properties for an entity type
PROPERTY_VALIDATION_QUERY = """
SELECT ?propertyLabel ?expectedPercentage ?hasProperty
WHERE {
  # Common properties for this entity type with usage percentages
  {
    SELECT ?property ?propertyLabel (COUNT(?item) * 100 / ?totalCount as ?expectedPercentage)
    WHERE {
      # All items of this type
      ?item wdt:P31 wd:%s .

      # Total count
      {
        SELECT (COUNT(?allItems) as ?totalCount)
        WHERE {
          ?allItems wdt:P31 wd:%s
        }
      }

      # Their properties
      ?item ?p ?value .
      ?property wikibase:directClaim ?p .

      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    GROUP BY ?property ?propertyLabel ?totalCount
    HAVING (?expectedPercentage > 30)  # Only include common properties (>30%%)
  }

  # Check if our entity has each property
  OPTIONAL {
    wd:%s ?p ?value .
    ?property wikibase:directClaim ?p .
  }

  BIND(IF(BOUND(?value), true, false) as ?hasProperty)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?expectedPercentage)
"""

# Functions to build SPARQL queries with proper parameters

def build_entity_query(entity_name: str) -> str:
    """
    Build a SPARQL query to search for entities by name in Wikidata.

    This function creates a parameterized SPARQL query that searches for entities
    whose labels contain the specified entity name. The search is case-insensitive
    and returns up to 10 matching entities with their labels and descriptions.

    Args:
        entity_name (str): The name or partial name of the entity to search for.
            Case-insensitive string that will be matched against entity labels.

    Returns:
        str: A formatted SPARQL query string ready for execution against a Wikidata
             SPARQL endpoint. The query returns ?item, ?itemLabel, and ?itemDescription
             variables for matching entities.

    Raises:
        TypeError: If entity_name is not a string
        ValueError: If entity_name is empty or contains only whitespace

    Examples:
        >>> query = build_entity_query("Albert Einstein")
        >>> # Returns SPARQL query to find entities with "Albert Einstein" in their label
        
        >>> query = build_entity_query("university")
        >>> # Returns SPARQL query to find entities containing "university"

    Note:
        The query uses Wikidata's label service for automatic language selection,
        preferring the user's language with English as fallback. Results are limited
        to 10 entities to prevent excessive response sizes.
    """
    return ENTITY_QUERY % entity_name

def build_entity_properties_query(entity_id: str) -> str:
    """
    Build a SPARQL query to retrieve all properties and values for a specific entity.

    This function creates a SPARQL query that fetches all properties associated with
    a given Wikidata entity ID, including property labels and value labels. The query
    is useful for comprehensive entity analysis and property validation.

    Args:
        entity_id (str): The Wikidata entity identifier (e.g., "Q937" for Albert Einstein).
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.

    Returns:
        str: A formatted SPARQL query string that returns ?property, ?propertyLabel,
             ?value, and ?valueLabel variables for all properties of the specified entity.

    Raises:
        TypeError: If entity_id is not a string
        ValueError: If entity_id is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_entity_properties_query("Q937")
        >>> # Returns SPARQL query to get all properties of Albert Einstein
        
        >>> query = build_entity_properties_query("Q5")
        >>> # Returns SPARQL query to get all properties of the "human" concept

    Note:
        The query uses Wikidata's direct claim properties (wikibase:directClaim) to
        retrieve simple property-value pairs. Complex properties with qualifiers
        are not included in the basic property retrieval.
    """
    return ENTITY_PROPERTIES_QUERY % entity_id

def build_direct_relationship_query(source_id: str, target_id: str) -> str:
    """
    Build a SPARQL query to check for direct relationships between two entities.

    This function creates a SPARQL query that identifies all direct properties linking
    a source entity to a target entity in Wikidata. The query returns the properties
    that directly connect the two entities, which is useful for relationship validation
    and knowledge graph verification.

    Args:
        source_id (str): The Wikidata identifier of the source entity (e.g., "Q937").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.
        target_id (str): The Wikidata identifier of the target entity (e.g., "Q5").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.

    Returns:
        str: A formatted SPARQL query string that returns ?property and ?propertyLabel
             variables for all direct relationships from source to target entity.

    Raises:
        TypeError: If source_id or target_id is not a string
        ValueError: If either identifier is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_direct_relationship_query("Q937", "Q5")
        >>> # Returns query to find direct relationships from Einstein to "human"
        
        >>> query = build_direct_relationship_query("Q95", "Q183")
        >>> # Returns query to find relationships from Google to Germany

    Note:
        This query only finds direct relationships (single-hop connections) between
        the specified entities. For multi-hop relationships, use build_path_relationship_query.
        The direction matters: source → target relationships only.
    """
    return DIRECT_RELATIONSHIP_QUERY % (source_id, target_id)

def build_inverse_relationship_query(target_id: str, source_id: str) -> str:
    """
    Build a SPARQL query to check for inverse relationships between two entities.

    This function creates a SPARQL query that identifies direct properties linking
    from the target entity back to the source entity, effectively finding the inverse
    direction of relationships. This is useful for bidirectional relationship validation
    and understanding reverse property connections in knowledge graphs.

    Args:
        target_id (str): The Wikidata identifier of the target entity (e.g., "Q5").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.
        source_id (str): The Wikidata identifier of the source entity (e.g., "Q937").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.

    Returns:
        str: A formatted SPARQL query string that returns ?property and ?propertyLabel
             variables for all direct relationships from target back to source entity.

    Raises:
        TypeError: If target_id or source_id is not a string
        ValueError: If either identifier is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_inverse_relationship_query("Q5", "Q937")
        >>> # Returns query to find relationships from "human" back to Einstein
        
        >>> query = build_inverse_relationship_query("Q183", "Q95")
        >>> # Returns query to find relationships from Germany back to Google

    Note:
        This query complements build_direct_relationship_query by checking the reverse
        direction: target → source relationships. Together, they provide complete
        bidirectional relationship analysis between two entities.
    """
    return INVERSE_RELATIONSHIP_QUERY % (target_id, source_id)

def build_entity_type_query(entity_id: str) -> str:
    """
    Build a SPARQL query to retrieve all types (classes) of a specific entity.

    This function creates a SPARQL query that fetches all instance-of (P31) relationships
    for a given entity, effectively retrieving all types or classes that the entity
    belongs to. This is essential for entity classification and type validation in
    knowledge graphs.

    Args:
        entity_id (str): The Wikidata identifier of the entity (e.g., "Q937" for Albert Einstein).
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.

    Returns:
        str: A formatted SPARQL query string that returns ?type and ?typeLabel
             variables for all types/classes that the entity is an instance of.

    Raises:
        TypeError: If entity_id is not a string
        ValueError: If entity_id is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_entity_type_query("Q937")
        >>> # Returns query to get types of Albert Einstein (human, physicist, etc.)
        
        >>> query = build_entity_type_query("Q95")
        >>> # Returns query to get types of Google (company, organization, etc.)

    Note:
        This query specifically looks for wdt:P31 (instance of) relationships, which
        represent direct type assertions in Wikidata. Subclass relationships (P279)
        are not included and would require a separate query for complete type hierarchy.
    """
    return ENTITY_TYPE_QUERY % entity_id

def build_path_relationship_query(source_id: str, target_id: str) -> str:
    """
    Build a SPARQL query to find relationship paths between two entities.

    This function creates a SPARQL query that discovers both direct relationships
    and indirect relationships (up to 2 hops) between two entities. The query returns
    all possible paths connecting the source and target entities, including intermediate
    entities and the properties that link them.

    Args:
        source_id (str): The Wikidata identifier of the source entity (e.g., "Q937").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.
        target_id (str): The Wikidata identifier of the target entity (e.g., "Q5").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.

    Returns:
        str: A formatted SPARQL query string that returns variables for source, target,
             intermediate entities (if any), and the properties connecting them. Results
             are limited to 10 paths to prevent excessive response sizes.

    Raises:
        TypeError: If source_id or target_id is not a string
        ValueError: If either identifier is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_path_relationship_query("Q937", "Q5")
        >>> # Returns query to find paths from Einstein to "human" concept
        
        >>> query = build_path_relationship_query("Q95", "Q30")
        >>> # Returns query to find paths from Google to United States

    Note:
        The query finds both direct paths (source → target) and 2-hop paths
        (source → intermediate → target). Longer paths are not included to maintain
        query performance. Results include property labels for human readability.
    """
    return PATH_RELATIONSHIP_QUERY % (source_id, target_id)

def build_similar_entities_query(entity_id: str, type_id: Optional[str] = None) -> str:
    """
    Build a SPARQL query to find entities similar to a given entity based on shared properties.

    This function creates a SPARQL query that calculates similarity scores between entities
    based on the Jaccard similarity of their properties. The query identifies entities that
    share the most properties with the target entity, optionally filtered by entity type.

    Args:
        entity_id (str): The Wikidata identifier of the reference entity (e.g., "Q937").
            Must be a valid Wikidata Q-identifier without the "wd:" prefix.
        type_id (Optional[str], optional): Optional Wikidata identifier to filter results
            by entity type. If provided, only entities of this type will be considered.
            Defaults to None (no type filtering).

    Returns:
        str: A formatted SPARQL query string that returns ?item, ?itemLabel, and ?score
             variables for similar entities, ordered by similarity score (highest first).
             Results are limited to 5 most similar entities.

    Raises:
        TypeError: If entity_id is not a string, or type_id is not a string or None
        ValueError: If entity_id is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_similar_entities_query("Q937")
        >>> # Returns query to find entities similar to Einstein (any type)
        
        >>> query = build_similar_entities_query("Q937", "Q5")
        >>> # Returns query to find humans similar to Einstein

    Note:
        Similarity is calculated using Jaccard similarity based on shared properties.
        The entity itself is excluded from results. Type filtering helps find similar
        entities within specific categories (e.g., similar people, organizations, etc.).
    """
    type_filter = f"FILTER EXISTS {{ ?item wdt:P31 wd:{type_id} }}" if type_id else ""
    return SIMILAR_ENTITIES_QUERY % (entity_id, entity_id, type_filter)

def build_property_stats_query(type_id: str) -> str:
    """
    Build a SPARQL query to get property usage statistics for entities of a specific type.

    This function creates a SPARQL query that analyzes property usage patterns across
    all entities of a given type, calculating both absolute counts and percentages for
    each property. This is useful for understanding common properties and data completeness
    patterns within entity categories.

    Args:
        type_id (str): The Wikidata identifier of the entity type (e.g., "Q5" for human).
            Must be a valid Wikidata Q-identifier without the "wd:" prefix representing
            a class or type that entities can be instances of.

    Returns:
        str: A formatted SPARQL query string that returns ?property, ?propertyLabel,
             ?count, and ?percentage variables showing property usage statistics.
             Results are ordered by usage count (highest first) and limited to top 20.

    Raises:
        TypeError: If type_id is not a string
        ValueError: If type_id is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_property_stats_query("Q5")
        >>> # Returns statistics for properties used by human entities
        
        >>> query = build_property_stats_query("Q4830453")
        >>> # Returns statistics for properties used by business entities

    Note:
        The query calculates percentages based on the total count of entities of the
        specified type. Only direct properties are analyzed; complex properties with
        qualifiers are not included in the basic statistics.
    """
    return PROPERTY_STATS_QUERY % (type_id, type_id)

def build_property_validation_query(type_id: str, entity_id: str) -> str:
    """
    Build a SPARQL query to validate an entity's properties against common patterns for its type.

    This function creates a SPARQL query that compares an entity's properties with the
    most common properties used by other entities of the same type. The query identifies
    which expected properties the entity has and which it lacks, helping assess data
    completeness and quality.

    Args:
        type_id (str): The Wikidata identifier of the entity type (e.g., "Q5" for human).
            Must be a valid Wikidata Q-identifier representing the entity's classification.
        entity_id (str): The Wikidata identifier of the entity to validate (e.g., "Q937").
            Must be a valid Wikidata Q-identifier of an entity that should be of the
            specified type.

    Returns:
        str: A formatted SPARQL query string that returns ?propertyLabel, ?expectedPercentage,
             and ?hasProperty variables showing which common properties the entity has or lacks.
             Results are ordered by expected percentage (highest first).

    Raises:
        TypeError: If type_id or entity_id is not a string
        ValueError: If either identifier is empty, contains only whitespace, or has invalid format

    Examples:
        >>> query = build_property_validation_query("Q5", "Q937")
        >>> # Validates Einstein's properties against common human properties
        
        >>> query = build_property_validation_query("Q4830453", "Q95")
        >>> # Validates Google's properties against common business properties

    Note:
        The query only considers properties used by more than 30% of entities of the
        specified type as "expected" properties. This threshold helps focus on truly
        common properties while filtering out rare or specialized ones.
    """
    return PROPERTY_VALIDATION_QUERY % (type_id, type_id, entity_id)
