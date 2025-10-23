# Enhanced Investigation Dashboard - Maps Feature

## 🗺️ Overview

The Enhanced Investigation Dashboard now includes a comprehensive **Maps** tab that provides geospatial analysis capabilities for investigating large archives of data. This feature allows data scientists, historians, and lawyers to analyze relationships, histories, actions, and properties of different entities with both spatial and temporal dimensions.

## 🎯 Key Features

### 1. Geospatial Entity Extraction
- **Automatic Location Detection**: Extracts geographic entities from unstructured text corpus
- **Coordinate Resolution**: Attempts to geocode locations with latitude/longitude coordinates
- **Confidence Scoring**: Provides confidence metrics for each extracted location
- **Context Preservation**: Maintains context snippets for each entity mention

### 2. Spatiotemporal Event Mapping
- **Event-Location Correlation**: Maps events to specific geographic coordinates
- **Temporal Clustering**: Groups events by time periods (hour, day, week, month)
- **Spatial Clustering**: Groups nearby events based on configurable distance thresholds
- **Multi-dimensional Analysis**: Combines spatial and temporal data for comprehensive insights

### 3. Interactive Map Visualization
- **Multiple Map Views**: Street, satellite, terrain, and hybrid views
- **Real-time Filtering**: Filter by entity types, time ranges, and geographic bounds
- **Cluster Management**: Configurable spatial clustering to avoid information overload
- **Timeline Slider**: Interactive temporal filtering with visual timeline controls

### 4. Advanced Query Interface
- **Natural Language Queries**: Search using plain language (e.g., "financial events in New York")
- **Geographic Context Search**: Find entities within specified radius of center location
- **Cross-Entity Analysis**: Discover relationships between entities across space and time
- **Export Capabilities**: Export analysis results in multiple formats

## 🛠️ Technical Implementation

### MCP Tools Integration
The Maps feature is built using three new MCP (Model Context Protocol) tools:

1. **`extract_geographic_entities`**
   - Extracts and geocodes location entities from corpus data
   - Supports confidence thresholds and geographic scope filtering
   - Returns coordinates, frequency, and context information

2. **`map_spatiotemporal_events`**
   - Maps events with both spatial and temporal dimensions
   - Supports time range filtering and geographic bounds
   - Provides clustering analysis and event statistics

3. **`query_geographic_context`**
   - Performs natural language queries on geographic data
   - Includes related entity discovery and temporal context
   - Supports radius-based search and relevance scoring

### JavaScript Integration
- **Leaflet Maps**: Open-source mapping library for interactive visualization
- **MCP Client**: Centralized JavaScript SDK for all server communication
- **Bootstrap UI**: Responsive interface with professional styling
- **Real-time Updates**: Live statistics and progress monitoring

## 📊 Use Cases

### For Data Scientists
- **Pattern Discovery**: Identify geographic patterns in large datasets
- **Correlation Analysis**: Find spatial-temporal correlations in event data
- **Clustering Analysis**: Discover geographic clusters and outliers
- **Export for ML**: Export processed geographic data for machine learning models

### For Historians
- **Timeline Mapping**: Visualize historical events across geographic locations
- **Migration Patterns**: Track movement and changes over time and space
- **Source Verification**: Cross-reference events with geographic context
- **Research Citations**: Generate properly formatted geographic references

### For Lawyers
- **Evidence Mapping**: Map legal events and evidence to specific locations
- **Jurisdiction Analysis**: Understand geographic scope of legal issues
- **Timeline Construction**: Build comprehensive timelines with location context
- **Discovery Support**: Identify relevant documents based on geographic criteria

## 🎮 User Interface

### Map Controls Panel
- **Query Input**: Natural language search for locations and events
- **Geographic Filters**: Center location and radius controls
- **Temporal Filters**: Date range selection with calendar inputs
- **Entity Type Filters**: Checkboxes for persons, organizations, events, locations
- **View Options**: Map style selection (street, satellite, terrain, hybrid)
- **Action Buttons**: Search, extract, analyze, and export functions

### Main Map Display
- **Interactive Map**: Full-featured map with zoom, pan, and marker interaction
- **Marker Clustering**: Intelligent grouping of nearby markers
- **Popup Information**: Detailed entity information on marker click
- **Timeline Controls**: Optional timeline slider for temporal filtering
- **View Controls**: Timeline toggle, clustering toggle, reset button

### Results Analysis
- **Statistics Dashboard**: Real-time counts of entities, events, and clusters
- **Results Table**: Detailed tabular view of analysis results
- **Geographic Summary**: Coverage statistics and analysis metrics
- **Export Options**: Multiple format support for data export

## 🔧 Configuration Options

### Spatial Parameters
- **Search Radius**: 1-5000 km radius for geographic queries
- **Cluster Distance**: 1-500 km distance for spatial clustering
- **Coordinate Precision**: Configurable precision for coordinate display

### Temporal Parameters
- **Time Range**: Start and end date selection
- **Resolution**: Hour, day, week, or month clustering
- **Timeline Granularity**: Configurable timeline slider precision

### Analysis Parameters
- **Confidence Threshold**: Minimum confidence for entity inclusion
- **Entity Types**: Selective filtering by entity categories
- **Geographic Scope**: Optional geographic boundary constraints

## 📈 Performance Features

### Efficient Processing
- **Incremental Loading**: Load markers progressively for large datasets
- **Client-side Caching**: Cache entity and coordinate data
- **Optimized Clustering**: Efficient spatial clustering algorithms
- **Lazy Map Loading**: Initialize map only when Maps tab is active

### Scalability Features
- **Virtual Scrolling**: Handle large result sets efficiently
- **Marker Optimization**: Intelligent marker management for performance
- **Progressive Enhancement**: Graceful degradation for limited resources
- **Memory Management**: Automatic cleanup of unused map resources

## 🔍 Example Workflows

### 1. Financial News Analysis
```
1. Ingest financial news corpus
2. Navigate to Maps tab
3. Query: "financial markets crash"
4. Set center: "New York"
5. Set radius: 500km
6. Analyze results showing global financial centers
7. Use timeline to see progression of events
8. Export results for further analysis
```

### 2. Government Document Investigation
```
1. Load government document corpus
2. Extract geographic entities
3. Query: "policy announcements Washington"
4. Filter by date range: Last 6 months
5. Map spatiotemporal events
6. Identify patterns across different agencies
7. Export timeline data for legal brief
```

### 3. Historical Event Research
```
1. Import historical document collection
2. Set temporal range: 1940-1945
3. Query: "military operations Europe"
4. Enable clustering with 100km distance
5. Use timeline slider to see progression
6. Cross-reference with entity relationships
7. Generate geographic citations
```

## 🚀 Future Enhancements

### Advanced Visualization
- **Heat Maps**: Density visualization for event frequency
- **Flow Maps**: Movement and migration pattern visualization
- **3D Visualization**: Temporal dimension as third axis
- **Custom Symbology**: User-defined marker styles and categories

### Enhanced Analysis
- **Machine Learning Integration**: Automated pattern recognition
- **Predictive Modeling**: Forecast future events based on patterns
- **Anomaly Detection**: Identify unusual geographic patterns
- **Network Analysis**: Visualize entity relationship networks on map

### Integration Improvements
- **Real-time Data**: Live data feeds for dynamic analysis
- **External APIs**: Integration with additional geocoding services
- **Custom Basemaps**: Support for specialized map layers
- **Collaboration Features**: Shared analysis sessions and annotations

---

*This Maps feature represents a significant enhancement to the Investigation Dashboard, providing powerful geospatial analysis capabilities that integrate seamlessly with existing GraphRAG and entity analysis tools.*