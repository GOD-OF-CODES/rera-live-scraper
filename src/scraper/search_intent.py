"""Interpret free-text clues using the current RERA form's own options."""
import re
from difflib import SequenceMatcher


PARCEL = re.compile(
    r'\b(?P<kind>khasra|plot)\b\s*(?:(?:number\b|no\b\.?)\s*)?[:#]?\s*'
    r'(?P<number>[a-z0-9]+(?:\s*[/\-]\s*[a-z0-9]+)*)\b', re.I)


def parcel_clues(query):
    """Keep compound identifiers intact; never fuzzy-match parcel numbers."""
    clues = []
    def remove(match):
        number = re.sub(r'\s+', '', match['number']).upper()
        if not any(c.isdigit() for c in number):
            return match[0]
        clues.append({'kind': match['kind'].lower(), 'number': number})
        return ' '
    remaining = PARCEL.sub(remove, query)
    return clues, remaining


def identifier_matches(number, value):
    tokens = re.findall(r'[a-z0-9]+(?:\s*[/\-]\s*[a-z0-9]+)*', str(value), re.I)
    return number.upper() in {re.sub(r'\s+', '', token).upper() for token in tokens}


def matching_parcels(clues, records, address):
    """Return evidence for every requested parcel, or no match.

    RERA sometimes combines khasra and plot numbers in one column. Preserve
    that source label instead of claiming a more precise record type.
    """
    evidence = []
    for clue in clues:
        hits = [record for record in records
                if clue['kind'] in record['kinds']
                and identifier_matches(clue['number'], record['number'])]
        if not hits and clue['kind'] == 'plot':
            address_clues, _ = parcel_clues(address)
            if clue in address_clues:
                hits = [{'number': clue['number'], 'source': 'Published project address'}]
        if not hits:
            return []
        evidence.append({'query': f"{clue['kind']} {clue['number']}",
                         'published_number': hits[0]['number'], 'source': hits[0]['source']})
    return evidence


def words(value):
    value = re.sub(r'\bsec\.?\s*(?=\d)', 'sector ', value.lower())
    return re.findall(r'[^\W_]+', value, re.UNICODE)


def matches(terms, text):
    available = words(text)
    return all(any(t == w or (t.isalpha() and w.isalpha() and len(t) >= 5 and len(w) >= 5 and
                   SequenceMatcher(None, t, w).ratio() >= .86)
                   for w in available) for t in terms)


def interpret(query, soup, prefix):
    parcels, remaining_query = parcel_clues(query)
    normalized = ' '.join(words(remaining_query))
    district = ''
    aliases = {'greater noida': 'Gautam Buddha Nagar', 'noida': 'Gautam Buddha Nagar',
               'allahabad': 'Prayagraj', 'banaras': 'Varanasi', 'gomti nagar': 'Lucknow',
               'vrindavan yojna': 'Lucknow', 'indirapuram': 'Ghaziabad',
               'raj nagar extension': 'Ghaziabad', 'crossings republik': 'Ghaziabad'}
    select = soup.find('select', attrs={'name': prefix + 'DdlprojectDistrict'})
    if select:
        for option in select.find_all('option'):
            if option.get('value') not in ('', '0', None):
                aliases[' '.join(words(option.get_text()))] = option['value']
    remaining = normalized
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(r'\b' + re.escape(alias) + r'\b', remaining):
            district = aliases[alias]
            if alias not in {'gomti nagar', 'vrindavan yojna', 'indirapuram', 'raj nagar extension', 'crossings republik'}:
                remaining = re.sub(r'\b' + re.escape(alias) + r'\b', ' ', remaining)
            break
    remaining = re.sub(r'\b(?:find|show|me|project|projects|property|properties|in|at|near|by|the|please|uttar pradesh|india)\b', ' ', remaining)
    terms = words(remaining)
    promoter = ''
    options = soup.find('select', attrs={'name': prefix + 'ddl_prm'})
    if terms and options and not parcels:
        candidates = [o for o in options.find_all('option')
                      if o.get('value') not in ('', '0', None) and matches(terms, o.get_text())]
        if len(candidates) == 1:
            promoter = candidates[0]['value']
    # District-scoped searches inspect source pages for all remaining clues,
    # including addresses which are absent from the public search form.
    return {'district': district, 'promoter': promoter,
            'project_name': '' if district or promoter else (' '.join(terms) or normalized),
            'terms': [] if promoter else terms,
            'parcels': parcels,
            'inspect_details': bool(district and (terms or parcels) and not promoter)}
