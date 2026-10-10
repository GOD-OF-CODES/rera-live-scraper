"""Collect the public all-UP directory after a user enters RERA's CAPTCHA."""
import argparse
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from src.scraper.district_dataset import save_summary_rows
from src.scraper.live import SEARCH_URL, PREFIX, form_values, search_rows, LiveScraper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/results/all_up')
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        response = session.get(SEARCH_URL, timeout=60)
        LiveScraper._check_response(response)
        soup = BeautifulSoup(response.text, 'html.parser')
        image = soup.select_one('img[src*="CaptchaImage"]')
        if not image:
            raise SystemExit('RERA did not supply its CAPTCHA; retry later.')
        image_url = urljoin(SEARCH_URL, image['src'])
        if not image_url.startswith('https://up-rera.in/'):
            raise SystemExit('Unexpected CAPTCHA source; directory not changed.')
        response = session.get(image_url, timeout=30)
        LiveScraper._check_response(response)
        captcha_path = directory / '_captcha.png'
        captcha_path.write_bytes(response.content)
        print(f'Open the CAPTCHA image: {captcha_path.resolve()}')
        captcha = input('Enter its characters: ').strip()
        fields = form_values(soup)
        fields.update({'__EVENTTARGET': '', '__EVENTARGUMENT': '',
                       PREFIX + 'txt_regid1': '', PREFIX + 'txtProject1': '',
                       PREFIX + 'DdlprojectDistrict': '0', PREFIX + 'ddl_prm': '0',
                       PREFIX + 'txtcap': captcha, PREFIX + 'btnSearch': 'Search'})
        response = session.post(SEARCH_URL, data=fields, timeout=180)
        LiveScraper._check_response(response)
        rows = search_rows(response.text, '')
        # The current directory returns the complete grid. Fail explicitly if
        # the source introduces pagination instead of publishing a partial list.
        if 'Page$' in response.text:
            raise SystemExit('RERA now paginates this directory. Update collection before replacing the index.')
        if not rows:
            raise SystemExit('No directory returned. Check the CAPTCHA and retry; previous directory preserved.')
        path = save_summary_rows(directory, 'All Uttar Pradesh', rows)
        captcha_path.unlink(missing_ok=True)
        print(f'Saved {len(rows)} official project links to {path}')


if __name__ == '__main__':
    main()
