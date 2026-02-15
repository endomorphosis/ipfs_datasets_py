# """
# iCalendar processing utilities using the icalendar library.

# This module contains functions for processing iCalendar (.ics) files
# using the icalendar library with fallback to basic line parsing.
# """

# import re
# from datetime import datetime
# from typing import Any, Optional, Union

# from logger import logger

# # TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# # Check if icalendar is available # TODO This should be moved to a constants.py file.
# try:
#     import icalendar
#     ICALENDAR_AVAILABLE = True
# except ImportError:
#     ICALENDAR_AVAILABLE = False
#     logger.warning("icalendar not available, calendar processing will use basic parsing")


# def format_datetime(dt_str: str) -> str:
#     """
#     Format an iCalendar datetime string to a human-readable format.
    
#     Args:
#         dt_str: The datetime string from iCalendar.
        
#     Returns:
#         Formatted datetime string.
#     """
#     # Basic formatting for common iCalendar datetime formats
#     if not dt_str:
#         return ""
    
#     # Handle date-only format (YYYYMMDD)
#     if len(dt_str) == 8 and dt_str.isdigit():
#         try:
#             dt = datetime.strptime(dt_str, "%Y%m%d")
#             return dt.strftime("%Y-%m-%d")
#         except ValueError:
#             return dt_str
    
#     # Handle datetime format (YYYYMMDDTHHMMSSZs)
#     elif len(dt_str) >= 15 and 'T' in dt_str:
#         try:
#             # Remove any timezone identifier
#             dt_str = dt_str.split('Z')[0].split('T')
#             date_part = dt_str[0]
#             time_part = dt_str[1] if len(dt_str) > 1 else "000000"
            
#             # Parse datetime
#             dt = datetime.strptime(f"{date_part}T{time_part}", "%Y%m%dT%H%M%S")
#             return dt.strftime("%Y-%m-%d %H:%M:%S")
#         except (ValueError, IndexError):
#             return dt_str
    
#     return dt_str


# def extract_icalendar_metadata_advanced(
#     ical_content: str,
#     options: Optional[dict[str, Any]] = None
# ) -> dict[str, Any]:
#     """
#     Extract metadata from iCalendar content using the icalendar library.
    
#     Args:
#         ical_content: The iCalendar content as text.
#         options: Optional extraction options.
        
#     Returns:
#         Dictionary of metadata.
#     """
#     if not ICALENDAR_AVAILABLE:
#         logger.warning("icalendar library not available, using basic extraction")
#         return extract_icalendar_metadata_basic(ical_content, options)
    
#     try:
#         # Parse iCalendar content
#         cal = icalendar.Calendar.from_ical(ical_content)
        
#         # Basic metadata
#         metadata = {
#             'format': 'calendar',
#             'calendar_name': str(cal.get('X-WR-CALNAME', '')),
#             'calendar_desc': str(cal.get('X-WR-CALDESC', '')),
#             'calendar_scale': str(cal.get('CALSCALE', 'GREGORIAN')),
#             'version': str(cal.get('VERSION', '2.0'))
#         }
        
#         # Count events
#         events = [comp for comp in cal.walk() if comp.name == 'VEVENT']
#         metadata['event_count'] = len(events)
        
#         # Get date range
#         if events:
#             start_dates = []
#             end_dates = []
            
#             for event in events:
#                 # Extract start and end dates
#                 dtstart = event.get('DTSTART')
#                 dtend = event.get('DTEND')
                
#                 if dtstart:
#                     if hasattr(dtstart.dt, 'isoformat'):
#                         start_dates.append(dtstart.dt)
                
#                 if dtend:
#                     if hasattr(dtend.dt, 'isoformat'):
#                         end_dates.append(dtend.dt)
            
#             if start_dates:
#                 first_event = min(start_dates)
#                 metadata['first_event'] = first_event.isoformat()
            
#             if end_dates:
#                 last_event = max(end_dates)
#                 metadata['last_event'] = last_event.isoformat()
        
#         return metadata
    
#     except Exception as e:
#         logger.warning(f"iCalendar parsing with icalendar failed: {e}")
#         return extract_icalendar_metadata_basic(ical_content, options)


# def extract_icalendar_metadata_basic(
#     ical_content: str,
#     options: Optional[dict[str, Any]] = None
# ) -> dict[str, Any]:
#     """
#     Extract metadata from iCalendar content using basic line parsing.
    
#     Args:
#         ical_content: The iCalendar content as text.
#         options: Optional extraction options.
        
#     Returns:
#         Dictionary of metadata.
#     """
#     # Basic metadata
#     metadata = {
#         'format': 'calendar'
#     }
    
#     # Count events
#     event_count = ical_content.count('BEGIN:VEVENT')
#     metadata['event_count'] = event_count
    
#     # Extract calendar properties
#     for prop in ['X-WR-CALNAME', 'X-WR-CALDESC', 'CALSCALE', 'VERSION']:
#         match = re.search(f"{prop}:([^\\r\\n]+)", ical_content)
#         if match:
#             metadata[prop.lower().replace('-', '_')] = match.group(1)
    
#     return metadata


# def create_icalendar_sections_advanced(
#     ical_content: str,
#     options: Optional[dict[str, Any]] = None
# ) -> list[dict[str, Any]]:
#     """
#     Create sections from iCalendar content using the icalendar library.
    
#     Args:
#         ical_content: The iCalendar content as text.
#         options: Optional extraction options.
        
#     Returns:
#         List of sections.
#     """
#     if not ICALENDAR_AVAILABLE:
#         logger.warning("icalendar library not available, using basic section creation")
#         return create_icalendar_sections_basic(ical_content, options)
    
#     try:
#         # Parse iCalendar content
#         cal = icalendar.Calendar.from_ical(ical_content)
        
#         sections = []
        
#         # Create a section for each event
#         for event in cal.walk('VEVENT'):
#             event_data = {}
            
#             # Extract common event properties
#             for key in ['SUMMARY', 'DESCRIPTION', 'LOCATION', 'STATUS']:
#                 if key in event:
#                     event_data[key.lower()] = str(event.get(key, ''))
            
#             # Extract dates
#             if 'DTSTART' in event:
#                 dtstart = event['DTSTART']
#                 event_data['start'] = dtstart.dt.isoformat() if hasattr(dtstart.dt, 'isoformat') else str(dtstart.dt)
            
#             if 'DTEND' in event:
#                 dtend = event['DTEND']
#                 event_data['end'] = dtend.dt.isoformat() if hasattr(dtend.dt, 'isoformat') else str(dtend.dt)
            
#             # Add to sections
#             sections.append({
#                 'type': 'event',
#                 'content': event_data.get('description', ''),
#                 'title': event_data.get('summary', ''),
#                 'start': event_data.get('start', ''),
#                 'end': event_data.get('end', ''),
#                 'location': event_data.get('location', ''),
#                 'status': event_data.get('status', '')
#             })
        
#         return sections
    
#     except Exception as e:
#         logger.warning(f"iCalendar section creation with icalendar failed: {e}")
#         return create_icalendar_sections_basic(ical_content, options)


# def create_icalendar_sections_basic(
#     ical_content: str,
#     options: Optional[dict[str, Any]] = None
# ) -> list[dict[str, Any]]:
#     """
#     Create sections from iCalendar content using basic line parsing.
    
#     Args:
#         ical_content: The iCalendar content as text.
#         options: Optional extraction options.
        
#     Returns:
#         List of sections.
#     """
#     sections = []
    
#     # Extract events
#     events = []
#     current_event = {}
#     lines = [line.strip() for line in ical_content.split('\n')]
#     in_event = False
    
#     for line in lines:
#         if line == 'BEGIN:VEVENT':
#             in_event = True
#             current_event = {}
#         elif line == 'END:VEVENT':
#             in_event = False
#             if current_event:
#                 events.append(current_event)
#         elif in_event and ':' in line:
#             key, value = line.split(':', 1)
#             current_event[key] = value
    
#     # Create sections for each event
#     for event in events:
#         section = {
#             'type': 'event',
#             'content': event.get('DESCRIPTION', ''),
#             'title': event.get('SUMMARY', '')
#         }
        
#         # Format dates
#         if 'DTSTART' in event:
#             section['start'] = format_datetime(event['DTSTART'])
        
#         if 'DTEND' in event:
#             section['end'] = format_datetime(event['DTEND'])
        
#         if 'LOCATION' in event:
#             section['location'] = event['LOCATION']
        
#         sections.append(section)
    
#     return sections


# def process_calendar(
#     file_content: Any,
#     options: dict[str, Any]
# ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
#     """
#     Process iCalendar content.
    
#     Args:
#         file_content: The file content to process.
#         options: Processing options.
        
#     Returns:
#         Tuple of (text content, metadata, sections).
#     """
#     # Get iCalendar content as text
#     if hasattr(file_content, 'get_as_text'):
#         ical_content = file_content.get_as_text()
#     else:
#         ical_content = file_content
    
#     # Extract metadata
#     if ICALENDAR_AVAILABLE:
#         metadata = extract_icalendar_metadata_advanced(ical_content, options)
#         sections = create_icalendar_sections_advanced(ical_content, options)
#     else:
#         metadata = extract_icalendar_metadata_basic(ical_content, options)
#         sections = create_icalendar_sections_basic(ical_content, options)
    
#     # Create human-readable text
#     output_text = []
    
#     # Add calendar info
#     if 'calendar_name' in metadata and metadata['calendar_name']:
#         output_text.append(f"Calendar: {metadata['calendar_name']}")
    
#     if 'calendar_desc' in metadata and metadata['calendar_desc']:
#         output_text.append(f"Description: {metadata['calendar_desc']}")
    
#     output_text.append(f"Events: {metadata['event_count']}")
#     output_text.append("")
    
#     # Add event info
#     for section in sections:
#         if section['type'] == 'event':
#             output_text.append(f"Event: {section.get('title', 'Untitled')}")
            
#             if section.get('start'):
#                 output_text.append(f"Start: {section['start']}")
            
#             if section.get('end'):
#                 output_text.append(f"End: {section['end']}")
            
#             if section.get('location'):
#                 output_text.append(f"Location: {section['location']}")
            
#             if section.get('content'):
#                 output_text.append(f"Description: {section['content']}")
            
#             output_text.append("")
    
#     return "\n".join(output_text), metadata, sections