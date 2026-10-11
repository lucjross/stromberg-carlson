# Stromberg-Carlson Jukebox

A vintage rotary phone turned into a voice-controlled jukebox. Pick up the handset,
dial **0** for the operator, say the song you want, and it plays on a Chromecast-compatible
speaker (built and tested with a WiiM Ultra).

Runs on a Raspberry Pi 3B+ wired into the phone's dial and hook switch.

## How it works

1. **Handset lifted** → the Pi plays a dial tone.
2. **Dial 0** → "What would you like to hear?"
3. **You speak** → the Pi records from the handset mic and ends the recording when you stop talking.
   The clip is sent to [Deepgram](https://deepgram.com) for speech-to-text.
4. **Search** → the text is searched on YouTube Music (`ytmusicapi`).
5. **Play** → the audio stream is extracted with `yt-dlp` and cast to the speaker with `pychromecast`.
   The phone announces "Playing *title* by *artist*" and returns to dial tone.

### Dial codes (at the dial tone)

| Digit | Action |
|-------|--------|
| 0 | Operator: request a song by voice |
| 8 | Stop the music |
| 6 | Shut down the Pi ("Self-destruct initiated") — requires passwordless `sudo shutdown` |

## Hardware

- Raspberry Pi (3B+ works) with a recent Debian-based OS
- A rotary phone: dial pulse contacts, the dial's off-normal switch, and the hook switch
- A USB sound card with microphone input and a speaker output wired to the handset
  (a Creative Sound Blaster Play! 3 is used here)
- A Chromecast-compatible audio device on the same network

GPIO (BCM numbering, internal pull-ups, switches pull to ground):

| Signal | Pin |
|--------|-----|
| Dial pulse contacts | 17 |
| Dial off-normal ("ready") switch | 27 |
| Hook switch | 22 |

Change these in `rotary_phone_voice_jukebox.py` if you wire it differently.

## Setup

```bash
git clone https://github.com/lucjross/stromberg-carlson.git
cd stromberg-carlson
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```
CHROMECAST_NAME=          # friendly name of your speaker; blank = first one found
DEEPGRAM_API_KEY=         # from https://console.deepgram.com
```

`python3 discover_chromecasts.py` lists the Chromecast devices it can see.
`python3 test_mic.py` helps check the microphone.

You also need `paplay` (PulseAudio/PipeWire tools) for the dial tone and speech, and an
audio output sink. The sink name is set in `audio_player.py`; change it to match your
sound card (`pactl list short sinks`).

Run it:

```bash
python3 rotary_phone_voice_jukebox.py
```

### Run at boot (systemd user service)

`~/.config/systemd/user/rotary-jukebox.service`:

```ini
[Unit]
Description=Rotary Phone Voice Jukebox
After=sound.target

[Service]
Type=simple
WorkingDirectory=/home/pi/stromberg-carlson
ExecStart=/home/pi/stromberg-carlson/venv/bin/python3 /home/pi/stromberg-carlson/rotary_phone_voice_jukebox.py
Restart=on-failure
RestartSec=10
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now rotary-jukebox
loginctl enable-linger "$USER"     # start at boot without logging in
journalctl _SYSTEMD_USER_UNIT=rotary-jukebox.service -f
```

## Notes and gotchas

- **Your speech leaves the device.** Recorded requests are sent to Deepgram for transcription.
- **Keep yt-dlp current.** YouTube changes often; when playback silently fails (the Chromecast
  goes `IDLE` with an error), run `pip install -U yt-dlp`. The app asks for audio-only AAC
  and reports failure if the speaker doesn't start playing.
- **Mains hum.** Some phone mic wiring picks up 60 Hz hum; the recorder high-pass filters it
  before transcription.
- **Pi 3B+ performance.** Heavy per-chunk processing during recording can overflow the mic
  buffer and drop audio, which is why transcription runs on the finished clip instead of live.
- **YouTube Music is unauthenticated** (public search only).

## License

[MIT](LICENSE)
