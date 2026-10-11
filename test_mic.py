#!/usr/bin/env python3
"""Test microphone input."""

import pyaudio
import wave
import sys
import os

# Suppress ALSA errors
from contextlib import contextmanager

@contextmanager
def suppress_stderr():
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    sys.stderr.flush()
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)

with suppress_stderr():
    audio = pyaudio.PyAudio()

print("Available input devices:")
for i in range(audio.get_device_count()):
    info = audio.get_device_info_by_index(i)
    if info['maxInputChannels'] > 0:
        print(f"  [{i}] {info['name']} - {info['maxInputChannels']} channels, {int(info['defaultSampleRate'])} Hz")

device_index = int(input("\nEnter device number to test: "))

print(f"\nRecording 3 seconds from device {device_index}...")

with suppress_stderr():
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=2,  # Use stereo to match hardware
        rate=44100,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=1024
    )

frames = []
for i in range(0, int(44100 / 1024 * 3)):
    data = stream.read(1024, exception_on_overflow=False)
    frames.append(data)

    # Calculate volume
    import struct
    values = struct.unpack('h' * (len(data) // 2), data)
    volume = max(abs(v) for v in values) if values else 0

    if i % 10 == 0:  # Print every ~0.25 seconds
        bars = '█' * (volume // 1000)
        print(f"\rVolume: {bars[:50]:<50} ({volume})    ", end='', flush=True)

stream.stop_stream()
stream.close()

# Save recording
print("\n\nSaving test.wav...")
wf = wave.open('/tmp/test.wav', 'wb')
wf.setnchannels(2)  # Stereo
wf.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
wf.setframerate(44100)
wf.writeframes(b''.join(frames))
wf.close()

audio.terminate()

print("Recording saved to /tmp/test.wav")
print("Play it back with: paplay /tmp/test.wav")
