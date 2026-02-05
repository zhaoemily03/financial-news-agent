#!/usr/bin/env python3
"""
Cookie Refresh Script
Runs scrapers in "refresh only" mode to keep session cookies valid.
Designed to run via cron job before the main pipeline.

Usage:
    python refresh_cookies.py          # Refresh all enabled portals
    python refresh_cookies.py jefferies  # Refresh specific portal
"""

import sys
import time
from datetime import datetime
from cookie_manager import CookieManager
import config


def refresh_portal_cookies(portal_name: str, headless: bool = True) -> bool:
    """
    Refresh cookies for a single portal by authenticating and saving new cookies.

    Returns:
        True if refresh successful, False if re-authentication needed
    """
    print(f"\n{'='*50}")
    print(f"Refreshing cookies: {portal_name}")
    print(f"{'='*50}")

    portal_config = config.SOURCES.get(portal_name, {})
    if not portal_config.get('enabled'):
        print(f"  {portal_name}: disabled in config, skipping")
        return True

    scraper = None
    try:
        # Import and instantiate the scraper
        if portal_name == 'jefferies':
            from jefferies_scraper import JefferiesScraper
            scraper = JefferiesScraper(headless=headless)
        elif portal_name == 'morgan_stanley':
            from morgan_stanley_scraper import MorganStanleyScraper
            scraper = MorganStanleyScraper(headless=headless)
        else:
            print(f"  {portal_name}: no scraper implemented")
            return True

        # Initialize driver (loads cookies, navigates to portal, checks auth)
        if scraper._init_driver():
            print(f"  {portal_name}: session valid, cookies refreshed")
            scraper.close_driver()
            return True
        else:
            print(f"  {portal_name}: SESSION EXPIRED - manual re-auth required")
            if scraper:
                scraper.close_driver()
            return False

    except Exception as e:
        print(f"  {portal_name}: error - {e}")
        if scraper:
            try:
                scraper.close_driver()
            except:
                pass
        return False


def refresh_all_cookies(headless: bool = True) -> dict:
    """
    Refresh cookies for all enabled portals.

    Returns:
        Dict with 'success' (list) and 'failed' (list) portal names
    """
    print(f"\n{'='*60}")
    print(f"COOKIE REFRESH - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    success = []
    failed = []

    # Get enabled portals
    enabled_portals = []
    for name, cfg in config.SOURCES.items():
        if cfg.get('enabled') and cfg.get('login_required'):
            enabled_portals.append(name)

    print(f"Enabled portals requiring auth: {enabled_portals}")

    for portal_name in enabled_portals:
        if refresh_portal_cookies(portal_name, headless=headless):
            success.append(portal_name)
        else:
            failed.append(portal_name)

    # Summary
    print(f"\n{'='*60}")
    print("REFRESH SUMMARY")
    print(f"{'='*60}")
    print(f"  Refreshed: {success if success else 'none'}")
    print(f"  Failed:    {failed if failed else 'none'}")

    if failed:
        print(f"\n  WARNING: {len(failed)} portal(s) need manual re-authentication!")
        print(f"  Run: python refresh_cookies.py --interactive {' '.join(failed)}")

    return {'success': success, 'failed': failed}


def interactive_reauth(portal_name: str) -> bool:
    """
    Open browser in visible mode for manual re-authentication.
    """
    print(f"\nOpening {portal_name} for manual login...")
    print("Log in when the browser opens. Cookies will be saved automatically.")

    return refresh_portal_cookies(portal_name, headless=False)


if __name__ == "__main__":
    args = sys.argv[1:]

    # Check for interactive mode
    interactive = '--interactive' in args or '-i' in args
    if interactive:
        args = [a for a in args if a not in ('--interactive', '-i')]

    if args:
        # Refresh specific portals
        for portal in args:
            if interactive:
                interactive_reauth(portal.lower())
            else:
                refresh_portal_cookies(portal.lower())
    else:
        # Refresh all enabled portals
        result = refresh_all_cookies(headless=not interactive)

        # Exit with error code if any failed
        if result['failed']:
            sys.exit(1)
