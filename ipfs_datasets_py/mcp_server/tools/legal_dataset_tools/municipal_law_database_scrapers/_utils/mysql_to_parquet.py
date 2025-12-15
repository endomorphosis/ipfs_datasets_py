# !/usr/bin/env python3
import asyncio
import json
import logging
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Optional
from types import ModuleType


from bs4 import BeautifulSoup
import duckdb
import pyarrow as pa
import pandas as pd
import tqdm


from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.municipal_law_database_scrapers._utils.configs import Configs, configs
from ipfs_datasets_py.ipfs_multiformats import get_cid
from .make_openai_embeddings import OpenAIEmbedding


_CID_RAND_NUM_SEED = 420


def _extract_date_with_m_d_y_format(text):
    """
    Extract dates from legislative references.
    
    This regex looks for:
    - Optional day-month separator (-, /, or .)
    - 1-2 digits for day or month
    - Separator (-, /, or .)
    - 1-2 digits for day or month
    - Separator (-, /, or .)
    - 2-4 digits for year
    
    Examples:
    - 1-19-1993
    - 01/19/1993
    - 1.19.93
    
    Args:
        text (str): Text containing a date
        
    Returns:
        str or None: Extracted date string or None if no date found
    """
    # Pattern matches dates like 1-19-1993, 01/19/1993, 1.19.93
    pattern = r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})'
    
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None

def _get_year(date):
    """
    Extract the year from a date string.
    
    Args:
        date (str): Date string
        
    Returns:
        str or None: Year extracted from date or None if no year found
    """
    def _get_year_from_date(date):
        if date:
            return date.split('-')[-1] if len(date) == 4 else None
        return None

    for func in [_extract_date_with_m_d_y_format]:
        year = func(date)
        if year:
            return year
    return None


def _clean_ordinance(ordinance: str):
    """
    Clean up ordinance numbers.
    
    Args:
        ordinance (str): Ordinance number
        
    Returns:
        str or None: Cleaned ordinance number or None if no ordinance found
    """
    if ordinance:
        # Remove any leading or trailing whitespace
        ordinance = ordinance.strip()
        # Make all whitespace a single space
        ordinance = re.sub(r'\s+', ' ', ordinance)
        # Remove newlines
        ordinance = ordinance.replace('\n', ' ')
        # Remove any leading or trailing punctuation
        ordinance = ordinance.strip('.,')
        # Remove any leading or trailing whitespace
        ordinance = ordinance.strip()
        return ordinance
    return None



def _get_random_str():
    # Initialize the random generator with the seed to ensure deterministic results
    random.seed(_CID_RAND_NUM_SEED)
    return str(random.randint(0, 12))

_STATE_CODE_CROSSWALK = {
    'AL': 'Ala.',
    'AK': 'Alaska',
    'AZ': 'Ariz.',
    'AR': 'Ark.',
    'CA': 'Cal.',
    'CO': 'Colo.',
    'CT': 'Conn.',
    'DE': 'Del.',
    'FL': 'Fla.',
    'GA': 'Ga.',
    'HI': 'Haw.',
    'ID': 'Idaho',
    'IL': 'Ill.',
    'IN': 'Ind.',
    'IA': 'Iowa',
    'KS': 'Kan.',
    'KY': 'Ky.',
    'LA': 'La.',
    'ME': 'Me.',
    'MD': 'Md.',
    'MA': 'Mass.',
    'MI': 'Mich.',
    'MN': 'Minn.',
    'MS': 'Miss.',
    'MO': 'Mo.',
    'MT': 'Mont.',
    'NE': 'Neb.',
    'NV': 'Nev.',
    'NH': 'N.H.',
    'NJ': 'N.J.',
    'NM': 'N.M.',
    'NY': 'N.Y.',
    'NC': 'N.C.',
    'ND': 'N.D.',
    'OH': 'Ohio',
    'OK': 'Okla.',
    'OR': 'Or.',
    'PA': 'Pa.',
    'RI': 'R.I.',
    'SC': 'S.C.',
    'SD': 'S.D.',
    'TN': 'Tenn.',
    'TX': 'Tex.',
    'UT': 'Utah',
    'VT': 'Vt.',
    'VA': 'Va.',
    'WA': 'Wash.',
    'WV': 'W. Va.',
    'WI': 'Wis.',
    'WY': 'Wyo.',
    'DC': 'D.C.',
    'PR': 'P.R.',
    'VI': 'V.I.',
    'GU': 'Guam',
    'AS': 'Am. Samoa',
    'MP': 'N. Mar. I.'
}

_MONTHS_OF_THE_YEAR = [
    'january', 'february', 'march', 'april', 'may', 
    'june', 'july', 'august', 'september', 'october', 
    'november', 'december',
    # Common abbreviations 
    'jan', 'feb', 'mar', 'apr', 'jun', 
    'jul', 'aug', 'sep', 'sept', 'oct', 
    'nov', 'dec',
    # Period abbreviations
    'jan.', 'feb.', 'mar.', 'apr.', 'jun.', 
    'jul.', 'aug.', 'sep.', 'sept.', 'oct.', 
    'nov.', 'dec.'
]


_DATE_PATTERNS = [ # (match pattern, year extraction pattern,)
    (r'(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', r'[-/.]\d{2,4}$'),  # matches dates like 1-19-1993, 01/19/1993, 1.19.93
    (r'(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})', r'^(\d{4})'),  # matches ISO format dates like 1993-01-19
    (r'([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})', r'\s(\d{4})$'),  # matches "January 19, 1993" or "Jan. 19, 1993"
    (r'(\d{1,2}\s+[A-Z][a-z]+\.?\s+\d{4})', r'\s(\d{4})$'),  # matches "19 January 1993" or "19 Jan. 1993"
    (r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Z][a-z]+\.?,?\s+\d{4})', r'\s(\d{4})$'),  # matches "19th of January, 1993"
    (r'([A-Z][a-z]+\.?\s+(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})', r'\s(\d{4})$'),  # matches "January the 19th, 1993"
    (r'(\d{4})', r'^(\d{4})$'),  # just a year like 1993
    (r'(\d{1,2}/\d{1,2}/\d{2})', r'/(\d{2})$'),  # matches 1/19/93
    (r'(\d{1,2}\s+[A-Z][a-z]{2,}\s+\d{2})', r'\s(\d{2})$'),  # matches "19 January 93"
    (r'([A-Z][a-z]{2,}\s+\d{1,2},?\s+\d{2})', r'\s(\d{2})$'),  # matches "January 19, 93"
    (r'(?:dated\s+)(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', r'[-/.]\d{2,4}$'),  # matches "dated 1/19/1993"
    (r'(?:dated\s+)([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})', r'\s(\d{4})$'),  # matches "dated January 19, 1993"
    (r'(?:effective\s+)(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', r'[-/.]\d{2,4}$'),  # matches "effective 1/19/1993"
    (r'(?:effective\s+)([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})', r'\s(\d{4})$'),  # matches "effective January 19, 1993"
    (r'(?:adopted\s+)(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})', r'[-/.]\d{2,4}$'),  # matches "adopted 1/19/1993"
    (r'(?:adopted\s+)([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})', r'\s(\d{4})$')  # matches "adopted January 19, 1993"
]




class MySqlToParquet:
    """
    Class to download data from MySQL and save it as parquet files.
    
    This class handles extracting data from MySQL tables using DuckDB as an intermediary,
    and saving the data as parquet files, organized by a partition column.
    """
    
    def __init__(self, *, resources: dict[str, Any], configs: Configs):
        self.configs = configs
        self.resources = resources

        self.logger: logging.Logger = resources['logger']
        self.duckdb = resources['duckdb']
        self.date_patterns = resources['date_patterns']

        # Setup database connection details
        self.db_name: str = configs.sql.DATABASE_NAME
        self.host: str = configs.sql.HOST
        self.user: str = configs.sql.USER
        self.password: str = configs.sql.PASSWORD
        self.compression_type: str = configs.sql.COMPRESSION_TYPE
    
        # Setup table names and other configurations
        self.data_table_names: list[str] = configs.sql.tables.DATA_TABLE_NAMES
        self.metadata_table_names: list[str] = configs.sql.tables.METADATA_TABLE_NAMES
        self.limit: int = configs.sql.LIMIT
        self.batch_size: int = configs.sql.BATCH_SIZE
        self.partition_column: str = configs.sql.PARTITION_COLUMN

        self.sql_type: str = "mysql"
        self.name_var: str = "gnis"
        self.html_metadata_table = None
        self.place_metadata_table = None
        self.data_table = None
        self.connection_string = None
        #self.open_ai_embedding = OpenAIEmbedding()
        self._create_sql_statements()

        # Setup paths
        self.data_output_path = Path(configs.sql.OUTPUT_FOLDER) / configs.TARGET_DIR_NAME / "data"
        self.metadata_output_path = Path(configs.sql.OUTPUT_FOLDER) / configs.TARGET_DIR_NAME / "metadata"
        self._ensure_output_directories()

        # Initialize database connection
        self._setup_duckdb()

    def _create_sql_statements(self):
        """Create sql statements."""
        self.connection_string = f"{self.sql_type}://{self.user}:{self.password}@{self.host}/{self.db_name}"
        self.db_typed = f"{self.sql_type}_db"

        # Tables
        self.data_table = f"{self.db_typed}.{self.db_name}.{self.data_table_names[0]}"
        self.raw_api_output_table = f"{self.db_typed}.{self.db_name}.{self.data_table_names[1]}"

        # Metadata tables
        self.html_metadata_table = f"{self.db_typed}.{self.db_name}.{self.metadata_table_names[0]}"
        self.place_metadata_table = f"{self.db_typed}.{self.db_name}.{self.metadata_table_names[1]}"

    def _setup_duckdb(self) -> None:
        """Setup DuckDB with MySQL extension and establish connection."""
        duckdb.sql(f'INSTALL {self.sql_type};')
        duckdb.sql(f'LOAD {self.sql_type};')

        # Using DuckDB's preferred connection format with MySQL extension
        duckdb.sql(f"ATTACH '{self.connection_string}' AS {self.db_typed} (TYPE {self.sql_type.upper()}, READ_ONLY);")

    def _ensure_output_directories(self) -> None:
        """Create output directories if they don't exist."""
        for directory in [self.data_output_path, self.metadata_output_path]:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)

    def _get_complete_groups(self) -> list[int]:
        """Get list of GNIS values with complete sets of laws."""
        group_list = duckdb.sql(f"""
            SELECT DISTINCT gnis 
            FROM {self.html_metadata_table} 
            WHERE we_have_all_the_laws = 1
        """).to_df()['gnis'].to_list()

        print(f"Got {len(group_list)} complete groups. Fetching...")
        return group_list
    
    def _save_data_to_parquet(self, df: pd.DataFrame, parquet_path: Path) -> None:
        """Save data to parquet files, grouped by partition column."""

        # Check if partition column exists
        if self.partition_column not in df.columns:
            raise ValueError(f"Partition column '{self.partition_column}' not found in DataFrame columns: {df.columns.tolist()}")

        # Group by partition column
        for partition_value, group_df in df.groupby(self.partition_column):

            # Pop off the partition column
            group_df = group_df.drop(columns=[self.partition_column])

            # Save the group as a parquet file
            group_df.to_parquet(parquet_path, compression=self.compression_type)  # type: ignore[call-overload]
            self.logger.info(f"Saved partition {str(partition_value)} with {len(group_df)} rows to {parquet_path}")

    def _get_metadata_from_server(self, gnis: int) -> pd.DataFrame:
        """Get combined metadata for a GNIS from MySQL server."""
        combined_metadata_query = f"""
        SELECT lm.place_name, 
            lm.state_name,
            lm.state_code, 
            lm.class_code,
            lm.place_name,
            hm.total_sections, 
            hm.last_updated 
        FROM {self.place_metadata_table} lm
            INNER JOIN {self.html_metadata_table} hm
        ON lm.gnis = hm.gnis
            WHERE lm.gnis = '{gnis}'
        """
        combined_metadata_df = duckdb.sql(combined_metadata_query).to_df()
        self.logger.debug(combined_metadata_df)
        return combined_metadata_df


    def _save_metadata(self, gnis: int, metadata_df: pd.DataFrame) -> None:
        """Save metadata for a GNIS to a JSON file."""
        # Save combined metadata to JSON
        json_path = self.metadata_output_path / f"{str(gnis)}.json"
        # Skip if the file already exists
        if self.metadata_output_path.exists():
            return
        else:
            metadata_df.to_json(json_path, orient='records', lines=True)
            self.logger.info(f"Saved metadata for GNIS {gnis} to {json_path}")


    @staticmethod
    def _try_patterns(input: str, pattern_list: list) -> str:
        """
        Try a bunch of patterns to extract the ordinance, section, and date.
        """
        for pattern in pattern_list:
            match = re.search(pattern, input)
            if match:
                return match.groups(1)[0] # type: ignore[assignment]
        return "NA"


    @staticmethod
    def _make_bluebook_cid(*, gnis: str, place_name: str) -> str:
        """Make a CID based on the Bluebook citation."""
        raise NotImplementedError("This method is not yet written. Use get_cid from ipfs_datasets_py.ipfs_multiformats instead.")


    def _make_citation_parquet_row(self, *,
                                bluebook_df: pd.DataFrame,
                                row: pd.Series, 
                                title: str, 
                                chapter: str, 
                                history_note: str,
                                metadata_df: pd.DataFrame) -> pd.DataFrame:
        """
        Create a row for the Bluebook citation parquet file.

        This method processes legal citation data from municipal/county codes and creates a standardized
        Bluebook citation format entry. It extracts title numbers, chapter numbers, dates from history notes,
        and combines them with metadata to generate proper legal citations.

        Args:
            bluebook_df (pd.DataFrame, optional): Existing DataFrame of Bluebook citations to append to.
            row (pd.Series, optional): Row containing source data including cid and gnis identifiers.
            title (str, optional): The title text of the legal provision.
            chapter (str, optional): The chapter text of the legal provision.
            history_note (str, optional): Text containing historical information about the provision,
                typically including dates and ordinance references.
            metadata_df (pd.DataFrame, optional): DataFrame containing metadata about the jurisdiction,
                including place name, state code, and class code.

        Returns:
            pd.DataFrame: Updated DataFrame with the new Bluebook citation row appended.

        Notes:
            - The function handles various date formats using multiple regex patterns.
            - Special handling is provided for appendices in chapter names.
            - The function creates a unique citation ID (bluebook_cid) based on 
                place_name, bluebook_state_code, title, and history_note.
            - Returns the original DataFrame if history_note is None.
            - Distinguishes between county and municipal codes based on metadata.
        """
        # Print inputs for debugging
        #print(f"title: {title}")
        #print(f"chapter: {chapter}")
        #print(f"history_note: {history_note}")

        # Skip over it if there's no history note.
        # This should never be called but just in case.
        if history_note is None:
            return bluebook_df

        code_label = "County Code" if "h" in metadata_df['class_code'].iloc[0].lower() else "Municipal Code"
        place_name = metadata_df['place_name'].iloc[0]
        bluebook_state_code = _STATE_CODE_CROSSWALK.get(metadata_df['state_code'].iloc[0])

        # Extract the title number from the title
        title_num = "NA"
        title_num_patterns = [
            r'(\d+\s*[-\.]\s*\d+)', # matches 1-19 or 1.19
            r'(\d+\.\d+)', # matches 1.19
            r'(\d+)' # matches 19
        ]
        if title:
            title = title.strip('. -').strip()
            title_num = self._try_patterns(title, title_num_patterns)
        #print(f"title_num: {title_num}")

        # Get the chapter number from the chapter name
        chapter_numbers = "NA"
        if chapter: # If there's a digit in it, it's probably the chapter number.
            if any(char.isdigit() for char in chapter):
                chapter_numbers = self._try_patterns(chapter, title_num_patterns)

        # Date Patterns

        # Parse history_note for the date

        # Get rid of round brackets
        history_note = history_note.replace('(', '').replace(')', '')

        # Get rid of excessive whitespace and all newlines.
        history_note = re.sub(r'\s+', ' ', history_note).strip()
        history_note = history_note.replace('\n', ' ').strip()

        date = "NA"
        year = "NA"

        # Using the date patterns, extract the year from the history note.
        if history_note:
            history_note_parts: list[str] = history_note.strip().replace('(', '').replace(')', '').strip().split(',')
            _history_note_parts = None

            # Remove the section part of the note.
            for part in history_note_parts:
                remove = False
                part = part.strip()
                # Filter out sections
                if "§" in part:
                    remove = True

                # If the word 'page' or 'pg' is in the part along with numbers, and NOTHING else, remove it.
                # Check if part contains 'page' or 'pg' followed by numbers
                if re.search(r'(page|pg\.?\s+\d+|\d+\s*p\.?)', part.lower()):
                    # Check if after removing page references, there's nothing substantial left
                    cleaned = re.sub(r'(page|pg\.?)\s+\d+|\d+\s*p\.?', '', part.lower(), flags=re.IGNORECASE)
                    if not cleaned.strip() or cleaned.strip() in [',', '.', ';', ':', '']:
                        remove = True

                # Remove the identified page parts from history_note_parts
                if remove:
                    _history_note_parts = [p for p in history_note_parts if p != part]

            if _history_note_parts: # If we found a section, use the remaining parts.
                history_note_parts = _history_note_parts

            try:
                for part in history_note_parts:
                    part = part.strip()
                    for pattern, extract_pattern in self.date_patterns:
                        current_year = int(time.strftime("%Y"))

                        # If there's a date in the part, extract it.
                        date_match = re.search(pattern, part)
                        if date_match:
                            date: str = date_match.groups(1)[0] # type: ignore[assignment]

                            # Extract the year from the date using the extract pattern
                            year_match = re.search(extract_pattern, date)
                            if year_match:
                                _year = None
                                #print(f"year_match: {year_match}")
                                
                                # If there are multiple matches, use the last one.
                                if isinstance(year_match.groups(), tuple) and len(year_match.groups()) > 0:
                                    for match in year_match.groups():
                                        match = match.strip(".,").strip("-").strip("—").strip()
                                        # If the _year is between 1776 and the current year, it's probably the year.
                                        if int(match) >= 1776 and int(match) <= current_year:
                                            _year = match
                                            if match not in date:
                                                date = match
                                                break
                                else:
                                    # If not, extract the match directly
                                    _year = year_match.group(0)

                                # Get rid of any leading or trailing punctuation
                                if _year:
                                    _year = _year.strip(".,").strip("-").strip("—").strip()
                                    #print("_year after strip: ", _year)

                                    if len(_year) == 4:
                                        if int(_year) >= 1776 and int(_year) <= current_year:
                                            year = _year
                                            if _year not in date:
                                                date = _year
                                    else:
                                        if len(_year) == 2:
                                            # If the year is between 00 and 25, it's probably the 21st century.
                                            if int(_year) > 0 and int(_year) <= 25:
                                                year = f"20{_year}" # Ex: 01 -> 2001
                                            else:
                                                year = f"19{_year}" # Ex: 93 -> 1993
                            
                            _history_note_parts = [p for p in history_note_parts if p != part]
                            break
            except Exception as e:
                self.logger.error(f"Error extracting date: {e}")

            if _history_note_parts: # If we found a date, use the remaining parts.
                history_note_parts = _history_note_parts

        parquet_row = {
            'cid': row.cid, # Foreign key to the main parquet file
            'gnis': row.gnis,
            'place_name': metadata_df['place_name'].iloc[0],
            'state_code': metadata_df['state_code'].iloc[0],
            'bluebook_state_code': bluebook_state_code,
            'state_name': metadata_df['state_name'].iloc[0],
            'chapter': chapter,
            'chapter_num': chapter_numbers,
            'title': title,
            'title_num': title_num, # AKA section
            'public_law_num': 'NA', # Placeholder for public law number since city ordinances don't have one.
            'date': date,
            'history_note': history_note,
        }

        appendix_name = None

        spellings = [
            'Appendix', 'Appendices', 'appendix', 'APPENDIX', 'APPENDICES', 
            'Apendix', 'Apendices', 'apendix', 'APENDIX', 'APENDICES', # Common misspellings
            'Appendx', 'appendx', 'APPENDX'
        ]
        for rep in spellings:
            if rep not in chapter.lower():
                continue

            # Standardize the appendix name
            chapter = chapter.replace(rep, 'appendix')

            # Extract which appendix it is.
            for splitter in [':', '—', '-']:
                if splitter in chapter:
                    appendix_name = chapter.split(splitter)[0].strip()
                    break

            # Get rid of the word "Appendix" and any other variations of it.
            # This should leave us with just the letter or number.
            if appendix_name is not None:
                appendix_name = appendix_name.replace(rep, '').strip()
                appendix_name = f"app. {appendix_name}".strip()

        # Build the Bluebook citation
        if title_num != "NA":
            # Appendix route
            if appendix_name:
                bluebook_section_str = f"{appendix_name} §{title_num}"
            else:
                bluebook_section_str = f"§{title_num}"
        else:
            if appendix_name:
                bluebook_section_str = f"{appendix_name}"
            else:
                bluebook_section_str = "NA"
        #print("bluebook_section_str: ", bluebook_section_str)

        bluebook_citation = f"{place_name}, {bluebook_state_code}, {code_label}, {bluebook_section_str}"
        #print(f"bluebook_citation before date", bluebook_citation)
        if "NA" not in year:
            # Append the year to the end if we have the full year in the history note.
            bluebook_citation += f" ({year})" if len(year) == 4 else ""

        # It's better to have missing information than wrong information.
        if "NA" in bluebook_citation:
            bluebook_citation = "NA"

        parquet_row['bluebook_citation']  = bluebook_citation
    
        bluebook_cid_string = f"{place_name}{bluebook_state_code}{title}{history_note}" 
        parquet_row['bluebook_cid'] = get_cid(bluebook_cid_string)

        bluebook_df = pd.concat([
            bluebook_df,
            pd.DataFrame([parquet_row])
        ], ignore_index=True)
        return bluebook_df


    def _get_citations_from_html(self, gnis: int, metadata_df: pd.DataFrame) -> pd.DataFrame:
        """
        """
        # Get Municode's raw output from the database
        api_output_df: pd.DataFrame = duckdb.sql(
            f"SELECT * FROM {self.raw_api_output_table} WHERE gnis = '{gnis}'"
        ).arrow(batch_size=self.batch_size).to_pandas()

        # Convert the content_json column to a dictionary
        api_output_df['content_json'] = api_output_df['content_json'].astype(str).apply(json.loads).apply(dict)

        # Get the chapter names.
        chapter_content_json = api_output_df[ # NOTE We do this because Pandas doesn't play nice with dictionaries in DataFrames
            api_output_df['content_json'].apply(lambda x: x.get('NodeDepth', None)) == 1
        ]['content_json']

        # Make an empty dataframe to store the extracted laws and history notes
        bluebook_df: Optional[pd.DataFrame] = pd.DataFrame(
            columns=['bluebook_cid', 'cid', 'gnis', 'title', 'public_law_num', 
                     'chapter', 'ordinance', 'section', 'enacted', 'year', 'history_note']
        )

        for row in tqdm.tqdm(api_output_df.itertuples(), total=len(api_output_df), desc=f"Processing citations for GNIS {gnis} rows"):

            content_json = row.content_json
            # NOTE: Pylance can't infer the type here, so we ignore it. It's stored in SQL as a json, so we assume it's a dict.
            # TODO: Some way to confirm this?
            title = content_json['Title'] # type: ignore[index]
            soup = BeautifulSoup(content_json['Content'], 'html.parser') # type: ignore[index]

            # Match the ChunkGroupStartingNodeId to the chapter name
            try:
                # Try to find the chapter name based on the ChunkGroupStartingNodeId
                matching_chapters = chapter_content_json[
                    chapter_content_json.apply(lambda x: x['Id'] == content_json.get('ChunkGroupStartingNodeId')) # type: ignore[method]
                ]
                
                if not matching_chapters.empty:
                    chapter = matching_chapters.apply(lambda x: x['Title']).values[0]
                else:
                    # If no matching chapter is found, use a placeholder or the title
                    self.logger.warning(f"No matching chapter found for node ID {content_json.get('ChunkGroupStartingNodeId')} in GNIS {gnis}") # type: ignore[method]
                    chapter = f"Unknown Chapter ({title})"
            except Exception as e:
                self.logger.warning(f"Error getting chapter name: {e}. Using title instead.")
                chapter = title

            # Find the history note
            try:
                history_note = soup.find(
                    class_=lambda class_name: class_name and class_name.startswith('historynote') # type: ignore[arg-value]
                )
                #print(f"history note for {title}: {history_note}")
            except Exception as e:
                #print(f"Error finding history note: {e}")
                history_note = None

            if history_note is not None:
                # Extract the text from the history note
                history_note = history_note.get_text().strip()

                # If there are multiple history notes, split them
                if ";" in history_note:
                    history_note = history_note.strip()
                    # Remove parentheses around the citations if they exist
                    if history_note.startswith("(") and history_note.endswith(")"):
                        history_note = history_note[1:-1].strip()

                    parts: list[str] = history_note.split(";")
                    for history_note_ in parts:
                        bluebook_df = self._make_citation_parquet_row(
                            bluebook_df=bluebook_df,
                            row=row, # type: ignore[arg-type]
                            title=title,
                            chapter=chapter,
                            history_note=history_note_,
                            metadata_df=metadata_df
                        )
                else:
                    bluebook_df = self._make_citation_parquet_row(
                        bluebook_df=bluebook_df,
                        row=row, # type: ignore[arg-type]
                        title=title,
                        chapter=chapter,
                        history_note=history_note,
                        metadata_df=metadata_df
                    )
            else:
                # We can assume that if there is no history note, there is no ordinance.
                #print(f"No history note found for '{title}'")
                continue
        
        if bluebook_df is None:
            raise ValueError("No ordinances or history notes were extracted.")

        # print("Finished extracting ordinances and history notes.")
        # print(f"bluebook_df: {bluebook_df.head()}")
        return bluebook_df


    async def get_files_from_sql_server_as_parquet(self) -> dict[str, list[str]]:
        """
        Download data from MySQL and save it as parquet files.
        
        Returns:
            dict[str, [list[str]]: A dictionary containing the following:
                html: list of string paths to html parquet files
                citation: list of string paths to citation parquet files
                embedding: list of string paths to embedding parquet files

        Example:
        >>> result = await converter.get_files_from_sql_server_as_parquet()
        >>> print(result)
        {
            "html": [
                "/path/to/output/repo_id/data/12345_html.parquet",
                "/path/to/output/repo_id/data/67890_html.parquet"
            ],
            "citation": [
                "/path/to/output/repo_id/data/12345_citation.parquet",
                "/path/to/output/repo_id/data/67890_citation.parquet"
            ],
            "embedding": [
                "/path/to/output/repo_id/data/12345_embedding.parquet"
            ]
        }
        Example Directory Structure:
        >>> output_folder/
            ├── input_from_sql
            │   ├── repo_id
            │   │   ├── data
            │   │   │   ├── 360420_html.parquet
            │   │   │   ├── 360420_citation.parquet
            │   │   │   ├── 360420_embedding.parquet
            │   │   │   ├── ...
            │   │   ├── metadata
            │   │   │   ├── 360420.json
            │   │   │   ├── ...
        Example HTML Parquet Structure:
        >>> {
            "cid":"bafkreicae7q27uvkofpnpgoqqnmq45a5mtlpff4ktfvdeuqaoqtwwaegqa",
            "doc_id":"CO_CH15BULI_ARTIISEORBU_S15-40IN",
            "doc_order":155,
            "html_title":"<div class=\"chunk-title\">Sec. 15-40. - Injunction.</div>",
            "html":"<div class=\"chunk-content\">\n ... </div>",
            "gnis":66855
        }
        Example Citation Parquet Structure:
        >>> {
            "bluebook_cid":"bafkreid3foaz35j7msukneriyygretlr45fddc32mesk6nrfkap6bdmnn4",
            "cid":"bafkreie3sy7cjyo5bnw2pzlnomsapu4dckxhhf5i7ed2vrfqr3763pntjy",
            "title":"Sec. 18-40. - Additional court costs for employment of an investigator for the public defender's office",
            "public_law_num":"NA",
            "chapter":"Chapter 18 - COURTS",
            "ordinance":null,
            "section":null,
            "enacted":null,
            "year":null,
            "history_note":"Code 1987, § 8-21",
            "place_name":"Garland",
            "state_code":"AR",
            "bluebook_state_code":"Ark.",
            "state_name":"Arkansas",
            "chapter_num":"18",
            "title_num":"18-40",
            "date":"1987",
            "bluebook_citation":"Garland, Ark., County Code, §18-40 (1987)",
            "gnis":66855
        }
        Example Embedding Parquet Structure:
        >>> {
            "embedding_cid":"bafkreiananlow6bodt4mqf23mrqn7mpq6sz4t2ourydxvfwwtbkaapzm6y",
            "gnis":"66855",
            "cid":"bafkreicswpqclipcmiglxdmnjemod4esk3u63ocdd6rtuodjijvajxewfi",
            "text_chunk_order":1,"embedding":[0.0123, -0.0456, 0.0789, ...]
        }
        """
        path_dict: dict[str, list[str]] = {
            "html": [],
            "citation": [],
            "embedding": []
        }

        self._ensure_output_directories()

        # Get list of complete groups
        group_list = self._get_complete_groups()

        query = f"SELECT gnis, cid, node_id AS doc_id, doc_order_id AS doc_order, html_title, html FROM {self.data_table}"

        with tqdm.tqdm(total=len(group_list), desc="Processing groups") as pbar:
            for gnis in group_list:
                gnis_query = query + f" WHERE gnis = '{gnis}'"

                # Convert non-string partition values to string for filename
                parquet_path = self.data_output_path / f"{str(gnis)}_html.parquet"
                citation_parquet_path = self.data_output_path / f"{str(gnis)}_citation.parquet"
                embedding_parquet_path = self.data_output_path / f"{str(gnis)}_embedding.parquet"

                kwargs = {
                    "gnis_query": gnis_query,
                    "gnis": gnis,
                    "embedding_parquet_path": embedding_parquet_path,
                }

                # Skip if all files exist.
                key = "default"
                try:
                    for path_tuple in [
                        (parquet_path, self._make_html_parquet, "html"), 
                        (citation_parquet_path, self._make_citation_parquet, "citation"), 
                        (embedding_parquet_path, self._make_embedding_parquet, "embedding")
                    ]:
                        path, func, key = path_tuple
                        parquet_type = path.stem.split("_")[1]
                        if path.exists():
                            self.logger.info(f"{parquet_type} parquet file for '{gnis}' already exists, skipping...")
                            continue
                        else:
                            self.logger.info(f"{parquet_type} parquet file for '{gnis}'...")
                            await func(path, gnis, kwargs)
                            self.logger.info(f"{parquet_type} parquet file for '{gnis}' created successfully")
                            path_dict[key].append(path)
                except Exception as e:
                    self.logger.exception(f"Error processing GNIS '{gnis}' parquet for '{key}': {e}")
                finally:
                    pbar.update(1)
                    continue
            pbar.close()
        return path_dict


    async def _make_html_parquet(self, html_parquet_path: Path, gnis: int, kwargs: dict) -> None:
        gnis_query = kwargs["gnis_query"] 

        # Get html data from the database
        arrow_table: pa.Table = duckdb.sql(gnis_query).arrow(batch_size=self.batch_size)

        # Convert to pandas for easier manipulation
        df: pd.DataFrame = arrow_table.to_pandas()
        self.logger.info(f"Retrieved {len(df)} rows for '{gnis}' from database.")

        # Save html data to parquet files
        self._save_data_to_parquet(df, html_parquet_path)
        return


    async def _make_citation_parquet(self, citation_parquet_path: Path, gnis: int, kwargs: dict) -> None:

        # Get metadata from the server
        metadata_df = self._get_metadata_from_server(gnis)

        # Save metadata to a JSON file
        self._save_metadata(gnis, metadata_df)

        # Get the ordinance data from the HTML
        bluebook_df = self._get_citations_from_html(gnis, metadata_df)

        # Save citations to parquet
        self._save_data_to_parquet(bluebook_df, citation_parquet_path)
        return


    async def _make_embedding_parquet(self, embedding_parquet_path: Path, gnis: int, kwargs: dict) -> None:
        # TODO Find a way to integrate OpenAI embeddings here. Right now, it's an independent program.
        pass
        # # Load in the HTML parquet file
        # html_parquet_path = self.data_output_path / f"{str(gnis)}_html.parquet"

        # embedding = self._make_openai_embeddings(html_parquet_path)
        # if embedding:
        #     embedding_df = pd.DataFrame([embedding])
        # self._save_data_to_parquet(embedding_df, embedding_parquet_path)



async def main() -> int:
    """
    Main function to run the MySqlToParquet process.
    """
    logger = logging.getLogger(__name__)
    resources = {
        "logger": logger,
        "date_patterns": _DATE_PATTERNS,
        "duckdb": duckdb,
        "make_openai_embeddings": None,
    }
    try:
        converter = MySqlToParquet(resources=resources,configs=configs)
        _ = await converter.get_files_from_sql_server_as_parquet()
        return 0
    except KeyboardInterrupt:
        print("User stopped the program. Hope nothing broke!")
        return 0
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
