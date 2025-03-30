"""
SPARQL Query Templates for Knowledge Graph Validation

This module provides a collection of SPARQL query templates for validating
knowledge graphs against endpoints like Wikidata. These templates can be
used to perform various types of validation, including entity validation,
relationship validation, and complex graph pattern validation.
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
    """Build a SPARQL query to search for an entity by name."""
    return ENTITY_QUERY % entity_name

def build_entity_properties_query(entity_id: str) -> str:
    """Build a SPARQL query to get properties of an entity."""
    return ENTITY_PROPERTIES_QUERY % entity_id

def build_direct_relationship_query(source_id: str, target_id: str) -> str:
    """Build a SPARQL query to check direct relationships between entities."""
    return DIRECT_RELATIONSHIP_QUERY % (source_id, target_id)

def build_inverse_relationship_query(target_id: str, source_id: str) -> str:
    """Build a SPARQL query to check inverse relationships between entities."""
    return INVERSE_RELATIONSHIP_QUERY % (target_id, source_id)

def build_entity_type_query(entity_id: str) -> str:
    """Build a SPARQL query to get types of an entity."""
    return ENTITY_TYPE_QUERY % entity_id

def build_path_relationship_query(source_id: str, target_id: str) -> str:
    """Build a SPARQL query to find paths between two entities."""
    return PATH_RELATIONSHIP_QUERY % (source_id, target_id)

def build_similar_entities_query(entity_id: str, type_id: Optional[str] = None) -> str:
    """Build a SPARQL query to find similar entities."""
    type_filter = f"FILTER EXISTS {{ ?item wdt:P31 wd:{type_id} }}" if type_id else ""
    return SIMILAR_ENTITIES_QUERY % (entity_id, entity_id, type_filter)

def build_property_stats_query(type_id: str) -> str:
    """Build a SPARQL query to get property statistics for an entity type."""
    return PROPERTY_STATS_QUERY % (type_id, type_id)

def build_property_validation_query(type_id: str, entity_id: str) -> str:
    """Build a SPARQL query to validate properties against common properties for an entity type."""
    return PROPERTY_VALIDATION_QUERY % (type_id, type_id, entity_id)