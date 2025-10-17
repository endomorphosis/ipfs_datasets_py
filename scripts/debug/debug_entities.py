#!/usr/bin/env python3
import re

text = 'Apple Inc. partnered with Microsoft Corporation and Harvard University. Amazon LLC also joined.'

# Reordered patterns - organizations first
patterns = {
    'organization': [
        r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Company|Corporation)\b',
        r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\s+University\b',
        r'\b[A-Z]{2,}(?:\s+[A-Z][a-zA-Z]+)*\b',
    ],
    'person': [
        r'\b(?:Dr|Mr|Ms|Mrs|Prof)\.?\s+[A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+\b',
        r'\b[A-Z][a-zA-Z]+\s+[A-Z][a-zA-Z]+\b(?!\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Company|Corporation|University))',
    ]
}

all_matches = []
for entity_type, type_patterns in patterns.items():
    for pattern in type_patterns:
        for match in re.finditer(pattern, text):
            match_text = match.group().strip()
            print(f'{entity_type}: "{match_text}" at {match.start()}-{match.end()}')
            if len(match_text) > 2:
                all_matches.append({
                    'text': match_text,
                    'type': entity_type,
                    'start': match.start(),
                    'end': match.end()
                })

print(f'\nTotal matches: {len(all_matches)}')
for match in all_matches:
    print(f'  {match}')

# Sort and check overlaps
all_matches.sort(key=lambda x: (x['start'], -(x['end'] - x['start'])))
print(f'\nAfter sorting:')
for match in all_matches:
    print(f'  {match}')

non_overlapping = []
for match in all_matches:
    overlaps = False
    for accepted in non_overlapping:
        if not (match['end'] <= accepted['start'] or match['start'] >= accepted['end']):
            print(f'Overlap: {match["text"]} overlaps with {accepted["text"]}')
            overlaps = True
            break
    if not overlaps:
        non_overlapping.append(match)

print(f'\nFinal non-overlapping matches:')
for match in non_overlapping:
    print(f'  {match["type"]}: {match["text"]}')
