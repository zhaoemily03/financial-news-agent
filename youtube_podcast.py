"""
YouTube Podcast Handler

Handles podcasts distributed via YouTube, using:
- YouTube RSS feeds for episode discovery
- youtube-transcript-api for transcript extraction

Supports: All-In Podcast and other YouTube-native shows
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
    from youtube_transcript_api import YouTubeTranscriptApi
    HAS_TRANSCRIPT_API = True
except ImportError:
    HAS_TRANSCRIPT_API = False
    print("Warning: youtube-transcript-api not installed. Run: pip install youtube-transcript-api")


class YouTubePodcast(BasePodcast):
    """
    Handler for YouTube-based podcasts with auto-generated transcripts.

    Uses YouTube RSS feeds for discovery (no API key needed) and
    youtube-transcript-api for transcript extraction.

    Subclasses must define CHANNEL_ID.
    """

    # Subclass must define
    CHANNEL_ID: str = None

    def __init__(self):
        if self.CHANNEL_ID is None:
            raise NotImplementedError("Subclass must define CHANNEL_ID")
        super().__init__()

    def discover_episodes(self, days: int = 7) -> List[Dict]:
        """
        Use YouTube RSS feed to find recent uploads.

        YouTube provides RSS feeds at:
        https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
        """
        if not HAS_FEEDPARSER:
            print("  feedparser not available - cannot discover episodes")
            return []

        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={self.CHANNEL_ID}"

        try:
            feed = feedparser.parse(feed_url)
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

            # Extract video ID from URL
            video_id = self._extract_video_id(entry.link)
            if not video_id:
                continue

            episodes.append({
                'title': entry.title,
                'url': entry.link,
                'video_id': video_id,
                'published_date': pub_date.strftime('%Y-%m-%d'),
                'description': getattr(entry, 'summary', ''),
            })

        return episodes

    def get_transcript(self, episode: Dict) -> Optional[str]:
        """Extract transcript using youtube-transcript-api."""
        if not HAS_TRANSCRIPT_API:
            print("    youtube-transcript-api not available")
            return None

        video_id = episode.get('video_id')
        if not video_id:
            video_id = self._extract_video_id(episode.get('url', ''))

        if not video_id:
            print("    Could not extract video ID")
            return None

        try:
            # Use new API (v1.2+): YouTubeTranscriptApi().fetch(video_id)
            ytt_api = YouTubeTranscriptApi()
            fetched_transcript = ytt_api.fetch(video_id, languages=['en', 'en-US', 'en-GB'])

            # Combine all segments into full text
            segments = []
            for snippet in fetched_transcript:
                text = snippet.text.strip() if hasattr(snippet, 'text') else str(snippet).strip()
                if text:
                    segments.append(text)

            full_text = ' '.join(segments)

            # Clean up common transcript artifacts
            full_text = self._clean_transcript(full_text)

            return full_text

        except Exception as e:
            print(f"    Transcript unavailable: {e}")
            return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from URL."""
        if not url:
            return None

        # Match various YouTube URL formats
        patterns = [
            r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def _clean_transcript(self, text: str) -> str:
        """Clean up common transcript artifacts."""
        # Remove [Music], [Applause], etc.
        text = re.sub(r'\[(?:Music|Applause|Laughter)\]', '', text, flags=re.IGNORECASE)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text


# ------------------------------------------------------------------
# Concrete Podcast Implementations
# ------------------------------------------------------------------

class AllInPodcast(YouTubePodcast):
    """
    All-In Podcast - Weekly tech and business podcast

    Hosts: Chamath Palihapitiya, Jason Calacanis, David Sacks, David Friedberg
    Topics: Tech, markets, politics, venture capital
    """
    PODCAST_NAME = "All-In Podcast"
    PODCAST_URL = "https://www.youtube.com/@allin"
    CHANNEL_ID = "UCESLZhusAkFfsNsApnjF_Cg"
    HOSTS = ["Chamath Palihapitiya", "Jason Calacanis", "David Sacks", "David Friedberg"]


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nYouTube Podcast Handler Tests")
    print("=" * 50)

    # Check dependencies
    print("\n[1/4] Checking dependencies...")
    if not HAS_FEEDPARSER:
        print("  feedparser: NOT INSTALLED")
        print("  Run: pip install feedparser")
    else:
        print("  feedparser: OK")

    if not HAS_TRANSCRIPT_API:
        print("  youtube-transcript-api: NOT INSTALLED")
        print("  Run: pip install youtube-transcript-api")
    else:
        print("  youtube-transcript-api: OK")

    if not (HAS_FEEDPARSER and HAS_TRANSCRIPT_API):
        print("\n Install missing dependencies and re-run")
        exit(1)

    # Test All-In Podcast discovery
    print("\n[2/4] Testing All-In Podcast episode discovery...")
    allin = AllInPodcast()
    episodes = allin.discover_episodes(days=14)
    print(f"  Found {len(episodes)} episodes from last 14 days")

    if episodes:
        for ep in episodes[:3]:
            print(f"    - {ep['title'][:50]}... ({ep['published_date']})")

    # Test transcript extraction (first episode only)
    print("\n[3/4] Testing transcript extraction...")
    if episodes:
        ep = episodes[0]
        print(f"  Getting transcript for: {ep['title'][:40]}...")
        transcript = allin.get_transcript(ep)
        if transcript:
            print(f"    Extracted {len(transcript):,} characters")
            print(f"    Preview: {transcript[:200]}...")
        else:
            print(f"    No transcript available")
    else:
        print("  No episodes to test")

    # Test full collection
    print("\n[4/4] Testing full collection pipeline...")
    results = allin.collect(days=7, max_episodes=1)
    print(f"  Collected {len(results)} episode(s)")

    if results:
        result = results[0]
        print(f"    Title: {result['title'][:50]}...")
        print(f"    Source: {result['source']}")
        print(f"    Analyst: {result['analyst'][:50]}...")
        print(f"    Content length: {len(result['content']):,} chars")

    print("\n YouTube podcast handler tests complete")
