"""
Base Podcast Handler for Podcast Ingestion

Abstract base class providing shared functionality for podcast
episode discovery and transcript extraction.

Subclasses must implement:
- discover_episodes() - Find recent episodes
- get_transcript() - Extract transcript text
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from podcast_tracker import PodcastTracker


class BasePodcast(ABC):
    """
    Abstract base class for podcast handlers.

    Provides common functionality:
    - Episode tracking (deduplication)
    - Date filtering
    - Standardized output format

    Subclasses must define:
    - PODCAST_NAME: str (e.g., "All-In Podcast")
    - PODCAST_URL: str (main podcast URL)
    - HOSTS: List[str] (host names)
    """

    # Subclasses MUST override these
    PODCAST_NAME: str = None
    PODCAST_URL: str = None
    HOSTS: List[str] = []

    def __init__(self):
        if self.PODCAST_NAME is None:
            raise NotImplementedError("Subclass must define PODCAST_NAME")

        self.tracker = PodcastTracker()

    # ------------------------------------------------------------------
    # Abstract Methods (podcast-specific, must override)
    # ------------------------------------------------------------------

    @abstractmethod
    def discover_episodes(self, days: int = 7) -> List[Dict]:
        """
        Find new episodes from the last N days.

        Returns:
            List of episode dicts with keys:
            - title: str
            - url: str (unique identifier)
            - published_date: str (YYYY-MM-DD)
            - duration_seconds: int (optional)
            - video_id: str (for YouTube, optional)
            - audio_url: str (for RSS, optional)
        """
        pass

    @abstractmethod
    def get_transcript(self, episode: Dict) -> Optional[str]:
        """
        Extract transcript text for an episode.

        Args:
            episode: Episode dict from discover_episodes()

        Returns:
            Full transcript text, or None if unavailable
        """
        pass

    # ------------------------------------------------------------------
    # Shared Methods
    # ------------------------------------------------------------------

    def filter_by_date(self, episodes: List[Dict], days: int = 7) -> List[Dict]:
        """Keep only episodes published within the last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        recent = []

        for episode in episodes:
            pub_date_str = episode.get('published_date')
            if not pub_date_str:
                recent.append(episode)  # Include if date unknown
                continue

            try:
                pub_date = datetime.strptime(pub_date_str, '%Y-%m-%d')
                if pub_date >= cutoff:
                    recent.append(episode)
            except ValueError:
                recent.append(episode)

        return recent

    def collect(self, days: int = 7, max_episodes: int = 5) -> List[Dict]:
        """
        Full pipeline: discover -> filter new -> get transcripts.

        Args:
            days: Only include episodes from last N days
            max_episodes: Maximum episodes to process

        Returns:
            List of episode dicts matching portal format:
            {title, url, analyst, source, source_type, date, content}
        """
        print(f"\n[{self.PODCAST_NAME}] Discovering episodes from last {days} days...")

        # Discover episodes
        try:
            episodes = self.discover_episodes(days=days)
        except Exception as e:
            print(f"  Failed to discover episodes: {e}")
            return []

        if not episodes:
            print(f"  No episodes found")
            return []

        print(f"  Found {len(episodes)} episode(s)")

        # Filter out already processed
        new_episodes = self.tracker.filter_unprocessed(episodes)
        skipped = len(episodes) - len(new_episodes)
        if skipped:
            print(f"  Skipped {skipped} previously processed episode(s)")

        if not new_episodes:
            print(f"  No new episodes to process")
            return []

        # Limit to max_episodes
        if len(new_episodes) > max_episodes:
            new_episodes = new_episodes[:max_episodes]
            print(f"  Limited to {max_episodes} episode(s)")

        # Extract transcripts
        results = []
        for i, episode in enumerate(new_episodes, 1):
            print(f"  [{i}/{len(new_episodes)}] {episode['title'][:50]}...")

            try:
                transcript = self.get_transcript(episode)
            except Exception as e:
                print(f"    Failed to get transcript: {e}")
                continue

            if not transcript:
                print(f"    No transcript available - skipping")
                continue

            # Format for pipeline (matches portal report structure)
            result = {
                'title': episode['title'],
                'url': episode['url'],
                'analyst': ', '.join(self.HOSTS),
                'source': self.PODCAST_NAME,
                'source_type': 'podcast',
                'date': episode.get('published_date', datetime.now().strftime('%Y-%m-%d')),
                'content': transcript,
            }
            results.append(result)

            # Mark as processed
            episode['podcast_name'] = self.PODCAST_NAME
            episode['hosts'] = self.HOSTS
            episode['content'] = transcript
            self.tracker.mark_as_processed(episode)

            print(f"    Extracted {len(transcript):,} chars of transcript")

        print(f"\n[{self.PODCAST_NAME}] Collected {len(results)} episode(s)")
        return results


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nBasePodcast - Abstract Base Class")
    print("=" * 50)
    print("This is an abstract class and cannot be instantiated directly.")
    print("Subclasses must implement:")
    print("  - PODCAST_NAME, PODCAST_URL, HOSTS")
    print("  - discover_episodes(days)")
    print("  - get_transcript(episode)")
    print("\nSee YouTubePodcast and RSSPodcast for concrete implementations.")
