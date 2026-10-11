#!/usr/bin/env python3
"""
Discover Chromecast devices on the network.
"""

import pychromecast
import time

print("Searching for Chromecast devices...")
print("(This may take a few seconds)\n")

# Discover devices
chromecasts, browser = pychromecast.get_chromecasts()

if not chromecasts:
    print("No Chromecast devices found.")
    print("Make sure your Chromecast is:")
    print("  - Powered on")
    print("  - Connected to the same network as this Raspberry Pi")
else:
    print(f"Found {len(chromecasts)} Chromecast device(s):\n")

    for i, cast in enumerate(chromecasts, 1):
        cast.wait()
        print(f"{i}. Name: '{cast.name}'")
        print(f"   Model: {cast.model_name}")
        print(f"   URI: {cast.uri}")
        print()

# Clean up
pychromecast.discovery.stop_discovery(browser)
