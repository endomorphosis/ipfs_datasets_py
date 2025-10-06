import faker
from faker.providers import DynamicProvider
from typing import Generator, List
import random
import itertools
import nltk
from nltk.corpus import brown
from collections import defaultdict

try:
    nltk.data.find('corpora/brown')
    nltk.data.find('taggers/averaged_perceptron_tagger')
except LookupError as e:
    raise LookupError(
        "NLTK Brown corpus or tagger not found. " \
        "Please run `nltk.download('brown')` and " \
        "`nltk.download('averaged_perceptron_tagger')`."
    ) from e








# Initialize faker with seed for reproducibility
fake = faker.Faker()
fake.seed_instance(420)

def extract_words_by_pos():
    """Extract words from Brown corpus by part-of-speech tags."""
    # Group words by POS tag
    pos_groups = defaultdict(set)

    for word, tag in brown.tagged_words(tagset='universal'):
        pos_groups[tag].add(word.lower()) 

    return {
        'adjectives': list(pos_groups['ADJ']),
        'nouns': list(pos_groups['NOUN']), 
        'verbs': list(pos_groups['VERB']),
        'adverbs': list(pos_groups['ADV']),
        'conjunctions': list(pos_groups['CONJ']),
        'prepositions': list(pos_groups['ADP']),
        'pronouns': list(pos_groups['PRON']),
        'determiners': list(pos_groups['DET']),
        'interjections': list(pos_groups['INTJ']),
        'symbols': list(pos_groups['SYM']),
        'numbers': list(pos_groups['NUM']),
        'particles': list(pos_groups['PART']),
    }

def extract_superlatives_and_comparatives():
    """Extract superlative and comparative adjectives from Brown corpus."""
    adjectives = []
    tagged_words = brown.tagged_words(tagset='universal')
    
    for word, tag in tagged_words:
        clean_word = word.lower()
        if tag == 'ADJ' and clean_word.isalpha():
            # Look for superlative patterns
            if clean_word.endswith('est') or clean_word.startswith('most'):
                adjectives.append(clean_word)
            # Look for comparative patterns  
            elif clean_word.endswith('er') or clean_word.startswith('more'):
                adjectives.append(clean_word)
    
    return list(set(adjectives))

# Extract word lists from Brown corpus
print("Extracting words from Brown corpus...")
WORD_LISTS = extract_words_by_pos()
SUPERLATIVES = extract_superlatives_and_comparatives()

# Filter for common/useful words and limit size for performance
ADJECTIVES = [w for w in WORD_LISTS['adjectives']]
NOUNS = [w for w in WORD_LISTS['nouns']][:800] 
VERBS = [w for w in WORD_LISTS['verbs']][:600]
ADVERBS = [w for w in WORD_LISTS['adverbs']][:300]
SUPERLATIVES = [w for w in SUPERLATIVES if len(w) < 15][:200]

print(f"Extracted: {len(ADJECTIVES)} adjectives, {len(NOUNS)} nouns, {len(VERBS)} verbs, {len(ADVERBS)} adverbs, {len(SUPERLATIVES)} superlatives")


def make_person_sentence_fragments(person_list: List[str]) -> List[str]:
    """
    Generate a list of incomplete sentence fragments about persons using Brown corpus vocabulary.

    Args:
        person_list (List[str]): List of person names to generate fragments about.

    Returns:
        List[str]: A list of incomplete sentence fragments about the persons.
    """
    fragments = []
    
    for person in person_list:
        # Basic templates
        basic_templates = [
            f"Who is {person}",
            f"Tell me about {person}",
            f"What can you tell me about {person}",
            f"What is {person} known for",
            f"Is {person}",
            f"Where does {person}",
            f"When was {person}",
            f"Does {person}",
            f"{person} is",
            f"{person}'s"
        ]
        fragments.extend(basic_templates)
        
        # How + adjective variations: "How brilliant is {person}"
        for adj in random.sample(ADJECTIVES, min(10, len(ADJECTIVES))):
            fragments.append(f"How {adj} is {person}")
        
        # Possessive + noun: "What is {person}'s philosophy"
        for noun in random.sample(NOUNS, min(15, len(NOUNS))):
            fragments.append(f"What is {person}'s {noun}")
        
        # Possessive + superlative: "What is {person}'s greatest"
        for sup in random.sample(SUPERLATIVES, min(8, len(SUPERLATIVES))):
            fragments.append(f"What is {person}'s {sup}")
        
        # Is + person + adjective: "Is {person} brilliant"  
        for adj in random.sample(ADJECTIVES, min(8, len(ADJECTIVES))):
            fragments.append(f"Is {person} {adj}")
        
        # Does + person + verb: "Does {person} understand"
        for verb in random.sample(VERBS, min(10, len(VERBS))):
            fragments.append(f"Does {person} {verb}")
        
        # Did + person + verb: "Did {person} accomplish"
        for verb in random.sample(VERBS, min(8, len(VERBS))):
            fragments.append(f"Did {person} {verb}")
        
        # When did + person + verb: "When did {person} discover" 
        for verb in random.sample(VERBS, min(6, len(VERBS))):
            fragments.append(f"When did {person} {verb}")
        
        # Where does + person + verb: "Where does {person} study"
        for verb in random.sample(VERBS, min(6, len(VERBS))):
            fragments.append(f"Where does {person} {verb}")
        
        # Adverb + adjective: "How remarkably intelligent is {person}"
        for adv in random.sample(ADVERBS, min(5, len(ADVERBS))):
            for adj in random.sample(ADJECTIVES, min(2, len(ADJECTIVES))):
                fragments.append(f"How {adv} {adj} is {person}")
    
    return fragments


def make_place_sentence_fragments(place_list: List[str]) -> List[str]:
    """Generate incomplete sentence fragments about places using Brown corpus vocabulary."""
    fragments = []
    
    for place in place_list:
        # Basic templates
        basic_templates = [
            f"Where is {place}",
            f"Tell me about {place}",
            f"What is {place} known for",
            f"How big is {place}",
            f"Is {place}",
            f"{place} is located",
            f"In {place}",
            f"The population of {place}"
        ]
        fragments.extend(basic_templates)
        
        # How + adjective + is + place: "How magnificent is Paris"
        for adj in random.sample(ADJECTIVES, min(8, len(ADJECTIVES))):
            fragments.append(f"How {adj} is {place}")
        
        # Is + place + adjective: "Is Tokyo crowded"
        for adj in random.sample(ADJECTIVES, min(6, len(ADJECTIVES))):
            fragments.append(f"Is {place} {adj}")
        
        # What is + place's + noun: "What is London's architecture"
        for noun in random.sample(NOUNS, min(10, len(NOUNS))):
            fragments.append(f"What is {place}'s {noun}")
        
        # What is + place's + superlative: "What is Rome's oldest"
        for sup in random.sample(SUPERLATIVES, min(5, len(SUPERLATIVES))):
            fragments.append(f"What is {place}'s {sup}")
        
        # Where in + place + verb: "Where in Japan can"
        for verb in random.sample(VERBS, min(4, len(VERBS))):
            fragments.append(f"Where in {place} can you {verb}")
        
        # When was + place: "When was Rome established"
        for verb in random.sample(VERBS, min(3, len(VERBS))):
            fragments.append(f"When was {place} {verb}")
    
    return fragments


def make_thing_sentence_fragments(thing_list: List[str]) -> List[str]:
    """Generate incomplete sentence fragments about things using Brown corpus vocabulary."""
    fragments = []
    
    for thing in thing_list:
        # Basic templates
        basic_templates = [
            f"What is {thing}",
            f"Tell me about {thing}",
            f"How does {thing}",
            f"Is {thing}",
            f"Where can I find {thing}",
            f"Who invented {thing}",
            f"When was {thing}",
            f"{thing} is",
            f"The {thing}",
            f"Using {thing}"
        ]
        fragments.extend(basic_templates)
        
        # How + adjective + is + thing: "How sophisticated is Bitcoin"
        for adj in random.sample(ADJECTIVES, min(8, len(ADJECTIVES))):
            fragments.append(f"How {adj} is {thing}")
        
        # Is + thing + adjective: "Is Python efficient"
        for adj in random.sample(ADJECTIVES, min(6, len(ADJECTIVES))):
            fragments.append(f"Is {thing} {adj}")
        
        # What is + thing's + noun: "What is Apple's strategy"
        for noun in random.sample(NOUNS, min(10, len(NOUNS))):
            fragments.append(f"What is {thing}'s {noun}")
        
        # What is + thing's + superlative: "What is Tesla's newest"
        for sup in random.sample(SUPERLATIVES, min(5, len(SUPERLATIVES))):
            fragments.append(f"What is {thing}'s {sup}")
        
        # Can + thing + verb: "Can Bitcoin revolutionize"
        for verb in random.sample(VERBS, min(6, len(VERBS))):
            fragments.append(f"Can {thing} {verb}")
        
        # Does + thing + verb: "Does Python support"
        for verb in random.sample(VERBS, min(6, len(VERBS))):
            fragments.append(f"Does {thing} {verb}")
        
        # How + adverb + does + thing + verb: "How efficiently does Python execute"
        for adv in random.sample(ADVERBS, min(3, len(ADVERBS))):
            for verb in random.sample(VERBS, min(2, len(VERBS))):
                fragments.append(f"How {adv} does {thing} {verb}")
    
    return fragments


def generate_entities_by_category(count: int = 10) -> dict:
    """Generate fake entities by category."""
    categories = {
        "person": [],
        "place": [],
        "thing": []
    }
    
    # Generate persons
    for _ in range(count):
        categories["person"].append(fake.name())
    
    # Generate places
    place_generators = [fake.city, fake.country, fake.state]
    for _ in range(count):
        generator = random.choice(place_generators)
        categories["place"].append(generator())
    
    # Generate things
    thing_generators = [
        fake.credit_card_provider, fake.job, fake.company,
        lambda: fake.cryptocurrency_name(), lambda: fake.currency_name()
    ]
    for _ in range(count):
        generator = random.choice(thing_generators)
        categories["thing"].append(generator())
    
    return categories


def generate_test_sentences(entity_count: int = 10) -> List[str]:
    """
    Generate a comprehensive list of test sentences for NLP processing.
    
    Args:
        entity_count (int): Number of entities to generate per category.
        
    Returns:
        List[str]: List of generated sentences.
    """
    # Generate entities
    entities = generate_entities_by_category(entity_count)
    
    all_sentences = []
    
    # Generate sentences for each category
    all_sentences.extend(make_person_sentence_fragments(entities["person"]))
    all_sentences.extend(make_place_sentence_fragments(entities["place"]))
    all_sentences.extend(make_thing_sentence_fragments(entities["thing"]))
    
    # Add some random sentences
    for _ in range(20):
        all_sentences.append(fake.sentence())
    
    return all_sentences


def main():
    """Generate and print test sentences."""
    sentences = generate_test_sentences(entity_count=5)
    
    print(f"Generated {len(sentences)} test sentences:")
    print("-" * 50)
    
    for i, sentence in enumerate(sentences[:20], 1):  # Show first 20
        print(f"{i:2d}. {sentence}")
    
    if len(sentences) > 20:
        print(f"... and {len(sentences) - 20} more sentences")
    
    return sentences


if __name__ == "__main__":
    main()