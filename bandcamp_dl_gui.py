"""
------------------------------------------------------------
Bandcamp Album Downloader - GUI Version
------------------------------------------------------------
Modern GUI for downloading Bandcamp albums with embedded metadata.

Features:
- Downloads full albums with proper metadata (title, artist, album, track number, date)
- Embeds album cover art into each MP3 file
- High-quality 320 kbps MP3 output
- 5 folder structure options
- Real-time progress display

Requirements:
- Python 3.11+
- yt-dlp (pip install -U yt-dlp)
- ffmpeg.exe in same folder as script
"""

# ============================================================================
# DEVELOPER SETTINGS
# ============================================================================
# Set to True to show "Skip post-processing" option in the UI (for testing)
SHOW_SKIP_POSTPROCESSING_OPTION = False
# ============================================================================

import sys
import subprocess
import webbrowser
import threading
import ctypes
import os
import tempfile
import hashlib
import time
import json
from pathlib import Path
from tkinter import (
    Tk, ttk, StringVar, BooleanVar, messagebox, scrolledtext, filedialog, W, E, N, S, END, WORD, BOTH,
    Frame, Label, Canvas, Checkbutton
)

# yt-dlp will be imported after checking if it's installed
try:
    import yt_dlp
except ImportError:
    yt_dlp = None


class ThinProgressBar:
    """Custom thin progress bar using Canvas for precise height control."""
    def __init__(self, parent, height=3, bg_color='#1E1E1E', fg_color='#2dacd5'):
        self.height = height
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.value = 0
        self.maximum = 100
        self.parent = parent
        
        # Create canvas with minimal height, no fixed width (will expand with grid)
        self.canvas = Canvas(parent, height=height, bg=bg_color, 
                            highlightthickness=0, borderwidth=0)
        
        # Bind to configure event to update when canvas resizes
        self.canvas.bind('<Configure>', self._on_resize)
        self._width = 1  # Initial width, will be updated on resize
        
        # Draw the background (trough) - will be updated on resize
        self.trough = self.canvas.create_rectangle(0, 0, 1, height, 
                                                   fill=bg_color, outline='')
        
        # Draw the progress bar (initially 0)
        self.bar = self.canvas.create_rectangle(0, 0, 0, height, 
                                                 fill=fg_color, outline='')
    
    def _on_resize(self, event=None):
        """Handle canvas resize to update width and redraw."""
        if event:
            self._width = event.width
            # Update trough to fill new width
            self.canvas.coords(self.trough, 0, 0, self._width, self.height)
            # Update progress bar
            self._update()
    
    def config(self, **kwargs):
        """Configure the progress bar (compatible with ttk.Progressbar interface)."""
        if 'value' in kwargs:
            self.value = max(0, min(kwargs['value'], self.maximum))
            self._update()
        if 'maximum' in kwargs:
            self.maximum = kwargs['maximum']
            self._update()
        if 'mode' in kwargs:
            # Ignore mode for now (we only support determinate)
            pass
    
    def _update(self):
        """Update the visual representation of the progress bar."""
        # Get current canvas width (or use stored width)
        try:
            current_width = self.canvas.winfo_width()
            if current_width > 1:
                self._width = current_width
        except:
            pass
        
        if self.maximum > 0 and self._width > 0:
            progress_width = int((self.value / self.maximum) * self._width)
        else:
            progress_width = 0
        
        # Update the progress bar rectangle
        self.canvas.coords(self.bar, 0, 0, progress_width, self.height)
    
    def grid(self, **kwargs):
        """Grid the canvas (compatible with ttk.Progressbar interface)."""
        self.canvas.grid(**kwargs)
    
    def grid_remove(self):
        """Remove from grid (compatible with ttk.Progressbar interface)."""
        self.canvas.grid_remove()
    
    def winfo_viewable(self):
        """Check if widget is viewable (compatible with ttk.Progressbar interface)."""
        try:
            return self.canvas.winfo_viewable()
        except:
            return False


class BandcampDownloaderGUI:
    # Constants for better maintainability
    FORMAT_EXTENSIONS = {
        "mp3": [".mp3"],
        "flac": [".flac"],
        "ogg": [".ogg", ".oga"],
        "wav": [".wav"],
    }
    THUMBNAIL_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']
    FOLDER_STRUCTURES = {
        "1": "Root directory",
        "2": "Album folder",
        "3": "Artist folder",
        "4": "Artist / Album",
        "5": "Album / Artist",
    }
    DEFAULT_STRUCTURE = "4"
    DEFAULT_FORMAT = "mp3 (128kbps)"
    DEFAULT_NUMBERING = "None"
    
    def _extract_format(self, format_val):
        """Extract base format from display value (e.g., 'mp3 (128kbps)' -> 'mp3')."""
        if format_val.startswith("mp3"):
            return "mp3"
        return format_val
    
    def __init__(self, root):
        self.root = root
        self.root.title(" Bandcamp Downloader")
        
        # Minimize console window immediately (before any other operations)
        self._minimize_console_immediately()
        
        # Center the window on screen
        window_width = 520
        window_height = 580
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        center_x = int(screen_width / 2 - window_width / 2)
        center_y = int(screen_height / 2 - window_height / 2)
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        
        self.root.resizable(False, False)
        
        # Get script directory first (needed for icon path)
        self.script_dir = Path(__file__).resolve().parent
        self.ffmpeg_path = None
        self.ydl = None
        
        # Variables
        self.url_var = StringVar()
        self.path_var = StringVar()
        self.folder_structure_var = StringVar(value=self.get_default_preference())
        self.format_var = StringVar(value=self.load_saved_format())
        self.numbering_var = StringVar(value=self.load_saved_numbering())
        self.skip_postprocessing_var = BooleanVar(value=self.load_saved_skip_postprocessing())
        self.create_playlist_var = BooleanVar(value=self.load_saved_create_playlist())
        self.download_cover_art_var = BooleanVar(value=self.load_saved_download_cover_art())
        
        # Store metadata for preview
        self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None}
        self.url_check_timer = None  # For debouncing URL changes
        self.album_art_image = None  # Store reference to prevent garbage collection
        self.album_art_fetching = False  # Flag to prevent multiple simultaneous fetches
        self.current_thumbnail_url = None  # Track current thumbnail to avoid re-downloading
        self.album_art_visible = True  # Track album art panel visibility
        
        # Download control
        self.download_thread = None
        self.is_cancelling = False
        self.ydl_instance = None  # Store yt-dlp instance for cancellation
        
        # Check dependencies first
        if not self.check_dependencies():
            self.root.destroy()
            return
        
        self.setup_dark_mode()
        self.setup_ui()
        self.load_saved_path()
        self.load_saved_album_art_state()
        self.update_preview()
        # Show format warnings if selected on startup
        format_val = self.format_var.get()
        base_format = self._extract_format(format_val)
        if base_format in ["flac", "ogg", "wav"] and hasattr(self, 'format_conversion_warning_label'):
            self.format_conversion_warning_label.grid()
        if base_format == "ogg" and hasattr(self, 'ogg_warning_label'):
            self.ogg_warning_label.grid()
        elif base_format == "wav" and hasattr(self, 'wav_warning_label'):
            self.wav_warning_label.grid()
        
        # Defer icon setting to after UI is shown (non-critical for startup speed)
        self.root.after_idle(self.set_icon)
        self.root.after(100, self.set_icon)
        self.root.after(1000, self.set_icon)
        
        # Bring window to front on startup
        self.root.after_idle(self._bring_to_front)
        
        # Close console when GUI closes
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_dark_mode(self):
        """Configure dark mode theme."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Modern dark color scheme - all backgrounds consistently dark
        bg_color = '#1E1E1E'  # Very dark background (consistent everywhere)
        fg_color = '#D4D4D4'  # Soft light text
        select_bg = '#252526'  # Slightly lighter for inputs only
        select_fg = '#FFFFFF'
        entry_bg = '#252526'  # Dark input background
        entry_fg = '#CCCCCC'  # Light input text
        border_color = '#3E3E42'  # Subtle borders
        accent_color = '#007ACC'  # Blue accent (more modern than green)
        success_color = '#2dacd5'  # Bandcamp blue for success/preview
        hover_bg = '#3E3E42'  # Hover state
        
        # Configure root background
        self.root.configure(bg=bg_color)
        
        # Configure styles - all backgrounds use bg_color
        style.configure('TFrame', background=bg_color, borderwidth=0)
        style.configure('TLabel', background=bg_color, foreground=fg_color)
        # Create a custom style for LabelFrame that forces dark background
        style.configure('TLabelFrame', background=bg_color, foreground=fg_color, 
                        bordercolor=border_color, borderwidth=1, relief='flat')
        style.configure('TLabelFrame.Label', background=bg_color, foreground=fg_color)
        # Ensure LabelFrame interior is also dark - map all states
        style.map('TLabelFrame',
                 background=[('active', bg_color), ('!active', bg_color), ('focus', bg_color), ('!focus', bg_color)],
                 bordercolor=[('active', border_color), ('!active', border_color), ('focus', border_color), ('!focus', border_color)])
        
        # Also configure the internal frame style that LabelFrame uses
        # The internal frame is typically styled as TFrame
        style.configure('TFrame', background=bg_color)
        style.configure('TEntry', fieldbackground=entry_bg, foreground=entry_fg, 
                       borderwidth=1, bordercolor=border_color, relief='flat',
                       insertcolor=fg_color)
        style.map('TEntry', 
                  bordercolor=[('focus', accent_color)],
                  lightcolor=[('focus', accent_color)],
                  darkcolor=[('focus', accent_color)])
        style.configure('TButton', background=select_bg, foreground=fg_color,
                       borderwidth=1, bordercolor=border_color, relief='flat',
                       padding=(10, 5))
        style.map('TButton', 
                 background=[('active', hover_bg), ('pressed', bg_color)],
                 bordercolor=[('active', border_color), ('pressed', border_color)])
        
        # Special style for download button with Bandcamp blue accent
        # Default is darker, hover is brighter/more prominent
        style.configure('Download.TButton', background='#2599b8', foreground='#FFFFFF',
                       borderwidth=2, bordercolor='#2599b8', relief='flat',
                       padding=(15, 8), font=("Segoe UI", 10, "bold"), width=20)
        style.map('Download.TButton',
                 background=[('active', success_color), ('pressed', '#1d7a95')],
                 bordercolor=[('active', success_color), ('pressed', '#1d7a95')])
        
        # Cancel button style - matches download button size but keeps muted default colors
        # Slightly wider to match visual size of download button
        style.configure('Cancel.TButton', background=select_bg, foreground=fg_color,
                       borderwidth=1, bordercolor=border_color, relief='flat',
                       padding=(15, 10), width=23)  # Slightly wider than download button to match visual size
        style.map('Cancel.TButton',
                 background=[('active', hover_bg), ('pressed', bg_color)],
                 bordercolor=[('active', border_color), ('pressed', border_color)])
        style.configure('TRadiobutton', background=bg_color, foreground=fg_color,
                        focuscolor=bg_color)
        style.map('TRadiobutton', 
                 background=[('active', bg_color), ('selected', bg_color)],
                 indicatorcolor=[('selected', accent_color)])
        style.configure('TCombobox', fieldbackground=entry_bg, foreground=entry_fg,
                        borderwidth=1, bordercolor=border_color, relief='flat',
                        arrowcolor=fg_color)
        style.map('TCombobox',
                 fieldbackground=[('readonly', entry_bg)],
                 bordercolor=[('focus', accent_color), ('!focus', border_color)],
                 arrowcolor=[('active', accent_color), ('!active', fg_color)])
        # Progress bar uses Bandcamp blue for a friendly, success-oriented feel
        style.configure('TProgressbar', background=success_color, troughcolor=bg_color,
                        borderwidth=0, lightcolor=success_color, darkcolor=success_color)
        
        # Overall progress bar style (thinner, more subtle color - gray/white)
        # Try to make it very thin (3px) - thickness may not work on all platforms
        try:
            style.configure('Overall.TProgressbar', 
                            background='#808080',  # Gray - visible but subtle
                            troughcolor=bg_color,
                            borderwidth=0,
                            lightcolor='#A0A0A0',  # Lighter gray for highlight
                            darkcolor='#606060',  # Darker gray for shadow
                            relief='flat',
                            thickness=3)  # Try to make it very thin (3px)
        except Exception:
            # Fallback: use same style as regular progress bar if custom style fails
            try:
                style.configure('Overall.TProgressbar', 
                                background='#808080',
                                troughcolor=bg_color,
                                borderwidth=0,
                                thickness=3)
            except Exception:
                # If thickness option not supported, just use basic style
                style.configure('Overall.TProgressbar', 
                                background='#808080',
                                troughcolor=bg_color,
                                borderwidth=0)
        
        # Configure Scrollbar for dark theme
        style.configure('TScrollbar', background=bg_color, troughcolor=bg_color,
                       bordercolor=bg_color, arrowcolor=fg_color, darkcolor=bg_color,
                       lightcolor=bg_color)
        style.map('TScrollbar',
                 background=[('active', hover_bg)],
                 arrowcolor=[('active', fg_color), ('!active', border_color)])
    
    def set_icon(self):
        """Set the custom icon for the window from icon.ico."""
        if not hasattr(self, 'root') or not self.root:
            return
        
        icon_path = self.script_dir / "icon.ico"
        
        try:
            if icon_path.exists():
                icon_path_str = str(icon_path)
                
                # Method 1: iconbitmap - sets title bar icon
                try:
                    self.root.iconbitmap(default=icon_path_str)
                except:
                    pass
                
                # Method 2: iconphoto - sets taskbar icon (more reliable)
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(icon_path)
                    photo = ImageTk.PhotoImage(img)
                    # Use True to set as default icon (affects taskbar)
                    self.root.iconphoto(True, photo)
                    # Keep a reference to prevent garbage collection
                    if not hasattr(self, '_icon_ref'):
                        self._icon_ref = photo
                except:
                    pass
                
                # Method 3: Windows API - force set taskbar icon (for batch-launched scripts)
                if sys.platform == 'win32':
                    try:
                        import ctypes
                        from ctypes import wintypes
                        
                        # Force window update to ensure it's ready
                        self.root.update_idletasks()
                        
                        # Get window handle - winfo_id() returns the HWND on Windows
                        hwnd = self.root.winfo_id()
                        if hwnd:
                            # Constants
                            LR_LOADFROMFILE = 0x0010
                            IMAGE_ICON = 1
                            WM_SETICON = 0x0080
                            ICON_SMALL = 0
                            ICON_BIG = 1
                            
                            # Load the icon from file
                            icon_handle = ctypes.windll.user32.LoadImageW(
                                None,  # hInst
                                icon_path_str,
                                IMAGE_ICON,
                                0,  # cx (0 = default size)
                                0,  # cy (0 = default size)
                                LR_LOADFROMFILE
                            )
                            
                            if icon_handle:
                                # SendMessageW expects HWND as void pointer
                                # On Windows, winfo_id() returns the actual HWND
                                # Use ctypes.windll.user32.SendMessageW with proper types
                                SendMessageW = ctypes.windll.user32.SendMessageW
                                SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                                SendMessageW.restype = wintypes.LPARAM
                                
                                SendMessageW(hwnd, WM_SETICON, ICON_SMALL, icon_handle)
                                SendMessageW(hwnd, WM_SETICON, ICON_BIG, icon_handle)
                    except Exception:
                        # Silently fail - other methods should still work
                        pass
        except Exception:
            # If icon setting fails, just continue without icon
            pass
    
    def _get_settings_file(self):
        """Get the path to the settings file."""
        return self.script_dir / "settings.json"
    
    def _migrate_old_settings(self):
        """Migrate old individual setting files to unified settings.json."""
        settings = {}
        migrated = False
        
        # Migrate folder structure
        old_file = self.script_dir / "folder_structure_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r') as f:
                    value = f.read().strip()
                    if value in ["1", "2", "3", "4", "5"]:
                        settings["folder_structure"] = value
                        migrated = True
            except:
                pass
        
        # Migrate download path
        old_file = self.script_dir / "last_download_path.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r') as f:
                    path = f.read().strip()
                    if Path(path).exists():
                        settings["download_path"] = path
                        migrated = True
            except:
                pass
        
        # Migrate audio format
        old_file = self.script_dir / "audio_format_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r') as f:
                    value = f.read().strip()
                    if value in ["mp3", "flac", "ogg", "wav"]:
                        settings["audio_format"] = value
                        migrated = True
            except:
                pass
        
        # Migrate audio quality
        old_file = self.script_dir / "audio_quality_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r') as f:
                    value = f.read().strip()
                    if value in ["128 kbps", "192 kbps", "256 kbps", "320 kbps", "lossless", "best"]:
                        settings["audio_quality"] = value
                        migrated = True
            except:
                pass
        
        # Migrate album art visibility
        old_file = self.script_dir / "album_art_visible.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r') as f:
                    value = f.read().strip().lower()
                    settings["album_art_visible"] = (value == "true")
                    migrated = True
            except:
                pass
        
        # Save migrated settings and clean up old files
        if migrated:
            self._save_settings(settings)
            # Optionally delete old files (commented out to be safe)
            # for old_file in [
            #     "folder_structure_default.txt",
            #     "last_download_path.txt",
            #     "audio_format_default.txt",
            #     "audio_quality_default.txt",
            #     "album_art_visible.txt"
            # ]:
            #     try:
            #         (self.script_dir / old_file).unlink()
            #     except:
            #         pass
    
    def _load_settings(self):
        """Load all settings from settings.json file."""
        settings_file = self._get_settings_file()
        settings = {}
        
        # Load from unified settings file
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except:
                pass
        else:
            # If settings.json doesn't exist, try to migrate old settings
            self._migrate_old_settings()
            # Try loading again after migration
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except:
                    pass
        
        return settings
    
    def _save_settings(self, settings=None):
        """Save all settings to settings.json file."""
        if settings is None:
            # Get current settings from UI
            settings = {
                "folder_structure": self._extract_structure_choice(self.folder_structure_var.get()) or self.DEFAULT_STRUCTURE,
                "download_path": self.path_var.get(),
                "audio_format": self.format_var.get(),
                "track_numbering": self.numbering_var.get(),
                "skip_postprocessing": self.skip_postprocessing_var.get(),
                "create_playlist": self.create_playlist_var.get(),
                "download_cover_art": self.download_cover_art_var.get(),
                "album_art_visible": self.album_art_visible
            }
        
        settings_file = self._get_settings_file()
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def get_default_preference(self):
        """Load saved folder structure preference, default to 4 if not found."""
        settings = self._load_settings()
        folder_structure = settings.get("folder_structure", self.DEFAULT_STRUCTURE)
        if folder_structure in ["1", "2", "3", "4", "5"]:
            return folder_structure
        return self.DEFAULT_STRUCTURE
    
    def save_default_preference(self, choice):
        """Save folder structure preference."""
        self._save_settings()
        return True
    
    def load_saved_path(self):
        """Load last used download path."""
        settings = self._load_settings()
        path = settings.get("download_path", "")
        if path and Path(path).exists():
            self.path_var.set(path)
    
    def save_path(self):
        """Save download path for next time."""
        self._save_settings()
    
    def load_saved_format(self):
        """Load saved audio format preference, default to mp3 (128kbps) if not found."""
        settings = self._load_settings()
        format_val = settings.get("audio_format", self.DEFAULT_FORMAT)
        # Support both old format ("mp3") and new format ("mp3 (128kbps)")
        if format_val in ["mp3", "mp3 (128kbps)", "flac", "ogg", "wav"]:
            # Convert old "mp3" to new format for consistency
            if format_val == "mp3":
                return "mp3 (128kbps)"
            return format_val
        return self.DEFAULT_FORMAT
    
    def save_format(self):
        """Save audio format preference."""
        self._save_settings()
    
    def load_saved_album_art_state(self):
        """Load saved album art visibility state, default to visible if not found."""
        settings = self._load_settings()
        self.album_art_visible = settings.get("album_art_visible", True)
        # Apply state after UI is set up
        if not self.album_art_visible:
            self.root.after(100, self._apply_saved_album_art_state)
    
    def _apply_saved_album_art_state(self):
        """Apply saved album art state after UI is set up."""
        if not self.album_art_visible:
            if hasattr(self, 'album_art_frame'):
                self.album_art_frame.grid_remove()
            if hasattr(self, 'settings_frame'):
                self.settings_frame.grid_configure(columnspan=3)
            if hasattr(self, 'show_album_art_btn'):
                self.show_album_art_btn.grid()
    
    def save_album_art_state(self):
        """Save album art visibility state."""
        self._save_settings()
    
    def load_saved_numbering(self):
        """Load saved track numbering preference, default to None if not found."""
        settings = self._load_settings()
        numbering_val = settings.get("track_numbering", self.DEFAULT_NUMBERING)
        valid_options = ["None", "01. Track", "1. Track", "01 - Track", "1 - Track"]
        if numbering_val in valid_options:
            return numbering_val
        return self.DEFAULT_NUMBERING
    
    def save_numbering(self):
        """Save track numbering preference."""
        self._save_settings()
    
    def load_saved_skip_postprocessing(self):
        """Load saved skip post-processing preference, default to False if not found."""
        settings = self._load_settings()
        return settings.get("skip_postprocessing", False)
    
    def save_skip_postprocessing(self):
        """Save skip post-processing preference."""
        self._save_settings()
    
    def on_skip_postprocessing_change(self):
        """Handle skip post-processing checkbox change."""
        self.save_skip_postprocessing()
    
    def load_saved_create_playlist(self):
        """Load saved create playlist preference, default to False if not found."""
        settings = self._load_settings()
        return settings.get("create_playlist", False)
    
    def save_create_playlist(self):
        """Save create playlist preference."""
        self._save_settings()
    
    def on_create_playlist_change(self):
        """Handle create playlist checkbox change."""
        self.save_create_playlist()
    
    def load_saved_download_cover_art(self):
        """Load saved download cover art preference, default to False if not found."""
        settings = self._load_settings()
        return settings.get("download_cover_art", False)
    
    def save_download_cover_art(self):
        """Save download cover art preference."""
        self._save_settings()
    
    def on_download_cover_art_change(self):
        """Handle download cover art checkbox change."""
        self.save_download_cover_art()
    
    def check_dependencies(self):
        """Check Python version, yt-dlp, and ffmpeg."""
        # Check Python version
        if sys.version_info < (3, 11):
            messagebox.showerror(
                "Python Version Error",
                f"Python 3.11+ is required!\n\nCurrent version: {sys.version}\n\n"
                "Please update Python from: https://www.python.org/downloads/"
            )
            webbrowser.open("https://www.python.org/downloads/")
            return False
        
        # Check yt-dlp
        global yt_dlp
        try:
            if yt_dlp is None:
                import yt_dlp
        except ImportError:
            response = messagebox.askyesno(
                "yt-dlp Not Found",
                "yt-dlp is not installed!\n\nWould you like to install it automatically?"
            )
            if response:
                self.install_ytdlp()
            else:
                messagebox.showinfo(
                    "Installation Required",
                    "Please install yt-dlp manually:\n\n"
                    "python -m pip install -U yt-dlp\n\n"
                    "Then restart this application."
                )
                webbrowser.open("https://github.com/yt-dlp/yt-dlp#installation")
                return False
        
        # Check ffmpeg
        ffmpeg_path = self.script_dir / "ffmpeg.exe"
        if not ffmpeg_path.exists():
            response = messagebox.askyesno(
                "ffmpeg.exe Not Found",
                f"ffmpeg.exe not found in:\n{self.script_dir}\n\n"
                "Would you like to open the download page?"
            )
            if response:
                webbrowser.open("https://www.gyan.dev/ffmpeg/builds/")
            messagebox.showinfo(
                "ffmpeg Required",
                "Please download ffmpeg:\n\n"
                "1. Visit: https://www.gyan.dev/ffmpeg/builds/\n"
                "2. Download 'ffmpeg-release-essentials.zip'\n"
                "3. Extract and copy 'ffmpeg.exe' from the 'bin' folder\n"
                "4. Place it in the same folder as this script\n\n"
                "Then restart this application."
            )
            return False
        
        self.ffmpeg_path = ffmpeg_path
        
        # Check PIL (optional - only needed for album art display)
        try:
            import PIL
        except ImportError:
            # PIL is optional, so we don't block startup, but offer to install
            response = messagebox.askyesno(
                "Pillow (PIL) Not Found",
                "Pillow is not installed. It's required for album art preview.\n\n"
                "Would you like to install it automatically?\n\n"
                "(You can skip this and install later if you don't need album art preview.)"
            )
            if response:
                self.install_pillow()
        
        return True
    
    def install_pillow(self):
        """Install Pillow in a separate thread."""
        def install():
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "Pillow"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                # Try to import after installation
                import importlib
                if 'PIL' in sys.modules:
                    del sys.modules['PIL']
                import PIL
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    "Pillow installed successfully!\n\n"
                    "Album art preview will now work.\n\n"
                    "You may need to restart the application for it to take full effect."
                ))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Installation Failed",
                    f"Failed to install Pillow automatically.\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please install manually:\n"
                    "python -m pip install Pillow"
                ))
        
        threading.Thread(target=install, daemon=True).start()
        messagebox.showinfo(
            "Installing",
            "Installing Pillow...\n\nThis may take a moment.\n\n"
            "You'll be notified when it's complete."
        )
    
    def install_ytdlp(self):
        """Install yt-dlp in a separate thread."""
        global yt_dlp
        def install():
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                # Try to import after installation
                import importlib
                import sys
                if 'yt_dlp' in sys.modules:
                    del sys.modules['yt_dlp']
                import yt_dlp
                globals()['yt_dlp'] = yt_dlp
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success",
                    "yt-dlp installed successfully!\n\nPlease restart this application."
                ))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Installation Failed",
                    f"Failed to install yt-dlp automatically.\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please install manually:\n"
                    "python -m pip install -U yt-dlp"
                ))
        
        threading.Thread(target=install, daemon=True).start()
        messagebox.showinfo(
            "Installing",
            "Installing yt-dlp...\n\nThis may take a moment.\n\n"
            "You'll be notified when it's complete."
        )
    
    def setup_ui(self):
        """Create the GUI interface."""
        # Main container with compact padding
        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # URL input - compact
        ttk.Label(main_frame, text="Album URL:", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky=W, pady=2
        )
        url_entry = ttk.Entry(main_frame, textvariable=self.url_var, width=45, font=("Segoe UI", 9))
        url_entry.grid(row=0, column=1, columnspan=2, sticky=(W, E), pady=2, padx=(8, 0))
        
        # Bind paste events for instant detection (no debounce for paste)
        url_entry.bind('<Control-v>', lambda e: self.root.after(10, self._check_url))
        url_entry.bind('<Shift-Insert>', lambda e: self.root.after(10, self._check_url))
        url_entry.bind('<Button-2>', lambda e: self.root.after(10, self._check_url))  # Middle mouse button paste
        # Right-click paste support
        url_entry.bind('<Button-3>', self._handle_right_click_paste)  # Right mouse button
        # Key release with shorter debounce for typing
        url_entry.bind('<KeyRelease>', lambda e: self.on_url_change())
        
        # Download path - compact
        ttk.Label(main_frame, text="Download Path:", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky=W, pady=2
        )
        path_entry = ttk.Entry(main_frame, textvariable=self.path_var, width=35, font=("Segoe UI", 9))
        path_entry.grid(row=1, column=1, sticky=(W, E), pady=2, padx=(8, 0))
        browse_btn = ttk.Button(main_frame, text="Browse", command=self.browse_folder)
        browse_btn.grid(row=1, column=2, padx=(4, 0), pady=2)
        
        # Bind path changes to update preview
        self.path_var.trace_add('write', lambda *args: self.update_preview())
        self.folder_structure_var.trace_add('write', lambda *args: self.update_preview())
        self.url_var.trace_add('write', lambda *args: self.on_url_change())
        
        # Settings section - reduced width to make room for album art panel
        self.settings_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.settings_frame.grid(row=2, column=0, columnspan=2, sticky=(W, E, N), pady=6, padx=0)
        self.settings_frame.grid_propagate(False)
        self.settings_frame.config(height=160)  # Fixed height with even padding
        
        # Label for the frame with show album art button (when hidden)
        settings_header = Frame(self.settings_frame, bg='#1E1E1E')
        settings_header.grid(row=0, column=0, sticky=(W, E), padx=6, pady=(4, 4))
        settings_header.columnconfigure(0, weight=1)
        
        settings_label = Label(settings_header, text="Settings", bg='#1E1E1E', fg='#D4D4D4', font=("Segoe UI", 9))
        settings_label.grid(row=0, column=0, sticky=W)
        
        # Show album art button (hidden by default, shown when album art is hidden)
        self.show_album_art_btn = Label(
            settings_header,
            text="👁",
            font=("Segoe UI", 10),
            bg='#1E1E1E',
            fg='#808080',
            cursor='hand2',
            width=2
        )
        self.show_album_art_btn.grid(row=0, column=1, sticky=E)
        self.show_album_art_btn.bind("<Button-1>", lambda e: self.toggle_album_art())
        self.show_album_art_btn.bind("<Enter>", lambda e: self.show_album_art_btn.config(fg='#D4D4D4'))
        self.show_album_art_btn.bind("<Leave>", lambda e: self.show_album_art_btn.config(fg='#808080'))
        self.show_album_art_btn.grid_remove()  # Hidden by default
        
        # Inner frame for content
        settings_content = Frame(self.settings_frame, bg='#1E1E1E')
        settings_content.grid(row=1, column=0, sticky=(W, E), padx=6, pady=(0, 4))
        self.settings_frame.columnconfigure(0, weight=1)
        
        # Album art panel (separate frame on the right, same height as settings, square for equal padding)
        self.album_art_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.album_art_frame.grid(row=2, column=2, sticky=(W, E, N), pady=6, padx=(6, 0))
        self.album_art_frame.grid_propagate(False)
        self.album_art_frame.config(width=160, height=160)  # Square panel for equal padding
        # Center content in the frame
        self.album_art_frame.columnconfigure(0, weight=1)
        self.album_art_frame.rowconfigure(0, weight=1)
        
        # Album art canvas with consistent padding all around (10px padding = 140x140 canvas)
        self.album_art_canvas = Canvas(
            self.album_art_frame,
            width=140,
            height=140,
            bg='#1E1E1E',
            highlightthickness=0,
            borderwidth=0,
            cursor='hand2'  # Show hand cursor to indicate it's clickable
        )
        # Center the canvas with equal padding on all sides (10px on each side = 20px total)
        self.album_art_canvas.grid(row=0, column=0, padx=10, pady=10)
        
        # Make canvas clickable to toggle album art
        self.album_art_canvas.bind("<Button-1>", lambda e: self.toggle_album_art())
        
        # Placeholder text on canvas
        self.album_art_canvas.create_text(
            70, 70,
            text="No album art",
            fill='#808080',
            font=("Segoe UI", 8)
        )
        
        # Audio Format (first)
        ttk.Label(settings_content, text="Audio Format:", font=("Segoe UI", 8)).grid(row=0, column=0, padx=4, sticky=W, pady=1)
        format_combo = ttk.Combobox(
            settings_content,
            textvariable=self.format_var,
            values=["mp3 (128kbps)", "flac", "ogg", "wav"],
            state="readonly",
            width=15
        )
        format_combo.grid(row=0, column=1, padx=4, sticky=W, pady=1)
        format_combo.bind("<<ComboboxSelected>>", lambda e: (self._deselect_combobox_text(e), self.on_format_change(e), self.update_preview()))
        
        # Numbering (second, below Audio Format)
        ttk.Label(settings_content, text="Numbering:", font=("Segoe UI", 8)).grid(row=1, column=0, padx=4, sticky=W, pady=1)
        numbering_combo = ttk.Combobox(
            settings_content,
            textvariable=self.numbering_var,
            values=["None", "01. Track", "1. Track", "01 - Track", "1 - Track"],
            state="readonly",
            width=15
        )
        numbering_combo.grid(row=1, column=1, padx=4, sticky=W, pady=1)
        numbering_combo.bind("<<ComboboxSelected>>", lambda e: (self._deselect_combobox_text(e), self.on_numbering_change(e), self.update_preview()))
        
        # Folder Structure (third, below Numbering)
        ttk.Label(settings_content, text="Folder Structure:", font=("Segoe UI", 8)).grid(row=2, column=0, padx=4, sticky=W, pady=1)
        
        # Create a separate display variable for the combobox using class constants
        structure_display_values = list(self.FOLDER_STRUCTURES.values())
        structure_combo = ttk.Combobox(
            settings_content,
            textvariable=self.folder_structure_var,
            values=structure_display_values,
            state="readonly",
            width=25
        )
        structure_combo.grid(row=2, column=1, padx=4, sticky=W, pady=1)
        structure_combo.bind("<<ComboboxSelected>>", lambda e: (self._deselect_combobox_text(e), self.on_structure_change(e)))
        
        # Store reference to combobox and display values for later updates
        self.structure_combo = structure_combo
        self.structure_display_values = structure_display_values
        
        # Set initial display value immediately
        self.update_structure_display()
        
        # Skip post-processing checkbox (below Folder Structure) - only shown if developer flag is enabled
        skip_postprocessing_check = Checkbutton(
            settings_content,
            text="Skip post-processing (output original files)",
            variable=self.skip_postprocessing_var,
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#D4D4D4',
            selectcolor='#1E1E1E',
            activebackground='#1E1E1E',
            activeforeground='#D4D4D4',
            command=self.on_skip_postprocessing_change
        )
        skip_postprocessing_check.grid(row=3, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        # Hide by default unless developer flag is enabled
        if not SHOW_SKIP_POSTPROCESSING_OPTION:
            skip_postprocessing_check.grid_remove()
        
        # Download cover art separately checkbox (below Skip post-processing)
        download_cover_art_check = Checkbutton(
            settings_content,
            text="Save copy of cover art in download folder",
            variable=self.download_cover_art_var,
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#D4D4D4',
            selectcolor='#1E1E1E',
            activebackground='#1E1E1E',
            activeforeground='#D4D4D4',
            command=self.on_download_cover_art_change
        )
        download_cover_art_check.grid(row=4, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        
        # Create playlist checkbox (below Save copy of cover art)
        create_playlist_check = Checkbutton(
            settings_content,
            text="Create playlist file (.m3u)",
            variable=self.create_playlist_var,
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#D4D4D4',
            selectcolor='#1E1E1E',
            activebackground='#1E1E1E',
            activeforeground='#D4D4D4',
            command=self.on_create_playlist_change
        )
        create_playlist_check.grid(row=5, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        
        # Configure column weights to keep dropdowns in place
        settings_content.columnconfigure(0, weight=0)
        settings_content.columnconfigure(1, weight=0)
        
        # Preview container (below both settings and album art panels)
        preview_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        preview_frame.grid(row=3, column=0, columnspan=3, sticky=(W, E), pady=(0, 6), padx=0)
        
        # Preview display with "Preview: " in white and path in blue
        preview_label_prefix = Label(
            preview_frame,
            text="Preview: ",
            font=("Consolas", 8),
            bg='#1E1E1E',
            fg='#D4D4D4',  # White text
            justify='left'
        )
        preview_label_prefix.grid(row=0, column=0, sticky=W, padx=(6, 0), pady=4)
        
        # Preview path label (blue, left-aligned)
        self.preview_var = StringVar(value="Select a download path")
        preview_label_path = Label(
            preview_frame,
            textvariable=self.preview_var,
            font=("Consolas", 8),
            bg='#1E1E1E',
            fg="#2dacd5",  # Blue text
            wraplength=450,  # Full width for preview path
            justify='left',
            anchor='w'  # Left-align the text
        )
        preview_label_path.grid(row=0, column=1, sticky=W, padx=(0, 6), pady=4)
        preview_frame.columnconfigure(1, weight=1)
        
        # Format conversion warning (shown below preview when FLAC, OGG, or WAV is selected)
        self.format_conversion_warning_label = Label(
            main_frame,
            text="⚠ Files are converted from 128kbps MP3 stream source. Quality is not improved. For higher quality, purchase/download directly from Bandcamp.",
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg="#FFA500",  # Orange color for warning
            wraplength=480,
            justify='left'
        )
        self.format_conversion_warning_label.grid(row=4, column=0, columnspan=3, padx=12, sticky=W, pady=(0, 6))
        self.format_conversion_warning_label.grid_remove()  # Hidden by default
        
        # Warning labels (shown below preview when OGG or WAV is selected)
        self.ogg_warning_label = Label(
            main_frame,
            text="⚠ Cover art must be embedded manually for OGG files",
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg="#FFA500"  # Orange color for warning
        )
        self.ogg_warning_label.grid(row=5, column=0, columnspan=3, padx=12, sticky=W, pady=(0, 6))
        self.ogg_warning_label.grid_remove()  # Hidden by default
        
        # WAV warning label (shown when WAV is selected, below preview)
        self.wav_warning_label = Label(
            main_frame,
            text="⚠ Metadata/cover art cannot be embedded for WAV files",
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg="#FFA500"  # Orange color for warning
        )
        self.wav_warning_label.grid(row=5, column=0, columnspan=3, padx=12, sticky=W, pady=(0, 6))
        self.wav_warning_label.grid_remove()  # Hidden by default
        
        # Download button - prominent with Bandcamp blue accent
        self.download_btn = ttk.Button(
            main_frame,
            text="Download Album",
            command=self.start_download,
            style='Download.TButton'
        )
        self.download_btn.grid(row=6, column=0, columnspan=3, pady=15)
        
        # Cancel button (hidden initially, shown during download)
        # Uses same style as download button for consistent size
        self.cancel_btn = ttk.Button(
            main_frame,
            text="Cancel Download",
            command=self.cancel_download,
            state='disabled',
            style='Cancel.TButton'
        )
        self.cancel_btn.grid(row=6, column=0, columnspan=3, pady=15)
        self.cancel_btn.grid_remove()  # Hidden by default
        
        # Progress bar - compact
        self.progress_var = StringVar(value="Ready")
        self.progress_label = ttk.Label(
            main_frame,
            textvariable=self.progress_var,
            font=("Segoe UI", 8)
        )
        self.progress_label.grid(row=7, column=0, columnspan=3, pady=2)
        
        # Progress bar - using indeterminate mode for smooth animation
        # Options: 'indeterminate' (animated, no specific progress) or 'determinate' (shows actual %)
        self.progress_bar = ttk.Progressbar(
            main_frame,
            mode='indeterminate',  # Smooth animated progress
            length=350
        )
        self.progress_bar.grid(row=8, column=0, columnspan=3, pady=2, sticky=(W, E))
        
        # Overall album progress bar (custom thin 3px bar using Canvas)
        self.overall_progress_bar = ThinProgressBar(
            main_frame,
            height=3,  # 3px thick as requested
            bg_color='#1E1E1E',  # Match dark background
            fg_color='#2dacd5'   # Blue color matching main progress bar
        )
        self.overall_progress_bar.config(mode='determinate', maximum=100, value=0)
        # Hide initially - will show when download starts
        self.overall_progress_bar.grid(row=9, column=0, columnspan=3, pady=(2, 4), sticky=(W, E))
        self.overall_progress_bar.grid_remove()
        
        # Status log - compact (using regular Frame for full control)
        self.log_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.log_frame.grid(row=10, column=0, columnspan=3, sticky=(W, E, N, S), pady=6, padx=0)
        
        # Label for the frame
        log_label = Label(self.log_frame, text="Status", bg='#1E1E1E', fg='#D4D4D4', font=("Segoe UI", 9))
        log_label.grid(row=0, column=0, sticky=W, padx=6, pady=(6, 2))
        
        # Inner frame for content
        log_content = Frame(self.log_frame, bg='#1E1E1E')
        log_content.grid(row=1, column=0, sticky=(W, E, N, S), padx=6, pady=(0, 6))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)
        log_content.columnconfigure(0, weight=1)
        log_content.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(
            log_content,
            height=6,
            width=55,
            font=("Consolas", 8),
            wrap=WORD,
            bg='#1E1E1E',
            fg='#D4D4D4',
            insertbackground='#D4D4D4',
            selectbackground='#264F78',
            selectforeground='#FFFFFF',
            borderwidth=0,
            highlightthickness=0,
            relief='flat'
        )
        self.log_text.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # Configure scrollbar after packing
        self.root.after(100, self.configure_scrollbar)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(2, weight=0)  # Album art column doesn't expand
        main_frame.rowconfigure(10, weight=1)  # Status log row expands
    
    def _minimize_console_immediately(self):
        """Minimize console window immediately at startup."""
        try:
            if sys.platform == 'win32':
                kernel32 = ctypes.windll.kernel32
                user32 = ctypes.windll.user32
                hwnd = kernel32.GetConsoleWindow()
                if hwnd:
                    # SW_MINIMIZE = 6 - minimizes to taskbar
                    user32.ShowWindow(hwnd, 6)
        except:
            pass
    
    def hide_console(self):
        """Hide the console window after GUI is ready (backup method)."""
        self._minimize_console_immediately()
    
    def _bring_to_front(self):
        """Bring the window to the front and give it focus."""
        try:
            # Make window topmost temporarily to bring it to front
            self.root.attributes('-topmost', True)
            self.root.update_idletasks()
            # Bring to front and focus
            self.root.lift()
            self.root.focus_force()
            # Remove topmost attribute so window behaves normally after
            self.root.after(100, lambda: self.root.attributes('-topmost', False))
        except Exception:
            # Fallback: just try to lift and focus
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
    
    def cancel_download(self):
        """Cancel the current download by making yt-dlp skip remaining tracks."""
        if not self.is_cancelling:
            self.is_cancelling = True
            self.log("Cancelling download...")
            self.cancel_btn.config(state='disabled')
            
            # Stop progress bar animation immediately
            try:
                self.progress_bar.stop()
            except:
                pass
            
            # Hide and reset overall progress bar
            if hasattr(self, 'overall_progress_bar') and self.overall_progress_bar:
                try:
                    self.overall_progress_bar.config(mode='determinate', value=0)
                    self.overall_progress_bar.grid_remove()
                except:
                    pass
            
            # Update UI immediately to show cancellation
            self.progress_var.set("Cancelling...")
            
            # Try to cancel yt-dlp instance (though match_filter will handle skipping tracks)
            if self.ydl_instance:
                try:
                    self.ydl_instance.cancel_download()
                except Exception:
                    pass
    
    def on_closing(self):
        """Handle window closing - also close console."""
        try:
            # Close console window
            kernel32 = ctypes.windll.kernel32
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                kernel32.FreeConsole()
        except:
            pass
        # Close the GUI
        self.root.destroy()
    
    def configure_scrollbar(self):
        """Configure scrollbar styling after widget creation."""
        try:
            # Find and configure the scrollbar in the log text widget
            for widget in self.log_text.master.winfo_children():
                widget_type = str(type(widget))
                if 'Scrollbar' in widget_type or 'scrollbar' in str(widget).lower():
                    widget.configure(
                        bg='#1E1E1E',
                        troughcolor='#1E1E1E',
                        activebackground='#3E3E42',
                        borderwidth=0,
                        highlightthickness=0
                    )
        except:
            pass
    
    def _deselect_combobox_text(self, event):
        """Deselect text and remove focus from combobox after selection."""
        widget = event.widget
        # Use after_idle to deselect and unfocus after the selection event is fully processed
        def clear_selection_and_focus():
            widget.selection_clear()
            # Remove focus by focusing on the root window
            self.root.focus_set()
        widget.after_idle(clear_selection_and_focus)
    
    def _extract_structure_choice(self, choice_str):
        """Helper method to extract numeric choice from folder structure string."""
        if not choice_str:
            return "4"  # Default
        # Check if it's already a number
        if choice_str in ["1", "2", "3", "4", "5"]:
            return choice_str
        # Try to match by display value
        for key, value in self.FOLDER_STRUCTURES.items():
            if choice_str == value:
                return key
        # Fallback to default
        return "4"
    
    def on_structure_change(self, event=None):
        """Handle folder structure dropdown change."""
        # The StringVar already contains the full display text from the combobox selection
        # No need to modify it - just update the preview
        self.update_preview()
    
    def on_numbering_change(self, event=None):
        """Handle track numbering change and save preference."""
        self.save_numbering()
    
    def update_structure_display(self):
        """Update the dropdown display to show the current selection."""
        if not hasattr(self, 'structure_combo'):
            return
            
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        
        # Get the display value using class constants
        display_value = self.FOLDER_STRUCTURES.get(choice, self.FOLDER_STRUCTURES[self.DEFAULT_STRUCTURE])
        
        # Set both the StringVar and the combobox to the display value
        # This ensures the combobox shows the full text
        self.folder_structure_var.set(display_value)
        self.structure_combo.set(display_value)
    
    def on_url_change(self):
        """Handle URL changes - fetch metadata for preview with debouncing."""
        # Cancel any pending timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
        
        # Debounce: wait 200ms after last change before fetching (shorter for faster response)
        self.url_check_timer = self.root.after(200, self._check_url)
    
    def _handle_right_click_paste(self, event):
        """Handle right-click paste in URL field."""
        try:
            # Get clipboard content
            clipboard_text = self.root.clipboard_get()
            if clipboard_text:
                # Clear current selection if any
                url_entry = event.widget
                url_entry.delete(0, END)
                url_entry.insert(0, clipboard_text)
                # Trigger URL check
                self.root.after(10, self._check_url)
        except Exception:
            # If clipboard is empty or not text, ignore
            pass
    
    def _check_url(self):
        """Actually check the URL and fetch metadata."""
        url = self.url_var.get().strip()
        
        # Reset metadata if URL is empty
        if not url:
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None}
            self.current_thumbnail_url = None
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            return
        
        # Only fetch if it looks like a valid URL
        if "bandcamp.com" not in url.lower() and not url.startswith(("http://", "https://")):
            return
        
        # Fetch metadata in background thread
        threading.Thread(target=self.fetch_album_metadata, args=(url,), daemon=True).start()
    
    def fetch_album_metadata(self, url):
        """Fetch album metadata from URL without downloading."""
        # Try fast HTML extraction first, then fall back to yt-dlp
        def fetch_from_html():
            try:
                import urllib.request
                import re
                from urllib.parse import urlparse
                
                # Fetch the HTML page directly (fast, single request)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    html = response.read().decode('utf-8', errors='ignore')
                
                artist = None
                album = None
                
                # Extract artist - look for various patterns
                artist_patterns = [
                    r'<span[^>]*class=["\'][^"]*artist[^"]*["\'][^>]*>([^<]+)',
                    r'<a[^>]*class=["\'][^"]*artist[^"]*["\'][^>]*>([^<]+)',
                    r'by\s+<a[^>]*>([^<]+)</a>',
                    r'property=["\']music:musician["\'][^>]*content=["\']([^"\']+)',
                    r'<meta[^>]*property=["\']og:music:musician["\'][^>]*content=["\']([^"\']+)',
                ]
                
                for pattern in artist_patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        artist = match.group(1).strip()
                        if artist:
                            break
                
                # Extract album - look for various patterns
                album_patterns = [
                    r'<h2[^>]*class=["\'][^"]*trackTitle[^"]*["\'][^>]*>([^<]+)',
                    r'<span[^>]*class=["\'][^"]*trackTitle[^"]*["\'][^>]*>([^<]+)',
                    r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
                    r'<title>([^<]+)</title>',
                ]
                
                for pattern in album_patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        album = match.group(1).strip()
                        # Clean up common suffixes
                        album = re.sub(r'\s*[-|]\s*by\s+.*$', '', album, flags=re.IGNORECASE)
                        album = re.sub(r'\s*on\s+Bandcamp.*$', '', album, flags=re.IGNORECASE)
                        if album:
                            break
                
                # Try extracting artist from URL if not found
                if not artist and "bandcamp.com" in url.lower():
                    try:
                        parsed = urlparse(url)
                        hostname = parsed.hostname or ""
                        if ".bandcamp.com" in hostname:
                            subdomain = hostname.replace(".bandcamp.com", "")
                            artist = " ".join(word.capitalize() for word in subdomain.split("-"))
                    except:
                        pass
                
                # Update preview immediately if we got data from HTML
                if artist or album:
                    self.album_info = {
                        "artist": artist or "Artist",
                        "album": album or "Album",
                        "title": "Track",
                        "thumbnail_url": None
                    }
                    self.root.after(0, self.update_preview)
                    
                    # Also fetch thumbnail from HTML (fast)
                    self.root.after(50, lambda: self.fetch_thumbnail_from_html(url))
                    
                    # Still do yt-dlp extraction in background for more complete data
                    # but don't block on it
                    threading.Thread(target=fetch_from_ytdlp, daemon=True).start()
                else:
                    # If HTML extraction failed, use yt-dlp
                    fetch_from_ytdlp()
                    
            except Exception:
                # If HTML extraction fails, use yt-dlp
                fetch_from_ytdlp()
        
        def fetch_from_ytdlp():
            try:
                if yt_dlp is None:
                    return
                
                # Use yt-dlp to extract info without downloading (fast mode - no track processing)
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": True,
                    "socket_timeout": 10,
                    "retries": 2,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    # Extract artist and album info
                    artist = None
                    album = None
                    
                    if info:
                        artist = (info.get("artist") or 
                                 info.get("uploader") or 
                                 info.get("channel") or
                                 info.get("creator"))
                        
                        # Try extracting from URL if not found
                        if not artist and "bandcamp.com" in url.lower():
                            try:
                                from urllib.parse import urlparse
                                parsed = urlparse(url)
                                hostname = parsed.hostname or ""
                                if ".bandcamp.com" in hostname:
                                    subdomain = hostname.replace(".bandcamp.com", "")
                                    artist = " ".join(word.capitalize() for word in subdomain.split("-"))
                            except:
                                pass
                        
                        album = info.get("album") or info.get("title")
                    
                    # Get thumbnail URL for album art (second phase - won't slow down preview)
                    # Prefer larger thumbnails for better quality (now that loading is fast)
                    thumbnail_url = None
                    
                    def get_largest_thumbnail(thumbnails_list):
                        """Get the largest/highest quality thumbnail URL from a list."""
                        if not thumbnails_list:
                            return None
                        # Look for larger sizes first (better quality)
                        for size in ["large", "default", "medium", "small"]:
                            for thumb in thumbnails_list:
                                if isinstance(thumb, dict):
                                    if thumb.get("id") == size or thumb.get("preference", 0) > 5:
                                        return thumb.get("url")
                                    url = thumb.get("url")
                                    if url and size in url.lower():
                                        return url
                                elif isinstance(thumb, str):
                                    if size in thumb.lower():
                                        return thumb
                        # If no size match, return first available
                        if isinstance(thumbnails_list[0], dict):
                            return thumbnails_list[0].get("url")
                        return thumbnails_list[0]
                    
                    # First try entries (tracks often have the album art)
                    if info.get("entries"):
                        entries = [e for e in info.get("entries", []) if e]  # Filter out None
                        for entry in entries:
                            if not entry:
                                continue
                            # Try thumbnails list first (may have multiple sizes)
                            if entry.get("thumbnails"):
                                thumbnail_url = get_largest_thumbnail(entry.get("thumbnails"))
                            # Fallback to direct fields
                            if not thumbnail_url:
                                thumbnail_url = (entry.get("thumbnail") or 
                                               entry.get("thumbnail_url") or
                                               entry.get("artwork_url") or
                                               entry.get("cover"))
                            if thumbnail_url:
                                break  # Found it, stop searching
                    
                    # If not found in entries, try top-level info
                    if not thumbnail_url:
                        # Try thumbnails list first (may have multiple sizes)
                        if info.get("thumbnails"):
                            thumbnail_url = get_largest_thumbnail(info.get("thumbnails"))
                        # Fallback to direct fields
                        if not thumbnail_url:
                            thumbnail_url = (info.get("thumbnail") or 
                                           info.get("thumbnail_url") or
                                           info.get("artwork_url") or
                                           info.get("cover"))
                    
                    # Update album info (keep "Track" as placeholder) - only if we got new data
                    if artist or album:
                        self.album_info = {
                            "artist": artist or self.album_info.get("artist") or "Artist",
                            "album": album or self.album_info.get("album") or "Album",
                            "title": "Track",
                            "thumbnail_url": thumbnail_url or self.album_info.get("thumbnail_url")
                        }
                        self.root.after(0, self.update_preview)
                    
                    # Fetch and display album art if we found a thumbnail
                    if thumbnail_url and thumbnail_url != self.current_thumbnail_url and not self.album_art_fetching:
                        self.current_thumbnail_url = thumbnail_url
                        self.root.after(0, lambda url=thumbnail_url: self.fetch_and_display_album_art(url))
            except Exception:
                pass  # Silently fail - HTML extraction is primary method
        
        # Start with fast HTML extraction
        threading.Thread(target=fetch_from_html, daemon=True).start()
    
    def fetch_thumbnail_from_html(self, url):
        """Extract thumbnail URL directly from Bandcamp HTML page (fast method)."""
        def fetch():
            try:
                import urllib.request
                import re
                
                # Fetch the HTML page directly (fast, single request)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    html = response.read().decode('utf-8', errors='ignore')
                
                # Look for album art in various patterns Bandcamp uses
                thumbnail_url = None
                
                # Pattern 1: Look for popupImage or main image in data attributes
                patterns = [
                    r'popupImage["\']?\s*:\s*["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'data-popup-image=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<img[^>]*id=["\']tralbum-art["\'][^>]*src=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<img[^>]*class=["\'][^"]*popupImage[^"]*["\'][^>]*src=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'property=["\']og:image["\'][^>]*content=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        thumbnail_url = match.group(1)
                        # Make sure it's a full URL
                        if thumbnail_url.startswith('//'):
                            thumbnail_url = 'https:' + thumbnail_url
                        elif thumbnail_url.startswith('/'):
                            # Extract base URL
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            thumbnail_url = f"{parsed.scheme}://{parsed.netloc}{thumbnail_url}"
                        break
                
                # If found, try to get a larger/higher quality size for better image quality
                if thumbnail_url and not self.album_art_fetching:
                    # Try to get a larger thumbnail by modifying the URL
                    # Bandcamp often has sizes like _16, _32, _64, _100, _200, _300, _500 in the URL
                    # Prefer larger sizes for better quality now that loading is fast
                    high_quality_thumbnail = thumbnail_url
                    
                    # Try to find a larger size in the URL
                    if '_' in thumbnail_url or 'bcbits.com' in thumbnail_url:
                        # Try common larger sizes (in order of preference)
                        for size in ['_500', '_300', '_200', '_100', '_64']:
                            if size in thumbnail_url:
                                # Already has a good size
                                break
                            # Try replacing smaller sizes with larger ones
                            test_url = thumbnail_url.replace('_16', size).replace('_32', size).replace('_64', size).replace('_100', size)
                            if test_url != thumbnail_url:
                                high_quality_thumbnail = test_url
                                break
                    
                    self.current_thumbnail_url = high_quality_thumbnail
                    self.root.after(0, lambda url=high_quality_thumbnail: self.fetch_and_display_album_art(url))
                else:
                    # Fallback to yt-dlp extraction if HTML method fails
                    if not self.album_art_fetching:
                        self.root.after(0, lambda: self.fetch_thumbnail_separately(url))
            except Exception:
                # If HTML extraction fails, try yt-dlp method
                if not self.album_art_fetching:
                    self.root.after(0, lambda: self.fetch_thumbnail_separately(url))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def fetch_thumbnail_separately(self, url):
        """Fetch thumbnail URL separately if not found with extract_flat (second attempt)."""
        def fetch():
            try:
                if yt_dlp is None:
                    return
                
                # Quick extraction without extract_flat to get thumbnail
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,  # Need full extraction to get thumbnail
                    "socket_timeout": 10,
                    "retries": 1,  # Just one retry for this secondary attempt
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if info:
                        # Try to get thumbnail from various locations
                        thumbnail_url = (info.get("thumbnail") or 
                                       info.get("thumbnail_url") or
                                       info.get("artwork_url") or
                                       info.get("cover"))
                        
                        # Try thumbnails list
                        if not thumbnail_url and info.get("thumbnails"):
                            thumbnails = info.get("thumbnails", [])
                            if thumbnails:
                                if isinstance(thumbnails[0], dict):
                                    thumbnail_url = thumbnails[0].get("url")
                                elif isinstance(thumbnails[0], str):
                                    thumbnail_url = thumbnails[0]
                        
                        # Try first entry if still not found
                        if not thumbnail_url and info.get("entries"):
                            entries = [e for e in info.get("entries", []) if e]
                            if entries and entries[0]:
                                entry = entries[0]
                                thumbnail_url = (entry.get("thumbnail") or 
                                               entry.get("thumbnail_url") or
                                               entry.get("artwork_url") or
                                               entry.get("cover"))
                        
                        # If found, display it (only if not already fetching)
                        if thumbnail_url and not self.album_art_fetching:
                            self.current_thumbnail_url = thumbnail_url
                            self.root.after(0, lambda url=thumbnail_url: self.fetch_and_display_album_art(url))
            except Exception:
                pass  # Silently fail - thumbnail is optional
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def fetch_and_display_album_art(self, thumbnail_url):
        """Fetch and display album art asynchronously (second phase - doesn't block preview)."""
        if not thumbnail_url:
            self.clear_album_art()
            return
        
        # Prevent multiple simultaneous fetches
        if self.album_art_fetching:
            return
        
        self.album_art_fetching = True
        
        def download_and_display():
            try:
                import urllib.request
                import io
                from PIL import Image, ImageTk
                
                # Download the image
                with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                    image_data = response.read()
                
                # Open and resize image
                img = Image.open(io.BytesIO(image_data))
                
                # Resize to fit canvas (140x140) while maintaining aspect ratio
                img.thumbnail((140, 140), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Update UI on main thread
                def update_ui():
                    # Clear canvas
                    self.album_art_canvas.delete("all")
                    
                    # Calculate position to center the image
                    img_width = photo.width()
                    img_height = photo.height()
                    x = (140 - img_width) // 2
                    y = (140 - img_height) // 2
                    
                    # Display image on canvas
                    self.album_art_canvas.create_image(x + img_width // 2, y + img_height // 2, image=photo, anchor='center')
                    
                    # Keep a reference to prevent garbage collection
                    self.album_art_image = photo
                
                self.root.after(0, update_ui)
                self.album_art_fetching = False
                
            except ImportError:
                # PIL not available - can't display images
                self.root.after(0, lambda: self.album_art_canvas.delete("all"))
                self.root.after(0, lambda: self.album_art_canvas.create_text(
                    70, 70, text="PIL required\nfor album art\n\nInstall Pillow:\npip install Pillow", 
                    fill='#808080', font=("Segoe UI", 7), justify='center'
                ))
                self.album_art_fetching = False
            except Exception as e:
                # Failed to load image - clear and show placeholder
                self.root.after(0, self.clear_album_art)
                self.album_art_fetching = False
        
        # Download in background thread
        threading.Thread(target=download_and_display, daemon=True).start()
    
    def clear_album_art(self):
        """Clear the album art display."""
        try:
            self.album_art_canvas.delete("all")
            self.album_art_canvas.create_text(
                70, 70,
                text="No album art",
                fill='#808080',
                font=("Segoe UI", 8)
            )
            self.album_art_image = None
        except Exception:
            pass
    
    def toggle_album_art(self):
        """Toggle album art panel visibility."""
        self.album_art_visible = not self.album_art_visible
        
        if self.album_art_visible:
            # Show album art panel
            self.album_art_frame.grid()
            # Update settings frame to span 2 columns (leaving room for album art)
            self.settings_frame.grid_configure(columnspan=2)
            # Hide the "show" button in settings header
            self.show_album_art_btn.grid_remove()
        else:
            # Hide album art panel
            self.album_art_frame.grid_remove()
            # Update settings frame to span 3 columns (full width)
            self.settings_frame.grid_configure(columnspan=3)
            # Show the "show" button in settings header
            self.show_album_art_btn.grid()
        
        # Save the state
        self.save_album_art_state()
    
    def sanitize_filename(self, name):
        """Remove invalid filename characters."""
        if not name:
            return name
        # Remove invalid characters for Windows/Linux filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '')
        # Remove leading/trailing spaces and dots
        name = name.strip(' .')
        return name or "Unknown"
    
    def update_preview(self):
        """Update the folder structure preview."""
        path = self.path_var.get().strip()
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        
        if not path:
            self.preview_var.set("Select a download path")
            return
        
        # Get format extension for preview
        format_val = self.format_var.get()
        base_format = self._extract_format(format_val)
        ext_map = {
            "mp3": ".mp3",
            "flac": ".flac",
            "ogg": ".ogg",
            "wav": ".wav"
        }
        ext = ext_map.get(base_format, ".mp3")
        
        # Use real metadata if available, otherwise use placeholders
        # Sanitize names to remove invalid filename characters
        artist = self.sanitize_filename(self.album_info.get("artist")) or "Artist"
        album = self.sanitize_filename(self.album_info.get("album")) or "Album"
        title = self.sanitize_filename(self.album_info.get("title")) or "Track"
        
        # Apply track numbering if selected
        numbering_style = self.numbering_var.get()
        if numbering_style != "None":
            # Use track number 1 for preview
            track_number = 1
            if numbering_style == "01. Track":
                title = f"{track_number:02d}. {title}"
            elif numbering_style == "1. Track":
                title = f"{track_number}. {title}"
            elif numbering_style == "01 - Track":
                title = f"{track_number:02d} - {title}"
            elif numbering_style == "1 - Track":
                title = f"{track_number} - {title}"
        
        # Get example path based on structure
        base_path = Path(path)
        examples = {
            "1": str(base_path / f"{title}{ext}"),
            "2": str(base_path / album / f"{title}{ext}"),
            "3": str(base_path / artist / f"{title}{ext}"),
            "4": str(base_path / artist / album / f"{title}{ext}"),
            "5": str(base_path / album / artist / f"{title}{ext}"),
        }
        
        preview_path = examples.get(choice, examples["4"])
        # Show only the path (no "Preview: " prefix - that's handled by the label)
        self.preview_var.set(preview_path)
    
    def on_format_change(self, event=None):
        """Update format warnings based on selection."""
        format_val = self.format_var.get()
        base_format = self._extract_format(format_val)
        self.save_format()  # Save format preference
        
        # Show/hide format conversion warning (for FLAC, OGG, WAV - formats that are converted)
        if hasattr(self, 'format_conversion_warning_label'):
            if base_format in ["flac", "ogg", "wav"]:
                self.format_conversion_warning_label.grid()
            else:
                self.format_conversion_warning_label.grid_remove()
        
        # Show/hide format-specific warnings
        if hasattr(self, 'ogg_warning_label'):
            if base_format == "ogg":
                self.ogg_warning_label.grid()
                if hasattr(self, 'wav_warning_label'):
                    self.wav_warning_label.grid_remove()
            else:
                self.ogg_warning_label.grid_remove()
        
        if hasattr(self, 'wav_warning_label'):
            if base_format == "wav":
                self.wav_warning_label.grid()
                if hasattr(self, 'ogg_warning_label'):
                    self.ogg_warning_label.grid_remove()
            else:
                self.wav_warning_label.grid_remove()
    
    def browse_folder(self):
        """Open folder browser dialog."""
        folder = filedialog.askdirectory(title="Select Download Folder")
        if folder:
            self.path_var.set(folder)
            self.save_path()
            self.update_preview()
    
    def log(self, message):
        """Add message to log."""
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.root.update_idletasks()
    
    def get_outtmpl(self):
        """Get output template based on folder structure."""
        base_folder = Path(self.path_var.get())
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        
        folder_options = {
            "1": str(base_folder / "%(title)s.%(ext)s"),
            "2": str(base_folder / "%(album)s" / "%(title)s.%(ext)s"),
            "3": str(base_folder / "%(artist)s" / "%(title)s.%(ext)s"),
            "4": str(base_folder / "%(artist)s" / "%(album)s" / "%(title)s.%(ext)s"),
            "5": str(base_folder / "%(album)s" / "%(artist)s" / "%(title)s.%(ext)s"),
        }
        return folder_options.get(choice, folder_options["4"])
    
    def validate_path(self, path):
        """Validate download path with comprehensive checks."""
        if not path:
            return False, "Please select a download path."
        
        path_obj = Path(path)
        
        # Check if path exists
        if not path_obj.exists():
            return False, "The selected download path does not exist."
        
        # Check if path is a directory
        if not path_obj.is_dir():
            return False, "The selected path is not a directory."
        
        # Check write permissions
        try:
            test_file = path_obj / ".write_test"
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            return False, "No write permission for the selected folder.\n\nPlease choose a different folder or check folder permissions."
        except Exception as e:
            return False, f"Cannot write to the selected folder:\n{str(e)}"
        
        # Check available disk space (warn if less than 1GB)
        try:
            import shutil
            free_space = shutil.disk_usage(path).free
            free_gb = free_space / (1024 ** 3)
            if free_gb < 1.0:
                response = messagebox.askyesno(
                    "Low Disk Space",
                    f"Warning: Less than 1 GB free space available ({free_gb:.2f} GB).\n\n"
                    "Downloads may fail if there's not enough space.\n\n"
                    "Continue anyway?"
                )
                if not response:
                    return False, "Download aborted due to low disk space."
        except Exception:
            pass  # If we can't check disk space, continue anyway
        
        return True, None
    
    def start_download(self):
        """Start the download process in a separate thread."""
        # Validate inputs
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a Bandcamp album URL.")
            return
        
        if "bandcamp.com" not in url.lower():
            response = messagebox.askyesno(
                "Warning",
                "This doesn't appear to be a Bandcamp URL.\n\nContinue anyway?"
            )
            if not response:
                return
        
        path = self.path_var.get().strip()
        is_valid, error_msg = self.validate_path(path)
        if not is_valid:
            messagebox.showerror("Path Error", error_msg)
            return
        
        # Save preferences
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        self.save_default_preference(choice)
        self.save_path()
        
        # Disable download button, show cancel button, and start progress
        self.download_btn.config(state='disabled')
        self.download_btn.grid_remove()
        self.cancel_btn.config(state='normal')
        self.cancel_btn.grid()
        self.is_cancelling = False
        
        # Start with indeterminate mode (will switch to determinate when we get progress)
        self.progress_bar.config(mode='indeterminate', maximum=100, value=0)
        self.progress_bar.start(10)  # Animation speed (lower = faster)
        # Reset overall progress bar (but don't show it yet - will show when first file starts)
        if hasattr(self, 'overall_progress_bar') and self.overall_progress_bar:
            try:
                self.overall_progress_bar.config(mode='determinate', maximum=100, value=0)
                # Don't show it yet - will show when we get actual progress data
            except:
                pass
        self.progress_var.set("Starting download...")
        self.log_text.delete(1.0, END)
        self.log("Starting download...")
        self.log(f"URL: {url}")
        self.log(f"Path: {path}")
        self.log("")
        
        # Start download in thread
        self.download_thread = threading.Thread(target=self.download_album, args=(url,), daemon=True)
        self.download_thread.start()
    
    def embed_cover_art_ffmpeg(self, audio_file, thumbnail_file):
        """Embed cover art into audio file using FFmpeg."""
        try:
            if not Path(audio_file).exists() or not Path(thumbnail_file).exists():
                return False
            
            format_val = self.format_var.get()
            base_format = self._extract_format(format_val)
            
            # Create temporary output file
            temp_output = str(Path(audio_file).with_suffix('.tmp' + Path(audio_file).suffix))
            
            # Format-specific handling
            if base_format == "flac":
                # FLAC: embed as METADATA_BLOCK_PICTURE
                cmd = [
                    str(self.ffmpeg_path),
                    "-i", str(audio_file),
                    "-i", str(thumbnail_file),
                    "-map", "0:a",
                    "-map", "1",
                    "-c:a", "copy",
                    "-c:v", "copy",
                    "-disposition:v:0", "attached_pic",
                    "-y",
                    temp_output,
                ]
            elif base_format == "ogg":
                # OGG/Vorbis: embed as METADATA_BLOCK_PICTURE
                cmd = [
                    str(self.ffmpeg_path),
                    "-i", str(audio_file),
                    "-i", str(thumbnail_file),
                    "-map", "0:a",
                    "-map", "1",
                    "-c:a", "copy",
                    "-c:v", "copy",
                    "-disposition:v:0", "attached_pic",
                    "-y",
                    temp_output,
                ]
            elif base_format == "wav":
                # WAV: Cannot reliably embed cover art - return False to skip
                # Cover art files will be kept in folder for manual embedding
                return False
            else:
                return False
            
            # Run FFmpeg
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0 and Path(temp_output).exists():
                # Replace original with new file
                Path(audio_file).unlink()
                Path(temp_output).rename(audio_file)
                return True
            else:
                # Clean up temp file if it exists
                if Path(temp_output).exists():
                    Path(temp_output).unlink()
                return False
                
        except Exception as e:
            return False
    
    def find_thumbnail_file(self, audio_file):
        """Find the corresponding thumbnail file for an audio file."""
        audio_path = Path(audio_file)
        audio_dir = audio_path.parent
        
        # Try to find thumbnail with same base name or common names
        base_name = audio_path.stem
        for ext in self.THUMBNAIL_EXTENSIONS:
            # Try exact match first
            thumb_file = audio_dir / f"{base_name}{ext}"
            if thumb_file.exists():
                return str(thumb_file)
            
            # Try common thumbnail names
            for name in ['cover', 'album', 'folder', 'artwork']:
                thumb_file = audio_dir / f"{name}{ext}"
                if thumb_file.exists():
                    return str(thumb_file)
        
        # Look for any image file in the directory
        for ext in self.THUMBNAIL_EXTENSIONS:
            for img_file in audio_dir.glob(f"*{ext}"):
                return str(img_file)
        
        return None
    
    def apply_track_numbering(self, download_path):
        """Apply track numbering to downloaded files based on user preference."""
        import re
        import time
        
        numbering_style = self.numbering_var.get()
        if numbering_style == "None":
            return
        
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Only process files that were just downloaded
            # Use downloaded_files set if available, otherwise use timestamp-based filtering
            files_to_process = []
            
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                # Process only files that were tracked as downloaded
                for downloaded_file in self.downloaded_files:
                    file_path = Path(downloaded_file)
                    if file_path.exists():
                        files_to_process.append(file_path)
            elif hasattr(self, 'download_start_time') and self.download_start_time:
                # Fallback: use timestamp-based filtering (files modified after download started)
                # Use a 30 second buffer before download started to catch files from this session
                time_threshold = self.download_start_time - 30
                format_val = self.format_var.get()
                base_format = self._extract_format(format_val)
                skip_postprocessing = self.skip_postprocessing_var.get()
                if skip_postprocessing:
                    target_exts = [".mp3", ".flac", ".ogg", ".oga", ".wav"]
                else:
                    target_exts = self.FORMAT_EXTENSIONS.get(base_format, [])
                
                for ext in target_exts:
                    for audio_file in base_path.rglob(f"*{ext}"):
                        try:
                            # Only include files modified after download started (with buffer)
                            file_mtime = audio_file.stat().st_mtime
                            if file_mtime >= time_threshold:
                                files_to_process.append(audio_file)
                        except Exception:
                            pass  # Skip files we can't access
            
            if not files_to_process:
                return
            
            # Sort files by name to maintain order
            files_to_process.sort(key=lambda x: x.name)
            
            # Process each file
            for audio_file in files_to_process:
                # Skip temporary files
                if audio_file.name.startswith('.') or 'tmp' in audio_file.name.lower():
                    continue
                
                # Get track number from metadata if available
                track_number = None
                file_title = audio_file.stem  # filename without extension
                track_title = file_title  # Will be updated if we find metadata
                
                # Try to find track number from download_info
                for title_key, info in self.download_info.items():
                    # Match by comparing filename with track title
                    if file_title.lower() in title_key or title_key in file_title.lower():
                        track_number = info.get("track_number")
                        track_title = info.get("title", file_title)
                        break
                
                # If no track number found, try to extract from filename or use index
                if track_number is None:
                    # Try to extract number from filename
                    match = re.search(r'\b(\d+)\b', file_title)
                    if match:
                        track_number = int(match.group(1))
                    else:
                        # Use file index as fallback (within the files we're processing)
                        track_number = files_to_process.index(audio_file) + 1
                
                # Use sanitized track title for the new filename
                track_title = self.sanitize_filename(track_title)
                
                # Format track number prefix based on style
                if numbering_style == "01. Track":
                    prefix = f"{track_number:02d}. "
                elif numbering_style == "1. Track":
                    prefix = f"{track_number}. "
                elif numbering_style == "01 - Track":
                    prefix = f"{track_number:02d} - "
                elif numbering_style == "1 - Track":
                    prefix = f"{track_number} - "
                else:
                    continue  # Unknown style
                
                # Get original filename parts
                parent_dir = audio_file.parent
                extension = audio_file.suffix
                
                # Check if filename already has numbering
                # Check if already starts with number
                if re.match(r'^\d+[.\-]\s*', file_title):
                    continue  # Already numbered, skip
                new_name = prefix + track_title + extension
                
                new_path = parent_dir / new_name
                
                # Rename file if new name is different
                if new_path != audio_file and not new_path.exists():
                    try:
                        audio_file.rename(new_path)
                        self.root.after(0, lambda old=audio_file.name, new=new_name: self.log(f"Renamed: {old} → {new_name}"))
                    except Exception as e:
                        self.root.after(0, lambda name=audio_file.name: self.log(f"⚠ Could not rename: {name}"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"⚠ Error applying track numbering: {str(e)}"))
    
    def process_downloaded_files(self, download_path):
        """Process all downloaded files to embed cover art for FLAC, OGG, and WAV."""
        
        # Apply track numbering first
        self.apply_track_numbering(download_path)
        
        format_val = self.format_var.get()
        base_format = self._extract_format(format_val)
        skip_postprocessing = self.skip_postprocessing_var.get()
        
        # If skipping post-processing, we need to check all audio formats (yt-dlp downloads original format)
        if skip_postprocessing:
            # Check all possible audio formats since we don't know what yt-dlp downloaded
            all_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav"]
            base_format = None  # Will process based on actual file extensions found
        else:
            all_extensions = self.FORMAT_EXTENSIONS.get(base_format, [])
        
        # Only process FLAC (MP3 is handled by yt-dlp's EmbedThumbnail)
        # OGG and WAV cannot reliably embed cover art, so we skip embedding and keep files
        if skip_postprocessing:
            # When skipping post-processing, handle cover art based on download_cover_art setting
            download_cover_art = self.download_cover_art_var.get()
            if download_cover_art:
                # Deduplicate cover art if download_cover_art is enabled
                try:
                    base_path = Path(download_path)
                    if base_path.exists():
                        processed_dirs = set()
                        for ext in all_extensions:
                            for audio_file in base_path.rglob(f"*{ext}"):
                                processed_dirs.add(audio_file.parent)
                        
                        if processed_dirs:
                            self.deduplicate_cover_art(processed_dirs)
                except Exception:
                    pass
            return
        elif base_format in ["mp3", "ogg", "wav"]:
            # For MP3, OGG, and WAV - handle cover art based on download_cover_art setting
            download_cover_art = self.download_cover_art_var.get()
            
            if download_cover_art or base_format in ["ogg", "wav"]:
                # If download cover art is enabled, or for OGG/WAV (which can't embed), deduplicate cover art files
                try:
                    base_path = Path(download_path)
                    if base_path.exists():
                        # Find all directories with audio files
                        extensions = {
                            "mp3": [".mp3"],
                            "ogg": [".ogg", ".oga"],
                            "wav": [".wav"],
                        }
                        target_exts = extensions.get(base_format, [])
                        if target_exts:
                            processed_dirs = set()
                            for ext in target_exts:
                                for audio_file in base_path.rglob(f"*{ext}"):
                                    processed_dirs.add(audio_file.parent)
                            
                            if processed_dirs:
                                self.deduplicate_cover_art(processed_dirs)
                except Exception:
                    pass
            return
        
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Find all audio files of the target format using class constants
            target_exts = self.FORMAT_EXTENSIONS.get(base_format, [])
            if not target_exts:
                return
            
            # Recursively find all audio files
            audio_files = []
            for ext in target_exts:
                audio_files.extend(base_path.rglob(f"*{ext}"))
            
            if not audio_files:
                return
            
            self.root.after(0, lambda: self.log(f"Embedding cover art for {len(audio_files)} file(s)..."))
            
            # Track directories where we've processed files and thumbnails we've used
            processed_dirs = set()
            used_thumbnails = set()
            
            # Process each file
            for audio_file in audio_files:
                
                # Skip temporary files
                name_lower = audio_file.name.lower()
                if audio_file.name.startswith('.') or 'tmp' in name_lower:
                    continue
                
                # Track the directory
                processed_dirs.add(audio_file.parent)
                
                # Find thumbnail
                thumbnail_file = self.find_thumbnail_file(str(audio_file))
                audio_file_str = str(audio_file)
                audio_file_name = audio_file.name
                
                if thumbnail_file:
                    used_thumbnails.add(Path(thumbnail_file))
                    self.root.after(0, lambda name=audio_file_name: self.log(f"Processing: {name}"))
                    success = self.embed_cover_art_ffmpeg(audio_file_str, thumbnail_file)
                    if success:
                        self.root.after(0, lambda name=audio_file_name: self.log(f"✓ Embedded cover art: {name}"))
                    else:
                        self.root.after(0, lambda name=audio_file_name: self.log(f"⚠ Could not embed cover art: {name}"))
                else:
                    self.root.after(0, lambda name=audio_file_name: self.log(f"⚠ No thumbnail found for: {name}"))
            
            # Handle cover art files after embedding
            download_cover_art = self.download_cover_art_var.get()
            
            if download_cover_art:
                # If download cover art is enabled, keep and deduplicate cover art files for all formats
                self.deduplicate_cover_art(processed_dirs)
            elif base_format != "ogg":
                # For formats other than OGG, delete thumbnail files after embedding (unless download_cover_art is enabled)
                deleted_count = 0
                
                for directory in processed_dirs:
                    for ext in self.THUMBNAIL_EXTENSIONS:
                        for thumb_file in directory.glob(f"*{ext}"):
                            # Delete the thumbnail file (we've already embedded it)
                            try:
                                thumb_file.unlink()
                                deleted_count += 1
                            except Exception:
                                pass  # Ignore errors deleting files
                
                if deleted_count > 0:
                    self.root.after(0, lambda count=deleted_count: self.log(f"Cleaned up {count} thumbnail file(s)"))
            else:
                # For OGG, deduplicate cover art files (keep only one if all are identical)
                self.deduplicate_cover_art(processed_dirs)
        
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Error processing files: {str(e)}"))
    
    def get_file_hash(self, file_path, cache=None):
        """Calculate MD5 hash of a file to detect duplicates.
        
        Args:
            file_path: Path to file
            cache: Optional dict to cache hashes (key: Path, value: hash)
        
        Returns:
            MD5 hash string or None if error
        """
        file_path_obj = Path(file_path)
        
        # Check cache first
        if cache is not None and file_path_obj in cache:
            return cache[file_path_obj]
        
        try:
            hash_md5 = hashlib.md5()
            with open(file_path_obj, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            result = hash_md5.hexdigest()
            
            # Store in cache if provided
            if cache is not None:
                cache[file_path_obj] = result
            
            return result
        except Exception:
            return None
    
    def check_mp3_metadata(self, mp3_file):
        """Check if MP3 file has metadata using FFprobe."""
        try:
            ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
            if not ffprobe_path.exists():
                # Try to find ffprobe
                ffprobe_path = self.script_dir / "ffprobe.exe"
                if not ffprobe_path.exists():
                    return None
            
            cmd = [
                str(ffprobe_path),
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(mp3_file)
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout.decode('utf-8', errors='ignore'))
                tags = data.get("format", {}).get("tags", {})
                return tags
            return None
        except Exception:
            return None
    
    def re_embed_mp3_metadata(self, mp3_file, metadata, thumbnail_file=None):
        """Re-embed metadata into MP3 file using FFmpeg."""
        try:
            temp_output = str(Path(mp3_file).with_suffix('.tmp.mp3'))
            
            cmd = [
                str(self.ffmpeg_path),
                "-i", str(mp3_file),
            ]
            
            # Add thumbnail if provided
            if thumbnail_file and Path(thumbnail_file).exists():
                cmd.extend(["-i", str(thumbnail_file)])
                cmd.extend(["-map", "0:a", "-map", "1"])
                cmd.extend(["-c:a", "copy", "-c:v", "copy"])
                cmd.extend(["-disposition:v:0", "attached_pic"])
            else:
                cmd.extend(["-c:a", "copy"])
            
            # Add metadata
            if metadata.get("title"):
                cmd.extend(["-metadata", f"title={metadata['title']}"])
            if metadata.get("artist"):
                cmd.extend(["-metadata", f"artist={metadata['artist']}"])
            if metadata.get("album"):
                cmd.extend(["-metadata", f"album={metadata['album']}"])
            if metadata.get("track_number"):
                track_num = str(metadata['track_number'])
                cmd.extend(["-metadata", f"track={track_num}"])
            if metadata.get("date"):
                cmd.extend(["-metadata", f"date={metadata['date']}"])
            
            cmd.extend(["-y", temp_output])
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode == 0 and Path(temp_output).exists():
                Path(mp3_file).unlink()
                Path(temp_output).rename(mp3_file)
                return True
            else:
                if Path(temp_output).exists():
                    Path(temp_output).unlink()
                return False
        except Exception:
            return False
    
    def verify_and_fix_mp3_metadata(self, download_path):
        """Verify MP3 files have metadata and fix missing ones."""
        
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Only check files that were just downloaded
            # Filter by: 1) files in downloaded_files set, or 2) files modified after download started
            mp3_files = []
            import time
            
            # Find MP3 files that were just downloaded
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                # Check files from downloaded_files set
                for downloaded_file in self.downloaded_files:
                    file_path = Path(downloaded_file)
                    if file_path.exists() and file_path.suffix.lower() == '.mp3':
                        mp3_files.append(file_path)
            
            # If no files tracked, use timestamp-based filtering (files modified after download started)
            if not mp3_files and hasattr(self, 'download_start_time'):
                # Cache file stats to avoid multiple stat() calls
                time_threshold = self.download_start_time - 30
                album_info = getattr(self, 'album_info_stored', None)
                artist_lower = (album_info.get("artist") or "").lower() if album_info else None
                album_lower = (album_info.get("album") or "").lower() if album_info else None
                
                for mp3_file in base_path.rglob("*.mp3"):
                    try:
                        # Check if file was modified after download started (with 30 second buffer before)
                        file_mtime = mp3_file.stat().st_mtime
                        if file_mtime >= time_threshold:
                            # Additional check: verify it matches the current album's artist/album if we have that info
                            if album_info and (artist_lower or album_lower):
                                # Check if file path contains artist or album name (basic heuristic)
                                file_path_str = str(mp3_file).lower()
                                
                                # Only include if path contains artist or album (helps filter out old downloads)
                                if (artist_lower and artist_lower in file_path_str) or \
                                   (album_lower and album_lower in file_path_str):
                                    mp3_files.append(mp3_file)
                            else:
                                # If no album info, just use timestamp
                                mp3_files.append(mp3_file)
                    except Exception:
                        pass
            
            if not mp3_files:
                return
            
            self.root.after(0, lambda: self.log(f"Verifying metadata for {len(mp3_files)} MP3 file(s)..."))
            
            fixed_count = 0
            for mp3_file in mp3_files:
                
                # Check if file has metadata
                tags = self.check_mp3_metadata(mp3_file)
                
                # Check if essential metadata is missing
                has_title = tags and tags.get("title") and tags.get("title").strip()
                has_artist = tags and tags.get("artist") and tags.get("artist").strip()
                has_album = tags and tags.get("album") and tags.get("album").strip()
                
                if not (has_title and has_artist and has_album):
                    # Try to find metadata from download_info
                    # Match by filename
                    metadata = None
                    filename = mp3_file.stem
                    filename_lower = filename.lower()
                    
                    # Try matching by title (download_info is keyed by title)
                    for title_key, track_meta in self.download_info.items():
                        # Check if filename matches title
                        if filename_lower in title_key or title_key in filename_lower:
                            metadata = track_meta.copy()
                            break
                        # Also check if track title contains filename
                        if track_meta.get("title") and filename_lower in track_meta["title"].lower():
                            metadata = track_meta.copy()
                            break
                    
                    # If not found, use album-level info and filename as title
                    if not metadata:
                        metadata = {
                            "title": filename,
                            "artist": self.album_info_stored.get("artist"),
                            "album": self.album_info_stored.get("album"),
                            "date": self.album_info_stored.get("date"),
                        }
                    
                    # Find thumbnail
                    thumbnail_file = self.find_thumbnail_file(str(mp3_file))
                    
                    # Re-embed metadata
                    if metadata.get("artist") or metadata.get("album") or metadata.get("title"):
                        self.root.after(0, lambda f=mp3_file.name: self.log(f"Fixing metadata: {f}"))
                        if self.re_embed_mp3_metadata(mp3_file, metadata, thumbnail_file):
                            fixed_count += 1
                            self.root.after(0, lambda f=mp3_file.name: self.log(f"✓ Fixed metadata: {f}"))
                        else:
                            self.root.after(0, lambda f=mp3_file.name: self.log(f"⚠ Could not fix metadata: {f}"))
            
            if fixed_count > 0:
                self.root.after(0, lambda count=fixed_count: self.log(f"Fixed metadata for {count} file(s)"))
        
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Error verifying MP3 metadata: {str(e)}"))
    
    def deduplicate_cover_art(self, directories):
        """Remove duplicate cover art files - keep only one if all are identical."""
        # Cache hashes to avoid recalculating for same files
        hash_cache = {}
        
        for directory in directories:
            # Find all cover art files in this directory (single glob call per directory)
            cover_art_files = []
            for ext in self.THUMBNAIL_EXTENSIONS:
                cover_art_files.extend(directory.glob(f"*{ext}"))
            
            if len(cover_art_files) <= 1:
                continue  # No duplicates possible
            
            # Calculate hashes for all cover art files (with caching)
            file_hashes = {}
            for thumb_file in cover_art_files:
                file_hash = self.get_file_hash(thumb_file, cache=hash_cache)
                if file_hash:
                    if file_hash not in file_hashes:
                        file_hashes[file_hash] = []
                    file_hashes[file_hash].append(thumb_file)
            
            # If all files have the same hash, keep only one
            if len(file_hashes) == 1:
                # All files are identical - keep the first one, delete the rest
                files_to_keep = list(file_hashes.values())[0]
                if len(files_to_keep) > 1:
                    # Keep the first file (prefer common names like 'cover', 'album', etc.)
                    files_to_keep.sort(key=lambda f: (
                        0 if any(name in f.stem.lower() for name in ['cover', 'album', 'folder', 'artwork']) else 1,
                        f.name
                    ))
                    kept_file = files_to_keep[0]
                    deleted_count = 0
                    for file_to_delete in files_to_keep[1:]:
                        try:
                            file_to_delete.unlink()
                            deleted_count += 1
                        except Exception:
                            pass
                    if deleted_count > 0:
                        self.root.after(0, lambda count=deleted_count, dir=str(directory): 
                                       self.log(f"Removed {count} duplicate cover art file(s) in {Path(dir).name}"))
            else:
                # Files are different - keep them all
                self.root.after(0, lambda count=len(cover_art_files): 
                               self.log(f"Keeping {count} unique cover art file(s) (they differ)"))
    
    def create_playlist_file(self, download_path, format_val):
        """Create an .m3u playlist file with all downloaded tracks."""
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Get file extensions for the format
            if format_val:
                extensions = self.FORMAT_EXTENSIONS.get(format_val, [".mp3"])
            else:
                # If format is unknown, check all audio formats
                extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav"]
            
            # Find all audio files
            audio_files = []
            for ext in extensions:
                audio_files.extend(base_path.rglob(f"*{ext}"))
            
            if not audio_files:
                return
            
            # Sort files by name to maintain track order
            audio_files.sort(key=lambda x: x.name)
            
            # Determine playlist location (in the album folder, or root if flat structure)
            # Find the directory containing the first file
            if len(audio_files) > 0:
                playlist_dir = audio_files[0].parent
                
                # Create playlist filename based on album name
                album_name = self.album_info_stored.get("album") or "Album"
                # Sanitize filename
                playlist_name = self.sanitize_filename(album_name)
                if not playlist_name:
                    playlist_name = "playlist"
                
                playlist_path = playlist_dir / f"{playlist_name}.m3u"
                
                # Write playlist file
                with open(playlist_path, 'w', encoding='utf-8') as f:
                    # Write M3U header
                    f.write("#EXTM3U\n")
                    
                    # Write each track entry
                    for audio_file in audio_files:
                        # Skip temporary files
                        if audio_file.name.startswith('.') or 'tmp' in audio_file.name.lower():
                            continue
                        
                        # Get relative path from playlist location
                        try:
                            relative_path = audio_file.relative_to(playlist_dir)
                            # Use forward slashes for M3U format (works on Windows too)
                            relative_path_str = str(relative_path).replace('\\', '/')
                        except ValueError:
                            # If files are in different directories, use absolute path
                            relative_path_str = str(audio_file)
                        
                        # Try to get track title from metadata or filename
                        track_title = audio_file.stem  # Default to filename without extension
                        
                        # Try to find track in download_info
                        for title_key, info in self.download_info.items():
                            # Match by comparing filename with track title
                            if audio_file.stem.lower() in title_key or title_key in audio_file.stem.lower():
                                track_title = info.get("title", track_title)
                                break
                        
                        # Write EXTINF line (duration is optional, use -1 if unknown)
                        f.write(f"#EXTINF:-1,{track_title}\n")
                        # Write file path
                        f.write(f"{relative_path_str}\n")
                
                self.root.after(0, lambda: self.log(f"✓ Created playlist: {playlist_path.name}"))
                
        except Exception as e:
            self.root.after(0, lambda: self.log(f"⚠ Could not create playlist: {str(e)}"))
    
    def download_album(self, url):
        """Download the album."""
        try:
            # Get format settings
            format_val = self.format_var.get()
            base_format = self._extract_format(format_val)
            skip_postprocessing = self.skip_postprocessing_var.get()
            download_cover_art = self.download_cover_art_var.get()
            
            # Configure postprocessors based on format
            postprocessors = []
            
            # If skip post-processing is enabled, only add metadata/thumbnail postprocessors (no format conversion)
            if skip_postprocessing:
                # Only add metadata and thumbnail embedding, no format conversion
                # This will output whatever format yt-dlp downloads (likely original format from Bandcamp)
                postprocessors = [
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ]
                # Only embed thumbnail if download_cover_art is disabled (to keep files separate when enabled)
                if not download_cover_art:
                    postprocessors.append({
                        "key": "EmbedThumbnail",
                        "already_have_thumbnail": False,
                    })
            elif base_format == "mp3":
                # Always use 128kbps for MP3 (matches source quality)
                postprocessors = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ]
                # Only embed thumbnail if download_cover_art is disabled (to keep files separate when enabled)
                if not download_cover_art:
                    postprocessors.append({
                        "key": "EmbedThumbnail",
                        "already_have_thumbnail": False,
                    })
            elif base_format == "flac":
                postprocessors = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "flac",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ]
            elif format_val == "ogg":
                postprocessors = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "vorbis",
                        "preferredquality": "9",  # High quality, but still converted from 128kbps source
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ]
            elif format_val == "wav":
                postprocessors = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "wav",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ]
            
            # Match filter to reject entries when cancelling
            def match_filter(info_dict):
                """Reject entries if cancellation is requested."""
                if self.is_cancelling:
                    return "Cancelled by user"
                return None  # None means accept the entry
            
            # yt-dlp options
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": self.get_outtmpl(),
                "ffmpeg_location": str(self.ffmpeg_path),
                "writethumbnail": True,
                "postprocessors": postprocessors,
                "noplaylist": False,
                "ignoreerrors": True,
                "quiet": False,  # Keep False to show console output and enable progress hooks
                "no_warnings": False,  # Show warnings in console
                "noprogress": False,  # Keep progress enabled so hooks are called frequently
                "progress_hooks": [self.progress_hook],
                "match_filter": match_filter,  # Reject entries when cancelling
            }
            
            # Store info for post-processing (maps filenames to metadata)
            self.download_info = {}
            self.album_info_stored = {}
            self.downloaded_files = set()  # Track files that were just downloaded
            self.download_start_time = None  # Track when download started
            self.total_tracks = 0  # Total number of tracks in album
            self.current_track = 0  # Current track being downloaded (0-based, will be incremented as tracks finish)
            
            # Get download start time
            self.download_start_time = time.time()
            
            # Two-phase extraction for better user experience:
            # Phase 1: Quick flat extraction to get track count (fast, ~1-2 seconds)
            # Phase 2: Full extraction for detailed metadata (slower, but user already sees progress)
            self.root.after(0, lambda: self.progress_var.set("Fetching album information..."))
            self.root.after(0, lambda: self.log("Fetching album information..."))
            
            # Phase 1: Quick flat extraction to get track count immediately
            try:
                quick_opts = {
                    "extract_flat": True,  # Fast mode - just get playlist structure
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": False,
                    "socket_timeout": 10,  # Faster timeout detection
                    "retries": 3,  # Fewer retries for faster failure
                }
                
                with yt_dlp.YoutubeDL(quick_opts) as quick_ydl:
                    quick_info = quick_ydl.extract_info(url, download=False)
                    if quick_info and "entries" in quick_info:
                        entries = [e for e in quick_info.get("entries", []) if e]
                        self.total_tracks = len(entries)
                        self.root.after(0, lambda count=len(entries): self.log(f"Found {count} track(s)"))
                        self.root.after(0, lambda count=len(entries): self.progress_var.set(f"Found {count} track(s) - Fetching track data..."))
            except Exception:
                # If quick extraction fails, continue to full extraction
                pass
            
            # Phase 2: Full extraction for detailed metadata (necessary for progress tracking and verification)
            try:
                extract_opts = ydl_opts.copy()
                extract_opts["extract_flat"] = False  # Get full metadata
                extract_opts["quiet"] = True
                extract_opts["no_warnings"] = True
                extract_opts["socket_timeout"] = 10  # Faster timeout detection
                extract_opts["retries"] = 3  # Fewer retries for faster failure
                
                with yt_dlp.YoutubeDL(extract_opts) as extract_ydl:
                    info = extract_ydl.extract_info(url, download=False)
                    if info:
                        # Store album-level info
                        self.album_info_stored = {
                            "artist": info.get("artist") or info.get("uploader") or info.get("creator"),
                            "album": info.get("album") or info.get("title"),
                            "date": info.get("release_date") or info.get("upload_date"),
                        }
                        
                        # Store metadata for each track and update total tracks if not already set
                        if "entries" in info:
                            entries = [e for e in info.get("entries", []) if e]  # Filter out None entries
                            if self.total_tracks == 0:  # Only update if quick extraction didn't work
                                self.total_tracks = len(entries)
                                self.root.after(0, lambda count=len(entries): self.log(f"Found {count} track(s)"))
                            
                            # Log format/bitrate info from first track (to show what yt-dlp is downloading)
                            # Always show source info so users know what quality they're getting
                            if entries:
                                first_entry = entries[0]
                                format_info = []
                                if first_entry.get("format"):
                                    format_info.append(f"Format: {first_entry.get('format')}")
                                if first_entry.get("abr"):
                                    format_info.append(f"Bitrate: {first_entry.get('abr')} kbps")
                                elif first_entry.get("tbr"):
                                    format_info.append(f"Bitrate: {first_entry.get('tbr')} kbps")
                                if first_entry.get("acodec"):
                                    format_info.append(f"Codec: {first_entry.get('acodec')}")
                                if first_entry.get("ext"):
                                    format_info.append(f"Extension: {first_entry.get('ext')}")
                                if format_info:
                                    self.root.after(0, lambda info=" | ".join(format_info): self.log(f"Source: {info}"))
                            
                            for entry in entries:
                                # Use title as key (will match by filename later)
                                title = entry.get("title", "")
                                if title:
                                    self.download_info[title.lower()] = {
                                        "title": entry.get("title"),
                                        "artist": entry.get("artist") or entry.get("uploader") or entry.get("creator") or self.album_info_stored.get("artist"),
                                        "album": entry.get("album") or info.get("title") or self.album_info_stored.get("album"),
                                        "track_number": entry.get("track_number") or entry.get("track"),
                                        "date": entry.get("release_date") or entry.get("upload_date") or self.album_info_stored.get("date"),
                                    }
            except Exception:
                # If extraction fails, continue with download anyway
                self.root.after(0, lambda: self.log("Warning: Could not fetch full metadata, continuing anyway..."))
                pass
            
            # Update status before starting download
            self.root.after(0, lambda: self.progress_var.set("Starting download..."))
            self.root.after(0, lambda: self.log("Starting download..."))
            
            # Get download path and count existing files before download
            download_path = self.path_var.get().strip()
            base_path = Path(download_path) if download_path else None
            
            # Count existing audio files before download (to verify files were actually downloaded)
            existing_files_before = set()
            if base_path and base_path.exists():
                for ext in self.FORMAT_EXTENSIONS.get(format_val, []):
                    existing_files_before.update(base_path.rglob(f"*{ext}"))
            
            # Download (store instance for cancellation)
            ydl = yt_dlp.YoutubeDL(ydl_opts)
            self.ydl_instance = ydl
            
            try:
                ydl.download([url])
            except KeyboardInterrupt:
                # Check if this was our cancellation or user's Ctrl+C
                if self.is_cancelling:
                    # Our cancellation - exit gracefully
                    self.ydl_instance = None
                    self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                    return
                # User's Ctrl+C - re-raise
                raise
            finally:
                # Clear instance after download
                self.ydl_instance = None
                
                # Check if cancelled - if so, exit early
                if self.is_cancelling:
                    self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                    return
            
            # Verify that files were actually downloaded
            files_downloaded = False
            if base_path and base_path.exists():
                # Count files after download
                existing_files_after = set()
                if skip_postprocessing:
                    # When skipping post-processing, check all audio formats
                    all_exts = [".mp3", ".flac", ".ogg", ".oga", ".wav"]
                    for ext in all_exts:
                        existing_files_after.update(base_path.rglob(f"*{ext}"))
                else:
                    for ext in self.FORMAT_EXTENSIONS.get(format_val, []):
                        existing_files_after.update(base_path.rglob(f"*{ext}"))
                
                # Check if new files were created
                new_files = existing_files_after - existing_files_before
                files_downloaded = len(new_files) > 0
                
                # Also check if files in downloaded_files set exist
                if hasattr(self, 'downloaded_files') and self.downloaded_files:
                    for file_path in self.downloaded_files:
                        if Path(file_path).exists():
                            files_downloaded = True
                            break
            
            # If no files were downloaded, it likely requires purchase/login
            if not files_downloaded:
                error_msg = (
                    "No files were downloaded. This album may require purchase or login.\n\n"
                    "Bandcamp albums that require purchase cannot be downloaded without:\n"
                    "• Purchasing the album first\n"
                    "• Logging into your Bandcamp account\n"
                    "• Using cookies for authentication\n\n"
                    "Please purchase the album on Bandcamp or check if it's available for free download."
                )
                self.root.after(0, self.download_complete, False, error_msg)
                return
            
            # Process downloaded files
            if download_path:
                # For MP3, verify and fix metadata if needed
                if base_format == "mp3":
                    self.verify_and_fix_mp3_metadata(download_path)
                # Process other formats (FLAC, OGG, WAV)
                self.process_downloaded_files(download_path)
                
                # Create playlist file if enabled
                if self.create_playlist_var.get():
                    self.create_playlist_file(download_path, base_format)
            
            # Success
            self.root.after(0, self.download_complete, True, "Download complete!")
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = self._format_error_message(str(e))
            self.root.after(0, self.download_complete, False, error_msg)
        except KeyboardInterrupt:
            # User pressed Ctrl+C - treat as error
            self.root.after(0, self.download_complete, False, "Download interrupted by user.")
        except Exception as e:
            error_msg = self._format_error_message(str(e), is_unexpected=True)
            self.root.after(0, self.download_complete, False, error_msg)
    
    def format_bytes(self, bytes_val):
        """Format bytes to human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.2f} TB"
    
    def format_time(self, seconds):
        """Format seconds to human-readable time string."""
        if seconds is None or seconds < 0:
            return "Calculating..."
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"
    
    def progress_hook(self, d):
        """Progress hook for yt-dlp - fresh clean implementation."""
        # Check cancellation first - if cancelled, raise KeyboardInterrupt to stop current track immediately
        if self.is_cancelling:
            raise KeyboardInterrupt("Download cancelled by user")
        
        try:
            status = d.get('status', '')
            
            if status == 'downloading':
                # Get track/playlist info
                # Note: playlist_index might only be present at the start of each track
                # We'll use it if available, but rely on incrementing when tracks finish
                playlist_index = d.get('playlist_index')
                if playlist_index is not None:
                    # Store 0-based index (0-based internally for consistency)
                    # Only update if it's different (new track started)
                    if playlist_index != self.current_track:
                        self.current_track = playlist_index
                
                # Get raw values from yt-dlp progress dict
                downloaded = d.get('downloaded_bytes', 0) or 0
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                speed = d.get('speed')
                eta = d.get('eta')
                
                # Calculate percentage
                percent = None
                if total > 0:
                    percent = min(100.0, max(0.0, (downloaded / total) * 100.0))
                
                # Format speed
                speed_str = None
                if speed and isinstance(speed, (int, float)) and speed > 0:
                    speed_str = self.format_bytes(speed) + "/s"
                
                # Format ETA - only show if meaningful (not 0s or very short)
                eta_str = None
                if eta is not None and isinstance(eta, (int, float)) and eta >= 5:  # Only show if >= 5 seconds
                    eta_str = self.format_time(eta)
                
                # Build progress text with track info
                track_prefix = ""
                if self.total_tracks > 0:
                    # Use stored current_track (0-based) and convert to 1-based for display
                    # current_track is incremented when each track finishes
                    current_track_1based = self.current_track + 1 if self.current_track >= 0 else 1
                    # Make sure we don't exceed total tracks
                    if current_track_1based > self.total_tracks:
                        current_track_1based = self.total_tracks
                    track_prefix = f"{current_track_1based} of {self.total_tracks}: "
                
                # Build progress text parts
                parts = []
                if percent is not None:
                    parts.append(f"{percent:.1f}%")
                if speed_str:
                    parts.append(speed_str)
                if eta_str:  # Only add ETA if meaningful
                    parts.append(f"ETA: {eta_str}")
                
                # Create final progress text
                if parts:
                    progress_text = f"Downloading {track_prefix}" + " | ".join(parts)
                elif downloaded > 0:
                    progress_text = f"Downloading {track_prefix}{self.format_bytes(downloaded)}..."
                else:
                    progress_text = f"Downloading {track_prefix}..."
                
                # Calculate overall album progress
                overall_percent = None
                if self.total_tracks > 0:
                    # Overall progress = (completed tracks + current track progress) / total tracks
                    # completed_tracks = current_track (0-based, so track 0 means 0 completed)
                    # current_track_progress = percent / 100.0 (0.0 to 1.0)
                    completed_tracks = self.current_track  # 0-based: 0 = first track, 1 = second track, etc.
                    current_track_progress = (percent / 100.0) if percent is not None else 0.0
                    overall_progress = (completed_tracks + current_track_progress) / self.total_tracks
                    overall_percent = overall_progress * 100.0
                
                # Update UI - capture values in closure properly
                def update_progress(text=progress_text, pct=percent, overall_pct=overall_percent):
                    
                    # Always update the progress text
                    self.progress_var.set(text)
                    
                    # Update overall album progress bar (thin bar below)
                    # Show it when we first get progress data (after first file starts downloading)
                    if overall_pct is not None and hasattr(self, 'overall_progress_bar'):
                        try:
                            # Show the overall progress bar if it's not already visible
                            if not self.overall_progress_bar.winfo_viewable():
                                self.overall_progress_bar.grid()
                            self.overall_progress_bar.config(mode='determinate', value=overall_pct)
                        except:
                            pass
                    
                    # Update track progress bar (main bar above)
                    if pct is not None:
                        # Stop indeterminate animation if running
                        try:
                            if self.progress_bar.cget('mode') == 'indeterminate':
                                self.progress_bar.stop()
                        except:
                            pass
                        # Switch to determinate mode and set value
                        self.progress_bar.config(mode='determinate', maximum=100, value=pct)
                    else:
                        # Keep indeterminate mode if no percentage available
                        if self.progress_bar.cget('mode') != 'indeterminate':
                            self.progress_bar.config(mode='indeterminate')
                            self.progress_bar.start(10)
                
                self.root.after(0, update_progress)
            
            elif status == 'finished':
                # Update track counter when a track finishes - increment to next track
                # This ensures we show the correct track number for the next track that will download
                # Only increment if we haven't reached the total
                if self.current_track < self.total_tracks - 1:
                    self.current_track += 1
                
                filename = d.get('filename', '')
                if filename and hasattr(self, 'downloaded_files'):
                    self.downloaded_files.add(filename)
                
                self.root.after(0, lambda: self.log(f"Processing: {d.get('filename', 'Unknown')}"))
            
            elif status == 'error':
                error_msg = d.get('error', 'Unknown error')
                self.root.after(0, lambda msg=error_msg: self.log(f"Error: {msg}"))
        
        except KeyboardInterrupt:
            raise
        except Exception:
            # Silently handle any errors in progress hook to not break download
            pass
    
    def _format_error_message(self, error_str, is_unexpected=False):
        """Format error messages to be more user-friendly."""
        error_lower = error_str.lower()
        
        # Network errors
        if any(term in error_lower for term in ['network', 'connection', 'timeout', 'dns', 'unreachable']):
            return f"Network Error: Unable to connect to Bandcamp.\n\nPossible causes:\n• No internet connection\n• Network timeout\n• Firewall blocking connection\n\nOriginal error: {error_str[:200]}"
        
        # Permission/access errors
        if any(term in error_lower for term in ['permission', 'access denied', 'forbidden', '403', '401']):
            return f"Access Error: Cannot access this album.\n\nPossible causes:\n• Album requires purchase or login\n• Private or restricted album\n• Bandcamp access issue\n\nOriginal error: {error_str[:200]}"
        
        # Not found errors
        if any(term in error_lower for term in ['not found', '404', 'does not exist', 'invalid url']):
            return f"Not Found: The album URL is invalid or the album no longer exists.\n\nPlease check:\n• The URL is correct\n• The album is still available\n• You have permission to access it\n\nOriginal error: {error_str[:200]}"
        
        # Disk space errors
        if any(term in error_lower for term in ['no space', 'disk full', 'insufficient space']):
            return f"Disk Space Error: Not enough space to save the download.\n\nPlease free up disk space and try again.\n\nOriginal error: {error_str[:200]}"
        
        # Format-specific errors
        if any(term in error_lower for term in ['format', 'codec', 'ffmpeg']):
            return f"Format Error: Problem processing audio format.\n\nPlease try:\n• A different audio format\n• Checking if ffmpeg.exe is working correctly\n\nOriginal error: {error_str[:200]}"
        
        # Generic error
        if is_unexpected:
            return f"Unexpected Error: {error_str[:300]}\n\nIf this persists, please check:\n• Your internet connection\n• The Bandcamp URL is correct\n• You have sufficient disk space"
        else:
            return f"Download Error: {error_str[:300]}"
    
    def download_complete(self, success, message):
        """Handle download completion."""
        # Stop progress bar animation immediately
        try:
            self.progress_bar.stop()
        except:
            pass
        
        # Restore UI state immediately - do this FIRST before any other operations
        self.is_cancelling = False
        self.ydl_instance = None
        
        # Restore buttons
        try:
            self.cancel_btn.grid_remove()
            self.cancel_btn.config(state='disabled')
        except:
            pass
        self.download_btn.config(state='normal')
        self.download_btn.grid()
        
        if success:
            # Show 100% completion for main progress bar
            self.progress_bar.config(mode='determinate', value=100)
            # Hide overall progress bar after completion
            if hasattr(self, 'overall_progress_bar') and self.overall_progress_bar:
                try:
                    self.overall_progress_bar.grid_remove()
                except:
                    pass
            self.progress_var.set("Download complete!")
            self.log("")
            self.log("[OK] Download complete!")
            messagebox.showinfo("Success", message)
        else:
            # Reset progress bar for failed/cancelled downloads
            self.progress_bar.config(mode='determinate', value=0)
            # Hide overall progress bar after failure/cancellation
            if hasattr(self, 'overall_progress_bar') and self.overall_progress_bar:
                try:
                    self.overall_progress_bar.grid_remove()
                except:
                    pass
            
            # Check if this is a cancellation (expected) vs an error
            is_cancelled = "cancelled" in message.lower()
            
            if is_cancelled:
                self.progress_var.set("Download cancelled")
                self.log("")
                self.log(f"[X] {message}")
                messagebox.showinfo("Cancelled", message)
            else:
                self.progress_var.set("Download failed")
                self.log("")
                self.log(f"[X] {message}")
                messagebox.showerror("Error", message)


def main():
    """Main entry point."""
    root = Tk()
    app = BandcampDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

