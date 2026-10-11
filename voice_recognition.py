#!/usr/bin/env python3
"""
Voice Recognition using Vosk
Handles speech-to-text for song requests.
"""

import json
import pyaudio
import vosk
import os
import sys
import struct
import numpy as np
from contextlib import contextmanager


def stereo_to_mono(stereo_data):
    """Convert stereo audio data to mono by averaging channels."""
    # Unpack stereo samples (2 channels, 16-bit integers)
    samples = struct.unpack(f'{len(stereo_data)//2}h', stereo_data)

    # Average left and right channels
    mono_samples = []
    for i in range(0, len(samples), 2):
        left = samples[i]
        right = samples[i+1] if i+1 < len(samples) else left
        mono_samples.append((left + right) // 2)

    # Pack back as 16-bit integers
    return struct.pack(f'{len(mono_samples)}h', *mono_samples)


class StreamResampler:
    """Chunk-safe resampler with an anti-alias low-pass filter (numpy only)."""

    def __init__(self, in_rate, out_rate, taps=101):
        self.step = in_rate / out_rate
        cutoff = 0.45 * out_rate / in_rate  # fraction of input sample rate
        n = np.arange(taps) - (taps - 1) / 2
        h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(taps)
        self.h = h / h.sum()
        self.taps = taps
        self.tail = np.zeros(taps - 1)
        self.pos = 0.0  # next output position, relative to the current chunk

    def process(self, samples):
        x = np.concatenate([self.tail, samples.astype(np.float64)])
        filtered = np.convolve(x, self.h, mode='valid')  # len == len(samples)
        self.tail = x[-(self.taps - 1):]
        idx = np.arange(self.pos, len(filtered) - 1, self.step)
        out = np.interp(idx, np.arange(len(filtered)), filtered)
        self.pos = idx[-1] + self.step - len(filtered) if len(idx) else self.pos - len(filtered)
        return np.clip(out, -32768, 32767).astype(np.int16)


@contextmanager
def suppress_alsa_errors():
    """Suppress ALSA/JACK error messages during PyAudio initialization."""
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


class VoiceRecognizer:
    """
    Handles voice recognition using Vosk for offline speech-to-text.
    """

    def __init__(self, model_path="vosk-model-small-en-us-0.15", sample_rate=44100):
        """
        Initialize Vosk voice recognizer.

        Args:
            model_path: Path to Vosk model directory
            sample_rate: Audio sample rate (44100 for Sound Blaster compatibility)
        """
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.capture_rate = 44100   # Sound Blaster's native rate (doesn't support 16kHz)
        self.hardware_rate = 16000  # Vosk model's expected rate
        self.model = None
        self.recognizer = None
        self.stop_listening = False  # Flag to stop listening early
        self._mic_channels = 1  # updated by find_microphone_device()

        # Load model
        self._load_model()

    def _load_model(self):
        """Load Vosk model from disk."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Vosk model not found at {self.model_path}\n"
                f"Download a model from https://alphacephei.com/vosk/models\n"
                f"Example: wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip\n"
                f"Then: unzip vosk-model-small-en-us-0.15.zip"
            )

        print(f"Loading Vosk model from {self.model_path}...")
        self.model = vosk.Model(self.model_path)
        # Use hardware rate for recognizer to match audio input
        self.recognizer = vosk.KaldiRecognizer(self.model, self.hardware_rate)
        print(f"Vosk model loaded successfully (using {self.hardware_rate} Hz)")

    def listen_for_speech(self, max_timeout=30, device_index=None):
        """
        Listen for speech and convert to text.
        Stops automatically when speech ends (voice activity detection).

        Args:
            max_timeout: Maximum seconds to wait (safety fallback)
            device_index: PyAudio device index (None = default mic)

        Returns:
            str: Recognized text, or empty string if nothing recognized.
            None if the microphone could not be used.
        """
        self.recognizer.Reset()

        with suppress_alsa_errors():
            audio = pyaudio.PyAudio()

        # Try the detected channel count first, then fall back to others
        candidates = [self._mic_channels] + [c for c in (2, 1) if c != self._mic_channels]
        stream = None
        channels = self._mic_channels

        try:
            last_error = None
            for channels in candidates:
                try:
                    print(f"Opening audio stream on device {device_index} ({channels}ch)...")
                    with suppress_alsa_errors():
                        stream = audio.open(
                            format=pyaudio.paInt16,
                            channels=channels,
                            rate=self.capture_rate,
                            input=True,
                            input_device_index=device_index,
                            frames_per_buffer=4096
                        )
                    break
                except OSError as e:
                    last_error = e
                    print(f"Could not open stream with {channels}ch: {e}")
            if stream is None:
                raise last_error
            print("Stream opened successfully")
            stream.start_stream()
            print("Stream started")

            print("Listening... (speak now, will auto-stop when you finish)")

            # Reset stop flag
            self.stop_listening = False

            # Read audio data until speech detected or timeout
            import time
            start_time = time.time()
            recognized_text = ""

            chunk_44k = 4096
            resampler = StreamResampler(self.capture_rate, self.hardware_rate)
            peak = 0
            utterances = []
            last_text_time = None
            silence_after_text = 2.0

            while time.time() - start_time < max_timeout and not self.stop_listening:
                data = stream.read(chunk_44k, exception_on_overflow=False)

                mono = stereo_to_mono(data) if channels == 2 else data
                samples = np.frombuffer(mono, dtype=np.int16)
                resampled = resampler.process(samples)
                peak = max(peak, int(np.abs(samples).max()))

                if self.recognizer.AcceptWaveform(resampled.tobytes()):
                    text = json.loads(self.recognizer.Result()).get('text', '')
                    if text:
                        utterances.append(text)
                        last_text_time = time.time()

                if last_text_time and time.time() - last_text_time > silence_after_text:
                    break

            if self.stop_listening:
                print("Listening cancelled (handset hung up)")
                recognized_text = ""
            else:
                final = json.loads(self.recognizer.FinalResult()).get('text', '')
                if final:
                    utterances.append(final)
                recognized_text = ' '.join(utterances)

            print(f"Closing stream, peak level {peak}/32767, recognized: '{recognized_text}'")
            stream.stop_stream()
            stream.close()

            return recognized_text.strip()

        except Exception as e:
            print(f"Error during voice recognition: {e}")
            return None

        finally:
            audio.terminate()

    def find_microphone_device(self):
        """
        Find the PulseAudio microphone device index.

        Returns:
            int: Device index, or None if not found
        """
        with suppress_alsa_errors():
            audio = pyaudio.PyAudio()

        print("\nAvailable audio input devices:")
        sound_blaster_device = None
        pulse_device = None
        for i in range(audio.get_device_count()):
            dev_info = audio.get_device_info_by_index(i)
            if dev_info['maxInputChannels'] > 0:
                ch = int(dev_info['maxInputChannels'])
                print(f"  [{i}] {dev_info['name']} ({ch}ch)")
                if 'Sound Blaster' in dev_info['name'] and sound_blaster_device is None:
                    sound_blaster_device = (i, ch)
                    print(f"      ^ Sound Blaster found")
                elif dev_info['name'] == 'pulse' and pulse_device is None:
                    pulse_device = i
                    print(f"      ^ PulseAudio device found")

        audio.terminate()

        if sound_blaster_device is not None:
            idx, ch = sound_blaster_device
            self._mic_channels = ch
            return idx

        if pulse_device is not None:
            self._mic_channels = 1
            return pulse_device

        self._mic_channels = 1
        return None


def test_voice_recognition():
    """Test voice recognition."""
    try:
        recognizer = VoiceRecognizer()

        # Find microphone
        device_index = recognizer.find_microphone_device()
        if device_index is not None:
            print(f"\nUsing device index: {device_index}")
        else:
            print("\nUsing default microphone")

        print("\nSay something (e.g., 'play bohemian rhapsody by queen'):")
        text = recognizer.listen_for_speech(timeout=5, device_index=device_index)

        if text:
            print(f"\nYou said: '{text}'")
        else:
            print("\nNo speech detected")

    except FileNotFoundError as e:
        print(f"\n{e}")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    test_voice_recognition()
