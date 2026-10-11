#!/usr/bin/env python3
"""
YouTube Music Jukebox
Handles playlist loading and playback control via YouTube Music API.
"""

from ytmusicapi import YTMusic
import pychromecast
import time
import os
import yt_dlp


class YouTubeJukebox:
    """
    Manages YouTube Music playlist access and playback.
    """

    def __init__(self, chromecast_name=None):
        """
        Initialize YouTube Music client.

        Args:
            chromecast_name: Name of Chromecast device (optional)
        """
        # Initialize client (can work without auth for public playlists)
        # For authenticated access, use: YTMusic('oauth.json')
        try:
            # Try authenticated access first
            if os.path.exists('oauth.json'):
                self.ytmusic = YTMusic('oauth.json')
                print("YouTube Music: Authenticated")
            else:
                self.ytmusic = YTMusic()
                print("YouTube Music: Unauthenticated (public access only)")
        except Exception as e:
            print(f"YouTube Music init error: {e}")
            self.ytmusic = YTMusic()

        # Chromecast setup
        self.chromecast_name = chromecast_name
        self.cast_device = None

    def search_song(self, query, limit=5):
        """
        Search YouTube Music for a song.

        Args:
            query: Search query (e.g., "bohemian rhapsody queen")
            limit: Number of results to return

        Returns:
            list: List of track dicts with artist, title, video_id
        """
        try:
            print(f"Searching YouTube Music for: '{query}'")
            results = self.ytmusic.search(query, filter="songs", limit=limit)

            tracks = []
            for result in results:
                artist = ', '.join([a['name'] for a in result.get('artists', [])])
                title = result.get('title', 'Unknown')
                video_id = result.get('videoId')

                if video_id:
                    tracks.append({
                        'artist': artist,
                        'title': title,
                        'video_id': video_id
                    })

            return tracks

        except Exception as e:
            print(f"Error searching: {e}")
            return []

    def get_track_url(self, video_id):
        """
        Get YouTube Music URL for a track.

        Args:
            video_id: YouTube video ID

        Returns:
            str: YouTube Music URL
        """
        return f"https://music.youtube.com/watch?v={video_id}"

    def get_audio_stream_url(self, video_id):
        """
        Extract direct audio stream URL from YouTube using yt-dlp.

        Args:
            video_id: YouTube video ID

        Returns:
            str: Direct audio stream URL, or None if extraction fails
        """
        url = f"https://music.youtube.com/watch?v={video_id}"

        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
            }

            print(f"Extracting audio stream URL...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get('url')
                print(f"✓ Got audio stream URL (length: {len(stream_url)} chars)")
                return stream_url

        except Exception as e:
            print(f"Error extracting stream URL: {e}")
            return None

    def find_chromecast(self, device_name=None):
        """
        Find and connect to a Chromecast device.

        Args:
            device_name: Name of Chromecast (None = first device found)

        Returns:
            bool: True if device found and connected
        """
        try:
            print("Searching for Chromecasts...")
            chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[device_name] if device_name else None)

            if not chromecasts:
                print("No Chromecasts found")
                return False

            self.cast_device = chromecasts[0]
            self.cast_device.wait()
            print(f"Connected to: {self.cast_device.name}")
            return True

        except Exception as e:
            print(f"Error finding Chromecast: {e}")
            return False

    def cast_to_youtube(self, video_id):
        """
        Cast a YouTube Music track to Chromecast (optimized for audio devices).

        Args:
            video_id: YouTube video ID

        Returns:
            bool: True if cast successful
        """
        if not self.cast_device:
            if not self.find_chromecast(self.chromecast_name):
                print("Cannot cast: No Chromecast connected")
                return False

        try:
            # Wait for connection
            self.cast_device.wait()

            print(f"Casting YouTube Music video ID: {video_id}")
            print(f"YouTube Music URL: https://music.youtube.com/watch?v={video_id}")

            # Extract direct audio stream URL for audio-only devices like WiiM
            stream_url = self.get_audio_stream_url(video_id)
            if not stream_url:
                print("Failed to extract audio stream URL")
                return False

            # Use default media controller to play the audio stream
            mc = self.cast_device.media_controller
            mc.play_media(stream_url, 'audio/mp4')
            mc.block_until_active()

            print(f"✓ Now playing audio stream on {self.cast_device.name}")
            return True

        except Exception as e:
            print(f"Error casting to Chromecast: {e}")
            import traceback
            traceback.print_exc()
            return False

    def play_track(self, video_id):
        """
        Play track by casting to Chromecast.

        Args:
            video_id: YouTube video ID

        Returns:
            bool: True if playback started successfully
        """
        return self.cast_to_youtube(video_id)


def test_youtube_jukebox():
    """Test YouTube Music voice search and Chromecast."""

    jukebox = YouTubeJukebox()

    # Test voice search
    query = input("What song do you want to hear? ").strip()
    if not query:
        print("No query provided")
        return

    print(f"\nSearching for: '{query}'")
    results = jukebox.search_song(query, limit=3)

    if results:
        print(f"\nFound {len(results)} results:")
        for i, track in enumerate(results):
            print(f"{i+1}. {track['artist']} - {track['title']}")

        # Play first result
        print(f"\nPlaying: {results[0]['artist']} - {results[0]['title']}")
        success = jukebox.play_track(results[0]['video_id'])

        if success:
            print("✓ Now playing on Chromecast!")
        else:
            print("✗ Could not cast to Chromecast")
            print(f"URL: {jukebox.get_track_url(results[0]['video_id'])}")
    else:
        print("No results found")


if __name__ == "__main__":
    test_youtube_jukebox()
