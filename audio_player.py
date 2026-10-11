#!/usr/bin/env python3
"""
Audio Player for Rotary Phone
Handles dial tone generation and text-to-speech playback.
"""

import subprocess
import tempfile
import os
from threading import Thread, Event


class AudioPlayer:
    """
    Handles audio playback for the rotary phone.
    Uses PulseAudio (paplay) for playback and gTTS for text-to-speech.
    """

    def __init__(self, sink_name="alsa_output.usb-Creative_Technology_Ltd_Sound_Blaster_Play__3_00179523-00.analog-stereo"):
        """
        Initialize audio player.

        Args:
            sink_name: PulseAudio sink name for Sound Blaster
        """
        self.sink_name = sink_name
        self.dial_tone_process = None
        self.dial_tone_thread = None
        self.playback_process = None
        self.stop_dial_tone = Event()

    def generate_dial_tone_wav(self, duration=60):
        """
        Generate dial tone WAV file (350Hz + 440Hz).

        Args:
            duration: Duration in seconds

        Returns:
            str: Path to generated WAV file
        """
        output_file = "/tmp/dial_tone.wav"

        # Generate dial tone using sox (350Hz + 440Hz)
        # North American dial tone is 350Hz + 440Hz continuous
        cmd = [
            "sox", "-n", "-r", "44100", "-c", "1", output_file,
            "synth", str(duration),
            "sine", "350",
            "sine", "440",
            "remix", "1,2"
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return output_file
        except subprocess.CalledProcessError:
            print("Warning: sox not found, using fallback beep")
            return None
        except FileNotFoundError:
            print("Warning: sox not installed")
            return None

    def play_dial_tone(self):
        """
        Play continuous dial tone in background thread.
        Call stop_dial_tone() to stop.
        """
        # Stop any existing dial tone first
        self.stop_dial_tone_playback()

        def _play():
            # Generate dial tone only if it doesn't exist
            dial_tone_file = "/tmp/dial_tone.wav"
            if not os.path.exists(dial_tone_file):
                dial_tone_file = self.generate_dial_tone_wav()

            if dial_tone_file and os.path.exists(dial_tone_file):
                # Play in loop until stopped
                while not self.stop_dial_tone.is_set():
                    # Check stop flag before starting each iteration
                    if self.stop_dial_tone.is_set():
                        break

                    try:
                        self.dial_tone_process = subprocess.Popen(
                            ["paplay", "--device=" + self.sink_name, dial_tone_file],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        self.dial_tone_process.wait()
                    except Exception as e:
                        print(f"Dial tone error: {e}")
                        break

                    # Check if we should stop between iterations
                    if self.stop_dial_tone.is_set():
                        break

        self.stop_dial_tone.clear()
        self.dial_tone_thread = Thread(target=_play, daemon=True)
        self.dial_tone_thread.start()

    def stop_dial_tone_playback(self):
        """Stop the dial tone playback."""
        # Signal the thread to stop
        self.stop_dial_tone.set()

        # Kill the current process if it exists
        if self.dial_tone_process:
            try:
                self.dial_tone_process.terminate()
                self.dial_tone_process.wait(timeout=0.5)
            except Exception:
                try:
                    self.dial_tone_process.kill()
                except Exception:
                    pass
            self.dial_tone_process = None

        # Wait for thread to finish
        if self.dial_tone_thread and self.dial_tone_thread.is_alive():
            self.dial_tone_thread.join(timeout=1.0)
            self.dial_tone_thread = None

    def speak(self, text, lang='en'):
        """
        Convert text to speech and play it.

        Args:
            text: Text to speak
            lang: Language code (default 'en')
        """
        try:
            from gtts import gTTS

            # Create temporary file for TTS audio
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                temp_file = f.name

            # Generate speech
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(temp_file)

            # Play the audio
            self.playback_process = subprocess.run(
                ["paplay", "--device=" + self.sink_name, temp_file],
                capture_output=True
            )

            # Clean up
            os.unlink(temp_file)

        except ImportError:
            print(f"gTTS not installed. Would say: {text}")
        except Exception as e:
            print(f"TTS error: {e}")

    def play_file(self, filepath):
        """
        Play an audio file.

        Args:
            filepath: Path to audio file
        """
        try:
            self.playback_process = subprocess.run(
                ["paplay", "--device=" + self.sink_name, filepath],
                capture_output=True,
                check=True
            )
        except Exception as e:
            print(f"Playback error: {e}")

    def stop_playback(self):
        """Stop any current playback."""
        self.stop_dial_tone_playback()

        if self.playback_process:
            try:
                self.playback_process.terminate()
            except Exception:
                pass

    def stop_all(self):
        """Stop all audio (alias for stop_playback)."""
        self.stop_playback()

    def cleanup(self):
        """Clean up audio resources."""
        self.stop_playback()


def test_audio():
    """Test audio player."""
    player = AudioPlayer()

    print("Testing dial tone (3 seconds)...")
    player.play_dial_tone()
    import time
    time.sleep(3)
    player.stop_dial_tone_playback()

    print("Testing TTS...")
    player.speak("Dial a song")

    print("Test complete!")
    player.cleanup()


if __name__ == "__main__":
    test_audio()
