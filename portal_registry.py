"""
Portal Registry - Multi-Portal Scraper Orchestration

Manages multiple sell-side research portal scrapers and provides
a unified interface for collecting reports from all sources.

Usage:
    from portal_registry import registry

    # Collect from all enabled portals
    result = registry.collect_all(days=5)
    reports = result['reports']
    failures = result['failures']

    # Or collect from specific portals
    result = registry.collect_from(['jefferies', 'jpmorgan'], days=7)
"""

import threading
from typing import Dict, List, Type, Optional
import config

# Per-portal timeout (seconds). If a scraper takes longer, it's killed.
PORTAL_TIMEOUT = 300  # 5 minutes default


class PortalRegistry:
    """
    Registry for sell-side research portal scrapers.

    Manages scraper classes and orchestrates collection from
    multiple portals with fail-safe aggregation.
    """

    def __init__(self):
        self._scrapers: Dict[str, Type] = {}  # BaseScraper or API-based scrapers

    def register(self, portal_name: str, scraper_class: Type):
        """
        Register a scraper class for a portal.

        Args:
            portal_name: Lowercase portal identifier (e.g., 'jefferies')
            scraper_class: Class that extends BaseScraper
        """
        self._scrapers[portal_name.lower()] = scraper_class
        print(f"[Registry] Registered scraper for '{portal_name}'")

    def get_scraper(self, portal_name: str, headless: bool = True) -> Optional[BaseScraper]:
        """
        Get an instance of the scraper for a portal.

        Args:
            portal_name: Portal identifier
            headless: Whether to run browser headless

        Returns:
            Scraper instance, or None if not registered
        """
        scraper_class = self._scrapers.get(portal_name.lower())
        if scraper_class:
            return scraper_class(headless=headless)
        return None

    def list_registered(self) -> List[str]:
        """List all registered portal names."""
        return list(self._scrapers.keys())

    def list_enabled(self) -> List[str]:
        """List portals that are both registered and enabled in config."""
        enabled = []
        for portal_name in self._scrapers.keys():
            portal_config = config.SOURCES.get(portal_name, {})
            if portal_config.get('enabled', False):
                enabled.append(portal_name)
        return enabled

    def _collect_single_portal(
        self,
        portal_name: str,
        days: int,
        max_reports: int,
        headless: bool,
        result_out: Dict,
    ):
        """Collect from a single portal. Live-writes to result_out['reports'] as reports arrive."""
        try:
            scraper = self.get_scraper(portal_name, headless=headless)
            if not scraper:
                result_out['failures'].append(f"{portal_name} (scraper not found)")
                return

            # Pass result_out so reports are live-written — partial results survive a timeout
            result = scraper.get_followed_reports(
                max_reports=max_reports,
                days=days,
                result_out=result_out,
            )

            if result.get('auth_required'):
                print(f"[Registry] {portal_name}: Authentication required - skipping")
                result_out['failures'].append(f"{portal_name} (auth required)")
                return

            # Reports are already in result_out['reports'] via live-writes.
            # Just add any failures from the return value.
            failures = result.get('failures', [])
            result_out['failures'].extend([f"{portal_name}: {f}" for f in failures])
            print(f"[Registry] {portal_name}: Collected {len(result_out['reports'])} reports")

        except Exception as e:
            result_out['failures'].append(f"{portal_name} (error: {str(e)[:80]})")
            print(f"[Registry] {portal_name}: Error - {e}")

    def collect_from(
        self,
        portal_names: List[str],
        days: int = 7,
        max_per_portal: int = 20,
        headless: bool = True,
        timeout: int = PORTAL_TIMEOUT,
    ) -> Dict:
        """
        Collect reports from specific portals.

        Each portal runs with a timeout — if it hangs, the pipeline
        moves on and records the failure instead of crashing.

        Args:
            portal_names: List of portal identifiers
            days: Only include reports from last N days
            max_per_portal: Max reports per portal
            headless: Whether to run browsers headless
            timeout: Per-portal timeout in seconds

        Returns:
            Dict with 'reports' (aggregated list), 'failures' (per-source)
        """
        all_reports = []
        all_failures = []

        for portal_name in portal_names:
            portal_name = portal_name.lower()

            if portal_name not in self._scrapers:
                all_failures.append(f"{portal_name} (not registered)")
                print(f"[Registry] {portal_name}: Not registered - skipping")
                continue

            portal_config = config.SOURCES.get(portal_name, {})
            max_reports = portal_config.get('max_reports', max_per_portal)
            portal_timeout = portal_config.get('timeout', timeout)  # Per-portal override

            # Run scraper in a thread with timeout
            result_out = {'reports': [], 'failures': []}
            thread = threading.Thread(
                target=self._collect_single_portal,
                args=(portal_name, days, max_reports, headless, result_out),
                daemon=True,
            )
            thread.start()
            thread.join(timeout=portal_timeout)

            if thread.is_alive():
                # Timed out — but live-writes may have already accumulated partial results
                partial = result_out['reports']
                if partial:
                    print(f"[Registry] {portal_name}: TIMEOUT after {portal_timeout}s — salvaging {len(partial)} partial reports")
                    all_reports.extend(partial)
                    all_failures.append(f"{portal_name} (timeout — {len(partial)} partial reports included)")
                else:
                    print(f"[Registry] {portal_name}: TIMEOUT after {portal_timeout}s — no reports collected")
                    all_failures.append(f"{portal_name} (timeout — 0 reports)")
                # Daemon thread continues in background; results already captured above
            else:
                all_reports.extend(result_out['reports'])
                all_failures.extend(result_out['failures'])

        return {
            'reports': all_reports,
            'failures': all_failures
        }

    def collect_all(
        self,
        days: int = 7,
        max_per_portal: int = 20,
        headless: bool = True
    ) -> Dict:
        """
        Collect reports from all enabled portals.

        Args:
            days: Only include reports from last N days
            max_per_portal: Max reports per portal
            headless: Whether to run browsers headless

        Returns:
            Dict with 'reports' (aggregated list), 'failures' (per-source)
        """
        enabled = self.list_enabled()

        if not enabled:
            print("[Registry] No enabled portals found")
            return {'reports': [], 'failures': ['No enabled portals']}

        print(f"[Registry] Collecting from {len(enabled)} enabled portal(s): {enabled}")
        return self.collect_from(
            portal_names=enabled,
            days=days,
            max_per_portal=max_per_portal,
            headless=headless
        )


# ------------------------------------------------------------------
# Global Registry Instance
# ------------------------------------------------------------------

registry = PortalRegistry()


# ------------------------------------------------------------------
# Auto-register available scrapers
# ------------------------------------------------------------------

def _auto_register():
    """Auto-register scrapers that are available."""
    try:
        from jefferies_scraper import JefferiesScraper
        registry.register('jefferies', JefferiesScraper)
    except ImportError:
        pass

    try:
        from morgan_stanley_scraper import MorganStanleyScraper
        registry.register('morgan_stanley', MorganStanleyScraper)
    except ImportError:
        pass

    try:
        from goldman_scraper import GoldmanScraper
        registry.register('goldman', GoldmanScraper)
    except ImportError:
        pass

    try:
        from bernstein_scraper import BernsteinScraper
        registry.register('bernstein', BernsteinScraper)
    except ImportError:
        pass

    try:
        from arete_scraper import AreteScraper
        registry.register('arete', AreteScraper)
    except ImportError:
        pass

    try:
        from ubs_scraper import UBSScraper
        registry.register('ubs', UBSScraper)
    except ImportError:
        pass

    try:
        from macquarie_scraper import MacquarieScraper
        registry.register('macquarie', MacquarieScraper)
    except ImportError:
        pass


# Run auto-registration on module import
_auto_register()


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nPortal Registry Test")
    print("=" * 50)

    # Test 1: List registered scrapers
    print("\n[1/3] Registered scrapers:")
    registered = registry.list_registered()
    for name in registered:
        print(f"  - {name}")
    assert 'jefferies' in registered, "Jefferies should be registered"
    print(" Scrapers registered correctly")

    # Test 2: List enabled portals
    print("\n[2/3] Enabled portals (from config):")
    enabled = registry.list_enabled()
    for name in enabled:
        print(f"  - {name}")
    print(f" {len(enabled)} portal(s) enabled")

    # Test 3: Collect from enabled portals
    print("\n[3/3] Collecting from enabled portals...")
    result = registry.collect_all(days=7, max_per_portal=5, headless=False)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports collected: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, report in enumerate(reports[:3], 1):
        print(f"\n  Report {i}:")
        print(f"    Title: {report.get('title', 'unknown')[:60]}")
        print(f"    Source: {report.get('source', 'unknown')}")
        print(f"    Date: {report.get('date', 'unknown')}")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n All registry tests passed")
