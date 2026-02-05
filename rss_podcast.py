"""
RSS Podcast Handler

Handles audio-first podcasts discovered via RSS feeds.
For transcripts, options include:
1. Check if show publishes transcripts (website scraping)
2. Use external transcription API (Deepgram, Whisper)
3. Fall back to episode descriptions

Supports: BG2 Pod, Acquired, and other RSS-based shows
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from base_podcast import BasePodcast

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("Warning: feedparser not installed. Run: pip install feedparser")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class RSSPodcast(BasePodcast):
    """
    Handler for audio-first podcasts discovered via RSS.

    Audio-first podcasts require external transcription.
    This base class provides episode discovery; transcript
    extraction can be customized per-podcast.

    Subclasses must define RSS_URL.
    """

    # Subclass must define
    RSS_URL: str = None

    def __init__(self):
        if self.RSS_URL is None:
            raise NotImplementedError("Subclass must define RSS_URL")
        super().__init__()

    def discover_episodes(self, days: int = 7) -> List[Dict]:
        """Parse RSS feed for recent episodes."""
        if not HAS_FEEDPARSER:
            print("  feedparser not available - cannot discover episodes")
            return []

        try:
            feed = feedparser.parse(self.RSS_URL)
        except Exception as e:
            print(f"  Failed to parse RSS feed: {e}")
            return []

        if not feed.entries:
            print(f"  No entries in RSS feed")
            return []

        episodes = []
        cutoff = datetime.now() - timedelta(days=days)

        for entry in feed.entries:
            # Parse published date
            try:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                else:
                    continue
            except Exception:
                continue

            # Filter by date
            if pub_date < cutoff:
                continue

            # Get audio URL from enclosure
            audio_url = None
            if hasattr(entry, 'enclosures') and entry.enclosures:
                for enclosure in entry.enclosures:
                    if enclosure.get('type', '').startswith('audio/'):
                        audio_url = enclosure.get('href')
                        break
                if not audio_url:
                    audio_url = entry.enclosures[0].get('href')

            # Get duration if available
            duration = None
            if hasattr(entry, 'itunes_duration'):
                duration = self._parse_duration(entry.itunes_duration)

            episodes.append({
                'title': entry.title,
                'url': entry.link,
                'audio_url': audio_url,
                'published_date': pub_date.strftime('%Y-%m-%d'),
                'description': self._clean_html(getattr(entry, 'summary', '')),
                'duration_seconds': duration,
            })

        return episodes

    def get_transcript(self, episode: Dict) -> Optional[str]:
        """
        Get transcript for an audio episode.

        Override this method in subclasses for podcast-specific
        transcript sources (e.g., website scraping).

        Default behavior: Return episode description as fallback.
        """
        # Try podcast-specific transcript source first
        transcript = self._fetch_published_transcript(episode)
        if transcript and len(transcript) > 500:
            return transcript

        # Fallback to description (show notes)
        description = episode.get('description', '')
        if description and len(description) > 200:
            return f"[Episode notes] {description}"

        return None

    def _fetch_published_transcript(self, episode: Dict) -> Optional[str]:
        """
        Override in subclass if podcast publishes transcripts.

        Some podcasts publish transcripts on their website or
        include them in show notes.
        """
        return None

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Parse iTunes duration string to seconds."""
        if not duration_str:
            return None

        try:
            # Handle HH:MM:SS or MM:SS format
            parts = str(duration_str).split(':')
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return int(duration_str)
        except (ValueError, TypeError):
            return None

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ''
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text


# ------------------------------------------------------------------
# Concrete Podcast Implementations
# ------------------------------------------------------------------

class BG2Pod(RSSPodcast):
    """
    BG2 Pod - Bi-weekly tech and investing podcast

    Hosts: Brad Gerstner (Altimeter), Bill Gurley (Benchmark)
    Topics: Tech, markets, investing, capitalism
    """
    PODCAST_NAME = "BG2 Pod"
    PODCAST_URL = "https://bg2pod.com"
    RSS_URL = "https://anchor.fm/s/f06c2370/podcast/rss"
    HOSTS = ["Brad Gerstner", "Bill Gurley"]

    def _fetch_published_transcript(self, episode: Dict) -> Optional[str]:
        """
        BG2 Pod may publish transcripts on their website.
        Check the episode page for transcript content.
        """
        if not HAS_REQUESTS:
            return None

        episode_url = episode.get('url')
        if not episode_url or 'bg2pod.com' not in episode_url:
            return None

        try:
            response = requests.get(episode_url, timeout=15)
            if response.status_code != 200:
                return None

            # Look for transcript section in page
            # This is a placeholder - actual implementation depends on site structure
            html = response.text

            # Check for common transcript markers
            if 'transcript' in html.lower():
                # Extract transcript section (site-specific logic needed)
                pass

            return None

        except Exception:
            return None


class AcquiredPodcast(RSSPodcast):
    """
    Acquired - Long-form business history podcast

    Hosts: Ben Gilbert, David Rosenthal
    Topics: Business history, company deep-dives, tech companies

    Note: Episodes are typically 3-4 hours long.
    """
    PODCAST_NAME = "Acquired"
    PODCAST_URL = "https://acquired.fm"
    RSS_URL = "https://feeds.transistor.fm/acquired"
    HOSTS = ["Ben Gilbert", "David Rosenthal"]

    def _fetch_published_transcript(self, episode: Dict) -> Optional[str]:
        """
        Acquired publishes detailed show notes but may not have full transcripts.
        Check acquired.fm for episode content.
        """
        if not HAS_REQUESTS:
            return None

        episode_url = episode.get('url')
        if not episode_url:
            return None

        try:
            response = requests.get(episode_url, timeout=15)
            if response.status_code != 200:
                return None

            # Look for show notes or transcript
            html = response.text

            # Acquired.fm structure - extract show notes
            # This is placeholder logic
            if 'show-notes' in html.lower() or 'transcript' in html.lower():
                pass

            return None

        except Exception:
            return None


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nRSS Podcast Handler Tests")
    print("=" * 50)

    # Check dependencies
    print("\n[1/5] Checking dependencies...")
    if not HAS_FEEDPARSER:
        print("  feedparser: NOT INSTALLED")
        print("  Run: pip install feedparser")
    else:
        print("  feedparser: OK")

    if not HAS_FEEDPARSER:
        print("\n Install missing dependencies and re-run")
        exit(1)

    # Test BG2 Pod discovery
    print("\n[2/5] Testing BG2 Pod episode discovery...")
    try:
        bg2 = BG2Pod()
        episodes = bg2.discover_episodes(days=30)  # Bi-weekly, so look back further
        print(f"  Found {len(episodes)} episodes from last 30 days")

        if episodes:
            for ep in episodes[:3]:
                duration = ep.get('duration_seconds')
                dur_str = f" ({duration//60}min)" if duration else ""
                print(f"    - {ep['title'][:45]}...{dur_str}")
    except Exception as e:
        print(f"  BG2 Pod test failed: {e}")

    # Test Acquired discovery
    print("\n[3/5] Testing Acquired episode discovery...")
    try:
        acquired = AcquiredPodcast()
        episodes = acquired.discover_episodes(days=60)  # Less frequent, look back further
        print(f"  Found {len(episodes)} episodes from last 60 days")

        if episodes:
            for ep in episodes[:3]:
                duration = ep.get('duration_seconds')
                dur_str = f" ({duration//60}min)" if duration else ""
                print(f"    - {ep['title'][:45]}...{dur_str}")
    except Exception as e:
        print(f"  Acquired test failed: {e}")

    # Test transcript extraction (BG2)
    print("\n[4/5] Testing transcript extraction (BG2 Pod)...")
    try:
        bg2 = BG2Pod()
        episodes = bg2.discover_episodes(days=30)
        if episodes:
            ep = episodes[0]
            print(f"  Testing: {ep['title'][:40]}...")
            transcript = bg2.get_transcript(ep)
            if transcript:
                print(f"    Got {len(transcript):,} characters")
                print(f"    Preview: {transcript[:150]}...")
            else:
                print(f"    No transcript available (description fallback may apply)")
        else:
            print("  No episodes to test")
    except Exception as e:
        print(f"  Transcript test failed: {e}")

    # Test full collection
    print("\n[5/5] Testing full collection pipeline (BG2 Pod)...")
    try:
        bg2 = BG2Pod()
        results = bg2.collect(days=30, max_episodes=1)
        print(f"  Collected {len(results)} episode(s)")

        if results:
            result = results[0]
            print(f"    Title: {result['title'][:50]}...")
            print(f"    Source: {result['source']}")
            print(f"    Content length: {len(result['content']):,} chars")
    except Exception as e:
        print(f"  Collection test failed: {e}")

    print("\n RSS podcast handler tests complete")
