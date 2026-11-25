"""Tests for the retry URL path in web/index.html.

This test file verifies the shared contract that the gRetry function
uses the correct /api/grill/sessions/{sid}/retry path.
"""
import sys
import unittest
from pathlib import Path

# Add server to path
sys.path.insert(0, "server")


class TestRetryURLPath(unittest.TestCase):
    """Test that the gRetry function uses the correct API path."""

    def _get_html_content(self):
        """Read web/index.html and return its content."""
        html_path = Path("web/index.html")
        return html_path.read_text()

    def _find_gr_retry_function(self, html_content):
        """Find the gRetry function in the HTML.
        
        Returns the function source code or None if not found.
        """
        # Look for "function gRetry" or "gRetry" in the HTML
        import re
        # Match the gRetry function definition
        pattern = r'async\s+function\s+gRetry\s*\([^)]*\)\s*\{[^}]*\}'
        match = re.search(pattern, html_content, re.DOTALL)
        if match:
            return match.group(0)
        
        # Fallback: look for gRetry and extract surrounding context
        if 'gRetry' in html_content:
            # Find the position of gRetry
            pos = html_content.find('gRetry')
            # Extract a reasonable chunk around it
            start = max(0, pos - 100)
            end = min(len(html_content), pos + 500)
            return html_content[start:end]
        
        return None

    def test_gRetry_does_not_use_the_unprefixed_path(self):
        """gRetry must use /api/grill/sessions/ not /grill/sessions/ (without /api/)."""
        html_content = self._get_html_content()
        gretry_function = self._find_gr_retry_function(html_content)
        
        # If we couldn't find the function, the test should fail
        self.assertIsNotNone(
            gretry_function,
            "Could not find gRetry function in web/index.html"
        )
        
        # Check that the gRetry function uses /api/grill/sessions/ (the correct path)
        self.assertIn(
            '/api/grill/sessions/',
            gretry_function,
            "gRetry should use /api/grill/sessions/ path"
        )

    def test_retry_url_contains_session_id_placeholder(self):
        """The retry URL must contain a session ID placeholder."""
        html_content = self._get_html_content()
        gretry_function = self._find_gr_retry_function(html_content)
        
        # If we couldn't find the function, the test should fail
        self.assertIsNotNone(
            gretry_function,
            "Could not find gRetry function in web/index.html"
        )
        
        # Check that the gRetry function contains a session ID placeholder
        # Common patterns: {sid}, ${sid}, {session_id}, etc.
        self.assertTrue(
            any(placeholder in gretry_function for placeholder in [
                '{sid}', '${sid}', '{session_id}', '${session_id}',
                '{sessionId}', '${sessionId}'
            ]),
            "gRetry URL should contain a session ID placeholder (e.g., {sid}, ${sid})"
        )


if __name__ == '__main__':
    unittest.main()
