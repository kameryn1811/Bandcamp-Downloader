<div align="center">

# <img src="images/icon-title.png" width="32" height="32" alt="Icon"> Bandcamp Downloader GUI

[![Download](images/download-button.png)](https://github.com/kameryn1811/Bandcamp-Downloader/releases/latest)

</div>

A Python-based GUI application for downloading Bandcamp albums with full metadata and cover art support.

## Why This Exists

This was created as an interim solution for users experiencing issues with [Otiel's BandcampDownloader](https://github.com/Otiel/BandcampDownloader). While we wait for official updates and fixes to that excellent C# application, this Python-based alternative provides a working solution.

## What It Does

Bandcamp Downloader GUI provides a simple way to download the freely available 128 kbps MP3 streams from Bandcamp albums, tracks, and artist pages. It automatically organizes files, embeds metadata, and handles cover art.

![Main Interface](images/screenshot-main.png) 
*The main download interface with album art preview and settings panel*

## Key Features

* **Auto-Setup** - Checks dependencies and guides you through installation
* **Simple GUI** - No command-line knowledge required
* **Organization** - Choose from 5 folder structures (Artist/Album is default)
* **Metadata** - Automatically tags files with artist, album, track number, and date
* **Cover Art** - Embeds artwork into files and optionally saves separate copies
* **Format Flexibility** - Output as MP3, FLAC, OGG, or WAV (note: all converted from 128 kbps source)
* **Track Numbering** - Optional automatic track number prefixes
* **Playlist Generation** - Create .m3u playlists automatically

## Quick Start

**Prerequisites**

1. **Python 3.11 or higher**
   * Download: https://www.python.org/downloads/
   * ⚠️ **Must check "Add Python to PATH" during installation**

2. **ffmpeg.exe**
   * Download: https://www.gyan.dev/ffmpeg/builds/
   * Get `ffmpeg-release-essentials.zip`
   * Extract `ffmpeg.exe` from the `bin` folder
   * Place it in the same folder as `bandcamp_dl_gui.py`

**Installation**

1. Download the [Latest Release](https://github.com/kameryn1811/Bandcamp-Downloader/releases/latest) and extract it into a folder
2. Place `ffmpeg.exe` in the folder
3. Double-click `Bandcamp Downloader GUI.bat` (optionally create a shortcut to this file and pin it to your startmenu, taskbar, desktop, etc)
4. The app will check for and help install any missing dependencies

**Supported URLs**

* Album pages: `https://[artist].bandcamp.com/album/[album]`
* Track pages: `https://[artist].bandcamp.com/track/[track]`
* Artist pages: `https://[artist].bandcamp.com` (downloads all available albums)

## Troubleshooting

**"Python not found"**
- Reinstall Python and ensure "Add Python to PATH" is checked
- Or manually add Python to your system PATH

**"ffmpeg.exe not found"**
- Download from https://www.gyan.dev/ffmpeg/builds/
- Place `ffmpeg.exe` in the same folder as the script

**"No files downloaded"**
- Album may require purchase
- Some content is only available after buying
- Verify the album streams for free on Bandcamp

**Album art not displaying in Interface**
- Install Pillow: `python -m pip install Pillow`
- The app will prompt to install it automatically

## Audio Quality & Artist Support

**⚠️ About Quality**

This tool downloads the **128 kbps MP3 streams** that Bandcamp makes available for free listening. These are the same quality files you hear when streaming on the website.

**Converting to FLAC, OGG, or WAV does NOT improve quality** - it only changes the file format. The source remains 128 kbps.

**🎵 Support the Artists**

For high-quality audio (FLAC, 320 kbps MP3, etc.), **please purchase albums directly from Bandcamp**. 

Bandcamp is one of the best platforms for independent artists:
* Artists receive a larger share of revenue than other platforms
* You get high-quality downloads with your purchase
* You're directly supporting the musicians you love

**If you enjoy the music, please support the artists by purchasing their work!**

## Credits & Inspiration

This project exists thanks to [Otiel's BandcampDownloader](https://github.com/Otiel/BandcampDownloader). This Python version was created to provide a working alternative while we await updates to the original project.

**Thank you, Otiel, for the inspiration and for building such a useful tool!**

## Legal & Ethical Use

This tool is designed for:
* Personal use of music you own or have permission to download
* Accessing freely available stream files
* Building a local library of music you've purchased

Please respect copyright laws and Bandcamp's terms of service. Support artists by purchasing music when possible.

## Disclaimer

This software is provided as-is for educational and personal use. The developers are not responsible for misuse. Please use responsibly and support the artists whose music you enjoy.
