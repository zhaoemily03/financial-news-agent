"""
Cookie Management System
Handles loading, saving, and updating cookies for authenticated portals
"""

import json
import os
from typing import Dict, Optional
from datetime import datetime


class CookieManager:
    """Manages cookies for authenticated web portals"""

    def __init__(self, cookie_file='data/cookies.json'):
        self.cookie_file = cookie_file
        self.cookies = self._load_cookies()

    def _load_cookies(self) -> Dict:
        """Load cookies from JSON file"""
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse {self.cookie_file}, starting fresh")
                return {}
        return {}

    def save_cookies(self, portal_name: str, cookies: Dict):
        """
        Save cookies for a specific portal

        Args:
            portal_name: Name of the portal (e.g., 'jefferies', 'jpmorgan')
            cookies: Dictionary of cookie name-value pairs
        """
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)

        # Update cookies for this portal
        self.cookies[portal_name] = {
            'cookies': cookies,
            'updated_at': datetime.now().isoformat()
        }

        # Save to file
        with open(self.cookie_file, 'w') as f:
            json.dump(self.cookies, f, indent=2)

        print(f"✓ Saved cookies for {portal_name}")

    def get_cookies(self, portal_name: str) -> Optional[Dict]:
        """
        Get cookies for a specific portal

        Args:
            portal_name: Name of the portal

        Returns:
            Dictionary of cookies, or None if not found
        """
        portal_data = self.cookies.get(portal_name)
        if portal_data:
            return portal_data.get('cookies')
        return None

    def update_cookies_from_response(self, portal_name: str, response):
        """
        Update cookies from a requests.Response object

        Args:
            portal_name: Name of the portal
            response: requests.Response object
        """
        if response.cookies:
            # Properly iterate through cookies (handles duplicates)
            new_cookies = {}
            for cookie in response.cookies:
                # Use the cookie name and value, ignoring domain/path for simple storage
                new_cookies[cookie.name] = cookie.value

            # Merge with existing cookies
            existing = self.get_cookies(portal_name) or {}
            existing.update(new_cookies)

            # Save updated cookies
            self.save_cookies(portal_name, existing)

    def get_cookies_as_dict(self, portal_name: str) -> Dict:
        """
        Get cookies as a simple dict for requests library

        Args:
            portal_name: Name of the portal

        Returns:
            Dictionary of cookie name-value pairs
        """
        return self.get_cookies(portal_name) or {}

    def has_cookies(self, portal_name: str) -> bool:
        """Check if cookies exist for a portal"""
        return portal_name in self.cookies

    def delete_cookies(self, portal_name: str):
        """Delete cookies for a specific portal"""
        if portal_name in self.cookies:
            del self.cookies[portal_name]
            with open(self.cookie_file, 'w') as f:
                json.dump(self.cookies, f, indent=2)
            print(f"✓ Deleted cookies for {portal_name}")

    def list_portals(self):
        """List all portals with stored cookies"""
        return list(self.cookies.keys())

    def update_cookies_from_driver(self, portal_name: str, driver_cookies: list):
        """
        Update cookies from Selenium WebDriver cookies list.

        Args:
            portal_name: Name of the portal
            driver_cookies: List of cookie dicts from driver.get_cookies()
        """
        if not driver_cookies:
            return

        # Extract name-value pairs from driver cookies
        new_cookies = {}
        for cookie in driver_cookies:
            name = cookie.get('name')
            value = cookie.get('value')
            if name and value:
                new_cookies[name] = value

        # Merge with existing cookies
        existing = self.get_cookies(portal_name) or {}
        existing.update(new_cookies)

        # Save updated cookies
        self.save_cookies(portal_name, existing)


def import_cookies_from_browser(portal_name: str, cookie_dict: Dict):
    """
    Helper function to import cookies from browser

    Args:
        portal_name: Name of the portal (e.g., 'jefferies')
        cookie_dict: Dictionary of cookies from browser

    Example:
        cookies = {
            '.ASPXAUTH': 'ABC123...',
            'SessionId': 'XYZ789...',
            # ... other cookies
        }
        import_cookies_from_browser('jefferies', cookies)
    """
    manager = CookieManager()
    manager.save_cookies(portal_name, cookie_dict)
    print(f"✓ Imported cookies for {portal_name}")
    print(f"  Cookies will be automatically updated on each request")
    print(f"  Valid for 365 days from browser authentication")
