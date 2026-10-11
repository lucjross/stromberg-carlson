#!/usr/bin/env python3
"""
Phone State Machine
Manages the state of the rotary phone jukebox.
"""

from enum import Enum


class PhoneState(Enum):
    """States the phone can be in."""
    ON_HOOK = "on_hook"           # Handset down, idle
    DIAL_TONE = "dial_tone"       # Handset up, playing dial tone
    WAITING_FOR_OPERATOR = "waiting_for_operator"  # After dial tone, waiting for 0
    OPERATOR_MESSAGE = "operator_message"  # Playing "say the song you want"
    REQUESTING = "requesting"     # User is speaking song request
    ANNOUNCING = "announcing"     # Speaking artist and song name, then back to dial tone


class PhoneStateMachine:
    """
    State machine for rotary phone jukebox.

    State transitions:
    ON_HOOK → DIAL_TONE (when handset lifted)
    DIAL_TONE → WAITING_FOR_OPERATOR (dial tone playing)
    WAITING_FOR_OPERATOR → OPERATOR_MESSAGE (when 0 dialed)
    OPERATOR_MESSAGE → REQUESTING (after message plays)
    REQUESTING → ANNOUNCING (after voice recognition completes)
    ANNOUNCING → DIAL_TONE (after announcement, song plays in background)
    ANY_STATE → ON_HOOK (when handset hung up)
    """

    def __init__(self):
        self.state = PhoneState.ON_HOOK
        self.requested_song = None

    def reset(self):
        """Reset to on-hook state."""
        self.state = PhoneState.ON_HOOK
        self.requested_song = None

    def handset_lifted(self):
        """Transition when handset is lifted."""
        if self.state == PhoneState.ON_HOOK:
            self.state = PhoneState.DIAL_TONE
            self.requested_song = None
            return True
        return False

    def handset_down(self):
        """Transition when handset is hung up."""
        self.state = PhoneState.ON_HOOK
        self.requested_song = None
        return False

    def dial_tone_started(self):
        """Transition after dial tone starts playing."""
        if self.state == PhoneState.DIAL_TONE:
            self.state = PhoneState.WAITING_FOR_OPERATOR
            return True
        return False

    def operator_requested(self):
        """Transition when 0 is dialed for operator."""
        if self.state == PhoneState.WAITING_FOR_OPERATOR:
            self.state = PhoneState.OPERATOR_MESSAGE
            return True
        return False

    def operator_message_complete(self):
        """Transition after operator message finishes."""
        if self.state == PhoneState.OPERATOR_MESSAGE:
            self.state = PhoneState.REQUESTING
            self.requested_song = None
            return True
        return False

    def digit_dialed(self, digit):
        """
        Handle a dialed digit.

        Args:
            digit: Integer 0-9

        Returns:
            bool: True if digit was accepted
        """
        if self.state == PhoneState.WAITING_FOR_OPERATOR:
            if digit == 0:
                return self.operator_requested()
            elif digit == 6:
                # Shutdown command - accept but don't change state
                return True
            else:
                # Invalid, ignore or reset to dial tone
                return False

        return False

    def voice_request_received(self, song_text):
        """
        Handle voice request for a song.

        Args:
            song_text: Recognized speech text

        Returns:
            bool: True if request was accepted
        """
        if self.state == PhoneState.REQUESTING:
            self.requested_song = song_text
            return True
        return False

    def start_announcing(self):
        """Transition to announcing state."""
        if self.state == PhoneState.REQUESTING:
            self.state = PhoneState.ANNOUNCING
            return True
        return False

    def announcing_complete(self):
        """Transition back to dial tone after announcement (song plays in background)."""
        if self.state == PhoneState.ANNOUNCING:
            self.state = PhoneState.DIAL_TONE
            self.requested_song = None  # Clear the request
            return True
        return False

    def __str__(self):
        song_info = f", Requested: '{self.requested_song}'" if self.requested_song else ""
        return f"PhoneState: {self.state.value}{song_info}"
