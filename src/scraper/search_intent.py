"""Interpret free-text clues using the current RERA form's own options."""
import re
from difflib import SequenceMatcher


def words(value):
    value = re.sub(r'\bsec\.?\s*(?=\d)', 'sector ', value.lower())
    return re.findall(r'[^\W_]+', value, re.UNICODE)


def matches(terms, text):
    available = words(text)
    return all(any(t == w or (len(t) >= 5 and len(w) >= 5 and
                   SequenceMatcher(None, t, w).ratio() >= .86)
                   for w in available) for t in terms)


def interpret(query, soup, prefix):
    normalized = ' '.join(words(query))
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
    if terms and options:
        candidates = [o for o in options.find_all('option')
                      if o.get('value') not in ('', '0', None) and matches(terms, o.get_text())]
        if len(candidates) == 1:
            promoter = candidates[0]['value']
    # District-scoped searches inspect source pages for all remaining clues,
    # including addresses which are absent from the public search form.
    return {'district': district, 'promoter': promoter,
            'project_name': '' if district or promoter else (' '.join(terms) or normalized),
            'terms': [] if promoter else terms,
            'inspect_details': bool(district and terms and not promoter)}
