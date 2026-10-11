#!/usr/bin/env python3
"""
Rotary Phone Controller for Raspberry Pi
Reads input from a vintage rotary phone via GPIO pins.
Supports rotary dial and hook switch.
"""

from gpiozero import Button
from time import time, sleep


class HookSwitch:
    """
    Monitors the hook switch on a rotary phone.

    When the handset is down (on-hook), the circuit is closed.
    When the handset is lifted (off-hook), the circuit is open.

    Args:
        hook_pin: GPIO pin number for hook switch
        bounce_time: Debounce time in seconds for hook detection
    """

    def __init__(self, hook_pin, bounce_time=0.05):
        self.hook_pin = hook_pin

        # Set up GPIO pin
        # The hook switch closes (pulls to ground) when handset is down
        self.hook_button = Button(hook_pin, pull_up=True, bounce_time=bounce_time)

        # Callbacks
        self.off_hook_callback = None  # Called when handset is lifted
        self.on_hook_callback = None   # Called when handset is placed down

        # Set up event handlers
        # When button is "pressed" (circuit closes), phone goes on-hook
        self.hook_button.when_pressed = self._on_hook_down
        # When button is "released" (circuit opens), phone goes off-hook
        self.hook_button.when_released = self._on_hook_up

    def _on_hook_down(self):
        """Called when handset is placed down (circuit closes)."""
        if self.on_hook_callback:
            self.on_hook_callback()

    def _on_hook_up(self):
        """Called when handset is lifted (circuit opens)."""
        if self.off_hook_callback:
            self.off_hook_callback()

    def is_off_hook(self):
        """
        Check if the phone is currently off-hook (handset lifted).

        Returns:
            bool: True if off-hook (handset lifted), False if on-hook
        """
        return not self.hook_button.is_pressed

    def is_on_hook(self):
        """
        Check if the phone is currently on-hook (handset down).

        Returns:
            bool: True if on-hook (handset down), False if off-hook
        """
        return self.hook_button.is_pressed

    def on_off_hook(self, callback):
        """
        Register a callback for when the handset is lifted (goes off-hook).

        Args:
            callback: Function to call when handset is lifted (no arguments)
        """
        self.off_hook_callback = callback

    def on_on_hook(self, callback):
        """
        Register a callback for when the handset is placed down (goes on-hook).

        Args:
            callback: Function to call when handset is placed down (no arguments)
        """
        self.on_hook_callback = callback

    def cleanup(self):
        """Clean up GPIO resources."""
        self.hook_button.close()


class RotaryDial:
    """
    Reads input from a rotary phone dial.

    Args:
        pulse_pin: GPIO pin number for pulse contacts (blue/green wires)
        ready_pin: GPIO pin number for off-normal switch (white wires)
        pulse_timeout: Time in seconds to wait after last pulse before reporting digit
        bounce_time: Debounce time in seconds for pulse detection
    """

    def __init__(self, pulse_pin, ready_pin, pulse_timeout=0.2, bounce_time=0.01):
        self.pulse_pin = pulse_pin
        self.ready_pin = ready_pin
        self.pulse_timeout = pulse_timeout

        # Set up GPIO pins
        # The pulse contact closes (pulls to ground) on each pulse
        self.pulse_button = Button(pulse_pin, pull_up=True, bounce_time=bounce_time)

        # The ready switch opens when dial is at rest, closes when turning
        self.ready_button = Button(ready_pin, pull_up=True, bounce_time=bounce_time)

        # State tracking
        self.pulse_count = 0
        self.last_pulse_time = 0
        self.dialing = False
        self.digit_callback = None
        self.dial_start_callback = None
        self._stop_polling = False

        # Set up event handlers
        self.pulse_button.when_pressed = self._on_pulse
        self.ready_button.when_pressed = self._on_dial_start
        self.ready_button.when_released = self._on_dial_end

        # Start background polling thread
        from threading import Thread
        self._polling_thread = Thread(target=self._poll_timeout, daemon=True)
        self._polling_thread.start()

    def _on_dial_start(self):
        """Called when the dial starts turning (ready switch closes)."""
        self.dialing = True
        self.pulse_count = 0

        # Call callback if set
        if self.dial_start_callback:
            self.dial_start_callback()

    def _on_dial_end(self):
        """Called when the dial returns to rest (ready switch opens)."""
        if self.dialing:
            self.dialing = False

    def _on_pulse(self):
        """Called on each pulse from the dial."""
        if self.dialing:
            self.pulse_count += 1
            self.last_pulse_time = time()

    def _check_timeout(self):
        """Check if enough time has passed since last pulse to report the digit."""
        if self.pulse_count > 0 and not self.dialing:
            if time() - self.last_pulse_time > self.pulse_timeout:
                # Convert pulse count to digit (10 pulses = 0)
                digit = self.pulse_count if self.pulse_count < 10 else 0
                print(f"\nDialed digit: {digit}\n")

                # Call the callback if set
                if self.digit_callback:
                    self.digit_callback(digit)

                # Reset pulse count
                self.pulse_count = 0

    def _poll_timeout(self):
        """Background thread to poll for timeout."""
        while not self._stop_polling:
            self._check_timeout()
            sleep(0.01)

    @property
    def when_dialed(self):
        """Get the digit callback."""
        return self.digit_callback

    @when_dialed.setter
    def when_dialed(self, callback):
        """Set the digit callback."""
        self.digit_callback = callback

    @property
    def when_dial_starts(self):
        """Get the dial start callback."""
        return self.dial_start_callback

    @when_dial_starts.setter
    def when_dial_starts(self, callback):
        """Set the dial start callback."""
        self.dial_start_callback = callback

    def on_digit(self, callback):
        """
        Register a callback function to be called when a digit is dialed.

        Args:
            callback: Function that takes a single integer argument (0-9)
        """
        self.digit_callback = callback

    def run(self):
        """
        Start monitoring the dial. This will run until interrupted.
        Call this after setting up any callbacks with on_digit().
        """
        print(f"Rotary dial reader started")
        print(f"Pulse pin: GPIO {self.pulse_pin}")
        print(f"Ready pin: GPIO {self.ready_pin}")
        print("Waiting for dial input... (Press Ctrl+C to exit)\n")

        try:
            while True:
                self._check_timeout()
                sleep(0.01)  # Small delay to prevent CPU spinning
        except KeyboardInterrupt:
            print("\nExiting...")
            self.cleanup()

    def cleanup(self):
        """Clean up GPIO resources."""
        self.pulse_button.close()
        self.ready_button.close()
