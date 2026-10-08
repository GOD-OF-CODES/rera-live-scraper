"""Server-rendered detail extraction for hosts without Chromium."""
from types import SimpleNamespace
from bs4 import BeautifulSoup
from src.scraper.project_details_extractor import ProjectDetailsExtractor


def extract_html(html, url, registration_number):
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(['script', 'style']):
        element.decompose()
    def text(element):
        return element.get_text(' ', strip=True).replace('\xa0', ' ')
    fields = []
    for element in soup.select('input, textarea, select, span[id], label[id]'):
        if element.get('type') == 'hidden':
            continue
        if element.name == 'select':
            option = element.find('option', selected=True) or element.find('option')
            value = text(option) if option else ''
        else:
            value = element.get('value', text(element))
        fields.append({'id': element.get('id', ''), 'name': element.get('name', ''),
                       'type': element.get('type', element.name), 'value': value})
    tables = []
    for table in soup.find_all('table'):
        if table.find('table'):
            continue
        tables.append([[text(cell) for cell in row.find_all(['td', 'th'], recursive=False)]
                       for row in table.find_all('tr') if row.find_parent('table') is table])
    links = [{'text': text(a), 'href': a.get('href', '')} for a in soup.find_all('a')
             if any(parent.get('id', '').startswith('ctl00_ContentPlaceHolder1_')
                    for parent in [a, *a.parents] if getattr(parent, 'attrs', None))]
    page = SimpleNamespace(url=url, title=lambda: text(soup.title) if soup.title else '')
    extractor = ProjectDetailsExtractor(page)
    extractor._snapshot = {'body_text': text(soup.body or soup), 'fields': fields,
                           'tables': tables, 'links': links}
    return extractor.extract_structured(registration_number)
