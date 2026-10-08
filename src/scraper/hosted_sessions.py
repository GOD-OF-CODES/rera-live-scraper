"""Authenticated encrypted continuation state; no hosted database required.

Each request restores a fresh scraper from a client-carried token. The client
cannot modify source URLs, source cookies or candidates. Tokens expire after
10 minutes of inactivity. They are never stored in localStorage or logs.
"""
import json
import time
import zlib

from cryptography.fernet import Fernet, InvalidToken
from src.scraper.live import LiveScraper, LiveScrapeError, SearchSession, fetch_project_http


class HostedSessions:
    def __init__(self, key, factory=None):
        self.cipher = Fernet(key)
        self.factory = factory or (lambda: LiveScraper(fetcher=fetch_project_http, clock=time.time))

    def execute(self, method, *args, session_state=None):
        live = self.factory()
        try:
            if method != 'start':
                try:
                    if not session_state or len(session_state) > 2_000_000:
                        raise ValueError('Missing state')
                    packed = self.cipher.decrypt(session_state.encode(), ttl=600)
                    decoder = zlib.decompressobj()
                    raw = decoder.decompress(packed, 8_000_000)
                    if not decoder.eof or decoder.unconsumed_tail:
                        raise ValueError('Oversized state')
                    saved = json.loads(raw)
                    token = args[0]
                    if saved['token'] != token:
                        raise ValueError('Wrong session')
                except (InvalidToken, ValueError, KeyError, TypeError, zlib.error) as exc:
                    raise LiveScrapeError('This search expired or is invalid. Start a new search.',
                                          'session_expired', 410) from exc
                state = SearchSession(saved['query'], live.session_factory(), live.clock()+live.ttl)
                state.http.cookies.update(saved['cookies'])
                for name in ('fields', 'rows', 'intent', 'candidates', 'scan_offset', 'scan_attempts'):
                    setattr(state, name, saved[name])
                state.scan_failures = set(saved['scan_failures'])
                live.sessions[token] = state
            result = getattr(live, method)(*args)
            token = result.get('session_id') if isinstance(result, dict) else None
            if token and token in live.sessions:
                state = live.sessions[token]
                saved = {name: getattr(state, name) for name in (
                    'query', 'fields', 'rows', 'intent', 'candidates', 'scan_offset', 'scan_attempts')}
                saved.update(token=token, cookies=state.http.cookies.get_dict(),
                             scan_failures=list(state.scan_failures))
                packed = zlib.compress(json.dumps(saved, separators=(',', ':')).encode())
                sealed = self.cipher.encrypt(packed).decode()
                if len(sealed) > 2_000_000:
                    raise LiveScrapeError('The source returned too many candidates. Narrow your search.', 'search_too_large', 422)
                result['session_state'] = sealed
            return result
        finally:
            live.close()
