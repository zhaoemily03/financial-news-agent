"""
Podcast Episode Tracking System
Tracks which podcast episodes have been processed to avoid duplicates
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional


class PodcastTracker:
    """Tracks processed podcast episodes to avoid duplicates"""

    def __init__(self, db_path='data/podcasts.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database with episodes table"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_url TEXT UNIQUE NOT NULL,
                episode_title TEXT,
                podcast_name TEXT,
                hosts TEXT,
                publish_date TEXT,
                processed_date TEXT NOT NULL,
                duration_seconds INTEGER,
                content_hash TEXT,
                transcript_length INTEGER
            )
        ''')

        conn.commit()
        conn.close()

    def is_processed(self, episode_url: str) -> bool:
        """Check if an episode has already been processed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            'SELECT COUNT(*) FROM processed_episodes WHERE episode_url = ?',
            (episode_url,)
        )
        count = cursor.fetchone()[0]

        conn.close()
        return count > 0

    def mark_as_processed(self, episode: Dict):
        """Mark an episode as processed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        hosts = episode.get('hosts', [])
        if isinstance(hosts, list):
            hosts = ', '.join(hosts)

        try:
            cursor.execute('''
                INSERT OR IGNORE INTO processed_episodes
                (episode_url, episode_title, podcast_name, hosts, publish_date,
                 processed_date, duration_seconds, transcript_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                episode.get('url'),
                episode.get('title'),
                episode.get('podcast_name') or episode.get('source'),
                hosts,
                episode.get('published_date') or episode.get('date'),
                datetime.now().isoformat(),
                episode.get('duration_seconds'),
                len(episode.get('content', '')) if episode.get('content') else 0
            ))

            conn.commit()
        except Exception as e:
            print(f"Error marking episode as processed: {e}")
        finally:
            conn.close()

    def filter_unprocessed(self, episodes: List[Dict]) -> List[Dict]:
        """Filter out episodes that have already been processed"""
        unprocessed = []
        for episode in episodes:
            if not self.is_processed(episode.get('url')):
                unprocessed.append(episode)
        return unprocessed

    def get_processed_count(self, days: int = 7) -> int:
        """Get count of episodes processed in the last N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) FROM processed_episodes
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
        ''', (days,))

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_recent_episodes(self, days: int = 7, limit: int = 50) -> List[Dict]:
        """Get recently processed episodes"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT episode_url, episode_title, podcast_name, hosts, publish_date,
                   processed_date, duration_seconds, transcript_length
            FROM processed_episodes
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY processed_date DESC
            LIMIT ?
        ''', (days, limit))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_episodes_by_podcast(self, podcast_name: str, days: int = 30) -> List[Dict]:
        """Get all episodes from a specific podcast within N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT episode_url, episode_title, podcast_name, hosts, publish_date,
                   processed_date, duration_seconds, transcript_length
            FROM processed_episodes
            WHERE podcast_name = ?
            AND datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY publish_date DESC
        ''', (podcast_name, days))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_podcast_stats(self, days: int = 30) -> Dict:
        """Get statistics on podcast coverage (episode counts by podcast)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT podcast_name, COUNT(*) as episode_count
            FROM processed_episodes
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            AND podcast_name IS NOT NULL
            GROUP BY podcast_name
            ORDER BY episode_count DESC
        ''', (days,))

        rows = cursor.fetchall()
        conn.close()

        return {row[0]: row[1] for row in rows}

    def _row_to_dict(self, row) -> Dict:
        """Convert a database row to an episode dictionary"""
        return {
            'url': row[0],
            'title': row[1],
            'podcast_name': row[2],
            'hosts': row[3].split(', ') if row[3] else [],
            'date': row[4],
            'processed_date': row[5],
            'duration_seconds': row[6],
            'transcript_length': row[7]
        }


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("\nPodcast Tracker Tests")
    print("=" * 50)

    # Use temp DB for testing
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        test_db = f.name

    tracker = PodcastTracker(db_path=test_db)

    # Test 1: Check unprocessed episode
    print("\n[1/4] Testing is_processed (new episode)...")
    test_url = "https://youtube.com/watch?v=test123"
    assert not tracker.is_processed(test_url), "New episode should not be processed"
    print("  New episode correctly identified as unprocessed")

    # Test 2: Mark as processed
    print("\n[2/4] Testing mark_as_processed...")
    test_episode = {
        'url': test_url,
        'title': 'Test Episode: AI Market Analysis',
        'podcast_name': 'All-In Podcast',
        'hosts': ['Chamath', 'Jason', 'Sacks', 'Friedberg'],
        'published_date': '2026-02-01',
        'content': 'This is the transcript content...',
    }
    tracker.mark_as_processed(test_episode)
    assert tracker.is_processed(test_url), "Episode should now be processed"
    print("  Episode marked and verified as processed")

    # Test 3: Filter unprocessed
    print("\n[3/4] Testing filter_unprocessed...")
    episodes = [
        {'url': test_url, 'title': 'Already Processed'},
        {'url': 'https://youtube.com/watch?v=new456', 'title': 'New Episode'},
    ]
    unprocessed = tracker.filter_unprocessed(episodes)
    assert len(unprocessed) == 1, "Should filter out processed episode"
    assert unprocessed[0]['url'] == 'https://youtube.com/watch?v=new456'
    print(f"  Correctly filtered: {len(unprocessed)} unprocessed of {len(episodes)} total")

    # Test 4: Get recent episodes
    print("\n[4/4] Testing get_recent_episodes...")
    recent = tracker.get_recent_episodes(days=1)
    assert len(recent) == 1, "Should have 1 recent episode"
    assert recent[0]['podcast_name'] == 'All-In Podcast'
    print(f"  Retrieved {len(recent)} recent episode(s)")

    # Cleanup
    os.unlink(test_db)

    print("\n All podcast tracker tests passed")
