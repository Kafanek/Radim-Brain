"""
Tests for Browser Agent (safety + fetcher + extractor + orchestrator).

Strategy:
    - Safety: pure unit tests, no network
    - Extractor: static HTML fixtures
    - Orchestrator: mock fetch, skip when feature disabled
    - Integration: one real hit to cs.wikipedia.org (skippable via env)
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Allow tests to import from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════
# SAFETY
# ═══════════════════════════════════════════════════════════════════

class TestBrowserSafety(unittest.TestCase):

    def setUp(self):
        from browser_agent_safety import validate_url, SafetyError, is_safe_url
        self.validate_url = validate_url
        self.SafetyError = SafetyError
        self.is_safe_url = is_safe_url

    def test_wikipedia_allowed(self):
        result = self.validate_url('https://cs.wikipedia.org/wiki/Praha')
        self.assertTrue(result['ok'])
        self.assertEqual(result['host'], 'cs.wikipedia.org')
        self.assertTrue(result['allowlisted'])

    def test_idnes_allowed(self):
        self.assertTrue(self.is_safe_url('https://www.idnes.cz/zpravy'))

    def test_subdomain_matches_allowlist(self):
        # pocasi.idnes.cz is in allowlist directly but also idnes.cz root
        result = self.validate_url('https://pocasi.idnes.cz/')
        self.assertTrue(result['ok'])

    def test_random_domain_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('https://evil.example.com/')
        self.assertEqual(ctx.exception.code, 'BLOCKED_DOMAIN')

    def test_ssrf_localhost_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('http://127.0.0.1:8080/admin')
        self.assertEqual(ctx.exception.code, 'BLOCKED_DOMAIN')

    def test_ssrf_private_range_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('http://192.168.1.1/')
        self.assertEqual(ctx.exception.code, 'BLOCKED_DOMAIN')

    def test_ssrf_metadata_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('http://metadata.google.internal/computeMetadata')
        self.assertEqual(ctx.exception.code, 'BLOCKED_DOMAIN')

    def test_ssrf_aws_metadata_ip_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('http://169.254.169.254/latest/meta-data/')
        self.assertEqual(ctx.exception.code, 'BLOCKED_DOMAIN')

    def test_file_scheme_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('file:///etc/passwd')
        self.assertEqual(ctx.exception.code, 'BLOCKED_SCHEME')

    def test_javascript_scheme_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('javascript:alert(1)')
        self.assertEqual(ctx.exception.code, 'BLOCKED_SCHEME')

    def test_invalid_port_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('http://cs.wikipedia.org:22/')
        self.assertEqual(ctx.exception.code, 'BLOCKED_PORT')

    def test_dangerous_extension_blocked(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('https://cs.wikipedia.org/malware.exe')
        self.assertEqual(ctx.exception.code, 'BLOCKED_CONTENT')

    def test_empty_url_rejected(self):
        with self.assertRaises(self.SafetyError):
            self.validate_url('')
        with self.assertRaises(self.SafetyError):
            self.validate_url(None)

    def test_control_chars_rejected(self):
        with self.assertRaises(self.SafetyError) as ctx:
            self.validate_url('https://cs.wikipedia.org/\r\nHost: evil.com')
        self.assertEqual(ctx.exception.code, 'INVALID_URL')

    def test_allow_external_bypass(self):
        """Admin flag allows external domains (used only for tests/debug)."""
        result = self.validate_url('https://example.com/', allow_external=True)
        self.assertTrue(result['ok'])
        self.assertFalse(result['allowlisted'])


# ═══════════════════════════════════════════════════════════════════
# EXTRACTOR
# ═══════════════════════════════════════════════════════════════════

SAMPLE_HTML = '''
<!DOCTYPE html>
<html lang="cs">
<head>
<title>Test Article — Praha</title>
<meta name="description" content="Testovací popis stránky">
<meta property="og:title" content="OG Title">
<meta property="og:site_name" content="Test Site">
</head>
<body>
<header>Header nav</header>
<nav><a href="/menu">Menu</a></nav>
<main>
  <article>
    <h1>Praha je hlavní město</h1>
    <p>Praha je hlavní a největší město České republiky.
       Leží v srdci Čech na řece Vltavě. Má přes 1,3 milionu obyvatel.</p>
    <p>Mezi významné památky patří Pražský hrad, Karlův most a Staroměstské náměstí.</p>
    <p>Historie města sahá až do 9. století.</p>
  </article>
</main>
<aside>Reklama</aside>
<footer>
  <a href="/kontakt">Kontakt</a>
  <a href="https://cs.wikipedia.org/wiki/Karel%C5%AFv_most">Karlův most</a>
  <a href="https://evil.example.com/">Externí</a>
</footer>
</body>
</html>
'''


class TestBrowserExtractor(unittest.TestCase):

    def setUp(self):
        from browser_agent_extractor import extract, find_in_content
        self.extract = extract
        self.find_in_content = find_in_content

    def test_extract_title(self):
        result = self.extract(SAMPLE_HTML, 'https://example.org/test')
        self.assertIn('Praha', result['title'])
        self.assertIn('Test', result['title'])

    def test_extract_meta_description(self):
        result = self.extract(SAMPLE_HTML, 'https://example.org/test')
        self.assertEqual(result['description'], 'Testovací popis stránky')

    def test_extract_language(self):
        result = self.extract(SAMPLE_HTML, 'https://example.org/test')
        self.assertEqual(result['language'], 'cs')

    def test_extract_main_content(self):
        result = self.extract(SAMPLE_HTML, 'https://example.org/test')
        self.assertIn('Praha', result['main_content'])
        self.assertIn('Vltavě', result['main_content'])
        # Nav/footer/aside should NOT appear in main_content
        self.assertNotIn('Reklama', result['main_content'])

    def test_extract_links_resolve_absolute(self):
        result = self.extract(SAMPLE_HTML, 'https://cs.wikipedia.org/wiki/Test')
        hrefs = [l['href'] for l in result['links']]
        # Relative link /kontakt should resolve against base
        self.assertTrue(any('cs.wikipedia.org/kontakt' in h for h in hrefs))
        # External link preserved as-is
        self.assertTrue(any('evil.example.com' in h for h in hrefs))

    def test_extract_links_safety_tagged(self):
        result = self.extract(SAMPLE_HTML, 'https://cs.wikipedia.org/wiki/Test')
        by_host = {l['href']: l for l in result['links']}
        evil = next((l for l in result['links'] if 'evil.example' in l['href']), None)
        safe = next((l for l in result['links'] if 'wikipedia' in l['href']), None)
        if evil:
            self.assertFalse(evil['is_safe'])
        if safe:
            self.assertTrue(safe['is_safe'])

    def test_find_in_content_finds_match(self):
        matches = self.find_in_content('Praha je hlavní město České republiky.', 'Praha')
        self.assertEqual(len(matches), 1)
        self.assertIn('Praha', matches[0]['snippet'])

    def test_find_in_content_case_insensitive(self):
        matches = self.find_in_content('Praha je město', 'praha')
        self.assertEqual(len(matches), 1)

    def test_find_in_content_multiple_matches(self):
        matches = self.find_in_content('Praha a Praha a Praha', 'Praha')
        self.assertEqual(len(matches), 3)

    def test_find_in_content_empty_query(self):
        matches = self.find_in_content('content', '')
        self.assertEqual(matches, [])


# ═══════════════════════════════════════════════════════════════════
# ORCHESTRATOR (with feature flag)
# ═══════════════════════════════════════════════════════════════════

class TestBrowserOrchestrator(unittest.TestCase):

    def setUp(self):
        # Import module fresh so we can toggle flag
        import browser_agent
        self.mod = browser_agent

    def test_disabled_by_default(self):
        original = self.mod.ENABLE_BROWSER_AGENT
        try:
            self.mod.ENABLE_BROWSER_AGENT = False
            result = self.mod.open_page('https://cs.wikipedia.org/wiki/Praha')
            self.assertFalse(result['success'])
            self.assertEqual(result['error_code'], 'DISABLED')
        finally:
            self.mod.ENABLE_BROWSER_AGENT = original

    def test_invalid_url_returns_error(self):
        original = self.mod.ENABLE_BROWSER_AGENT
        try:
            self.mod.ENABLE_BROWSER_AGENT = True
            result = self.mod.open_page('not-a-url')
            self.assertFalse(result['success'])
            self.assertIn(result['error_code'], ('INVALID_URL', 'BLOCKED_DOMAIN'))
        finally:
            self.mod.ENABLE_BROWSER_AGENT = original

    def test_blocked_domain_returns_error(self):
        original = self.mod.ENABLE_BROWSER_AGENT
        try:
            self.mod.ENABLE_BROWSER_AGENT = True
            result = self.mod.open_page('https://evil.example.com/')
            self.assertFalse(result['success'])
            self.assertEqual(result['error_code'], 'BLOCKED_DOMAIN')
        finally:
            self.mod.ENABLE_BROWSER_AGENT = original

    def test_session_not_found(self):
        original = self.mod.ENABLE_BROWSER_AGENT
        try:
            self.mod.ENABLE_BROWSER_AGENT = True
            result = self.mod.read_page('br_nonexistent')
            self.assertFalse(result['success'])
            self.assertEqual(result['error_code'], 'SESSION_NOT_FOUND')
        finally:
            self.mod.ENABLE_BROWSER_AGENT = original

    def test_close_nonexistent_session_ok(self):
        """Closing a session that doesn't exist should still succeed."""
        original = self.mod.ENABLE_BROWSER_AGENT
        try:
            self.mod.ENABLE_BROWSER_AGENT = True
            result = self.mod.close_session('br_nonexistent')
            self.assertTrue(result['success'])
            self.assertFalse(result['closed'])
        finally:
            self.mod.ENABLE_BROWSER_AGENT = original

    def test_stats_structure(self):
        s = self.mod.stats()
        self.assertTrue(s['success'])
        self.assertIn('enabled', s)
        self.assertIn('sessions_active', s)
        self.assertIn('session_ttl_sec', s)


# ═══════════════════════════════════════════════════════════════════
# ORCHESTRATOR WITH MOCKED FETCH (end-to-end, no network)
# ═══════════════════════════════════════════════════════════════════

class TestBrowserEndToEnd(unittest.TestCase):

    def test_open_page_with_mock_fetch(self):
        import browser_agent
        original = browser_agent.ENABLE_BROWSER_AGENT
        try:
            browser_agent.ENABLE_BROWSER_AGENT = True

            mock_fetch_result = {
                'url': 'https://cs.wikipedia.org/wiki/Praha',
                'final_url': 'https://cs.wikipedia.org/wiki/Praha',
                'status_code': 200,
                'content_type': 'text/html; charset=utf-8',
                'content': SAMPLE_HTML,
                'content_length': len(SAMPLE_HTML),
                'encoding': 'utf-8',
                'redirect_chain': ['https://cs.wikipedia.org/wiki/Praha'],
                'latency_ms': 123,
                'headers': {'content-type': 'text/html'},
            }

            with patch('browser_agent_fetcher.fetch', return_value=mock_fetch_result):
                result = browser_agent.open_page('https://cs.wikipedia.org/wiki/Praha')

            self.assertTrue(result['success'])
            self.assertTrue(result['session_id'].startswith('br_'))
            self.assertIn('Praha', result['title'])
            self.assertIn('Praha', result['main_content'])
            self.assertIsInstance(result['links'], list)
            self.assertEqual(result['reasoning']['load_state'], 'complete')

            # Read page from cache
            read_result = browser_agent.read_page(result['session_id'])
            self.assertTrue(read_result['success'])

            # Find query in cached content
            find_result = browser_agent.find_on_page(result['session_id'], 'Vltavě')
            self.assertTrue(find_result['success'])
            self.assertGreaterEqual(find_result['count'], 1)

            # Close session
            close_result = browser_agent.close_session(result['session_id'])
            self.assertTrue(close_result['closed'])

        finally:
            browser_agent.ENABLE_BROWSER_AGENT = original


# ═══════════════════════════════════════════════════════════════════
# ROUTES (HTTP layer)
# ═══════════════════════════════════════════════════════════════════

class TestBrowserRoutes(unittest.TestCase):

    def setUp(self):
        import app as app_module
        self.client = app_module.app.test_client()

    def test_stats_endpoint_accessible(self):
        resp = self.client.get('/api/browser/stats')
        # 200 when available, 503 otherwise — both acceptable
        self.assertIn(resp.status_code, (200, 503))
        data = resp.get_json()
        self.assertIn('enabled', data)

    def test_open_missing_url(self):
        import browser_agent
        original = browser_agent.ENABLE_BROWSER_AGENT
        try:
            browser_agent.ENABLE_BROWSER_AGENT = True
            resp = self.client.post('/api/browser/open', json={})
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertEqual(data['error_code'], 'INVALID_URL')
        finally:
            browser_agent.ENABLE_BROWSER_AGENT = original

    def test_open_blocked_domain(self):
        import browser_agent
        original = browser_agent.ENABLE_BROWSER_AGENT
        try:
            browser_agent.ENABLE_BROWSER_AGENT = True
            resp = self.client.post('/api/browser/open',
                                    json={'url': 'https://evil.example.com/'})
            self.assertEqual(resp.status_code, 403)
            data = resp.get_json()
            self.assertEqual(data['error_code'], 'BLOCKED_DOMAIN')
        finally:
            browser_agent.ENABLE_BROWSER_AGENT = original

    def test_disabled_flag_returns_503(self):
        import browser_agent
        original = browser_agent.ENABLE_BROWSER_AGENT
        try:
            browser_agent.ENABLE_BROWSER_AGENT = False
            resp = self.client.post('/api/browser/open',
                                    json={'url': 'https://cs.wikipedia.org/wiki/Praha'})
            self.assertEqual(resp.status_code, 503)
        finally:
            browser_agent.ENABLE_BROWSER_AGENT = original


if __name__ == '__main__':
    unittest.main()
