"""
Podcast Registry - Multi-Podcast Orchestration

Manages multiple podcast sources and provides a unified interface
for collecting episodes from all sources.

Usage:
    from podcast_registry import podcast_registry

    # Collect from all enabled podcasts
    result = podcast_registry.collect_all(days=7)
    episodes = result['episodes']
    failures = result['failures']

    # Or collect from specific podcasts
    result = podcast_registry.collect_from(['all-in', 'bg2'], days=7)
"""

from typing import Dict, List, Type, Optional
from base_podcast import BasePodcast
import config


class PodcastRegistry:
    """
    Registry for podcast sources.

    Manages podcast classes and orchestrates collection from
    multiple podcasts with fail-safe aggregation.
    """

    def __init__(self):
        self._podcasts: Dict[str, Type[BasePodcast]] = {}

    def register(self, podcast_name: str, podcast_class: Type[BasePodcast]):
        """
        Register a podcast class.

        Args:
            podcast_name: Lowercase identifier (e.g., 'all-in', 'bg2')
            podcast_class: Class that extends BasePodcast
        """
        self._podcasts[podcast_name.lower()] = podcast_class
        print(f"[PodcastRegistry] Registered '{podcast_name}'")

    def get_podcast(self, podcast_name: str) -> Optional[BasePodcast]:
        """
        Get an instance of a podcast handler.

        Args:
            podcast_name: Podcast identifier

        Returns:
            Podcast handler instance, or None if not registered
        """
        podcast_class = self._podcasts.get(podcast_name.lower())
        if podcast_class:
            return podcast_class()
        return None

    def list_registered(self) -> List[str]:
        """List all registered podcast names."""
        return list(self._podcasts.keys())

    def list_enabled(self) -> List[str]:
        """List podcasts that are both registered and enabled in config."""
        enabled = []

        # Check if podcasts are globally enabled
        podcast_config = config.SOURCES.get('podcasts', {})
        if not podcast_config.get('enabled', False):
            return []

        sources = podcast_config.get('sources', {})

        for podcast_name in self._podcasts.keys():
            source_config = sources.get(podcast_name, {})
            # Default to enabled if registered and no explicit config
            if source_config.get('enabled', True):
                enabled.append(podcast_name)

        return enabled

    def collect_from(
        self,
        podcast_names: List[str],
        days: int = 7,
        max_per_podcast: int = 3
    ) -> Dict:
        """
        Collect episodes from specific podcasts.

        Args:
            podcast_names: List of podcast identifiers
            days: Only include episodes from last N days
            max_per_podcast: Max episodes per podcast

        Returns:
            Dict with 'episodes' (aggregated list), 'failures' (per-source)
        """
        all_episodes = []
        all_failures = []

        for podcast_name in podcast_names:
            podcast_name = podcast_name.lower()

            # Check if podcast is registered
            if podcast_name not in self._podcasts:
                all_failures.append(f"{podcast_name} (not registered)")
                print(f"[PodcastRegistry] {podcast_name}: Not registered - skipping")
                continue

            # Get podcast config
            podcast_config = config.SOURCES.get('podcasts', {})
            source_config = podcast_config.get('sources', {}).get(podcast_name, {})
            max_episodes = source_config.get('max_episodes', max_per_podcast)

            # Create podcast instance and collect
            try:
                podcast = self.get_podcast(podcast_name)
                if not podcast:
                    all_failures.append(f"{podcast_name} (handler not found)")
                    continue

                episodes = podcast.collect(days=days, max_episodes=max_episodes)
                all_episodes.extend(episodes)

                print(f"[PodcastRegistry] {podcast_name}: Collected {len(episodes)} episode(s)")

            except Exception as e:
                all_failures.append(f"{podcast_name} (error: {str(e)[:50]})")
                print(f"[PodcastRegistry] {podcast_name}: Error - {e}")
                continue

        return {
            'episodes': all_episodes,
            'failures': all_failures
        }

    def collect_all(
        self,
        days: int = 7,
        max_per_podcast: int = 3
    ) -> Dict:
        """
        Collect episodes from all enabled podcasts.

        Args:
            days: Only include episodes from last N days
            max_per_podcast: Max episodes per podcast

        Returns:
            Dict with 'episodes' (aggregated list), 'failures' (per-source)
        """
        enabled = self.list_enabled()

        if not enabled:
            print("[PodcastRegistry] No enabled podcasts found")
            return {'episodes': [], 'failures': ['No enabled podcasts']}

        print(f"[PodcastRegistry] Collecting from {len(enabled)} enabled podcast(s): {enabled}")
        return self.collect_from(
            podcast_names=enabled,
            days=days,
            max_per_podcast=max_per_podcast
        )


# ------------------------------------------------------------------
# Global Registry Instance
# ------------------------------------------------------------------

podcast_registry = PodcastRegistry()


# ------------------------------------------------------------------
# Auto-register available podcasts
# ------------------------------------------------------------------

def _auto_register():
    """Auto-register podcasts that are available."""
    try:
        from youtube_podcast import AllInPodcast
        podcast_registry.register('all-in', AllInPodcast)
    except ImportError:
        pass

    try:
        from rss_podcast import BG2Pod, AcquiredPodcast
        podcast_registry.register('bg2', BG2Pod)
        podcast_registry.register('acquired', AcquiredPodcast)
    except ImportError:
        pass


# Run auto-registration on module import
_auto_register()


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nPodcast Registry Tests")
    print("=" * 50)

    # Test 1: List registered podcasts
    print("\n[1/3] Registered podcasts:")
    registered = podcast_registry.list_registered()
    for name in registered:
        print(f"  - {name}")
    print(f" {len(registered)} podcast(s) registered")

    # Test 2: List enabled podcasts
    print("\n[2/3] Enabled podcasts (from config):")
    enabled = podcast_registry.list_enabled()
    for name in enabled:
        print(f"  - {name}")
    print(f" {len(enabled)} podcast(s) enabled")

    # Test 3: Collect from enabled podcasts
    print("\n[3/3] Collecting from enabled podcasts...")

    if not enabled:
        print("  No podcasts enabled in config")
        print("  To enable, set SOURCES['podcasts']['enabled'] = True in config.py")
    else:
        result = podcast_registry.collect_all(days=14, max_per_podcast=1)

        episodes = result.get('episodes', [])
        failures = result.get('failures', [])

        print(f"\n--- Results ---")
        print(f"Episodes collected: {len(episodes)}")
        print(f"Failures: {len(failures)}")

        for i, episode in enumerate(episodes[:3], 1):
            print(f"\n  Episode {i}:")
            print(f"    Title: {episode.get('title', 'unknown')[:50]}...")
            print(f"    Source: {episode.get('source', 'unknown')}")
            print(f"    Date: {episode.get('date', 'unknown')}")

        if failures:
            print(f"\n--- Failures ---")
            for f in failures[:5]:
                print(f"  - {f}")

    print("\n All podcast registry tests complete")
