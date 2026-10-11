#!/usr/bin/env python3
"""
Rotary Phone Voice Jukebox
Main application integrating rotary phone, voice recognition, and YouTube Music.
"""

import os
import time
from dotenv import load_dotenv
from rotary_dial import RotaryDial, HookSwitch
from phone_state import PhoneStateMachine, PhoneState
from audio_player import AudioPlayer
from voice_recognition import VoiceRecognizer
from youtube_jukebox import YouTubeJukebox


class RotaryPhoneVoiceJukebox:
    """
    Main jukebox controller integrating all components.
    """

    def __init__(self, chromecast_name=None, vosk_model_path="vosk-model-small-en-us-0.15"):
        """
        Initialize the rotary phone voice jukebox.

        Args:
            chromecast_name: Name of Chromecast device (None = auto-discover)
            vosk_model_path: Path to Vosk model directory
        """
        print("Initializing Rotary Phone Voice Jukebox...")

        # Hardware
        self.dial = RotaryDial(pulse_pin=17, ready_pin=27)
        self.hook = HookSwitch(hook_pin=22)

        # State machine
        self.state_machine = PhoneStateMachine()

        # Audio playback (dial tone, TTS)
        self.audio = AudioPlayer()

        # Voice recognition
        print("Loading voice recognition...")
        self.voice = VoiceRecognizer(model_path=vosk_model_path)

        # YouTube Music + Chromecast
        print("Connecting to YouTube Music...")
        self.jukebox = YouTubeJukebox(chromecast_name=chromecast_name)

        # Find microphone device
        self.mic_device_index = self.voice.find_microphone_device()

        # Setup callbacks
        self._setup_callbacks()

        print("Jukebox ready!")

    def _setup_callbacks(self):
        """Setup hardware event callbacks."""
        self.hook.off_hook_callback = self._on_handset_lifted
        self.hook.on_hook_callback = self._on_handset_down
        self.dial.when_dialed = self._on_digit_dialed
        self.dial.when_dial_starts = self._on_dial_starts

    def _on_dial_starts(self):
        """Handle dial starting to turn."""
        # Stop dial tone when user starts dialing
        if self.state_machine.state in [PhoneState.DIAL_TONE, PhoneState.WAITING_FOR_OPERATOR]:
            self.audio.stop_all()

    def _on_handset_lifted(self):
        """Handle handset lifted event."""
        print("\n=== Handset LIFTED ===")

        if self.state_machine.handset_lifted():
            print(f"State: {self.state_machine}")
            # Start dial tone
            self.audio.play_dial_tone()
            time.sleep(1)  # Let dial tone play for a moment
            self.state_machine.dial_tone_started()
            print(f"State: {self.state_machine}")

    def _on_handset_down(self):
        """Handle handset hung up event."""
        print("\n=== Handset DOWN ===")

        # Stop any audio
        self.audio.stop_all()

        # Stop voice recognition if listening
        self.voice.stop_listening = True

        self.state_machine.handset_down()
        print(f"State: {self.state_machine}")

    def _on_digit_dialed(self, digit):
        """Handle dialed digit."""
        print(f"\n=== Digit dialed: {digit} ===")

        if self.state_machine.digit_dialed(digit):
            print(f"State: {self.state_machine}")

            # Handle shutdown command (digit 6)
            if digit == 6:
                print("Shutdown command received!")
                self.audio.stop_all()
                self.audio.speak("Self-destruct initiated.")
                time.sleep(3)  # Let the message finish
                print("Initiating system shutdown...")
                import subprocess
                subprocess.run(["sudo", "shutdown", "-h", "now"])
                return

            if self.state_machine.state == PhoneState.OPERATOR_MESSAGE:
                # Stop dial tone
                self.audio.stop_all()

                # Play operator message
                print("Playing operator message...")
                self.audio.speak("What would you like to hear?")

                # Transition to requesting
                self.state_machine.operator_message_complete()
                print(f"State: {self.state_machine}")

                # Start voice recognition
                self._handle_voice_request()

    def _handle_voice_request(self):
        """Handle voice recognition and song search."""
        print("\n=== Listening for song request ===")

        # Listen for speech (15 second timeout)
        recognized_text = self.voice.listen_for_speech(
            device_index=self.mic_device_index
        )

        if not recognized_text:
            print("No speech detected, returning to dial tone")
            self.audio.speak("I didn't hear anything. Please try again.")
            self.state_machine.reset()
            return

        print(f"Recognized: '{recognized_text}'")

        # Save request and transition to announcing
        self.state_machine.voice_request_received(recognized_text)
        self.state_machine.start_announcing()
        print(f"State: {self.state_machine}")

        # Search YouTube Music
        print(f"Searching YouTube Music for: '{recognized_text}'")
        results = self.jukebox.search_song(recognized_text, limit=1)

        if not results:
            print("No results found")
            self.audio.speak("Sorry, I couldn't find that song. Please try again.")
            self.state_machine.reset()
            return

        # Get top result
        track = results[0]
        print(f"Found: {track['artist']} - {track['title']}")

        # Announce the song
        announcement = f"Playing {track['title']} by {track['artist']}"
        print(f"Announcing: {announcement}")
        self.audio.speak(announcement)

        # Cast to Chromecast
        print("Casting to Chromecast...")
        success = self.jukebox.play_track(track['video_id'])

        if success:
            print("✓ Now playing on Chromecast!")
        else:
            print("✗ Failed to cast to Chromecast")
            self.audio.speak("Sorry, I couldn't play that on your speaker.")

        # Return to dial tone (song plays in background)
        time.sleep(2)  # Brief pause before returning to dial tone
        self.state_machine.announcing_complete()
        print(f"State: {self.state_machine}")

        if self.state_machine.state != PhoneState.ON_HOOK:
            self.audio.play_dial_tone()
            self.state_machine.dial_tone_started()
            print(f"State: {self.state_machine}")

    def run(self):
        """Run the jukebox main loop."""
        print("\n" + "="*50)
        print("Rotary Phone Voice Jukebox - Ready!")
        print("="*50)
        print("\n1. Pick up the handset")
        print("2. Dial 0 for operator")
        print("3. Say the song you want to hear")
        print("4. Listen to the music!")
        print("\nPress Ctrl+C to exit\n")

        try:
            while True:
                time.sleep(0.1)

        except KeyboardInterrupt:
            print("\n\nShutting down...")
            self.audio.stop_all()
            print("Goodbye!")


def main():
    """Main entry point."""
    # Load configuration from .env file
    load_dotenv()

    chromecast_name = os.getenv("CHROMECAST_NAME")
    vosk_model_path = os.getenv("VOSK_MODEL_PATH", "vosk-model-small-en-us-0.15")

    print(f"Configuration:")
    print(f"  Chromecast: {chromecast_name or 'Auto-discover'}")
    print(f"  Vosk Model: {vosk_model_path}\n")

    jukebox = RotaryPhoneVoiceJukebox(
        chromecast_name=chromecast_name,
        vosk_model_path=vosk_model_path
    )
    jukebox.run()


if __name__ == "__main__":
    main()
