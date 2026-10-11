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
import io
import wave
import requests
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


class HighPass:
    """Chunk-safe FIR high-pass filter; removes mains hum (60 Hz and low harmonics)."""

    def __init__(self, rate, cutoff=180, taps=501):
        n = np.arange(taps) - (taps - 1) / 2
        lp = 2 * (cutoff / rate) * np.sinc(2 * (cutoff / rate) * n) * np.hamming(taps)
        lp /= lp.sum()
        self.h = -lp
        self.h[(taps - 1) // 2] += 1.0
        self.taps = taps
        self.tail = np.zeros(taps - 1)

    def process(self, samples):
        x = np.concatenate([self.tail, samples.astype(np.float64)])
        y = np.convolve(x, self.h, mode='valid')
        self.tail = x[-(self.taps - 1):]
        return np.clip(y, -32768, 32767).astype(np.int16)


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

    def _transcribe_deepgram(self, pcm16k):
        """Transcribe 16 kHz mono int16 audio with Deepgram. Returns text ('' if none heard), or None on failure."""
        api_key = os.environ.get('DEEPGRAM_API_KEY')
        if not api_key:
            print("DEEPGRAM_API_KEY is not set")
            return None
        try:
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.hardware_rate)
                w.writeframes(pcm16k.tobytes())
            resp = requests.post(
                'https://api.deepgram.com/v1/listen',
                params={'model': 'nova-3', 'language': 'en', 'smart_format': 'true'},
                headers={'Authorization': f'Token {api_key}', 'Content-Type': 'audio/wav'},
                data=buf.getvalue(),
                timeout=10,
            )
            resp.raise_for_status()
            alt = resp.json()['results']['channels'][0]['alternatives'][0]
            return alt.get('transcript', '').strip()
        except Exception as e:
            print(f"Deepgram error: {e}")
            return None

    def listen_for_speech(self, max_timeout=12, device_index=None):
        """
        Listen for speech and convert to text.
        Stops automatically when speech ends (voice activity detection).

        Args:
            max_timeout: Maximum seconds to wait (safety fallback)
            device_index: PyAudio device index (None = default mic)

        Returns:
            str: Recognized text, or empty string if nothing recognized.
            None if the microphone or transcription failed.
        """
        self.recognizer.Reset()
        import time
        t_called = time.time()

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
            print(f"Stream started ({time.time() - t_called:.2f}s after listen requested)")

            print("Listening... (speak now, will auto-stop when you finish)")

            # Reset stop flag
            self.stop_listening = False

            # Capture until speech has been heard and then ends, or timeout.
            # The loop only does cheap work: Vosk runs ~2x slower than real time on a
            # Pi 3B+, and running it here made the mic buffer overflow and drop audio.
            recognized_text = ""

            chunk_44k = 4096
            chunk_seconds = chunk_44k / self.capture_rate
            resampler = StreamResampler(self.capture_rate, self.hardware_rate)
            highpass = HighPass(self.hardware_rate)
            peak = 0
            resampled_chunks = []
            raw_chunks = []  # debug: keep raw capture so it can be replayed offline
            noise_floor = float('inf')
            speech_blocks = 0
            last_voice_time = 0.0  # in audio time (seconds of audio captured)
            silence_after_text = 1.2

            while len(raw_chunks) * chunk_seconds < max_timeout and not self.stop_listening:
                data = stream.read(chunk_44k, exception_on_overflow=False)
                raw_chunks.append(data)
                audio_time = len(raw_chunks) * chunk_seconds

                mono = stereo_to_mono(data) if channels == 2 else data
                samples = np.frombuffer(mono, dtype=np.int16)
                resampled = highpass.process(resampler.process(samples))
                resampled_chunks.append(resampled)
                peak = max(peak, int(np.abs(samples).max()))

                # Energy-based end-of-speech: speech must rise above the noise floor,
                # then stay below it for silence_after_text seconds.
                block_rms = float(np.sqrt(np.mean(resampled.astype(np.float64) ** 2)))
                noise_floor = min(noise_floor, max(block_rms, 50.0))
                if block_rms > max(3 * noise_floor, 350.0):
                    speech_blocks += 1
                    last_voice_time = audio_time
                if speech_blocks >= 3 and audio_time - last_voice_time > silence_after_text:
                    break

            if self.stop_listening:
                print("Listening cancelled (handset hung up)")
            elif speech_blocks < 3:
                print("No speech detected above the noise floor")
            else:
                recognized_text = self._transcribe_deepgram(np.concatenate(resampled_chunks))
                if recognized_text is None:
                    print("Transcription failed")
                else:
                    print(f"Deepgram heard: '{recognized_text}'")

            try:
                import wave
                with wave.open('/tmp/last_request.wav', 'wb') as w:
                    w.setnchannels(channels)
                    w.setsampwidth(2)
                    w.setframerate(self.capture_rate)
                    w.writeframes(b''.join(raw_chunks))
            except Exception as e:
                print(f"Could not save debug recording: {e}")

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
