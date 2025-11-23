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
    Frame, Label, Canvas, Checkbutton, Menu, Entry, Button
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
        "original": [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mpa", ".aac", ".opus"],  # Common audio formats
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
        if format_val == "Original":
            return "original"
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
        self.default_window_height = window_height  # Store default height for expand/collapse
        self.expand_amount = 150  # Amount to expand by
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        center_x = int(screen_width / 2 - window_width / 2)
        center_y = int(screen_height / 2 - window_height / 2)
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        
        # Allow vertical resizing only (width fixed, height resizable)
        # Set minimum height to current height
        self.root.resizable(False, True)
        self.root.minsize(window_width, window_height)
        
        # Get script directory first (needed for icon path)
        self.script_dir = Path(__file__).resolve().parent
        self.ffmpeg_path = None
        self.ydl = None
        
        # Variables
        self.url_var = StringVar()
        self.path_var = StringVar()
        # Initialize with numeric value, will be converted to display value in setup_ui
        saved_choice = self.get_default_preference()
        # Convert to display value immediately
        display_value = self.FOLDER_STRUCTURES.get(saved_choice, self.FOLDER_STRUCTURES[self.DEFAULT_STRUCTURE])
        self.folder_structure_var = StringVar(value=display_value)
        self.format_var = StringVar(value=self.load_saved_format())
        self.numbering_var = StringVar(value=self.load_saved_numbering())
        self.skip_postprocessing_var = BooleanVar(value=self.load_saved_skip_postprocessing())
        self.create_playlist_var = BooleanVar(value=self.load_saved_create_playlist())
        self.download_cover_art_var = BooleanVar(value=self.load_saved_download_cover_art())
        self.download_discography_var = BooleanVar(value=False)  # Always default to off, not persistent
        
        # Batch URL mode tracking
        self.batch_mode = False  # Track if we're in batch mode (multiple URLs)
        self.url_entry_widget = None  # Store reference to Entry widget
        self.url_text_widget = None  # Store reference to ScrolledText widget
        self.url_container_frame = None  # Container frame for URL widgets
        
        # Content history for undo/redo functionality (tracks content state, not just pastes)
        self.content_history = []  # List of content states (full field content at each change)
        self.content_history_index = -1  # Current position in history (-1 = most recent)
        self.content_save_timer = None  # Timer for debounced content state saving
        
        # Debug mode flag (default: False)
        self.debug_mode = False
        
        # Store metadata for preview
        self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
        self.format_suggestion_shown = False  # Track if format suggestion has been shown for current URL
        self.url_check_timer = None  # For debouncing URL changes
        self.album_art_image = None  # Store reference to prevent garbage collection
        self.album_art_fetching = False  # Flag to prevent multiple simultaneous fetches
        self.current_thumbnail_url = None  # Track current thumbnail to avoid re-downloading
        self.artwork_fetch_id = 0  # Track fetch requests to cancel stale ones
        self.current_url_being_processed = None  # Track URL currently being processed to avoid cancelling valid fetches
        self.album_art_visible = True  # Track album art panel visibility
        
        # URL text widget resize state
        self.url_text_height = 2  # Default height in lines
        self.url_text_max_height_px = 250  # Maximum height in pixels
        self.url_text_resizing = False  # Track if currently resizing
        self.url_text_resize_start_y = 0  # Starting Y position for resize
        self.url_text_resize_start_height = 0  # Starting height for resize
        self.url_text_resize_drag_started = False  # Track if drag has actually started
        
        # Download control
        self.download_thread = None
        self.is_cancelling = False
        self.ydl_instance = None  # Store yt-dlp instance for cancellation
        
        # Search/find functionality for log
        self.search_frame = None  # Search bar frame
        self.search_entry = None  # Search input field
        self.search_matches = []  # List of match positions
        self.current_match_index = -1  # Current match position
        self.search_tag_name = "search_match"  # Tag name for all matches (yellow)
        self.current_match_tag_name = "current_search_match"  # Tag name for current match (green)
        
        # Check dependencies first
        if not self.check_dependencies():
            self.root.destroy()
            return
        
        self.setup_dark_mode()
        self.setup_ui()
        self.load_saved_path()
        self.load_saved_album_art_state()
        self.update_preview()
        # Initialize URL count and button text
        self.root.after(100, self._update_url_count_and_button)
        # Initialize clear button visibility
        self.root.after(100, self._update_url_clear_button)
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
        
        # Bind to window resize events to update expand/collapse button state
        self.root.bind('<Configure>', self._on_window_configure)
    
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
                       padding=(15, 8), font=("Segoe UI", 10, "bold"), width=25)
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
                        arrowcolor='#808080',  # Gray arrows matching expand/collapse button
                        background=select_bg)  # Button area matches browse button
        style.map('TCombobox',
                 fieldbackground=[('readonly', entry_bg)],
                 bordercolor=[('focus', accent_color), ('!focus', border_color)],
                 arrowcolor=[('active', '#808080'), ('!active', '#808080')],  # Always gray, always visible
                 background=[('active', select_bg), ('!active', select_bg)])  # Button area always dark
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
                # download_discography is intentionally not saved - always defaults to off
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
        if format_val in ["Original", "mp3", "mp3 (128kbps)", "flac", "ogg", "wav"]:
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
                # Show the button by making it visible (it's always in grid, just invisible)
                self.show_album_art_btn.config(fg='#808080', cursor='hand2')
    
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
    
    def load_saved_download_discography(self):
        """Load saved download discography preference, default to False if not found."""
        # This function is kept for compatibility but always returns False
        # download_discography is intentionally not persistent
        return False
    
    def save_download_discography(self):
        """Save download discography preference."""
        # Intentionally does nothing - download_discography is not persistent
        pass
    
    def on_download_discography_change(self):
        """Handle download discography checkbox change."""
        # Update button text when discography mode changes
        self._update_url_count_and_button()
    
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
        
        # URL input - supports both single Entry and multi-line ScrolledText
        ttk.Label(main_frame, text="Album URL:", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky=(W, N), pady=2
        )
        
        # Container frame for URL widgets (Entry and ScrolledText)
        self.url_container_frame = Frame(main_frame, bg='#1E1E1E')
        self.url_container_frame.grid(row=0, column=1, columnspan=2, sticky=(W, E), pady=2, padx=(8, 0))
        self.url_container_frame.columnconfigure(0, weight=1)  # URL field expands
        self.url_container_frame.columnconfigure(1, weight=0, minsize=20)  # Clear button fixed width
        self.url_container_frame.columnconfigure(2, weight=0, minsize=20)  # Expand button fixed width
        self.url_container_frame.rowconfigure(0, weight=1)  # Allow vertical expansion for ScrolledText
        
        # Single-line Entry widget (default)
        url_entry = ttk.Entry(
            self.url_container_frame,
            textvariable=self.url_var,
            width=45,
            font=("Segoe UI", 9)
        )
        url_entry.grid(row=0, column=0, sticky=(W, E), pady=0, padx=(0, 4))
        self.url_entry_widget = url_entry
        
        # Add placeholder text to Entry
        self._set_entry_placeholder(url_entry, "Paste one URL or multiple to create a batch.")
        
        # Clear button (X) - appears when URL field has content
        # Use smaller font and minimal padding to match entry field height
        self.url_clear_btn = Label(
            self.url_container_frame,
            text="✕",
            font=("Segoe UI", 9),
            bg='#1E1E1E',
            fg='#808080',
            cursor='hand2',
            width=1,
            height=1,
            padx=2,
            pady=0
        )
        # Use grid_remove (not grid_forget) to preserve space, sticky='' prevents expansion
        # Align to center vertically to match entry field
        self.url_clear_btn.grid(row=0, column=1, sticky='', pady=0, padx=(2, 0))
        self.url_clear_btn.bind("<Button-1>", lambda e: self._clear_url_field())
        self.url_clear_btn.bind("<Enter>", lambda e: self.url_clear_btn.config(fg='#D4D4D4'))
        self.url_clear_btn.bind("<Leave>", lambda e: self.url_clear_btn.config(fg='#808080'))
        # Always visible - no grid_remove()
        
        # Expand/Collapse button - toggles between Entry and ScrolledText modes
        # Shows expand icon (⤢) in Entry mode, collapse icon (⤡) in ScrolledText mode
        self.url_expand_btn = Label(
            self.url_container_frame,
            text="⤢",  # Default to expand icon
            font=("Segoe UI", 9),
            bg='#1E1E1E',
            fg='#808080',
            cursor='hand2',
            width=1,
            height=1,
            padx=2,
            pady=0
        )
        # Use grid_remove to preserve space, sticky='' prevents expansion
        self.url_expand_btn.grid(row=0, column=2, sticky='', pady=0, padx=(2, 0))
        self.url_expand_btn.bind("<Button-1>", lambda e: self._toggle_url_field_mode())
        self.url_expand_btn.bind("<Enter>", lambda e: self.url_expand_btn.config(fg='#D4D4D4'))
        self.url_expand_btn.bind("<Leave>", lambda e: self.url_expand_btn.config(fg='#808080'))
        # Always visible - no grid_remove()
        
        # Bind events for Entry
        url_entry.bind('<Control-v>', self._handle_entry_paste)
        url_entry.bind('<Shift-Insert>', self._handle_entry_paste)
        url_entry.bind('<Button-2>', self._handle_entry_paste)  # Middle mouse button paste
        url_entry.bind('<Button-3>', self._handle_right_click_paste_entry)  # Right mouse button
        url_entry.bind('<KeyRelease>', lambda e: (self.on_url_change(), self._check_entry_for_newlines(), self._update_url_clear_button()))
        url_entry.bind('<Return>', self._handle_entry_return)  # Enter key - expand to multi-line
        url_entry.bind('<Control-z>', self._handle_entry_undo)  # Undo (Ctrl+Z)
        url_entry.bind('<Control-Shift-Z>', self._handle_entry_redo)  # Redo (Ctrl+Shift+Z)
        url_entry.bind('<Control-y>', self._handle_entry_redo)  # Redo (Ctrl+Y - alternative)
        
        # Multi-line ScrolledText widget (hidden initially, shown when needed)
        url_text_frame = Frame(self.url_container_frame, bg='#1E1E1E')
        url_text_frame.grid(row=0, column=0, sticky=(W, E, N, S), pady=0)
        url_text_frame.columnconfigure(0, weight=1)
        url_text_frame.rowconfigure(0, weight=1)
        url_text_frame.grid_remove()  # Hidden initially
        self.url_text_frame = url_text_frame  # Store reference for easier access
        
        url_text = scrolledtext.ScrolledText(
            url_text_frame,
            width=45,
            height=2,  # Start with 2 lines (collapsed)
            font=("Segoe UI", 9),
            bg='#252526',
            fg='#CCCCCC',
            insertbackground='#D4D4D4',
            relief='flat',
            borderwidth=1,
            highlightthickness=1,
            highlightbackground='#3E3E42',
            highlightcolor='#007ACC',
            wrap='none'  # Disable text wrapping
        )
        url_text.grid(row=0, column=0, sticky=(W, E, N, S))
        self.url_text_widget = url_text
        
        # Create resize handle at the bottom of the text widget (thin, minimal space)
        self.url_text_resize_handle = Label(
            url_text_frame,
            text="━\n━\n━",  # Three stacked lines for grip icon to indicate draggable
            bg='#252526',  # Match text widget background to blend in
            fg='#A0A0A0',  # Lighter gray for better visibility
            cursor='sb_v_double_arrow',  # Vertical resize cursor
            height=3,  # Allow space for 3 lines
            relief='flat',
            borderwidth=0,
            font=("Segoe UI", 7),  # Slightly larger font for better visibility
            anchor='center',  # Center the text
            justify='center',  # Center the lines
            wraplength=50  # Allow text wrapping if needed
        )
        # Use place() to position it just above the bottom edge, centered and narrower
        # This way it doesn't take up grid space, doesn't cover borders or scrollbar
        # Position it centered with some padding from edges
        # Height matches user's adjustment (10px) to accommodate 3 stacked lines
        self.url_text_resize_handle.place(relx=0.5, rely=1.0, relwidth=0.9, anchor='s', height=10, y=-1)
        self.url_text_resize_handle.lower()  # Place behind text widget initially
        self.url_text_resize_handle.place_forget()  # Hidden initially, shown when text widget is visible
        
        # Bind resize handle events
        self.url_text_resize_handle.bind("<Button-1>", self._start_url_text_resize)
        self.url_text_resize_handle.bind("<B1-Motion>", self._on_url_text_resize)
        self.url_text_resize_handle.bind("<ButtonRelease-1>", self._end_url_text_resize)
        self.url_text_resize_handle.bind("<Double-Button-1>", self._toggle_url_text_height)
        
        # Create placeholder label overlay (ghost text that doesn't interfere with content)
        # This will be positioned over the ScrolledText but won't interfere with editing
        placeholder_label = Label(
            url_text_frame,
            text="Paste one URL or multiple to create a batch.",
            font=("Segoe UI", 9),
            bg='#252526',
            fg='#808080',
            anchor='nw',
            justify='left',
            padx=4,
            pady=2,
            cursor='xterm'  # Text cursor (I-beam) to blend with the field
        )
        # Position the label to overlay the text widget (same position)
        placeholder_label.place(x=4, y=2, anchor='nw')
        # Make label non-interactive - pass all events through to text widget
        placeholder_label.bind('<Button-1>', lambda e: url_text.focus_set())
        placeholder_label.bind('<Key>', lambda e: url_text.focus_set())
        placeholder_label.bind('<FocusIn>', lambda e: url_text.focus_set())
        # Allow right-click on placeholder to show context menu
        placeholder_label.bind('<Button-3>', self._show_text_context_menu)
        self.url_text_placeholder_label = placeholder_label
        # Initially show placeholder since widget is empty
        self._update_text_placeholder_visibility()
        
        # Create custom context menu for ScrolledText
        context_menu = Menu(url_text, tearoff=0, bg='#252526', fg='#CCCCCC', 
                           activebackground='#007ACC', activeforeground='#FFFFFF',
                           selectcolor='#007ACC')
        context_menu.add_command(label="Paste", command=self._handle_right_click_paste_text)
        self.url_text_context_menu = context_menu
        
        # Bind events for ScrolledText
        url_text.bind('<Control-v>', self._handle_text_paste)
        url_text.bind('<Shift-Insert>', self._handle_text_paste)
        url_text.bind('<Button-2>', self._handle_text_paste)  # Middle mouse button paste
        url_text.bind('<Button-3>', self._show_text_context_menu)  # Right mouse button - show context menu
        url_text.bind('<KeyRelease>', lambda e: (self._on_text_key_release(), self._update_url_clear_button()))
        url_text.bind('<KeyPress>', lambda e: self._hide_text_placeholder())  # Hide on any key press
        url_text.bind('<Button-1>', lambda e: self._hide_text_placeholder())  # Hide on click
        url_text.bind('<FocusIn>', lambda e: self._on_text_focus_in())
        url_text.bind('<FocusOut>', lambda e: self._on_text_focus_out())
        url_text.bind('<Return>', self._handle_text_return)  # Enter key - save state when new line added
        url_text.bind('<Control-z>', self._handle_text_undo)  # Undo (Ctrl+Z)
        url_text.bind('<Control-Shift-Z>', self._handle_text_redo)  # Redo (Ctrl+Shift+Z)
        url_text.bind('<Control-y>', self._handle_text_redo)  # Redo (Ctrl+Y - alternative)
        
        # Download path - compact
        ttk.Label(main_frame, text="Download Path:", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky=W, pady=2
        )
        path_entry = ttk.Entry(main_frame, textvariable=self.path_var, width=35, font=("Segoe UI", 9), state='normal')
        path_entry.grid(row=1, column=1, sticky=(W, E), pady=2, padx=(8, 0))
        self.path_entry = path_entry  # Store reference for unfocus handling
        
        # Bind focus out event to deselect text when path entry loses focus
        def on_path_focus_out(event):
            path_entry.selection_clear()
        path_entry.bind('<FocusOut>', on_path_focus_out)
        
        browse_btn = ttk.Button(main_frame, text="Browse", command=self.browse_folder, cursor='hand2')
        browse_btn.grid(row=1, column=2, padx=(4, 0), pady=2)
        self.browse_btn = browse_btn  # Store reference for unfocus handling
        
        # Bind path changes to update preview
        self.path_var.trace_add('write', lambda *args: self.update_preview())
        self.folder_structure_var.trace_add('write', lambda *args: self.update_preview())
        # Note: URL changes are handled by direct event bindings, not trace_add
        # (trace_add would trigger on placeholder text changes)
        
        # Settings section - reduced width to make room for album art panel
        self.settings_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.settings_frame.grid(row=2, column=0, columnspan=2, sticky=(W, E, N), pady=6, padx=0)
        self.settings_frame.grid_propagate(False)
        self.settings_frame.config(height=170)  # Reduced height with equal padding top and bottom
        
        # Inner frame for content
        self.settings_content = Frame(self.settings_frame, bg='#1E1E1E')
        # Start at row 0 (no separate header row)
        self.settings_content.grid(row=0, column=0, sticky=(W, E), padx=6, pady=(6, 6))  # Equal padding top and bottom
        self.settings_frame.columnconfigure(0, weight=1)
        # Configure columns: label, combo, button (right-aligned)
        self.settings_content.columnconfigure(1, weight=1)  # Allow combo to expand
        
        # Album art panel (separate frame on the right, same height as settings, square for equal padding)
        self.album_art_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.album_art_frame.grid(row=2, column=2, sticky=(W, E, N), pady=6, padx=(6, 0))
        self.album_art_frame.grid_propagate(False)
        self.album_art_frame.config(width=170, height=170)  # Square panel matching settings height for equal padding
        # Center content in the frame
        self.album_art_frame.columnconfigure(0, weight=1)
        self.album_art_frame.rowconfigure(0, weight=1)
        
        # Album art canvas with consistent padding all around (10px padding = 150x150 canvas)
        self.album_art_canvas = Canvas(
            self.album_art_frame,
            width=150,
            height=150,
            bg='#1E1E1E',
            highlightthickness=0,
            borderwidth=0,
            cursor='hand2'  # Show hand cursor to indicate it's clickable
        )
        # Center the canvas with equal padding on all sides (10px on each side = 20px total, 150 + 20 = 170)
        self.album_art_canvas.grid(row=0, column=0, padx=10, pady=10)
        
        # Make canvas clickable to toggle album art
        self.album_art_canvas.bind("<Button-1>", lambda e: self.toggle_album_art())
        
        # Placeholder text on canvas (centered at 75, 75 for 150x150 canvas)
        self.album_art_canvas.create_text(
            75, 75,
            text="Album Art",
            fill='#808080',
            font=("Segoe UI", 8)
        )
        
        # Audio Format (first) - with eye icon button on the right when album art is hidden
        ttk.Label(self.settings_content, text="Audio Format:", font=("Segoe UI", 8)).grid(row=0, column=0, padx=4, sticky=W, pady=1)
        format_combo = ttk.Combobox(
            self.settings_content,
            textvariable=self.format_var,
            values=["Original", "mp3 (128kbps)", "flac", "ogg", "wav"],
            state="readonly",
            width=15
        )
        format_combo.grid(row=0, column=1, padx=4, sticky=W, pady=1)
        format_combo.bind("<<ComboboxSelected>>", lambda e: (self._deselect_combobox_text(e), self.on_format_change(e), self.update_preview()))
        
        # Show album art button (hidden by default, shown when album art is hidden)
        # Placed in the same row as Audio Format, right-aligned
        # Always keep it in grid to prevent layout shifts - just make it invisible when not needed
        self.show_album_art_btn = Label(
            self.settings_content,
            text="👁",
            font=("Segoe UI", 10),
            bg='#1E1E1E',
            fg='#808080',
            cursor='hand2',
            width=2
        )
        self.show_album_art_btn.grid(row=0, column=2, sticky=E, padx=(4, 0), pady=1)
        self.show_album_art_btn.bind("<Button-1>", lambda e: self.toggle_album_art() if self.show_album_art_btn.cget('fg') != '#1E1E1E' else None)
        self.show_album_art_btn.bind("<Enter>", lambda e: self.show_album_art_btn.config(fg='#D4D4D4') if self.show_album_art_btn.cget('fg') != '#1E1E1E' else None)
        self.show_album_art_btn.bind("<Leave>", lambda e: self.show_album_art_btn.config(fg='#808080') if self.show_album_art_btn.cget('fg') != '#1E1E1E' else None)
        # Make invisible by default (only visible when album art is hidden)
        self.show_album_art_btn.config(fg='#1E1E1E')  # Match background to make invisible
        
        # Numbering (second, below Audio Format)
        ttk.Label(self.settings_content, text="Numbering:", font=("Segoe UI", 8)).grid(row=1, column=0, padx=4, sticky=W, pady=1)
        numbering_combo = ttk.Combobox(
            self.settings_content,
            textvariable=self.numbering_var,
            values=["None", "01. Track", "1. Track", "01 - Track", "1 - Track"],
            state="readonly",
            width=15
        )
        numbering_combo.grid(row=1, column=1, padx=4, sticky=W, pady=1)
        numbering_combo.bind("<<ComboboxSelected>>", lambda e: (self._deselect_combobox_text(e), self.on_numbering_change(e), self.update_preview()))
        
        # Folder Structure (third, below Numbering)
        ttk.Label(self.settings_content, text="Folder Structure:", font=("Segoe UI", 8)).grid(row=2, column=0, padx=4, sticky=W, pady=1)
        
        # Create a separate display variable for the combobox using class constants
        structure_display_values = list(self.FOLDER_STRUCTURES.values())
        structure_combo = ttk.Combobox(
            self.settings_content,
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
            self.settings_content,
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
            self.settings_content,
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
            self.settings_content,
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
        
        # Download artist discography checkbox (below Create playlist)
        download_discography_check = Checkbutton(
            self.settings_content,
            text="Download artist discography",
            variable=self.download_discography_var,
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#D4D4D4',
            selectcolor='#1E1E1E',
            activebackground='#1E1E1E',
            activeforeground='#D4D4D4',
            command=self.on_download_discography_change
        )
        download_discography_check.grid(row=6, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        self.download_discography_check = download_discography_check  # Store reference for enabling/disabling
        
        # Configure column weights: label (0), combo (1), button (2)
        self.settings_content.columnconfigure(0, weight=0)  # Label column - fixed width
        self.settings_content.columnconfigure(1, weight=1)  # Combo column - can expand
        self.settings_content.columnconfigure(2, weight=0)  # Button column - fixed width
        
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
            style='Download.TButton',
            cursor='hand2'
        )
        self.download_btn.grid(row=6, column=0, columnspan=3, pady=15)
        
        # Cancel button (hidden initially, shown during download)
        # Uses same style as download button for consistent size
        self.cancel_btn = ttk.Button(
            main_frame,
            text="Cancel Download",
            command=self.cancel_download,
            state='disabled',
            style='Cancel.TButton',
            cursor='hand2'
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
        # Reduced bottom padding slightly to make room for expand button
        self.log_frame = Frame(main_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        self.log_frame.grid(row=10, column=0, columnspan=3, sticky=(W, E, N, S), pady=(6, 4), padx=0)
        
        # Label for the frame and controls on same row
        log_label = Label(self.log_frame, text="Status", bg='#1E1E1E', fg='#D4D4D4', font=("Segoe UI", 9))
        log_label.grid(row=0, column=0, sticky=W, padx=6, pady=(6, 2))
        
        # Clear log button (between Status label and Debug toggle) - styled like Browse button
        # Use same font size as Debug toggle (8) for consistency in header
        # Create a custom style for the small button (based on TButton but with smaller padding and font)
        style = ttk.Style()
        style.configure('Small.TButton', 
                       background='#252526',  # select_bg
                       foreground='#D4D4D4',  # fg_color
                       borderwidth=1,
                       bordercolor='#3E3E42',  # border_color
                       relief='flat',
                       padding=(6, 2),
                       font=("Segoe UI", 8))
        style.map('Small.TButton',
                 background=[('active', '#3E3E42'), ('pressed', '#1E1E1E')],  # hover_bg, bg_color
                 bordercolor=[('active', '#3E3E42'), ('pressed', '#3E3E42')])  # border_color
        
        clear_log_btn = ttk.Button(
            self.log_frame,
            text="Clear Log",
            command=self._clear_log,
            cursor='hand2',
            style='Small.TButton'
        )
        clear_log_btn.grid(row=0, column=1, sticky=E, padx=(0, 6), pady=(6, 2))
        
        # Debug toggle checkbox (right-aligned on same row as Status label)
        self.debug_mode_var = BooleanVar(value=False)
        debug_toggle = Checkbutton(
            self.log_frame,
            text="Debug",
            variable=self.debug_mode_var,
            bg='#1E1E1E',
            fg='#D4D4D4',
            selectcolor='#252526',
            activebackground='#1E1E1E',
            activeforeground='#D4D4D4',
            font=("Segoe UI", 8),
            command=self._toggle_debug_mode
        )
        debug_toggle.grid(row=0, column=2, sticky=E, padx=6, pady=(6, 2))
        
        # Configure column weights so controls stay on the right
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.columnconfigure(1, weight=0)
        self.log_frame.columnconfigure(2, weight=0)
        
        # Inner frame for content (spans all columns to stay full width)
        # Search bar will be at the bottom (row=2), log_content at row=1
        log_content = Frame(self.log_frame, bg='#1E1E1E')
        log_content.grid(row=1, column=0, columnspan=3, sticky=(W, E, N, S), padx=6, pady=(0, 6))
        self.log_frame.rowconfigure(1, weight=1)  # Log content row expands
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
            relief='flat',
            state='disabled'  # Make read-only to prevent user editing
        )
        self.log_text.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # Configure search tags for highlighting matches
        # Yellow for all matches
        self.log_text.tag_config(self.search_tag_name, background='#FFD700', foreground='#000000')
        # Green for current/selected match
        self.log_text.tag_config(self.current_match_tag_name, background='#00FF00', foreground='#000000')
        
        # Bind Ctrl+F globally to show search (works anywhere in the app)
        self.log_text.bind('<Button-1>', lambda e: self._on_log_click())  # Enable focus when clicking log
        # Use bind_all to ensure Ctrl+F works regardless of which widget has focus
        self.root.bind_all('<Control-f>', lambda e: self._show_search_bar())  # Global Ctrl+F hotkey
        
        # Configure scrollbar after packing
        self.root.after(100, self.configure_scrollbar)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(2, weight=0)  # Album art column doesn't expand
        main_frame.rowconfigure(10, weight=1)  # Status log row expands
        
        # Expand/Collapse button at the bottom (centered, fits in log_frame bottom padding, no extra space)
        # Place it in log_frame at the very bottom, centered
        self.expand_collapse_btn = Label(
            self.log_frame,  # Place in log_frame so it's at the bottom
            text="▼",  # Down triangle (like > rotated down)
            font=("Segoe UI", 7),
            bg='#1E1E1E',
            fg='#808080',
            cursor='hand2',
            width=1,
            height=1,
            padx=0,
            pady=0
        )
        # Use place() to position at bottom center, overlaying without adding grid space
        # This positions it absolutely at the bottom center of log_frame
        def position_button():
            if hasattr(self, 'expand_collapse_btn') and self.expand_collapse_btn.winfo_exists():
                frame_width = self.log_frame.winfo_width()
                if frame_width > 1:  # Only position if frame is visible
                    # Center horizontally, position at bottom (2px from bottom)
                    self.expand_collapse_btn.place(relx=0.5, rely=1.0, anchor='s', y=-2)
        
        # Position after frame is rendered
        self.root.after(100, position_button)
        # Also reposition on resize
        self.log_frame.bind('<Configure>', lambda e: position_button())
        
        self.expand_collapse_btn.bind("<Button-1>", lambda e: self._toggle_window_height())
        self.expand_collapse_btn.bind("<Enter>", lambda e: self.expand_collapse_btn.config(fg='#D4D4D4'))
        self.expand_collapse_btn.bind("<Leave>", lambda e: self.expand_collapse_btn.config(fg='#808080'))
        
        # Track if window is expanded
        self.is_expanded = False
        
        # Bind click events to main frame and root to unfocus URL field when clicking elsewhere
        def unfocus_url_field(event):
            """Unfocus URL field when clicking on empty areas or non-interactive widgets."""
            # Get the widget that was clicked
            widget_clicked = event.widget
            
            # Check if click is on URL field, path entry, browse button, clear button, expand button, log text, search bar, or any of their parent containers
            current = widget_clicked
            is_interactive_widget = False
            while current:
                if (current == self.url_entry_widget or 
                    current == self.url_text_widget or 
                    current == self.url_container_frame or
                    current == self.url_text_frame or
                    current == self.path_entry or
                    current == self.browse_btn or
                    (hasattr(self, 'log_text') and current == self.log_text) or
                    (hasattr(self, 'url_clear_btn') and current == self.url_clear_btn) or
                    (hasattr(self, 'url_expand_btn') and current == self.url_expand_btn) or
                    (hasattr(self, 'search_frame') and self.search_frame and (current == self.search_frame or self._is_widget_in_search_frame(current)))):
                    is_interactive_widget = True
                    break
                try:
                    current = current.master
                except:
                    break
            
            # Only unfocus URL field if the click is NOT on any interactive widget
            if not is_interactive_widget:
                # Remove focus from URL field by focusing on root or main frame
                try:
                    main_frame.focus_set()
                except:
                    self.root.focus_set()
        
        # Bind to main frame and root window
        main_frame.bind('<Button-1>', unfocus_url_field)
        self.root.bind('<Button-1>', unfocus_url_field)
    
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
        # Save the preference immediately when changed
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        self.save_default_preference(choice)
    
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
        # Get current content to check if it's empty
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            content = self.url_text_widget.get(1.0, END).strip()
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            content = self.url_var.get().strip()
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.":
                content = ""
        else:
            content = ""
        
        # If content is empty, immediately clear preview and artwork (don't wait for debounce)
        if not content:
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
            self.format_suggestion_shown = False
            self.current_thumbnail_url = None
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            # Cancel any pending timer since we've already handled the empty state
            if self.url_check_timer:
                self.root.after_cancel(self.url_check_timer)
                self.url_check_timer = None
            return
        
        # Update URL count dynamically
        self._update_url_count_and_button()
        
        # Update clear button visibility
        self._update_url_clear_button()
        
        # Cancel any pending timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
        
        # Debounce: wait 200ms after last change before fetching (shorter for faster response)
        self.url_check_timer = self.root.after(200, self._check_url)
    
    def _update_url_clear_button(self):
        """Update the expand/collapse button icon based on current mode. Buttons are always visible."""
        if not hasattr(self, 'url_clear_btn'):
            return
        
        # Ensure buttons are always visible
        self.url_clear_btn.grid()
        
        # Determine current mode and update expand/collapse button icon
        is_entry_mode = False
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            # ScrolledText is visible (multi-line mode)
            is_entry_mode = False
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Entry is visible (single-line mode)
            is_entry_mode = True
        
        # Always show expand/collapse button and update icon based on current mode
        if hasattr(self, 'url_expand_btn'):
            self.url_expand_btn.grid()
            if is_entry_mode:
                # Entry mode - show expand icon (⤢)
                self.url_expand_btn.config(text="⤢")
            else:
                # ScrolledText mode - show collapse icon (⤡)
                self.url_expand_btn.config(text="⤡")
    
    def _toggle_url_field_mode(self):
        """Toggle between Entry (single-line) and ScrolledText (multi-line) modes."""
        if self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Currently in Entry mode - expand to ScrolledText
            content = self.url_var.get().strip()
            # Remove placeholder text if present
            if content == "Paste one URL or multiple to create a batch.":
                content = ""
            # Expand to multi-line
            self._expand_to_multiline(content)
        elif self.url_text_widget and self.url_text_widget.winfo_viewable():
            # Currently in ScrolledText mode - collapse to Entry
            self._collapse_to_entry()
    
    def _clear_url_field(self):
        """Clear the URL field and unfocus it."""
        # Cancel any pending URL check timer to prevent race conditions
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            # ScrolledText is visible - clear it
            self.url_text_widget.delete(1.0, END)
            self._update_text_placeholder_visibility()
            # Unfocus
            self.root.focus_set()
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Entry is visible - clear it and restore placeholder
            self.url_var.set("")
            self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.")
            # Unfocus
            self.root.focus_set()
        
        # Update clear button visibility
        self._update_url_clear_button()
        
        # Reset metadata and preview immediately
        self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
        self.format_suggestion_shown = False  # Reset format suggestion flag
        self.current_thumbnail_url = None
        self.album_art_fetching = False
        self.update_preview()
        self.clear_album_art()
        
        # Update URL count
        self._update_url_count_and_button()
        
        # Immediately check URL to ensure empty state is processed (this will clear preview/artwork)
        self._check_url()
    
    def _handle_right_click_paste(self, event):
        """Handle right-click paste in URL field (Entry widget)."""
        try:
            # Save current content state before pasting (so we can undo back to it)
            self._save_content_state()
            
            # Get clipboard content
            clipboard_text = self.root.clipboard_get()
            if clipboard_text:
                # Clear current selection if any
                url_entry = event.widget
                url_entry.delete(0, END)
                url_entry.insert(0, clipboard_text)
                # Check if paste contains newlines - if so, expand to multi-line
                if '\n' in clipboard_text:
                    self._expand_to_multiline(clipboard_text)
                    # After expansion, save state and trigger URL check (similar to single-line paste)
                    self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
                else:
                    # Save new state after paste, then trigger URL check
                    self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_url_clear_button()))
        except Exception:
            # If clipboard is empty or not text, ignore
            pass
    
    def _handle_right_click_paste_entry(self, event):
        """Handle right-click paste in Entry widget."""
        self._handle_right_click_paste(event)
    
    def _show_text_context_menu(self, event):
        """Show context menu for ScrolledText widget on right-click."""
        try:
            # Show context menu at cursor position
            self.url_text_context_menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass
        finally:
            # Ensure menu is released
            self.url_text_context_menu.grab_release()
    
    def _handle_right_click_paste_text(self, event=None):
        """Handle right-click paste in ScrolledText widget (can be called from context menu or event)."""
        try:
            # Save current content state before pasting (so we can undo back to it)
            self._save_content_state()
            
            # Hide placeholder immediately when pasting
            self._hide_text_placeholder()
            # Get clipboard content
            clipboard_text = self.root.clipboard_get()
            if clipboard_text:
                # Get the text widget - from event or use stored reference
                url_text = event.widget if event and hasattr(event, 'widget') else self.url_text_widget
                if url_text:
                    # Insert at cursor position (Text widget)
                    url_text.insert("insert", clipboard_text)
                    # Save new state after paste, then trigger URL check and update count
                    self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        except Exception:
            # If clipboard is empty or not text, ignore
            pass
    
    def _handle_entry_paste(self, event):
        """Handle paste in Entry widget - check for newlines and expand if needed."""
        # Save current content state before pasting (so we can undo back to it)
        self._save_content_state()
        # Let the paste happen first, then save new state and check
        self.root.after(10, lambda: (self._check_entry_paste(), self._save_content_state()))
    
    def _check_entry_paste(self):
        """Check if Entry content has newlines and expand if needed."""
        if self.url_entry_widget:
            content = self.url_var.get()
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.":
                content = ""
            if '\n' in content:
                # Has newlines - expand to multi-line
                self._expand_to_multiline(content)
                # After expansion, trigger URL check (similar to right-click paste)
                self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
            else:
                # No newlines - just update count
                self._update_url_count_and_button()
                self._update_url_clear_button()
                self.root.after(10, self._check_url)
    
    def _check_entry_for_newlines(self):
        """Check if Entry content has newlines (from typing) and expand if needed."""
        if self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            content = self.url_var.get()
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.":
                return
            if '\n' in content:
                # Has newlines - expand to multi-line
                self._expand_to_multiline(content)
    
    def _save_content_state(self):
        """Save current content state to history for undo/redo."""
        try:
            # Get current content
            if self.url_text_widget and self.url_text_widget.winfo_viewable():
                current_content = self.url_text_widget.get(1.0, END).rstrip('\n')
            elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
                current_content = self.url_var.get().strip()
                # Skip placeholder text
                if current_content == "Paste one URL or multiple to create a batch.":
                    current_content = ""
            else:
                current_content = ""
            
            # Only save if content is different from current history position
            if (self.content_history_index < 0 or 
                self.content_history_index >= len(self.content_history) or
                self.content_history[self.content_history_index] != current_content):
                # Remove any future history if we're not at the end
                if self.content_history_index < len(self.content_history) - 1:
                    self.content_history = self.content_history[:self.content_history_index + 1]
                # Add new content state to history
                self.content_history.append(current_content)
                self.content_history_index = len(self.content_history) - 1
                # Limit history size to 50 items (more than paste history since we track more states)
                if len(self.content_history) > 50:
                    self.content_history = self.content_history[-50:]
                    self.content_history_index = len(self.content_history) - 1
        except Exception:
            pass
    
    def _handle_entry_return(self, event):
        """Handle Enter key in Entry - expand to multi-line."""
        # Save current content state before adding newline
        self._save_content_state()
        
        # Get current content
        content = self.url_var.get()
        # Expand to multi-line with current content
        self._expand_to_multiline(content + '\n')
        
        # Save state after expansion (with newline) - wait a bit for widget to update
        self.root.after(50, self._save_content_state)
        
        # Focus the text widget
        if self.url_text_widget:
            self.url_text_widget.focus_set()
            # Move cursor to end
            self.url_text_widget.mark_set("insert", "end")
        return "break"  # Prevent default behavior
    
    def _handle_text_paste(self, event):
        """Handle paste in ScrolledText widget."""
        # Save current content state before pasting (so we can undo back to it)
        self._save_content_state()
        
        # Hide placeholder immediately when pasting
        self._hide_text_placeholder()
        # Let the paste happen first, then save the new state and check
        self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
    
    def _handle_entry_undo(self, event):
        """Handle undo (Ctrl+Z) in Entry widget - cycle to previous content state."""
        # Check if Shift is pressed (Ctrl+Shift+Z = redo)
        if event.state & 0x1:  # Shift key is pressed (state bit 0)
            return self._handle_entry_redo(event)
        
        if not self.content_history:
            return None  # No history, allow default behavior
        
        # Cancel any pending artwork fetches and clear artwork if field will be empty
        # Increment fetch ID to cancel any in-flight artwork fetches
        self.artwork_fetch_id += 1
        self.album_art_fetching = False
        # Cancel any pending URL check timer and content save timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        if self.content_save_timer:
            self.root.after_cancel(self.content_save_timer)
            self.content_save_timer = None
        
        # Save current content to history before undoing (so we can redo back to it)
        self._save_content_state()
        
        # Move back in history
        if self.content_history_index > 0:
            self.content_history_index -= 1
            previous_content = self.content_history[self.content_history_index]
            
            # Replace current content with previous state
            self.url_var.set(previous_content)
            
            # Check if content contains newlines - if so, expand to multi-line
            if '\n' in previous_content:
                self._expand_to_multiline(previous_content)
            else:
                # Handle empty content - clear preview and artwork
                if not previous_content or not previous_content.strip() or previous_content == "Paste one URL or multiple to create a batch.":
                    self.url_var.set("")
                    self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.")
                    # Immediately clear preview and artwork
                    self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
                    self.current_thumbnail_url = None
                    self.album_art_fetching = False
                    self.update_preview()
                    self.clear_album_art()
                
                # Trigger URL check (will handle empty content correctly)
                self.root.after(10, self._check_url)
                self._update_url_count_and_button()
                self._update_url_clear_button()
        else:
            # At the beginning of history - insert empty state at position 0 so we can redo
            # This ensures that if we undo past the beginning, we can still redo back
            if self.content_history and self.content_history[0] != "":
                # Insert empty state at the beginning
                self.content_history.insert(0, "")
                self.content_history_index = 0
            elif not self.content_history:
                # No history at all - create empty state
                self.content_history = [""]
                self.content_history_index = 0
            
            # Clear the field
            self.url_var.set("")
            self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.")
            # Immediately clear preview and artwork
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
            self.current_thumbnail_url = None
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            self.root.after(10, self._check_url)
            self._update_url_count_and_button()
            self._update_url_clear_button()
        
        return "break"  # Prevent default undo behavior
    
    def _handle_entry_redo(self, event):
        """Handle redo (Ctrl+Shift+Z) in Entry widget - cycle to next content state."""
        if not self.content_history:
            return None  # No history, allow default behavior
        
        # Cancel any pending artwork fetches and clear artwork if field will be empty
        # Increment fetch ID to cancel any in-flight artwork fetches
        self.artwork_fetch_id += 1
        self.album_art_fetching = False
        # Cancel any pending URL check timer and content save timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        if self.content_save_timer:
            self.root.after_cancel(self.content_save_timer)
            self.content_save_timer = None
        
        # Save current content to history before redoing (so we can undo back to it)
        self._save_content_state()
        
        # Move forward in history
        if self.content_history_index < len(self.content_history) - 1:
            self.content_history_index += 1
            next_content = self.content_history[self.content_history_index]
            
            # Replace current content with next state
            self.url_var.set(next_content)
            
            # Check if content contains newlines - if so, expand to multi-line
            if '\n' in next_content:
                self._expand_to_multiline(next_content)
            else:
                # Handle empty content - clear preview and artwork
                if not next_content or not next_content.strip() or next_content == "Paste one URL or multiple to create a batch.":
                    self.url_var.set("")
                    self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.")
                    # Immediately clear preview and artwork
                    self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
                    self.current_thumbnail_url = None
                    self.album_art_fetching = False
                    self.update_preview()
                    self.clear_album_art()
                
                # Trigger URL check (will handle empty content correctly)
                self.root.after(10, self._check_url)
                self._update_url_count_and_button()
                self._update_url_clear_button()
        
        return "break"  # Prevent default redo behavior
    
    def _handle_text_undo(self, event):
        """Handle undo (Ctrl+Z) in ScrolledText widget - cycle to previous content state."""
        # Check if Shift is pressed (Ctrl+Shift+Z = redo)
        if event.state & 0x1:  # Shift key is pressed (state bit 0)
            return self._handle_text_redo(event)
        
        if not self.content_history or not self.url_text_widget:
            return None  # No history or widget, allow default behavior
        
        # Cancel any pending artwork fetches and clear artwork if field will be empty
        # Increment fetch ID to cancel any in-flight artwork fetches
        self.artwork_fetch_id += 1
        self.album_art_fetching = False
        # Cancel any pending URL check timer and content save timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        if self.content_save_timer:
            self.root.after_cancel(self.content_save_timer)
            self.content_save_timer = None
        
        # Save current content to history before undoing (so we can redo back to it)
        self._save_content_state()
        
        # Move back in history
        if self.content_history_index > 0:
            self.content_history_index -= 1
            previous_content = self.content_history[self.content_history_index]
            
            # Replace current content with previous state (preserve newlines)
            self.url_text_widget.delete(1.0, END)
            self.url_text_widget.insert(1.0, previous_content)
            
            # Handle empty content - clear preview and artwork
            if not previous_content or not previous_content.strip():
                self._update_text_placeholder_visibility()
                # Immediately clear preview and artwork
                self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
                self.current_thumbnail_url = None
                self.album_art_fetching = False
                self.update_preview()
                self.clear_album_art()
            else:
                self._hide_text_placeholder()
            
            # Trigger URL check and update count (will handle empty content correctly)
            self.root.after(10, lambda: (self._ensure_trailing_newline(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        else:
            # At the beginning of history - insert empty state at position 0 so we can redo
            # This ensures that if we undo past the beginning, we can still redo back
            if self.content_history and self.content_history[0] != "":
                # Insert empty state at the beginning
                self.content_history.insert(0, "")
                self.content_history_index = 0
            elif not self.content_history:
                # No history at all - create empty state
                self.content_history = [""]
                self.content_history_index = 0
            
            # Clear the field
            self.url_text_widget.delete(1.0, END)
            self._update_text_placeholder_visibility()
            # Immediately clear preview and artwork
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
            self.current_thumbnail_url = None
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            self.root.after(10, lambda: (self._ensure_trailing_newline(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        
        return "break"  # Prevent default undo behavior
    
    def _handle_text_redo(self, event):
        """Handle redo (Ctrl+Shift+Z) in ScrolledText widget - cycle to next content state."""
        if not self.content_history or not self.url_text_widget:
            return None  # No history or widget, allow default behavior
        
        # Cancel any pending artwork fetches and clear artwork if field will be empty
        # Increment fetch ID to cancel any in-flight artwork fetches
        self.artwork_fetch_id += 1
        self.album_art_fetching = False
        # Cancel any pending URL check timer and content save timer
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        if self.content_save_timer:
            self.root.after_cancel(self.content_save_timer)
            self.content_save_timer = None
        
        # Save current content to history before redoing (so we can undo back to it)
        self._save_content_state()
        
        # Move forward in history
        if self.content_history_index < len(self.content_history) - 1:
            self.content_history_index += 1
            next_content = self.content_history[self.content_history_index]
            
            # Replace current content with next state (preserve newlines)
            self.url_text_widget.delete(1.0, END)
            self.url_text_widget.insert(1.0, next_content)
            
            # Handle empty content - clear preview and artwork
            if not next_content or not next_content.strip():
                self._update_text_placeholder_visibility()
                # Immediately clear preview and artwork
                self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
                self.current_thumbnail_url = None
                self.album_art_fetching = False
                self.update_preview()
                self.clear_album_art()
            else:
                self._hide_text_placeholder()
            
            # Trigger URL check and update count (will handle empty content correctly)
            self.root.after(10, lambda: (self._ensure_trailing_newline(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        
        return "break"  # Prevent default redo behavior
    
    def _handle_text_return(self, event):
        """Handle Enter key in ScrolledText - save content state when new line is added."""
        # Save current content state before Enter adds newline
        self._save_content_state()
        # Allow default Enter behavior (adds newline), then save state again after
        self.root.after(10, self._save_content_state)
        return None  # Allow default behavior
    
    def _on_text_key_release(self):
        """Handle key release in ScrolledText - update URL count dynamically and update placeholder visibility."""
        # Ensure trailing newline for easy editing
        self._ensure_trailing_newline()
        
        # Update placeholder visibility based on content
        self._update_text_placeholder_visibility()
        
        self._update_url_count_and_button()
        # Also trigger URL check with debounce
        self.on_url_change()
        
        # Save content state with debounce for undo/redo (only for typing, not for special keys)
        # Cancel any pending save timer
        if self.content_save_timer:
            self.root.after_cancel(self.content_save_timer)
        # Debounce: save state 500ms after last keystroke (allows typing without saving every keystroke)
        self.content_save_timer = self.root.after(500, self._save_content_state)
    
    def _ensure_trailing_newline(self):
        """Ensure ScrolledText always ends with an empty line for easy editing."""
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return
        
        try:
            # Get current content (END includes trailing newline)
            content = self.url_text_widget.get(1.0, END)
            
            # Text widget's END always includes a trailing newline, so content[-1] is always '\n'
            # We want to ensure the last line (before the implicit trailing newline) is empty
            # So we check if content ends with '\n\n' (content + implicit newline = two newlines)
            
            # Get current cursor position before modifying
            cursor_pos = self.url_text_widget.index("insert")
            
            # Check if we need to add a newline to create an empty line
            # If content has at least 2 chars, check if second-to-last is '\n'
            # If content is just '\n' (empty), we need to add another '\n' to have an empty line
            needs_newline = False
            
            if len(content) >= 2:
                # Check if second-to-last character is a newline (meaning last line is empty)
                if content[-2] != '\n':
                    needs_newline = True
            elif len(content) == 1:
                # Only the implicit newline - need another for empty line
                needs_newline = True
            # If content is empty, we already have the empty line (just '\n')
            
            if needs_newline:
                # Insert newline at the end (before the implicit trailing newline)
                # END is after the last character, so END + "-1c" is the last character
                # Inserting there will add a newline before the implicit one
                self.url_text_widget.insert(END + "-1c", '\n')
                
                # Restore cursor position
                try:
                    self.url_text_widget.mark_set("insert", cursor_pos)
                except:
                    pass
        except Exception:
            # Silently fail if there's any issue
            pass
    
    def _hide_text_placeholder(self):
        """Hide the placeholder label overlay."""
        if hasattr(self, 'url_text_placeholder_label') and self.url_text_placeholder_label:
            self.url_text_placeholder_label.place_forget()
    
    def _show_text_placeholder(self):
        """Show the placeholder label overlay."""
        if hasattr(self, 'url_text_placeholder_label') and self.url_text_placeholder_label:
            self.url_text_placeholder_label.place(x=4, y=2, anchor='nw')
            # Raise above text widget to be visible, but keep it non-interactive
            self.url_text_placeholder_label.lift(self.url_text_widget)
    
    def _update_text_placeholder_visibility(self):
        """Update placeholder visibility based on ScrolledText content."""
        if self.url_text_widget:
            content = self.url_text_widget.get(1.0, END).strip()
            if not content:
                # Field is empty - show placeholder
                self._show_text_placeholder()
            else:
                # Field has content - hide placeholder
                self._hide_text_placeholder()
    
    def _on_text_focus_in(self):
        """Handle focus in on ScrolledText - restore saved height if available."""
        if self.url_text_widget:
            # Restore saved height if available, otherwise keep at minimum
            if hasattr(self, 'url_text_height') and self.url_text_height > 2:
                self.url_text_widget.config(height=self.url_text_height)
            else:
                self.url_text_widget.config(height=2)
            # Restore scroll position if we saved it
            if hasattr(self, '_saved_text_scroll_position'):
                try:
                    # Restore to saved position
                    self.url_text_widget.see(self._saved_text_scroll_position)
                    delattr(self, '_saved_text_scroll_position')
                except Exception:
                    pass
    
    def _on_text_focus_out(self):
        """Handle focus out on ScrolledText - collapse height and update placeholder visibility."""
        if self.url_text_widget:
            # Deselect any selected text when losing focus
            try:
                self.url_text_widget.tag_remove("sel", "1.0", "end")
            except Exception:
                pass
            
            # Check if the app is losing focus (focus going outside the app)
            # If so, don't collapse - keep the current height
            try:
                new_focus = self.root.focus_get()
                # If focus is None or not a widget in our app, the app is losing focus
                if new_focus is None:
                    # App is losing focus - don't collapse, just return
                    return
                
                # Check if the new focus widget is within our root window
                current = new_focus
                is_in_app = False
                while current:
                    if current == self.root:
                        is_in_app = True
                        break
                    try:
                        current = current.master
                    except:
                        break
                
                # If focus is going outside the app, don't collapse
                if not is_in_app:
                    return
            except Exception:
                # If we can't determine focus, default to collapsing (safe behavior)
                pass
            
            # Focus is going to another widget in the app - collapse as normal
            # Save current scroll position before collapsing
            try:
                # Get the first visible line (top of viewport)
                top_index = self.url_text_widget.index("@0,0")
                self._saved_text_scroll_position = top_index
            except Exception:
                pass
            
            # Save current height before collapsing (if user resized it)
            if hasattr(self, 'url_text_widget'):
                try:
                    current_height = self.url_text_widget.cget('height')
                    if current_height > 2:
                        self.url_text_height = current_height
                except Exception:
                    pass
            
            # Collapse height to 2 lines (hide extra lines but keep content)
            self.url_text_widget.config(height=2)
            
            # Don't scroll to top - maintain position when focus returns
            # The scroll position will be restored when focus returns
            
            # Update placeholder visibility based on content
            self._update_text_placeholder_visibility()
            
            # Force update to ensure height change is applied
            self.url_text_widget.update_idletasks()
    
    def _expand_to_multiline(self, initial_content=""):
        """Expand from Entry to ScrolledText for multi-line input."""
        if not self.url_text_widget:
            return
        
        # Get content from Entry if not provided
        if not initial_content and self.url_entry_widget:
            initial_content = self.url_var.get()
            # Remove placeholder text if present
            if initial_content == "Paste one URL or multiple to create a batch.":
                initial_content = ""
        
        # Extract URLs from the single-line content (handles multiple URLs on one line)
        urls = self._extract_urls_from_content(initial_content)
        
        # Format content: if multiple URLs were found, put each on its own line
        if len(urls) > 1:
            formatted_content = '\n'.join(urls)
        elif initial_content and initial_content.strip():
            # Single URL or non-URL text, keep as-is
            formatted_content = initial_content
        else:
            formatted_content = ""
        
        # Get the text frame - use stored reference if available, otherwise get from widget
        text_frame = getattr(self, 'url_text_frame', None) or self.url_text_widget.master
        
        # Hide Entry first - completely remove it from grid
        if self.url_entry_widget:
            try:
                self.url_entry_widget.grid_forget()
            except:
                pass  # Already removed
        
        # Show the text frame - it was grid_remove'd initially, so grid() will restore it
        # Explicitly configure it with all parameters to ensure it's visible
        text_frame.grid(row=0, column=0, sticky=(W, E, N, S), pady=0)
        
        # The ScrolledText is already gridded inside text_frame, but ensure it's configured
        # Re-grid it to ensure it's visible and properly sized
        self.url_text_widget.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # Ensure the widget is in normal state (not disabled)
        self.url_text_widget.config(state='normal')
        
        # Force the container and frame to update their layout immediately
        self.url_container_frame.update_idletasks()
        text_frame.update_idletasks()
        self.url_text_widget.update_idletasks()
        
        # Set content in ScrolledText
        self.url_text_widget.delete(1.0, END)
        if formatted_content and formatted_content.strip():
            self.url_text_widget.insert(1.0, formatted_content)
            self.url_text_widget.config(foreground='#CCCCCC')  # Normal text color
        
        # Ensure trailing newline for easy editing
        self._ensure_trailing_newline()
        
        # Update placeholder visibility based on content
        self._update_text_placeholder_visibility()
        
        # Set height based on content (min 2, max 8) or use saved height
        if hasattr(self, 'url_text_height') and self.url_text_height > 2:
            height = self.url_text_height
        else:
            content = formatted_content.strip() if formatted_content else ""
            if content:
                lines = content.split('\n')
                line_count = len([line for line in lines if line.strip()])
                height = max(2, min(line_count + 1, 8))
            else:
                height = 2
            self.url_text_height = height
        self.url_text_widget.config(height=height)
        
        # Show resize handle when text widget is visible (place it just above bottom edge, centered)
        if hasattr(self, 'url_text_resize_handle'):
            self.url_text_resize_handle.place(relx=0.5, rely=1.0, relwidth=0.9, anchor='s', height=5, y=-1)
            self.url_text_resize_handle.lift()  # Bring to front so it's draggable
        
        # Make sure the widget is actually visible
        self.url_text_widget.update_idletasks()
        text_frame.update_idletasks()
        self.url_container_frame.update_idletasks()
        
        # Focus the text widget
        self.url_text_widget.focus_set()
        
        # Update URL count and clear button
        self._update_url_count_and_button()
        self._update_url_clear_button()
    
    def _collapse_to_entry(self):
        """Collapse from ScrolledText back to Entry (single URL mode)."""
        if not self.url_entry_widget or not self.url_text_widget:
            return
        
        # Get content from ScrolledText
        content = self.url_text_widget.get(1.0, END).strip()
        
        # Skip placeholder text
        if content == "Paste one URL or multiple to create a batch.":
            content = ""
        
        # Extract all URLs from content (handles both single and multi-line)
        urls = self._extract_urls_from_content(content)
        
        if urls:
            # Join all URLs with a space to flatten them into a single line
            flattened_urls = ' '.join(urls)
            self.url_var.set(flattened_urls)
            # Remove placeholder styling
            self.url_entry_widget.config(foreground='#CCCCCC')
        else:
            self.url_var.set("")
            # Set placeholder
            self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.")
        
        # Save current height before hiding
        if hasattr(self, 'url_text_widget'):
            try:
                current_height = self.url_text_widget.cget('height')
                if current_height > 2:
                    self.url_text_height = current_height
            except Exception:
                pass
        
        # Hide ScrolledText, show Entry
        text_frame = getattr(self, 'url_text_frame', None) or self.url_text_widget.master
        if text_frame:
            text_frame.grid_remove()  # Hide but preserve space
            # Also hide resize handle
            if hasattr(self, 'url_text_resize_handle'):
                self.url_text_resize_handle.place_forget()
        
        # Re-grid the Entry widget with original padding
        if self.url_entry_widget:
            self.url_entry_widget.grid(row=0, column=0, sticky=(W, E), pady=0, padx=(0, 4))
        
        # Force layout update
        self.url_container_frame.update_idletasks()
        
        # Update URL count and clear button
        self._update_url_count_and_button()
        self._update_url_clear_button()
        
        # Focus the Entry widget
        if self.url_entry_widget:
            self.url_entry_widget.focus_set()
        
        # Trigger URL check
        self.root.after(10, self._check_url)
    
    def _count_urls_in_text(self, text):
        """Count number of bandcamp.com URLs in text (by counting 'bandcamp.com' occurrences)."""
        if not text or not text.strip():
            return 0
        # Skip placeholder text
        if text.strip() == "Paste one URL or multiple to create a batch.":
            return 0
        # Count occurrences of 'bandcamp.com' (case-insensitive)
        text_lower = text.lower()
        count = text_lower.count('bandcamp.com')
        return count
    
    def _extract_urls_from_content(self, content):
        """Extract URLs from content string, handling both single and multi-line input.
        Also handles concatenated URLs (no separator) on the same line."""
        if not content or not content.strip():
            return []
        # Skip placeholder text
        if content.strip() == "Paste one URL or multiple to create a batch.":
            return []
        
        import re
        # Split by lines first
        lines = content.split('\n')
        all_urls = []
        
        for line in lines:
            line = line.strip()
            if not line or line == "Paste one URL or multiple to create a batch.":
                continue
            
            # Check if line contains multiple URLs (by counting 'bandcamp.com' or 'https://' patterns)
            line_lower = line.lower()
            bandcamp_count = line_lower.count('bandcamp.com')
            https_count = len(re.findall(r'https?://', line, re.IGNORECASE))
            
            if bandcamp_count > 1 or https_count > 1:
                # Multiple URLs on same line - extract all URLs
                # Find all positions where URLs start (https:// or http://)
                url_starts = []
                for match in re.finditer(r'https?://', line, re.IGNORECASE):
                    url_starts.append(match.start())
                
                # Extract each URL
                for i, start_pos in enumerate(url_starts):
                    # Find the end of this URL (start of next URL or end of line)
                    if i + 1 < len(url_starts):
                        # There's another URL after this one
                        end_pos = url_starts[i + 1]
                        url = line[start_pos:end_pos]
                    else:
                        # This is the last URL
                        url = line[start_pos:]
                    
                    # Clean up the URL (remove trailing whitespace, commas, semicolons)
                    url = url.rstrip(' \t,;')
                    
                    # Validate it contains bandcamp.com
                    if 'bandcamp.com' in url.lower():
                        all_urls.append(url)
            else:
                # Single URL (or no URL) - just add the line
                all_urls.append(line)
        
        return all_urls
    
    def _remove_duplicate_urls(self, urls):
        """Remove duplicate URLs, normalizing them first (case-insensitive, trailing slash handling)."""
        if not urls:
            return []
        seen = set()
        unique_urls = []
        for url in urls:
            # Normalize URL: lowercase, remove trailing slash (except for root URLs)
            normalized = url.lower().strip()
            # Remove trailing slash unless it's just the domain
            if normalized.endswith('/') and normalized.count('/') > 3:
                normalized = normalized.rstrip('/')
            # Check if we've seen this URL before
            if normalized not in seen:
                seen.add(normalized)
                unique_urls.append(url)  # Keep original case for display
        return unique_urls
    
    def _get_urls_from_text(self):
        """Extract URLs from text widget, one per line."""
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            text_content = self.url_text_widget.get(1.0, END).strip()
            if not text_content:
                return []
            # Skip placeholder text
            if text_content == "Paste one URL or multiple to create a batch.":
                return []
            # Split by lines and filter out empty lines and placeholder
            urls = [line.strip() for line in text_content.split('\n') 
                   if line.strip() and line.strip() != "Paste one URL or multiple to create a batch."]
            return urls
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Fallback to Entry widget
            content = self.url_var.get().strip()
            if not content:
                return []
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.":
                return []
            # Check if it has newlines (shouldn't happen in Entry, but handle it)
            if '\n' in content:
                urls = [line.strip() for line in content.split('\n') 
                       if line.strip() and line.strip() != "Paste one URL or multiple to create a batch."]
                return urls
            return [content] if content else []
        return []
    
    def _validate_and_clean_urls(self, text):
        """Validate and clean URLs: split multiple URLs per line, remove empty lines, trim."""
        if not text or not text.strip():
            return ""
        
        # Remove placeholder text if present
        if text.strip() == "Paste one URL or multiple to create a batch.":
            return ""
        
        import re
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip placeholder text
            if line == "Paste one URL or multiple to create a batch.":
                continue
            
            # Check if line contains multiple 'bandcamp.com' occurrences
            line_lower = line.lower()
            bandcamp_count = line_lower.count('bandcamp.com')
            
            if bandcamp_count > 1:
                # Multiple URLs on same line - extract all URLs
                # First, find all positions where URLs start (https:// or http://)
                url_starts = []
                for match in re.finditer(r'https?://', line, re.IGNORECASE):
                    url_starts.append(match.start())
                
                # Extract each URL
                extracted_urls = []
                for i, start_pos in enumerate(url_starts):
                    # Find the end of this URL (start of next URL or end of line)
                    if i + 1 < len(url_starts):
                        # There's another URL after this one
                        end_pos = url_starts[i + 1]
                        url = line[start_pos:end_pos]
                    else:
                        # This is the last URL
                        url = line[start_pos:]
                    
                    # Clean up the URL (remove trailing whitespace, commas, semicolons)
                    url = url.rstrip(' \t,;')
                    
                    # Validate it contains bandcamp.com
                    if 'bandcamp.com' in url.lower():
                        extracted_urls.append(url)
                
                if extracted_urls:
                    # Add each found URL as a separate line
                    cleaned_lines.extend(extracted_urls)
                else:
                    # Fallback: try the original regex pattern (for URLs with separators)
                    url_pattern = r'https?://[^\s]*bandcamp\.com[^\s,;]*'
                    urls = re.findall(url_pattern, line, re.IGNORECASE)
                    if urls:
                        cleaned_lines.extend(urls)
                    else:
                        # Last resort: split by common delimiters and then extract URLs
                        parts = re.split(r'[\s,;]+', line)
                        for part in parts:
                            part = part.strip()
                            if part and 'bandcamp.com' in part.lower():
                                # Try to extract a valid URL from this part
                                url_match = re.search(r'https?://[^\s]*bandcamp\.com[^\s,;]*', part, re.IGNORECASE)
                                if url_match:
                                    cleaned_lines.append(url_match.group())
            elif bandcamp_count == 1:
                # Single URL - just add the line
                cleaned_lines.append(line)
            else:
                # No bandcamp.com - might be partial URL or invalid, keep it anyway
                cleaned_lines.append(line)
        
        # Join with newlines
        return '\n'.join(cleaned_lines)
    
    def _update_url_count_and_button(self):
        """Update URL count and download button text dynamically."""
        # Get current content
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            # ScrolledText is visible
            content = self.url_text_widget.get(1.0, END)
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Entry is visible
            content = self.url_var.get()
        else:
            content = ""
        
        # Get unique URLs (remove duplicates for counting)
        urls = self._extract_urls_from_content(content)
        unique_urls = self._remove_duplicate_urls(urls)
        url_count = len(unique_urls)
        
        # Update batch mode
        self.batch_mode = (url_count > 1)
        
        # Update download button text
        if hasattr(self, 'download_btn'):
            # Check if discography mode is enabled (for single URL or no URL)
            if url_count <= 1 and hasattr(self, 'download_discography_var') and self.download_discography_var.get():
                self.download_btn.config(text="Download Discography")
            elif url_count > 1:
                self.download_btn.config(text=f"Download {url_count} Albums")
            else:
                self.download_btn.config(text="Download Album")
        
        # Update discography checkbox state
        if hasattr(self, 'download_discography_var'):
            if url_count > 1:
                # Multiple URLs - disable discography checkbox
                self._disable_discography_checkbox()
            else:
                # Single URL - enable discography checkbox
                self._enable_discography_checkbox()
    
    def _disable_discography_checkbox(self):
        """Disable discography checkbox."""
        if hasattr(self, 'download_discography_check'):
            self.download_discography_check.config(state='disabled', fg='#808080')
            # Also uncheck it
            self.download_discography_var.set(False)
    
    def _enable_discography_checkbox(self):
        """Enable discography checkbox."""
        if hasattr(self, 'download_discography_check'):
            self.download_discography_check.config(state='normal', fg='#D4D4D4')
    
    def _set_entry_placeholder(self, entry, placeholder_text):
        """Set placeholder text for Entry widget."""
        # Only set if entry is empty
        if not entry.get():
            entry.insert(0, placeholder_text)
            entry.config(foreground='#808080')  # Gray color for placeholder
        
        def on_focus_in(event):
            if entry.get() == placeholder_text:
                entry.delete(0, END)
                entry.config(foreground='#CCCCCC')  # Normal text color
        
        def on_focus_out(event):
            # Deselect any selected text when losing focus
            entry.selection_clear()
            if not entry.get():
                entry.insert(0, placeholder_text)
                entry.config(foreground='#808080')
        
        entry.bind('<FocusIn>', on_focus_in)
        entry.bind('<FocusOut>', on_focus_out)
    
    
    def _check_url(self):
        """Actually check the URL and fetch metadata."""
        # Get content from either Entry or ScrolledText
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            content = self.url_text_widget.get(1.0, END)
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            content = self.url_var.get()
        else:
            content = ""
        
        # Extract URLs using the proper method that handles space-separated URLs
        urls = self._extract_urls_from_content(content)
        # Remove duplicates to match button counting behavior
        unique_urls = self._remove_duplicate_urls(urls)
        url = unique_urls[0] if unique_urls else ""
        
        # Strip whitespace and check if URL is actually empty
        url = url.strip() if url else ""
        
        # Reset metadata if URL is empty or just whitespace
        if not url or url == "Paste one URL or multiple to create a batch.":
            # Cancel any in-flight artwork fetches
            self.artwork_fetch_id += 1
            self.current_url_being_processed = None
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
            self.format_suggestion_shown = False  # Reset format suggestion flag
            self.current_thumbnail_url = None
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            return
        
        # Only fetch if it looks like a valid URL
        if "bandcamp.com" not in url.lower() and not url.startswith(("http://", "https://")):
            return
        
        # Only cancel artwork fetches if the URL actually changed
        # This prevents cancelling valid fetches when _check_url is called multiple times for the same URL
        if self.current_url_being_processed != url:
            # URL changed - cancel any in-flight artwork fetches for the old URL
            self.artwork_fetch_id += 1
            self.current_url_being_processed = url
            self.current_thumbnail_url = None
            self.album_art_fetching = False
        
        # Fetch metadata in background thread (only for first URL for preview)
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
                # Use better headers for restricted networks
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                headers = {
                    'User-Agent': user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive',
                    'Referer': 'https://bandcamp.com/',
                }
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
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
                # Enhanced options for restricted networks
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": True,
                    "socket_timeout": 30,
                    "retries": 5,
                    "fragment_retries": 5,
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "referer": "https://bandcamp.com/",
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
                    # Reset current_thumbnail_url check to allow fetching even if URL is same (new album might have same art)
                    # The flag reset in _check_url ensures we fetch new artwork when URL changes
                    if thumbnail_url and not self.album_art_fetching:
                        self.current_thumbnail_url = thumbnail_url
                        self.root.after(0, lambda url=thumbnail_url: self.fetch_and_display_album_art(url))
                    
                    # Try to detect format from first track (if entries available)
                    detected_format = None
                    if info.get("entries"):
                        entries = [e for e in info.get("entries", []) if e]
                        if entries:
                            first_entry = entries[0]
                            # With extract_flat, we might not have format info, so try to get it
                            # Check if we have format info in the entry
                            if first_entry.get("ext") or first_entry.get("acodec") or first_entry.get("container"):
                                ext = first_entry.get("ext") or ""
                                acodec = first_entry.get("acodec") or ""
                                container = first_entry.get("container") or ""
                                
                                # Determine format
                                if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                    detected_format = "m4a"
                                elif ext == "flac" or acodec == "flac":
                                    detected_format = "flac"
                                elif ext == "ogg" or acodec == "vorbis":
                                    detected_format = "ogg"
                                elif ext == "wav" or acodec == "pcm":
                                    detected_format = "wav"
                                elif ext == "mp3" or acodec == "mp3":
                                    detected_format = "mp3"
                            
                            # If we don't have format info (extract_flat mode), do a quick extraction for first track
                            if not detected_format and first_entry.get("url"):
                                try:
                                    track_url = first_entry.get("url")
                                    if track_url:
                                        # Quick format detection extraction
                                        # Enhanced options for restricted networks
                                        format_ydl_opts = {
                                            "quiet": True,
                                            "no_warnings": True,
                                            "extract_flat": False,
                                            "socket_timeout": 30,
                                            "retries": 5,
                                            "fragment_retries": 5,
                                            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                            "referer": "https://bandcamp.com/",
                                        }
                                        with yt_dlp.YoutubeDL(format_ydl_opts) as format_ydl:
                                            track_info = format_ydl.extract_info(track_url, download=False)
                                            if track_info:
                                                ext = track_info.get("ext") or ""
                                                acodec = track_info.get("acodec") or ""
                                                container = track_info.get("container") or ""
                                                
                                                # Determine format
                                                if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                                    detected_format = "m4a"
                                                elif ext == "flac" or acodec == "flac":
                                                    detected_format = "flac"
                                                elif ext == "ogg" or acodec == "vorbis":
                                                    detected_format = "ogg"
                                                elif ext == "wav" or acodec == "pcm":
                                                    detected_format = "wav"
                                                elif ext == "mp3" or acodec == "mp3":
                                                    detected_format = "mp3"
                                except Exception as e:
                                    # Log format detection failure for debugging (but don't show to user)
                                    pass  # Silently fail format detection - will try again during download
                            
                            # Also try to get format from the album-level info if available
                            if not detected_format and info:
                                # Check if format info is available at album level
                                ext = info.get("ext") or ""
                                acodec = info.get("acodec") or ""
                                container = info.get("container") or ""
                                
                                if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                    detected_format = "m4a"
                                elif ext == "flac" or acodec == "flac":
                                    detected_format = "flac"
                                elif ext == "ogg" or acodec == "vorbis":
                                    detected_format = "ogg"
                                elif ext == "wav" or acodec == "pcm":
                                    detected_format = "wav"
                                elif ext == "mp3" or acodec == "mp3":
                                    detected_format = "mp3"
                    
                    # Update album_info with detected format
                    if detected_format:
                        self.album_info["detected_format"] = detected_format
                        # Update preview to show detected format extension
                        self.root.after(0, self.update_preview)
                        # If format is not MP3, suggest Original format
                        if detected_format != "mp3":
                            self.root.after(0, lambda fmt=detected_format: self._suggest_format_for_detected(fmt))
                    else:
                        # If format still not detected, try a full extraction of the album URL as fallback
                        # This is more reliable than extracting individual tracks
                        try:
                            full_extract_opts = {
                                "quiet": True,
                                "no_warnings": True,
                                "extract_flat": False,  # Full extraction
                                "socket_timeout": 30,
                                "retries": 3,
                                "fragment_retries": 3,
                                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                "referer": "https://bandcamp.com/",
                            }
                            with yt_dlp.YoutubeDL(full_extract_opts) as full_ydl:
                                full_info = full_ydl.extract_info(url, download=False)
                                if full_info:
                                    # Try to get format from first entry
                                    if full_info.get("entries"):
                                        entries = [e for e in full_info.get("entries", []) if e]
                                        if entries:
                                            first_entry = entries[0]
                                            ext = first_entry.get("ext") or ""
                                            acodec = first_entry.get("acodec") or ""
                                            container = first_entry.get("container") or ""
                                            
                                            # Determine format
                                            if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                                detected_format = "m4a"
                                            elif ext == "flac" or acodec == "flac":
                                                detected_format = "flac"
                                            elif ext == "ogg" or acodec == "vorbis":
                                                detected_format = "ogg"
                                            elif ext == "wav" or acodec == "pcm":
                                                detected_format = "wav"
                                            elif ext == "mp3" or acodec == "mp3":
                                                detected_format = "mp3"
                                    
                                    # If still not found, try album-level
                                    if not detected_format:
                                        ext = full_info.get("ext") or ""
                                        acodec = full_info.get("acodec") or ""
                                        container = full_info.get("container") or ""
                                        
                                        if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                            detected_format = "m4a"
                                        elif ext == "flac" or acodec == "flac":
                                            detected_format = "flac"
                                        elif ext == "ogg" or acodec == "vorbis":
                                            detected_format = "ogg"
                                        elif ext == "wav" or acodec == "pcm":
                                            detected_format = "wav"
                                        elif ext == "mp3" or acodec == "mp3":
                                            detected_format = "mp3"
                                    
                                    # Update if format was detected
                                    if detected_format:
                                        self.album_info["detected_format"] = detected_format
                                        self.root.after(0, self.update_preview)
                        except Exception:
                            pass  # Silently fail - format detection is optional
            except Exception:
                pass  # Silently fail - HTML extraction is primary method
        
        # Start with fast HTML extraction
        threading.Thread(target=fetch_from_html, daemon=True).start()
    
    def _suggest_format_for_detected(self, detected_format):
        """Suggest Original format when a non-MP3 format is detected."""
        # Only suggest once per URL and if current format is not already Original
        if self.format_suggestion_shown:
            return
        
        current_format = self.format_var.get()
        if current_format != "Original":
            # Log the detected format
            format_names = {
                "m4a": "M4A/ALAC",
                "flac": "FLAC",
                "ogg": "OGG",
                "wav": "WAV"
            }
            format_name = format_names.get(detected_format, detected_format.upper())
            self.log(f"ℹ Detected format: {format_name}. Consider using 'Original' format to download without conversion.")
            self.format_suggestion_shown = True  # Mark as shown
    
    def fetch_thumbnail_from_html(self, url):
        """Extract thumbnail URL directly from Bandcamp HTML page (fast method)."""
        def fetch():
            try:
                import urllib.request
                import re
                
                # Fetch the HTML page directly (fast, single request)
                # Use better headers for restricted networks
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                headers = {
                    'User-Agent': user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive',
                    'Referer': 'https://bandcamp.com/',
                }
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
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
                # Enhanced options for restricted networks
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,  # Need full extraction to get thumbnail
                    "socket_timeout": 30,
                    "retries": 5,
                    "fragment_retries": 5,
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "referer": "https://bandcamp.com/",
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
                        
                        # Also detect format from this full extraction (since we have full info here)
                        # This is a good fallback if format wasn't detected earlier
                        if not self.album_info.get("detected_format"):
                            detected_format = None
                            # Try to get format from first entry
                            if info.get("entries"):
                                entries = [e for e in info.get("entries", []) if e]
                                if entries:
                                    first_entry = entries[0]
                                    ext = first_entry.get("ext") or ""
                                    acodec = first_entry.get("acodec") or ""
                                    container = first_entry.get("container") or ""
                                    
                                    # Determine format
                                    if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                        detected_format = "m4a"
                                    elif ext == "flac" or acodec == "flac":
                                        detected_format = "flac"
                                    elif ext == "ogg" or acodec == "vorbis":
                                        detected_format = "ogg"
                                    elif ext == "wav" or acodec == "pcm":
                                        detected_format = "wav"
                                    elif ext == "mp3" or acodec == "mp3":
                                        detected_format = "mp3"
                            
                            # If not found in entries, try album-level info
                            if not detected_format:
                                ext = info.get("ext") or ""
                                acodec = info.get("acodec") or ""
                                container = info.get("container") or ""
                                
                                if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                    detected_format = "m4a"
                                elif ext == "flac" or acodec == "flac":
                                    detected_format = "flac"
                                elif ext == "ogg" or acodec == "vorbis":
                                    detected_format = "ogg"
                                elif ext == "wav" or acodec == "pcm":
                                    detected_format = "wav"
                                elif ext == "mp3" or acodec == "mp3":
                                    detected_format = "mp3"
                            
                            # Update album_info with detected format and refresh preview
                            if detected_format:
                                self.album_info["detected_format"] = detected_format
                                self.root.after(0, self.update_preview)
            except Exception:
                pass  # Silently fail - thumbnail is optional
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _fetch_with_retry(self, url, max_retries=3, timeout=15):
        """Fetch URL with retry logic and better headers for restricted networks."""
        import urllib.request
        import time
        
        # Use a more complete user agent string (mimics a real browser)
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        headers = {
            'User-Agent': user_agent,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'identity',  # Don't request compression
            'Connection': 'keep-alive',
            'Referer': 'https://bandcamp.com/',
        }
        
        last_error = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return response.read()
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    # Exponential backoff: wait 1s, 2s, 4s
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                else:
                    # Last attempt failed
                    raise last_error
        
        raise last_error
    
    def _is_url_field_empty(self):
        """Check if the URL field is currently empty."""
        try:
            if self.url_text_widget and self.url_text_widget.winfo_viewable():
                content = self.url_text_widget.get(1.0, END).strip()
            elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
                content = self.url_var.get().strip()
                # Skip placeholder text
                if content == "Paste one URL or multiple to create a batch.":
                    content = ""
            else:
                content = ""
            return not content or not content.strip()
        except Exception:
            return True  # If we can't check, assume empty to be safe
    
    def _verify_file_fully_written(self, file_path, is_fast_mode=False):
        """
        Verify that a file is fully written to disk.
        Checks: file exists, has non-zero size, is readable, and size is stable.
        Returns True if file is fully written and accessible, False otherwise.
        
        Args:
            file_path: Path object to the file to verify
            is_fast_mode: If True, uses longer delay for stability check (for Original Format mode)
        """
        try:
            if not file_path.exists():
                return False
            
            # Check file has non-zero size
            size1 = file_path.stat().st_size
            if size1 == 0:
                return False  # Empty file, not fully written yet
            
            # Small delay to check if size is stable (not still being written)
            # Fast modes (Original Format) need slightly longer delay since files complete very quickly
            import time
            stability_delay = 0.15 if is_fast_mode else 0.1
            time.sleep(stability_delay)
            
            # Check size again - if it changed, file is still being written
            if not file_path.exists():
                return False
            size2 = file_path.stat().st_size
            if size1 != size2:
                return False  # Size changed, still being written
            
            # Try to open file to ensure it's readable (fully flushed to disk)
            try:
                with open(file_path, 'rb') as f:
                    # Try to read first byte to ensure file is accessible
                    f.read(1)
                return True
            except (IOError, OSError, PermissionError):
                # File exists but can't be read - might still be locked by writer
                return False
                
        except (OSError, PermissionError, Exception):
            # Any error means file isn't ready
            return False
    
    def fetch_and_display_album_art(self, thumbnail_url):
        """Fetch and display album art asynchronously (second phase - doesn't block preview)."""
        if not thumbnail_url:
            self.clear_album_art()
            return
        
        # Check if URL field is empty - if so, don't fetch/display artwork
        if self._is_url_field_empty():
            self.clear_album_art()
            return
        
        # Prevent multiple simultaneous fetches
        # If flag is stuck (has been True for more than 30 seconds), reset it to allow new fetches
        if self.album_art_fetching:
            # Check if we should force reset (safety mechanism)
            if hasattr(self, '_artwork_fetch_start_time'):
                import time
                if time.time() - self._artwork_fetch_start_time > 30:
                    # Flag has been stuck for 30+ seconds, reset it
                    self.album_art_fetching = False
                else:
                    return
            else:
                return
        
        # Increment fetch ID to cancel any in-flight fetches
        self.artwork_fetch_id += 1
        fetch_id = self.artwork_fetch_id
        
        # Track when fetch started (for timeout detection)
        import time
        self._artwork_fetch_start_time = time.time()
        
        self.album_art_fetching = True
        
        def download_and_display():
            try:
                # Check if this fetch was cancelled (new fetch started)
                if fetch_id != self.artwork_fetch_id:
                    # Reset flag in a thread-safe way
                    def reset_flag():
                        self.album_art_fetching = False
                    self.root.after(0, reset_flag)
                    return
                
                # Check again before downloading (field might have been cleared)
                if self._is_url_field_empty():
                    if fetch_id == self.artwork_fetch_id:  # Only clear if still current
                        self.root.after(0, self.clear_album_art)
                    # Reset flag in a thread-safe way
                    def reset_flag():
                        self.album_art_fetching = False
                        if hasattr(self, '_artwork_fetch_start_time'):
                            del self._artwork_fetch_start_time
                    self.root.after(0, reset_flag)
                    return
                
                import io
                from PIL import Image, ImageTk
                
                # Download the image with retry logic
                image_data = self._fetch_with_retry(thumbnail_url, max_retries=3, timeout=15)
                
                # Check if this fetch was cancelled during download
                if fetch_id != self.artwork_fetch_id:
                    # Reset flag in a thread-safe way
                    def reset_flag():
                        self.album_art_fetching = False
                    self.root.after(0, reset_flag)
                    return
                
                # Check again after download (field might have been cleared during download)
                if self._is_url_field_empty():
                    if fetch_id == self.artwork_fetch_id:  # Only clear if still current
                        self.root.after(0, self.clear_album_art)
                    # Reset flag in a thread-safe way
                    def reset_flag():
                        self.album_art_fetching = False
                        if hasattr(self, '_artwork_fetch_start_time'):
                            del self._artwork_fetch_start_time
                    self.root.after(0, reset_flag)
                    return
                
                # Open and resize image
                img = Image.open(io.BytesIO(image_data))
                
                # Resize to fit canvas (150x150) while maintaining aspect ratio
                img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Update UI on main thread
                def update_ui():
                    # Check if this fetch was cancelled before updating UI
                    if fetch_id != self.artwork_fetch_id:
                        return
                    
                    # Final check before displaying - field might have been cleared
                    if self._is_url_field_empty():
                        self.clear_album_art()
                        return
                    
                    # Clear canvas
                    self.album_art_canvas.delete("all")
                    
                    # Calculate position to center the image
                    img_width = photo.width()
                    img_height = photo.height()
                    x = (150 - img_width) // 2
                    y = (150 - img_height) // 2
                    
                    # Display image on canvas
                    self.album_art_canvas.create_image(x + img_width // 2, y + img_height // 2, image=photo, anchor='center')
                    
                    # Keep a reference to prevent garbage collection
                    self.album_art_image = photo
                
                if fetch_id == self.artwork_fetch_id:  # Only update if still current
                    self.root.after(0, update_ui)
                
                # Always reset flag after completion (use root.after to ensure thread safety)
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
                
            except ImportError:
                # PIL not available - can't display images
                if fetch_id == self.artwork_fetch_id:  # Only update if still current
                    self.root.after(0, lambda: self.album_art_canvas.delete("all"))
                    self.root.after(0, lambda: self.album_art_canvas.create_text(
                        75, 75, text="PIL required\nfor album art\n\nInstall Pillow:\npip install Pillow", 
                        fill='#808080', font=("Segoe UI", 7), justify='center'
                    ))
                # Always reset flag after error
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
            except Exception as e:
                # Failed to load image - clear and show placeholder
                if fetch_id == self.artwork_fetch_id:  # Only clear if still current
                    self.root.after(0, self.clear_album_art)
                # Always reset flag after error
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
        
        # Download in background thread
        threading.Thread(target=download_and_display, daemon=True).start()
    
    def clear_album_art(self):
        """Clear the album art display."""
        try:
            self.album_art_canvas.delete("all")
            self.album_art_canvas.create_text(
                75, 75,
                text="Album Art",
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
            # Hide the show album art button by making it invisible (keep in grid to prevent layout shift)
            self.show_album_art_btn.config(fg='#1E1E1E', cursor='arrow')  # Match background, no hand cursor
        else:
            # Hide album art panel
            self.album_art_frame.grid_remove()
            # Update settings frame to span 3 columns (full width)
            self.settings_frame.grid_configure(columnspan=3)
            # Show the show album art button by making it visible
            self.show_album_art_btn.config(fg='#808080', cursor='hand2')  # Visible, hand cursor
        
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
            "original": ".mp3",  # Default to .mp3 instead of .??? since most Bandcamp albums are MP3
            "mp3": ".mp3",
            "flac": ".flac",
            "ogg": ".ogg",
            "wav": ".wav"
        }
        ext = ext_map.get(base_format, ".mp3")
        
        # If Original format is selected and we have a detected format, use that instead of default .mp3
        if base_format == "original" and self.album_info.get("detected_format"):
            detected = self.album_info.get("detected_format")
            detected_ext_map = {
                "m4a": ".m4a",
                "flac": ".flac",
                "ogg": ".ogg",
                "wav": ".wav",
                "mp3": ".mp3"
            }
            detected_ext = detected_ext_map.get(detected)
            if detected_ext:
                ext = detected_ext
        
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
    
    def extract_artist_page_url(self, url):
        """Extract artist page URL from album/track URL.
        
        Args:
            url: Bandcamp URL (can be album, track, or artist page)
            
        Returns:
            Artist page URL (e.g., https://artist.bandcamp.com) or None if invalid
        """
        try:
            from urllib.parse import urlparse, urlunparse
            
            parsed = urlparse(url)
            
            # Check if it's already an artist page (no path or just '/')
            if not parsed.path or parsed.path == '/':
                return url  # Already an artist page
            
            # Extract artist page URL by removing path and query
            # Keep scheme, netloc (domain), but remove path, params, query, fragment
            artist_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                '',  # Empty path = artist page
                '',  # No params
                '',  # No query
                ''   # No fragment
            ))
            
            return artist_url
        except Exception:
            return None
    
    def browse_folder(self):
        """Open folder browser dialog."""
        folder = filedialog.askdirectory(title="Select Download Folder")
        if folder:
            self.path_var.set(folder)
            self.save_path()
            self.update_preview()
    
    def _clear_log(self):
        """Clear the status log."""
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, END)
        self.log_text.config(state='disabled')
        # Clear any search highlights
        if hasattr(self, 'search_tag_name'):
            self.log_text.tag_remove(self.search_tag_name, 1.0, END)
        if hasattr(self, 'current_match_tag_name'):
            self.log_text.tag_remove(self.current_match_tag_name, 1.0, END)
    
    def _toggle_debug_mode(self):
        """Toggle debug mode on/off."""
        self.debug_mode = self.debug_mode_var.get()
    
    def log(self, message):
        """Add message to log. Filters DEBUG messages if debug mode is disabled."""
        # If message starts with "DEBUG:" and debug mode is off, skip it
        if message.startswith("DEBUG:") and not self.debug_mode:
            return
        # Temporarily enable widget to insert text, then disable again (read-only)
        self.log_text.config(state='normal')
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()
    
    def _on_log_click(self):
        """Handle click on log text to enable Ctrl+F."""
        # Give focus to log_text so Ctrl+F works
        self.log_text.focus_set()
        return "break"  # Prevent default behavior
    
    def _show_search_bar_if_log_focused(self):
        """Show search bar if log text has focus."""
        try:
            focused = self.root.focus_get()
            if focused == self.log_text or (hasattr(focused, 'master') and focused.master == self.log_text.master):
                self._show_search_bar()
        except:
            pass
    
    def _show_search_bar(self):
        """Show the search bar for finding text in the log. If already visible, hide it (toggle behavior)."""
        if self.search_frame and self.search_frame.winfo_viewable():
            # Already visible - call _hide_search_bar directly (same as close button)
            self._hide_search_bar()
            return
        
        # Create search frame if it doesn't exist
        if not self.search_frame:
            self._create_search_bar()
        
        # Show the search frame at the bottom (after log_content)
        self.search_frame.grid(row=2, column=0, columnspan=2, sticky=(W, E), padx=6, pady=(4, 6))
        if self.search_entry:
            self.search_entry.focus_set()
            self.search_entry.select_range(0, END)
    
    def _create_search_bar(self):
        """Create the search bar UI."""
        self.search_frame = Frame(self.log_frame, bg='#252526', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        
        # Search label
        search_label = Label(self.search_frame, text="Find:", bg='#252526', fg='#D4D4D4', font=("Segoe UI", 8))
        search_label.grid(row=0, column=0, sticky=W, padx=(6, 4), pady=4)
        
        # Search entry
        self.search_var = StringVar()
        self.search_entry = Entry(self.search_frame, textvariable=self.search_var, width=25, 
                                 font=("Segoe UI", 8), bg='#1E1E1E', fg='#CCCCCC', 
                                 insertbackground='#CCCCCC', relief='flat', borderwidth=1, 
                                 highlightthickness=1, highlightbackground='#3E3E42',
                                 highlightcolor='#007ACC')
        self.search_entry.grid(row=0, column=1, sticky=(W, E), padx=(0, 4), pady=4)
        
        # Match count label (shows "X of Y" or "No matches") - between search field and buttons
        self.search_count_label = Label(self.search_frame, text="", bg='#252526', fg='#808080',
                                       font=("Segoe UI", 8))
        self.search_count_label.grid(row=0, column=2, sticky=W, padx=(0, 4), pady=4)
        
        # Next button - styled like Clear Log button
        next_btn = ttk.Button(self.search_frame, text="Next", command=self._find_next,
                              cursor='hand2', style='Small.TButton')
        next_btn.grid(row=0, column=3, sticky=W, padx=(0, 2), pady=4)
        
        # Previous button - styled like Clear Log button
        prev_btn = ttk.Button(self.search_frame, text="Previous", command=self._find_previous,
                             cursor='hand2', style='Small.TButton')
        prev_btn.grid(row=0, column=4, sticky=W, padx=(0, 2), pady=4)
        
        # Close button (X)
        self.search_close_btn = Label(self.search_frame, text="✕", bg='#252526', fg='#808080',
                                     font=("Segoe UI", 9), cursor='hand2', width=1, height=1)
        self.search_close_btn.grid(row=0, column=5, sticky=E, padx=(4, 6), pady=4)
        
        # Store close button reference and bind properly
        def on_close_click(event):
            self._hide_search_bar()
            return "break"  # Prevent event propagation
        
        self.search_close_btn.bind("<Button-1>", on_close_click)
        self.search_close_btn.bind("<Enter>", lambda e: self.search_close_btn.config(fg='#D4D4D4'))
        self.search_close_btn.bind("<Leave>", lambda e: self.search_close_btn.config(fg='#808080'))
        
        # Configure column weights
        self.search_frame.columnconfigure(1, weight=1)
        
        # Bind events
        # Use KeyRelease for search-as-you-type, but skip Enter key to avoid double-triggering
        def on_key_release(event):
            if event.keysym != 'Return':
                self._on_search_change()
        
        self.search_entry.bind('<KeyRelease>', on_key_release)
        
        # Enter key - find next match (only if search has been performed)
        def on_enter(event):
            search_text = self.search_var.get()
            if search_text:
                # If no matches yet, perform search first (will go to first match)
                if not self.search_matches:
                    self._perform_search(search_text, reset_index=True)
                else:
                    # Otherwise, just go to next match (don't reset)
                    self._find_next()
            return "break"  # Prevent default behavior
        
        self.search_entry.bind('<Return>', on_enter)
        self.search_entry.bind('<Shift-Return>', lambda e: (self._find_previous() if self.search_matches else None) or "break")
        # ESC and Ctrl+F call the exact same handler as the close button
        self.search_entry.bind('<Escape>', on_close_click)
        self.search_entry.bind('<Control-f>', on_close_click)
        
        # Make search frame and all its children clickable/interactive
        # This prevents the unfocus handler from stealing focus
        def on_search_frame_click(event):
            # Allow clicking on search frame to work normally
            return None  # Don't prevent default
        
        self.search_frame.bind('<Button-1>', on_search_frame_click)
        
        # Also bind to all children to ensure they're interactive
        # But skip the close button since it has its own handler
        for child in self.search_frame.winfo_children():
            if child != self.search_close_btn:
                child.bind('<Button-1>', lambda e: None)  # Allow clicks
    
    def _hide_search_bar(self):
        """Hide the search bar and clear highlights."""
        # Clear the search field first - this will trigger _on_search_change() which clears highlights
        if hasattr(self, 'search_var') and self.search_var:
            self.search_var.set("")
        
        if self.search_frame:
            self.search_frame.grid_remove()
        
        # Also explicitly clear highlights as backup
        self._clear_search_highlights()
        
        # Ensure root window can receive keyboard events (for Ctrl+F to work)
        # Use after_idle to ensure this happens after the search frame is removed
        self.root.after_idle(lambda: self.root.focus_set())
    
    def _toggle_window_height(self):
        """Toggle window height between default and expanded (default + 150px)."""
        current_height = self.root.winfo_height()
        current_width = self.root.winfo_width()
        
        # Determine if we should expand or collapse
        # If current height is greater than default, collapse to default
        # Otherwise, expand to default + expand_amount
        if current_height > self.default_window_height:
            # Collapse to default height
            new_height = self.default_window_height
            self.is_expanded = False
            self.expand_collapse_btn.config(text="▼")  # Down triangle (like > rotated down)
        else:
            # Expand by expand_amount
            new_height = self.default_window_height + self.expand_amount
            self.is_expanded = True
            self.expand_collapse_btn.config(text="▲")  # Up triangle (like > rotated up)
        
        # Get current window position
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        
        # Update window geometry
        self.root.geometry(f"{current_width}x{new_height}+{x}+{y}")
        
        # Update button state based on new height
        self.root.after(100, self._update_expand_button_state)
    
    def _update_expand_button_state(self):
        """Update expand/collapse button arrow based on current window height."""
        if not hasattr(self, 'expand_collapse_btn'):
            return
        
        current_height = self.root.winfo_height()
        if current_height > self.default_window_height:
            self.expand_collapse_btn.config(text="▲")  # Up triangle (like > rotated up)
            self.is_expanded = True
        else:
            self.expand_collapse_btn.config(text="▼")  # Down triangle (like > rotated down)
            self.is_expanded = False
    
    def _on_window_configure(self, event):
        """Handle window resize events to update expand/collapse button state."""
        # Only update if this is a window resize (not widget resize)
        if event.widget == self.root:
            # Update button state immediately when window is resized
            # Use a small delay to ensure height is updated
            self.root.after(10, self._update_expand_button_state)
    
    def _start_url_text_resize(self, event):
        """Start resizing the URL text widget."""
        if not self.url_text_widget:
            return
        # Use a small delay to allow double-click detection
        self.url_text_resize_drag_started = False
        self.url_text_resize_start_y = event.y_root
        # Get current widget height in pixels
        self.url_text_resize_start_height = self.url_text_widget.winfo_height()
        # Start drag after a small delay (allows double-click to cancel it)
        self.root.after(150, lambda: self._actually_start_url_text_resize())
    
    def _actually_start_url_text_resize(self):
        """Actually start the resize drag operation (called after delay to allow double-click detection)."""
        if not self.url_text_resize_drag_started:
            self.url_text_resizing = True
            self.url_text_resize_drag_started = True
    
    def _on_url_text_resize(self, event):
        """Handle dragging to resize the URL text widget."""
        if not self.url_text_resizing or not self.url_text_widget:
            return
        
        # Calculate the change in Y position
        delta_y = event.y_root - self.url_text_resize_start_y
        
        # Calculate new height in pixels
        new_height_px = self.url_text_resize_start_height + delta_y
        
        # Enforce maximum height (250px)
        new_height_px = min(new_height_px, self.url_text_max_height_px)
        
        # Convert pixels to lines (approximate: each line is about 20px with Segoe UI 9pt)
        # Get actual line height from the widget
        try:
            line_height = self.url_text_widget.dlineinfo("1.0")
            if line_height:
                pixels_per_line = line_height[3]  # Height of line
                if pixels_per_line > 0:
                    new_height_lines = max(2, int(new_height_px / pixels_per_line))
                else:
                    # Fallback: assume ~20px per line
                    new_height_lines = max(2, int(new_height_px / 20))
            else:
                # Fallback: assume ~20px per line
                new_height_lines = max(2, int(new_height_px / 20))
        except Exception:
            # Fallback: assume ~20px per line
            new_height_lines = max(2, int(new_height_px / 20))
        
        # Update widget height
        self.url_text_widget.config(height=new_height_lines)
        self.url_text_height = new_height_lines
    
    def _end_url_text_resize(self, event):
        """End resizing the URL text widget."""
        self.url_text_resizing = False
    
    def _toggle_url_text_height(self, event):
        """Toggle URL text widget between minimum and maximum height on double-click."""
        if not self.url_text_widget:
            return
        
        # Cancel any ongoing drag operation
        self.url_text_resizing = False
        
        try:
            current_height = self.url_text_widget.cget('height')
            
            # If at minimum height (2 lines), maximize it
            if current_height <= 2:
                # Calculate maximum height in lines based on pixel limit
                try:
                    line_height = self.url_text_widget.dlineinfo("1.0")
                    if line_height:
                        pixels_per_line = line_height[3]  # Height of line
                        if pixels_per_line > 0:
                            max_height_lines = int(self.url_text_max_height_px / pixels_per_line)
                        else:
                            # Fallback: assume ~20px per line
                            max_height_lines = int(self.url_text_max_height_px / 20)
                    else:
                        # Fallback: assume ~20px per line
                        max_height_lines = int(self.url_text_max_height_px / 20)
                except Exception:
                    # Fallback: assume ~20px per line
                    max_height_lines = int(self.url_text_max_height_px / 20)
                
                # Set to maximum height
                self.url_text_widget.config(height=max_height_lines)
                self.url_text_height = max_height_lines
            else:
                # If taller than minimum, minimize it
                self.url_text_widget.config(height=2)
                self.url_text_height = 2
        except Exception:
            pass  # Silently fail if there's an issue
    
    def _is_widget_in_search_frame(self, widget):
        """Check if widget is part of the search frame."""
        if not self.search_frame:
            return False
        current = widget
        while current:
            if current == self.search_frame:
                return True
            try:
                current = current.master
            except:
                break
        return False
    
    def _on_search_change(self):
        """Handle search text change."""
        search_text = self.search_var.get()
        if not search_text:
            self._clear_search_highlights()
            return
        self._perform_search(search_text)
    
    def _perform_search(self, search_text, reset_index=True):
        """Search for text in log and highlight matches.
        
        Args:
            search_text: Text to search for
            reset_index: If True, reset to first match. If False, preserve current index if valid.
        """
        if not search_text:
            return
        
        # Clear previous highlights
        self._clear_search_highlights()
        
        # Get all text from log
        self.log_text.config(state='normal')
        content = self.log_text.get(1.0, END)
        self.log_text.config(state='disabled')
        
        if not content:
            return
        
        # Find all matches (case-insensitive)
        import re
        pattern = re.escape(search_text)
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        
        if not matches:
            return
        
        # Store match positions
        self.search_matches = []
        for match in matches:
            start_char = match.start()
            end_char = match.end()
            
            # Convert character position to line.column format
            # Count lines up to start position
            lines_before_start = content[:start_char].split('\n')
            line_start = len(lines_before_start)
            col_start = len(lines_before_start[-1])
            
            # Count lines up to end position
            lines_before_end = content[:end_char].split('\n')
            line_end = len(lines_before_end)
            col_end = len(lines_before_end[-1])
            
            start_index = f"{line_start}.{col_start}"
            end_index = f"{line_end}.{col_end}"
            self.search_matches.append((start_index, end_index))
        
        # Highlight all matches
        for start, end in self.search_matches:
            self.log_text.tag_add(self.search_tag_name, start, end)
        
        # Update match count display
        self._update_search_count()
        
        # Go to first match (or preserve current if reset_index is False)
        if self.search_matches:
            if reset_index or self.current_match_index < 0 or self.current_match_index >= len(self.search_matches):
                self.current_match_index = 0
            self._scroll_to_match(self.current_match_index)
    
    def _clear_search_highlights(self):
        """Clear all search highlights."""
        self.log_text.tag_remove(self.search_tag_name, 1.0, END)
        self.log_text.tag_remove(self.current_match_tag_name, 1.0, END)
        self.search_matches = []
        self.current_match_index = -1
        # Clear match count display
        if hasattr(self, 'search_count_label') and self.search_count_label:
            self.search_count_label.config(text="")
    
    def _update_search_count(self):
        """Update the match count display."""
        if not hasattr(self, 'search_count_label') or not self.search_count_label:
            return
        
        match_count = len(self.search_matches)
        if match_count == 0:
            self.search_count_label.config(text="No matches", fg='#808080')
        else:
            current = self.current_match_index + 1 if self.current_match_index >= 0 else 1
            self.search_count_label.config(text=f"{current} of {match_count}", fg='#D4D4D4')
    
    def _find_next(self):
        """Find next match."""
        if not self.search_matches:
            search_text = self.search_var.get()
            if search_text:
                self._perform_search(search_text)
            return
        
        if self.current_match_index < len(self.search_matches) - 1:
            self.current_match_index += 1
        else:
            self.current_match_index = 0  # Wrap around
        
        self._update_search_count()
        self._scroll_to_match(self.current_match_index)
    
    def _find_previous(self):
        """Find previous match."""
        if not self.search_matches:
            search_text = self.search_var.get()
            if search_text:
                self._perform_search(search_text)
            return
        
        if self.current_match_index > 0:
            self.current_match_index -= 1
        else:
            self.current_match_index = len(self.search_matches) - 1  # Wrap around
        
        self._update_search_count()
        self._scroll_to_match(self.current_match_index)
    
    def _scroll_to_match(self, match_index):
        """Scroll to the specified match and highlight it in green."""
        if not self.search_matches or match_index < 0 or match_index >= len(self.search_matches):
            return
        
        # Remove green highlight from previous current match
        self.log_text.tag_remove(self.current_match_tag_name, 1.0, END)
        
        start_pos, end_pos = self.search_matches[match_index]
        
        # Temporarily enable to scroll
        self.log_text.config(state='normal')
        # Remove previous selection
        self.log_text.tag_remove("sel", 1.0, END)
        # Add green highlight to current match (on top of yellow)
        self.log_text.tag_add(self.current_match_tag_name, start_pos, end_pos)
        # Select the current match (for text selection)
        self.log_text.tag_add("sel", start_pos, end_pos)
        # Scroll to make it visible
        self.log_text.see(start_pos)
        self.log_text.config(state='disabled')
    
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
        
        # Check if path exists - if not, offer to create it
        if not path_obj.exists():
            # Ask user if they want to create the directory
            response = messagebox.askyesno(
                "Path Does Not Exist",
                f"The path does not exist:\n{path}\n\n"
                "Would you like to create it?"
            )
            if response:
                try:
                    # Create the directory and all parent directories if needed
                    path_obj.mkdir(parents=True, exist_ok=True)
                    # Verify it was created successfully
                    if not path_obj.exists() or not path_obj.is_dir():
                        return False, f"Failed to create the directory:\n{path}\n\nPlease check the path and try again."
                except PermissionError:
                    return False, f"Permission denied: Cannot create directory at:\n{path}\n\nPlease choose a different location or run with administrator privileges."
                except OSError as e:
                    # Handle various OS errors (invalid characters, too long path, network issues, etc.)
                    error_msg = str(e)
                    if "invalid argument" in error_msg.lower() or "filename" in error_msg.lower():
                        return False, f"Invalid path: The path contains invalid characters or is too long.\n\nPath: {path}\n\nPlease choose a different path."
                    elif "network" in error_msg.lower() or "unreachable" in error_msg.lower():
                        return False, f"Network error: Cannot access the network path:\n{path}\n\nPlease check your network connection."
                    else:
                        return False, f"Cannot create directory:\n{path}\n\nError: {error_msg}"
                except Exception as e:
                    return False, f"Unexpected error creating directory:\n{path}\n\nError: {str(e)}"
            else:
                return False, "Please select an existing download path or allow the app to create it."
        
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
        # If multi-line field is visible, collapse to single-line to preserve all URLs
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            self._collapse_to_entry()
        
        # Get content from current input widget (should be Entry now)
        if self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            content = self.url_var.get()
        elif self.url_text_widget and self.url_text_widget.winfo_viewable():
            # Fallback in case collapse didn't work
            content = self.url_text_widget.get(1.0, END)
        else:
            content = ""
        
        # Validate and clean URLs (split multiple URLs on same line, etc.)
        cleaned_content = self._validate_and_clean_urls(content)
        
        # Extract URLs from cleaned content
        urls = self._extract_urls_from_content(cleaned_content)
        
        # Remove duplicates
        unique_urls = self._remove_duplicate_urls(urls)
        
        if not unique_urls:
            messagebox.showerror("Error", "Please enter at least one Bandcamp album URL.")
            return
        
        # Validate URLs
        valid_urls = []
        for url in unique_urls:
            url = url.strip()
            if not url:
                continue
            if "bandcamp.com" not in url.lower():
                response = messagebox.askyesno(
                    "Warning",
                    f"This doesn't appear to be a Bandcamp URL:\n{url}\n\nContinue anyway?"
                )
                if not response:
                    continue
            valid_urls.append(url)
        
        if not valid_urls:
            messagebox.showerror("Error", "No valid URLs to download.")
            return
        
        # Update the UI with cleaned, deduplicated URLs
        # Flatten all URLs to single line for Entry widget
        flattened_urls = ' '.join(valid_urls)
        
        # Always update Entry widget (we collapsed it earlier if it was multiline)
        if self.url_entry_widget:
            self.url_var.set(flattened_urls)
            # Remove placeholder styling
            self.url_entry_widget.config(foreground='#CCCCCC')
            # Ensure Entry is visible
            if not self.url_entry_widget.winfo_viewable():
                # Re-grid Entry if it's not visible
                text_frame = getattr(self, 'url_text_frame', None) or (self.url_text_widget.master if self.url_text_widget else None)
                if text_frame:
                    text_frame.grid_remove()
                self.url_entry_widget.grid(row=0, column=0, sticky=(W, E), pady=0, padx=(0, 4))
                self.url_container_frame.update_idletasks()
        
        # Hide multiline widget if it's visible
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            text_frame = getattr(self, 'url_text_frame', None) or self.url_text_widget.master
            if text_frame:
                text_frame.grid_remove()
        
        # Update button text with deduplicated count
        self._update_url_count_and_button()
        
        # Check if discography download is enabled (only for single URL)
        if len(valid_urls) == 1 and self.download_discography_var.get():
            # Extract artist page URL from album/track URL
            original_url = valid_urls[0]
            artist_url = self.extract_artist_page_url(original_url)
            if artist_url:
                valid_urls = [artist_url]
            else:
                messagebox.showerror("Error", "Could not extract artist page URL from the provided URL.")
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
        # Temporarily enable widget to clear it, then disable again (read-only)
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, END)
        self.log_text.config(state='disabled')
        self.log("Starting download...")
        if len(valid_urls) > 1:
            self.log(f"Found {len(valid_urls)} album URL(s) to download")
        else:
            self.log(f"URL: {valid_urls[0]}")
        self.log(f"Path: {path}")
        self.log("")
        
        # Start download in thread - pass list of URLs
        self.download_thread = threading.Thread(target=self.download_album, args=(valid_urls,), daemon=True)
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
            elif base_format == "original":
                # For original format, check file extension to determine how to embed
                audio_ext = Path(audio_file).suffix.lower()
                if audio_ext in [".m4a", ".mp4", ".aac"]:
                    # M4A/MP4/AAC: embed as video stream with attached picture
                    # Use explicit stream mapping: map audio from first input, image from second input
                    cmd = [
                        str(self.ffmpeg_path),
                        "-i", str(audio_file),
                        "-i", str(thumbnail_file),
                        "-c", "copy",
                        "-map", "0:0",  # Map audio stream from first input
                        "-map", "1:0",  # Map image stream from second input
                        "-metadata:s:v", "title=Album cover",
                        "-metadata:s:v", "comment=Cover (front)",
                        "-disposition:v:0", "attached_pic",
                        "-y",
                        temp_output,
                    ]
                else:
                    # Unknown format - cannot embed
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
                if skip_postprocessing or base_format == "original":
                    # For skip_postprocessing or original format, check all possible audio formats
                    target_exts = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".aac", ".mpa", ".opus"]
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
            
            # Group files by directory to handle mixed formats correctly
            files_by_dir = {}
            for audio_file in files_to_process:
                # Skip temporary files
                if audio_file.name.startswith('.') or 'tmp' in audio_file.name.lower():
                    continue
                
                dir_path = audio_file.parent
                if dir_path not in files_by_dir:
                    files_by_dir[dir_path] = []
                files_by_dir[dir_path].append(audio_file)
            
            # Process each directory separately
            for dir_path, dir_files in files_by_dir.items():
                # First, try to get track numbers from metadata for all files in this directory
                files_with_track_numbers = []
                files_without_track_numbers = []
                
                for audio_file in dir_files:
                    file_title = audio_file.stem
                    track_number = None
                    track_title = file_title
                    
                    # Try to find track number from download_info
                    for title_key, info in self.download_info.items():
                        # Match by comparing filename with track title
                        if file_title.lower() in title_key.lower() or title_key.lower() in file_title.lower():
                            track_number = info.get("track_number")
                            track_title = info.get("title", file_title)
                            break
                    
                    # If not found in download_info, try to extract from metadata in file
                    if track_number is None:
                        try:
                            # Use ffprobe to get track number from file metadata
                            ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
                            if not ffprobe_path.exists():
                                ffprobe_path = self.script_dir / "ffprobe.exe"
                            
                            if ffprobe_path.exists():
                                cmd = [
                                    str(ffprobe_path),
                                    "-v", "quiet",
                                    "-print_format", "json",
                                    "-show_format",
                                    str(audio_file)
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
                                    
                                    # Try to get track number
                                    track_str = tags.get("track") or tags.get("TRACK") or tags.get("tracknumber") or tags.get("TRACKNUMBER")
                                    if track_str:
                                        # Handle formats like "1/10" or just "1"
                                        track_match = re.search(r'(\d+)', str(track_str))
                                        if track_match:
                                            track_number = int(track_match.group(1))
                                    
                                    # Also get title if available
                                    if not track_title or track_title == file_title:
                                        track_title = tags.get("title") or tags.get("TITLE") or track_title
                        except Exception:
                            pass
                    
                    # If still no track number, try to extract from filename
                    if track_number is None:
                        match = re.search(r'\b(\d+)\b', file_title)
                        if match:
                            track_number = int(match.group(1))
                    
                    if track_number is not None:
                        files_with_track_numbers.append((audio_file, track_number, track_title))
                    else:
                        files_without_track_numbers.append((audio_file, None, track_title))
                
                # Sort files with track numbers by track number
                files_with_track_numbers.sort(key=lambda x: x[1])
                
                # Sort files without track numbers by filename
                files_without_track_numbers.sort(key=lambda x: x[0].name)
                
                # Combine: files with track numbers first (sorted by track number), then files without (sorted by name)
                all_dir_files = files_with_track_numbers + files_without_track_numbers
                
                # Process each file in this directory
                for idx, (audio_file, track_number, track_title) in enumerate(all_dir_files):
                    # If no track number was found, use index within this directory
                    if track_number is None:
                        track_number = idx + 1
                    
                    file_title = audio_file.stem
                    
                    # Use sanitized track title for the new filename
                    sanitized_title = self.sanitize_filename(track_title)
                    
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
                    
                    new_name = prefix + sanitized_title + extension
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
    
    def rename_cover_art_files(self, download_path):
        """Rename cover art files to 'artist - album' format."""
        import re
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Get album info - try multiple sources for accuracy
            artist = None
            album = None
            
            # Method 1: Try to extract from folder structure (most reliable for "Artist / Album" structure)
            # Check if we're in an "Artist/Album" folder structure
            try:
                # Get the folder structure choice
                choice = self._extract_structure_choice(self.folder_structure_var.get())
                
                # If structure is "Artist / Album" (4) or "Album / Artist" (5), extract from path
                if choice in ["4", "5"]:
                    # Find any downloaded audio file to get its path
                    if hasattr(self, 'downloaded_files') and self.downloaded_files:
                        for downloaded_file in list(self.downloaded_files)[:1]:  # Just check first file
                            audio_path = Path(downloaded_file)
                            if audio_path.exists():
                                # For structure 4: Artist/Album/Track
                                # For structure 5: Album/Artist/Track
                                parts = audio_path.parts
                                if len(parts) >= 3:
                                    if choice == "4":
                                        # Structure: base/Artist/Album/Track
                                        artist = parts[-3]  # Second to last folder
                                        album = parts[-2]  # Last folder before filename
                                    elif choice == "5":
                                        # Structure: base/Album/Artist/Track
                                        album = parts[-3]  # Second to last folder
                                        artist = parts[-2]  # Last folder before filename
                                break
            except Exception:
                pass
            
            # Method 2: Try to get from download_info, but only if album field exists (not fallback to title)
            if not album and hasattr(self, 'download_info') and self.download_info:
                # Look for a track that has an explicit album field (not fallback)
                for track_info in self.download_info.values():
                    # Only use if album is explicitly set (not None and not empty)
                    track_album = track_info.get("album")
                    if track_album and track_album.strip():
                        # Verify it's not the same as a track title (basic check)
                        track_title = track_info.get("title", "")
                        if track_album != track_title:
                            album = track_album
                    if track_info.get("artist"):
                        artist = track_info.get("artist")
                    if album and artist:
                        break
            
            # Method 3: Fallback to album_info_stored
            if not album:
                album = self.album_info_stored.get("album") if hasattr(self, 'album_info_stored') else None
            if not artist:
                artist = self.album_info_stored.get("artist") if hasattr(self, 'album_info_stored') else None
            
            # Final fallback to "Unknown"
            artist = self.sanitize_filename(artist) if artist else "Unknown Artist"
            album = self.sanitize_filename(album) if album else "Unknown Album"
            
            # Create the target filename
            cover_art_name = f"{artist} - {album}"
            
            # Find all cover art files that were just downloaded
            # Only search in directories that contain downloaded audio files
            cover_art_files = []
            
            # Get directories that contain downloaded audio files
            directories_to_search = set()
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                for downloaded_file in self.downloaded_files:
                    try:
                        audio_path = Path(downloaded_file)
                        if audio_path.exists():
                            directories_to_search.add(audio_path.parent)
                    except Exception:
                        pass
            
            # If no downloaded files found, fall back to searching base_path but only immediate subdirectories
            if not directories_to_search:
                # Only search immediate subdirectories, not recursively from root
                try:
                    for item in base_path.iterdir():
                        if item.is_dir():
                            directories_to_search.add(item)
                except Exception:
                    pass
            
            # Only search in directories that contain downloaded files
            if hasattr(self, 'download_start_time') and self.download_start_time:
                # Use timestamp-based filtering to find recently downloaded cover art files
                time_threshold = self.download_start_time - 30
                for search_dir in directories_to_search:
                    if not search_dir.exists():
                        continue
                    for ext in self.THUMBNAIL_EXTENSIONS:
                        # Only search in this specific directory, not recursively
                        for thumb_file in search_dir.glob(f"*{ext}"):
                            try:
                                file_mtime = thumb_file.stat().st_mtime
                                if file_mtime >= time_threshold:
                                    # Skip files that already have the "artist - album" format
                                    if not re.match(r'^[^-]+ - [^-]+$', thumb_file.stem):
                                        cover_art_files.append(thumb_file)
                            except Exception:
                                pass
            
            if not cover_art_files:
                return
            
            # Group cover art files by directory (each album folder gets one cover art)
            cover_art_by_dir = {}
            for thumb_file in cover_art_files:
                thumb_dir = thumb_file.parent
                if thumb_dir not in cover_art_by_dir:
                    cover_art_by_dir[thumb_dir] = []
                cover_art_by_dir[thumb_dir].append(thumb_file)
            
            # Rename cover art files in each directory
            for thumb_dir, thumb_files in cover_art_by_dir.items():
                # Find the best cover art file to keep (prefer common names, then first one)
                thumb_files.sort(key=lambda f: (
                    0 if any(name in f.stem.lower() for name in ['cover', 'album', 'folder', 'artwork']) else 1,
                    f.name
                ))
                
                # Keep the first file, rename others or delete duplicates
                kept_file = thumb_files[0]
                target_name = cover_art_name + kept_file.suffix
                target_path = thumb_dir / target_name
                
                # If the target already exists and is the same file, skip
                if target_path == kept_file:
                    # Already has the right name, just delete duplicates
                    for thumb_file in thumb_files[1:]:
                        try:
                            thumb_file.unlink()
                        except Exception:
                            pass
                    continue
                
                # Rename the kept file to "artist - album"
                try:
                    # If target exists, delete it first (might be from previous download)
                    if target_path.exists():
                        target_path.unlink()
                    
                    kept_file.rename(target_path)
                    self.root.after(0, lambda old=kept_file.name, new=target_name: 
                                   self.log(f"Renamed cover art: {old} → {new}"))
                    
                    # Delete any remaining duplicate cover art files
                    for thumb_file in thumb_files[1:]:
                        try:
                            thumb_file.unlink()
                        except Exception:
                            pass
                except Exception as e:
                    self.root.after(0, lambda name=kept_file.name: 
                                   self.log(f"⚠ Could not rename cover art: {name}"))
        
        except Exception as e:
            self.root.after(0, lambda: self.log(f"⚠ Error renaming cover art: {str(e)}"))
    
    def _get_metadata_from_directory(self, directory):
        """Extract artist and album metadata from the first audio file in a directory."""
        try:
            # Look for audio files in this directory
            audio_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a"]
            audio_files = []
            for ext in audio_extensions:
                audio_files.extend(directory.glob(f"*{ext}"))
            
            if not audio_files:
                return None, None
            
            # Use the first audio file to get metadata
            audio_file = audio_files[0]
            
            # Try to read metadata using ffprobe (works for all formats)
            try:
                ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
                if not ffprobe_path.exists():
                    ffprobe_path = self.script_dir / "ffprobe.exe"
                    if not ffprobe_path.exists():
                        return None, None
                
                cmd = [
                    str(ffprobe_path),
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    str(audio_file)
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
                    
                    # Extract artist and album from tags
                    artist = tags.get("artist") or tags.get("ARTIST") or tags.get("album_artist") or tags.get("ALBUMARTIST")
                    album = tags.get("album") or tags.get("ALBUM")
                    
                    return artist, album
            except Exception:
                pass
            
            return None, None
        except Exception:
            return None, None
    
    def final_cover_art_cleanup(self, download_path):
        """Final cleanup pass: rename all cover art files to 'folder.{ext}' format."""
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Only check directories that contain downloaded audio files
            directories_to_check = set()
            
            # Get directories from downloaded files
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                for downloaded_file in self.downloaded_files:
                    try:
                        audio_path = Path(downloaded_file)
                        if audio_path.exists():
                            directories_to_check.add(audio_path.parent)
                    except Exception:
                        pass
            
            # If no downloaded files found, fall back to structure-based search
            # but only search immediate subdirectories, not recursively from root
            if not directories_to_check:
                # Get folder structure choice
                choice = self._extract_structure_choice(self.folder_structure_var.get())
                
                # For structure 4 (Artist/Album) or 5 (Album/Artist), check album-level directories
                if choice in ["4", "5"]:
                    # Find all directories that are 2 levels deep (Artist/Album or Album/Artist)
                    try:
                        for item in base_path.iterdir():
                            if item.is_dir():
                                for subitem in item.iterdir():
                                    if subitem.is_dir():
                                        directories_to_check.add(subitem)
                    except Exception:
                        pass
                elif choice == "2":
                    # Structure 2: Album folder - check album directories
                    try:
                        for item in base_path.iterdir():
                            if item.is_dir():
                                directories_to_check.add(item)
                    except Exception:
                        pass
                elif choice == "3":
                    # Structure 3: Artist folder - check artist directories
                    try:
                        for item in base_path.iterdir():
                            if item.is_dir():
                                directories_to_check.add(item)
                    except Exception:
                        pass
                else:
                    # Structure 1: Root - check base path only (not recursively)
                    directories_to_check.add(base_path)
            
            # Process each directory
            for directory in directories_to_check:
                # Find all cover art files in this directory
                cover_art_files = []
                for ext in self.THUMBNAIL_EXTENSIONS:
                    cover_art_files.extend(directory.glob(f"*{ext}"))
                
                if not cover_art_files:
                    continue
                
                # Find the best cover art file to keep (prefer common names, then prefer jpg)
                cover_art_files.sort(key=lambda f: (
                    0 if any(name in f.stem.lower() for name in ['cover', 'album', 'folder', 'artwork']) else 1,
                    0 if f.suffix.lower() == '.jpg' else 1,  # Prefer .jpg
                    f.name
                ))
                
                kept_file = cover_art_files[0]
                target_name = f"folder{kept_file.suffix}"
                target_path = directory / target_name
                
                # Skip if already correctly named
                if kept_file.name.lower() == target_name.lower():
                    # Delete duplicates
                    for thumb_file in cover_art_files[1:]:
                        try:
                            thumb_file.unlink()
                        except Exception:
                            pass
                    continue
                
                # Rename the kept file
                try:
                    # If target exists, delete it first
                    if target_path.exists():
                        target_path.unlink()
                    
                    kept_file.rename(target_path)
                    self.root.after(0, lambda old=kept_file.name, new=target_name: 
                                   self.log(f"Final cleanup: Renamed cover art {old} → {new}"))
                    
                    # Delete all other cover art files in this directory
                    for thumb_file in cover_art_files[1:]:
                        try:
                            thumb_file.unlink()
                        except Exception:
                            pass
                except Exception as e:
                    self.root.after(0, lambda name=kept_file.name: 
                                   self.log(f"⚠ Could not rename cover art: {name}"))
        
        except Exception as e:
            self.root.after(0, lambda: self.log(f"⚠ Error in final cover art cleanup: {str(e)}"))
    
    def process_downloaded_files(self, download_path):
        """Process all downloaded files to embed cover art for FLAC, OGG, and WAV."""
        
        # Apply track numbering first
        self.apply_track_numbering(download_path)
        
        # Rename cover art files to "artist - album" format
        self.rename_cover_art_files(download_path)
        
        format_val = self.format_var.get()
        base_format = self._extract_format(format_val)
        skip_postprocessing = self.skip_postprocessing_var.get()
        
        # If skipping post-processing, or Original format is selected, we need to check all audio formats
        if skip_postprocessing or base_format == "original":
            # Check all possible audio formats since we don't know what yt-dlp downloaded
            all_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".aac", ".mpa", ".opus"]
            if base_format == "original":
                # Keep base_format as "original" so we can handle it specially
                pass
            else:
                base_format = None  # Will process based on actual file extensions found
        else:
            all_extensions = self.FORMAT_EXTENSIONS.get(base_format, [])
        
        # Only process FLAC (MP3 is handled by yt-dlp's EmbedThumbnail)
        # OGG and WAV cannot reliably embed cover art, so we skip embedding and keep files
        # Original format needs special handling for M4A files
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
        elif base_format == "original":
            # For Original format, try to embed artwork for all supported formats (MP3, M4A, MP4, AAC, FLAC)
            download_cover_art = self.download_cover_art_var.get()
            
            try:
                base_path = Path(download_path)
                if base_path.exists():
                    # Find audio files - only process files that were just downloaded
                    # Use downloaded_files set if available, otherwise use timestamp-based filtering
                    audio_extensions = [".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".oga", ".wav"]
                    audio_files = []
                    
                    if hasattr(self, 'downloaded_files') and self.downloaded_files:
                        # Process only files that were tracked as downloaded (most reliable)
                        for downloaded_file in self.downloaded_files:
                            file_path = Path(downloaded_file)
                            if file_path.exists() and file_path.suffix.lower() in audio_extensions:
                                audio_files.append(file_path)
                    elif hasattr(self, 'download_start_time') and self.download_start_time:
                        # Fallback: use timestamp-based filtering (files modified after download started)
                        import time
                        time_threshold = self.download_start_time - 30  # 30 second buffer
                        for ext in audio_extensions:
                            for audio_file in base_path.rglob(f"*{ext}"):
                                try:
                                    file_mtime = audio_file.stat().st_mtime
                                    if file_mtime >= time_threshold:
                                        audio_files.append(audio_file)
                                except (OSError, Exception):
                                    continue
                    else:
                        # Last resort: find all audio files (shouldn't happen in normal operation)
                        for ext in audio_extensions:
                            audio_files.extend(base_path.rglob(f"*{ext}"))
                    
                    if audio_files:
                        self.root.after(0, lambda: self.log(f"Embedding cover art for {len(audio_files)} file(s)..."))
                        
                        processed_dirs = set()
                        used_thumbnails = set()
                        
                        # Group files by directory for better organization
                        files_by_dir = {}
                        for audio_file in audio_files:
                            # Skip temporary files
                            name_lower = audio_file.name.lower()
                            if audio_file.name.startswith('.') or 'tmp' in name_lower:
                                continue
                            
                            dir_path = audio_file.parent
                            if dir_path not in files_by_dir:
                                files_by_dir[dir_path] = []
                            files_by_dir[dir_path].append(audio_file)
                            processed_dirs.add(dir_path)
                        
                        # Process each directory
                        for dir_path, dir_files in files_by_dir.items():
                            # Find thumbnail for this directory
                            thumbnail_file = None
                            for audio_file in dir_files:
                                thumb = self.find_thumbnail_file(str(audio_file))
                                if thumb:
                                    thumbnail_file = thumb
                                    break
                            
                            if not thumbnail_file:
                                continue
                            
                            used_thumbnails.add(Path(thumbnail_file))
                            
                            # Process each file in this directory
                            for audio_file in dir_files:
                                audio_file_str = str(audio_file)
                                audio_file_name = audio_file.name
                                audio_ext = audio_file.suffix.lower()
                                
                                self.root.after(0, lambda name=audio_file_name: self.log(f"Processing: {name}"))
                                
                                # Handle different formats
                                success = False
                                if audio_ext in [".m4a", ".mp4", ".aac"]:
                                    # M4A/MP4/AAC: use embed_cover_art_ffmpeg
                                    success = self.embed_cover_art_ffmpeg(audio_file_str, thumbnail_file)
                                elif audio_ext == ".mp3":
                                    # MP3: use re_embed_mp3_metadata
                                    # Get metadata from download_info if available
                                    metadata = {}
                                    file_title = audio_file.stem
                                    for title_key, info in self.download_info.items():
                                        if file_title.lower() in title_key.lower() or title_key.lower() in file_title.lower():
                                            metadata = info.copy()
                                            break
                                    
                                    # If no metadata found, try to get from file
                                    if not metadata:
                                        try:
                                            artist, album = self._get_metadata_from_directory(dir_path)
                                            if artist or album:
                                                metadata = {
                                                    "artist": artist,
                                                    "album": album,
                                                    "title": file_title
                                                }
                                        except Exception:
                                            pass
                                    
                                    if metadata:
                                        success = self.re_embed_mp3_metadata(audio_file_str, metadata, thumbnail_file)
                                    else:
                                        # Try without metadata, just artwork
                                        success = self.re_embed_mp3_metadata(audio_file_str, {"title": file_title}, thumbnail_file)
                                elif audio_ext in [".flac", ".ogg", ".oga"]:
                                    # FLAC/OGG: use embed_cover_art_ffmpeg
                                    success = self.embed_cover_art_ffmpeg(audio_file_str, thumbnail_file)
                                
                                if success:
                                    self.root.after(0, lambda name=audio_file_name: self.log(f"✓ Embedded cover art: {name}"))
                                else:
                                    self.root.after(0, lambda name=audio_file_name: self.log(f"⚠ Could not embed cover art: {name}"))
                        
                        # Handle cover art files after embedding
                        if download_cover_art:
                            # Deduplicate cover art files
                            if processed_dirs:
                                self.deduplicate_cover_art(processed_dirs)
                        else:
                            # Remove used thumbnails if not keeping cover art files
                            for thumb in used_thumbnails:
                                try:
                                    if thumb.exists():
                                        thumb.unlink()
                                except Exception:
                                    pass
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"⚠ Error embedding cover art: {err}"))
            
            return
        elif base_format == "mp3":
            # For MP3 format, yt-dlp's EmbedThumbnail should handle it, but add fallback for files that don't get artwork
            download_cover_art = self.download_cover_art_var.get()
            
            # Try to embed artwork for MP3 files that might not have gotten it from yt-dlp
            try:
                base_path = Path(download_path)
                if base_path.exists():
                    # Find all MP3 files
                    mp3_files = list(base_path.rglob("*.mp3"))
                    
                    if mp3_files:
                        # Group files by directory
                        files_by_dir = {}
                        for mp3_file in mp3_files:
                            # Skip temporary files
                            name_lower = mp3_file.name.lower()
                            if mp3_file.name.startswith('.') or 'tmp' in name_lower:
                                continue
                            
                            dir_path = mp3_file.parent
                            if dir_path not in files_by_dir:
                                files_by_dir[dir_path] = []
                            files_by_dir[dir_path].append(mp3_file)
                        
                        # Process each directory
                        processed_count = 0
                        for dir_path, dir_files in files_by_dir.items():
                            # Find thumbnail for this directory
                            thumbnail_file = None
                            for mp3_file in dir_files:
                                thumb = self.find_thumbnail_file(str(mp3_file))
                                if thumb:
                                    thumbnail_file = thumb
                                    break
                            
                            if not thumbnail_file:
                                continue
                            
                            # Check each MP3 file and embed artwork if needed
                            for mp3_file in dir_files:
                                mp3_file_str = str(mp3_file)
                                mp3_file_name = mp3_file.name
                                file_title = mp3_file.stem
                                
                                # Get metadata from download_info if available
                                metadata = {}
                                for title_key, info in self.download_info.items():
                                    if file_title.lower() in title_key.lower() or title_key.lower() in file_title.lower():
                                        metadata = info.copy()
                                        break
                                
                                # If no metadata found, try to get from file
                                if not metadata:
                                    try:
                                        artist, album = self._get_metadata_from_directory(dir_path)
                                        if artist or album:
                                            metadata = {
                                                "artist": artist,
                                                "album": album,
                                                "title": file_title
                                            }
                                    except Exception:
                                        pass
                                
                                # Try to embed artwork (will work for all MP3 types)
                                if metadata:
                                    success = self.re_embed_mp3_metadata(mp3_file_str, metadata, thumbnail_file)
                                else:
                                    # Try without metadata, just artwork
                                    success = self.re_embed_mp3_metadata(mp3_file_str, {"title": file_title}, thumbnail_file)
                                
                                if success:
                                    processed_count += 1
                                    self.root.after(0, lambda name=mp3_file_name: self.log(f"✓ Embedded cover art: {name}"))
                        
                        if processed_count > 0:
                            self.root.after(0, lambda count=processed_count: self.log(f"Embedded cover art for {count} MP3 file(s)"))
                        
                        # Handle cover art files
                        if download_cover_art:
                            # Deduplicate cover art files
                            processed_dirs = set(files_by_dir.keys())
                            if processed_dirs:
                                self.deduplicate_cover_art(processed_dirs)
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"⚠ Error embedding MP3 cover art: {err}"))
            
            return
        elif base_format in ["ogg", "wav"]:
            # For OGG and WAV - handle cover art based on download_cover_art setting
            download_cover_art = self.download_cover_art_var.get()
            
            if download_cover_art:
                # If download cover art is enabled, deduplicate cover art files
                try:
                    base_path = Path(download_path)
                    if base_path.exists():
                        # Find all directories with audio files
                        extensions = {
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
    
    def download_single_album(self, album_url, album_index=0, total_albums=0):
        """Download a single album (used for both single album and discography mode)."""
        try:
            # Get format settings
            format_val = self.format_var.get()
            base_format = self._extract_format(format_val)
            skip_postprocessing = self.skip_postprocessing_var.get()
            download_cover_art = self.download_cover_art_var.get()
            
            # Configure postprocessors based on format
            postprocessors = []
            
            # If skip post-processing is enabled, or Original format is selected, only add metadata/thumbnail postprocessors (no format conversion)
            if skip_postprocessing or base_format == "original":
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
            # Enhanced options for restricted networks (better user agent, retries, timeouts)
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
                # Enhanced network options for restricted networks
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "referer": "https://bandcamp.com/",
                "socket_timeout": 30,  # Increased timeout
                "retries": 5,  # More retries for unstable connections
                "fragment_retries": 5,  # Retry fragments
                "file_access_retries": 3,  # Retry file access
                "http_chunk_size": 10485760,  # 10MB chunks (may help with some restrictions)
            }
            
            # Store info for post-processing (maps filenames to metadata)
            self.download_info = {}
            self.album_info_stored = {}
            self.downloaded_files = set()  # Track files that were just downloaded
            self.download_start_time = None  # Track when download started
            self.total_tracks = 0  # Total number of tracks in current album
            self.current_track = 0  # Current track being downloaded (0-based, will be incremented as tracks finish)
            
            # Discography tracking (for multi-album downloads) - only set if in discography mode
            self.is_discography_mode = (total_albums > 1)  # True if downloading multiple albums
            if self.is_discography_mode:
                self.current_album = album_index  # Set current album index
                self.total_albums = total_albums  # Set total albums
            else:
                self.total_albums = 0
                self.current_album = 0
            self.albums_info = []  # List of album info: [{"tracks": count, "name": name}, ...]
            self.current_album_name = None  # Track current album name to detect album changes
            self.current_album_path = None  # Track current album folder path to detect album changes
            self.total_tracks_all_albums = 0  # Total tracks across all albums
            self.completed_tracks_all_albums = 0  # Completed tracks across all albums
            self.last_playlist_index = None  # Track last playlist_index to detect album changes
            self.last_filename = None  # Track last filename to detect album changes via path
            self.seen_album_paths = set()  # Track which album paths we've already seen to prevent duplicate detections
            
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
                    quick_info = quick_ydl.extract_info(album_url, download=False)
                    if quick_info and "entries" in quick_info:
                        entries = [e for e in quick_info.get("entries", []) if e]
                        
                        # Single album mode, entries are tracks
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
                    info = extract_ydl.extract_info(album_url, download=False)
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
                            
                            # Single album mode, entries are tracks
                            if self.total_tracks == 0:  # Only update if quick extraction didn't work
                                self.total_tracks = len(entries)
                                self.root.after(0, lambda count=len(entries): self.log(f"Found {count} track(s)"))
                            
                            # Log format/bitrate info from first track (to show what yt-dlp is downloading)
                            # Always show source info so users know what quality they're getting
                            # Also detect format for Original Format mode preview
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
                                
                                # Detect format for Original Format mode preview
                                ext = first_entry.get("ext") or ""
                                acodec = first_entry.get("acodec") or ""
                                container = first_entry.get("container") or ""
                                detected_format = None
                                if ext in ["m4a", "mp4"] or acodec in ["alac", "aac"] or container in ["m4a", "mp4"]:
                                    detected_format = "m4a"
                                elif ext == "flac" or acodec == "flac":
                                    detected_format = "flac"
                                elif ext == "ogg" or acodec == "vorbis":
                                    detected_format = "ogg"
                                elif ext == "wav" or acodec == "pcm":
                                    detected_format = "wav"
                                elif ext == "mp3" or acodec == "mp3":
                                    detected_format = "mp3"
                                
                                # Update album_info with detected format and refresh preview
                                if detected_format:
                                    self.album_info["detected_format"] = detected_format
                                    self.root.after(0, self.update_preview)
                            
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
                # Ensure album_info_stored is at least initialized (will try to get from files later)
                if not self.album_info_stored or not self.album_info_stored.get("artist") or not self.album_info_stored.get("album"):
                    self.album_info_stored = self.album_info_stored or {}
            
            # Check if we found any tracks - if not, retry extraction once
            if self.total_tracks == 0:
                self.root.after(0, lambda: self.log("DEBUG: No tracks found in initial extraction, retrying..."))
                time.sleep(1.5)  # Brief delay before retry
                
                # Retry extraction
                try:
                    retry_opts = ydl_opts.copy()
                    retry_opts["extract_flat"] = False
                    retry_opts["quiet"] = True
                    retry_opts["no_warnings"] = True
                    retry_opts["socket_timeout"] = 15  # Longer timeout for retry
                    retry_opts["retries"] = 5  # More retries for retry
                    
                    with yt_dlp.YoutubeDL(retry_opts) as retry_ydl:
                        retry_info = retry_ydl.extract_info(album_url, download=False)
                        if retry_info and "entries" in retry_info:
                            entries = [e for e in retry_info.get("entries", []) if e]
                            if entries:
                                self.total_tracks = len(entries)
                                self.root.after(0, lambda count=len(entries): self.log(f"Found {count} track(s) (retry)"))
                except Exception as e:
                    self.root.after(0, lambda err=str(e): self.log(f"DEBUG: Retry extraction also failed: {err}"))
            
            # If still no tracks found, skip download
            if self.total_tracks == 0:
                self.root.after(0, lambda: self.log("⚠ No tracks found for this album. Skipping download."))
                return False
            
            # Get download path
            download_path = self.path_var.get().strip()
            
            # Download and process the album
            success = self._do_album_download_and_processing(album_url, ydl_opts, format_val, base_format, skip_postprocessing, download_path)
            
            # After download, if album_info_stored is still empty, try to get it from downloaded files
            if success and (not self.album_info_stored or not self.album_info_stored.get("artist") or not self.album_info_stored.get("album")):
                try:
                    base_path = Path(download_path)
                    if base_path.exists():
                        # Find first audio file and get metadata
                        audio_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a"]
                        for ext in audio_extensions:
                            audio_files = list(base_path.rglob(f"*{ext}"))
                            if audio_files:
                                file_artist, file_album = self._get_metadata_from_directory(audio_files[0].parent)
                                if file_artist or file_album:
                                    if not self.album_info_stored:
                                        self.album_info_stored = {}
                                    if file_artist and not self.album_info_stored.get("artist"):
                                        self.album_info_stored["artist"] = file_artist
                                    if file_album and not self.album_info_stored.get("album"):
                                        self.album_info_stored["album"] = file_album
                                break
                except Exception:
                    pass  # If we can't get it from files, continue anyway
            
            return success
            
        except Exception as e:
            self.root.after(0, lambda msg=str(e): self.log(f"Error: {msg}"))
            return False
    
    def download_album(self, urls):
        """Download albums (main entry point - handles multiple URLs, discography, or single album)."""
        try:
            # Handle both single URL (string) and multiple URLs (list) for backward compatibility
            if isinstance(urls, str):
                urls = [urls]
            
            # Get format settings
            format_val = self.format_var.get()
            base_format = self._extract_format(format_val)
            skip_postprocessing = self.skip_postprocessing_var.get()
            download_cover_art = self.download_cover_art_var.get()
            
            # Configure postprocessors based on format
            postprocessors = []
            
            # If skip post-processing is enabled, or Original format is selected, only add metadata/thumbnail postprocessors (no format conversion)
            if skip_postprocessing or base_format == "original":
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
            # Enhanced options for restricted networks (better user agent, retries, timeouts)
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
                # Enhanced network options for restricted networks
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "referer": "https://bandcamp.com/",
                "socket_timeout": 30,  # Increased timeout
                "retries": 5,  # More retries for unstable connections
                "fragment_retries": 5,  # Retry fragments
                "file_access_retries": 3,  # Retry file access
                "http_chunk_size": 10485760,  # 10MB chunks (may help with some restrictions)
            }
            
            # Store info for post-processing (maps filenames to metadata)
            self.download_info = {}
            self.album_info_stored = {}
            self.downloaded_files = set()  # Track files that were just downloaded
            self.download_start_time = None  # Track when download started
            self.total_tracks = 0  # Total number of tracks in current album
            self.current_track = 0  # Current track being downloaded (0-based, will be incremented as tracks finish)
            
            # Discography tracking (for multi-album downloads)
            # Check if discography mode is enabled (only for single URL)
            # OR if multiple URLs are provided (batch mode)
            is_discography_checkbox = (len(urls) == 1 and self.download_discography_var.get())
            is_batch_mode = (len(urls) > 1)
            self.is_discography_mode = is_discography_checkbox or is_batch_mode
            self.total_albums = 0  # Total number of albums (will be set after metadata fetch)
            self.current_album = 0  # Current album being downloaded (0-based)
            self.albums_info = []  # List of album info: [{"tracks": count, "name": name}, ...]
            self.current_album_name = None  # Track current album name to detect album changes
            self.current_album_path = None  # Track current album folder path to detect album changes
            self.total_tracks_all_albums = 0  # Total tracks across all albums
            self.completed_tracks_all_albums = 0  # Completed tracks across all albums
            self.last_playlist_index = None  # Track last playlist_index to detect album changes
            self.last_filename = None  # Track last filename to detect album changes via path
            self.seen_album_paths = set()  # Track which album paths we've already seen to prevent duplicate detections
            
            # Get download start time
            self.download_start_time = time.time()
            
            # Handle discography mode (single URL with discography checkbox enabled)
            if is_discography_checkbox:
                # Show initial discography message
                self.root.after(0, lambda: self.progress_var.set("Fetching artist discography..."))
                self.root.after(0, lambda: self.log("Fetching artist discography..."))
                
                # Extract album URLs from the artist page
                album_urls = []
                try:
                    extract_opts = ydl_opts.copy()
                    extract_opts["extract_flat"] = True  # Fast extraction to get album URLs
                    extract_opts["quiet"] = True
                    extract_opts["no_warnings"] = True
                    
                    with yt_dlp.YoutubeDL(extract_opts) as extract_ydl:
                        info = extract_ydl.extract_info(urls[0], download=False)
                        if info and "entries" in info:
                            entries = [e for e in info.get("entries", []) if e]
                            for entry in entries:
                                # Get the URL for each album
                                entry_url = entry.get("url") or entry.get("webpage_url")
                                if entry_url:
                                    album_urls.append(entry_url)
                    
                    if not album_urls:
                        self.root.after(0, self.download_complete, False, 
                                      "Could not find any albums in the discography. The artist page may be empty or require login.")
                        return
                    
                    self.total_albums = len(album_urls)
                    # Show queuing message
                    self.root.after(0, lambda count=len(album_urls): 
                                  self.progress_var.set(f"Queuing {count} album(s)..."))
                    self.root.after(0, lambda count=len(album_urls): 
                                  self.log(f"Queuing {count} album(s)..."))
                    
                    # Add a brief delay so the user can see the queuing message
                    time.sleep(0.8)
                    
                except Exception as e:
                    self.root.after(0, self.download_complete, False, 
                                  f"Failed to extract album list from artist page:\n{str(e)}")
                    return
                
                # Download each album individually
                successful_albums = 0
                failed_albums = 0
                
                for idx, album_url in enumerate(album_urls):
                    # Check for cancellation
                    if self.is_cancelling:
                        self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                        return
                    
                    # Update current album counter
                    self.current_album = idx
                    if self.current_album >= self.total_albums:
                        self.total_albums = self.current_album + 1
                    
                    # Log which album we're starting
                    album_num = idx + 1
                    self.root.after(0, lambda num=album_num, total=self.total_albums, url=album_url: 
                                  self.log(f"Downloading album {num} of {total}: {url}"))
                    
                    # Update preview and artwork for current album
                    # Fetch metadata and artwork (will update preview and artwork)
                    self.fetch_album_metadata(album_url)
                    
                    # Download this album
                    success = self.download_single_album(album_url, album_index=idx, total_albums=len(album_urls))
                    
                    if success:
                        successful_albums += 1
                        # Add completed tracks from this album
                        if self.total_tracks > 0:
                            self.completed_tracks_all_albums += self.total_tracks
                    else:
                        failed_albums += 1
                        self.root.after(0, lambda num=album_num, url=album_url: 
                                      self.log(f"⚠ Failed to download album {num}: {url}"))
                    
                    # Reset track counter for next album
                    self.current_track = 0
                    self.total_tracks = 0
                    self.downloaded_files = set()  # Clear for next album
                
                # Final summary
                if successful_albums > 0:
                    msg = f"Downloaded {successful_albums} album(s)"
                    if failed_albums > 0:
                        msg += f" ({failed_albums} failed)"
                    self.root.after(0, self.download_complete, True, msg + "!")
                else:
                    self.root.after(0, self.download_complete, False, 
                                  f"Failed to download any albums. {failed_albums} album(s) failed.")
                return
            
            # Batch mode (multiple URLs) or single album mode
            # Phase 1: Fetch metadata for all albums first (for batch mode)
            if is_batch_mode:
                self.root.after(0, lambda: self.progress_var.set("Fetching metadata for all albums..."))
                self.root.after(0, lambda: self.log("Fetching metadata for all albums..."))
                
                album_metadata = []
                extract_opts_quick = {
                    "extract_flat": True,
                    "quiet": True,
                    "no_warnings": True,
                    "socket_timeout": 10,
                    "retries": 3,
                }
                
                for idx, url in enumerate(urls):
                    if self.is_cancelling:
                        self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                        return
                    
                    try:
                        self.root.after(0, lambda num=idx+1, total=len(urls), u=url:
                                      self.log(f"Fetching metadata [{num}/{total}]: {u}"))
                        
                        with yt_dlp.YoutubeDL(extract_opts_quick) as extract_ydl:
                            info = extract_ydl.extract_info(url, download=False)
                            if info:
                                album_name = info.get("album") or info.get("title") or url
                                
                                # Try to get artist from various sources
                                artist_name = (info.get("artist") or 
                                             info.get("uploader") or 
                                             info.get("creator") or 
                                             None)
                                
                                # If not found, try getting from first track entry
                                if not artist_name and "entries" in info and info["entries"]:
                                    first_entry = info["entries"][0]
                                    artist_name = (first_entry.get("artist") or 
                                                 first_entry.get("uploader") or 
                                                 first_entry.get("creator") or 
                                                 None)
                                
                                # If still not found, try extracting from URL subdomain
                                if not artist_name and "bandcamp.com" in url.lower():
                                    try:
                                        from urllib.parse import urlparse
                                        parsed = urlparse(url)
                                        hostname = parsed.hostname or ""
                                        if ".bandcamp.com" in hostname:
                                            subdomain = hostname.replace(".bandcamp.com", "")
                                            artist_name = " ".join(word.capitalize() for word in subdomain.split("-"))
                                    except Exception:
                                        pass
                                
                                # Final fallback
                                if not artist_name:
                                    artist_name = "Unknown"
                                
                                track_count = len(info.get("entries", [])) if "entries" in info else 0
                                album_metadata.append({
                                    "url": url,
                                    "name": album_name,
                                    "artist": artist_name,
                                    "track_count": track_count,
                                    "info": info
                                })
                                self.root.after(0, lambda name=album_name, artist=artist_name, count=track_count:
                                              self.log(f"  ✓ {artist} - {name} ({count} tracks)"))
                            else:
                                album_metadata.append({
                                    "url": url,
                                    "name": url,
                                    "artist": "Unknown",
                                    "track_count": 0,
                                    "info": None
                                })
                                self.root.after(0, lambda u=url: self.log(f"  ⚠ Could not fetch metadata for: {u}"))
                    except Exception as e:
                        album_metadata.append({
                            "url": url,
                            "name": url,
                            "artist": "Unknown",
                            "track_count": 0,
                            "info": None
                        })
                        self.root.after(0, lambda u=url, err=str(e): self.log(f"  ⚠ Error fetching metadata for {u}: {err}"))
                
                if not album_metadata:
                    self.root.after(0, self.download_complete, False, "No valid albums found.")
                    return
                
                self.total_albums = len(album_metadata)
                total_tracks = sum(meta.get("track_count", 0) for meta in album_metadata)
                self.root.after(0, lambda count=len(album_metadata), tracks=total_tracks:
                              self.log(f"\nFound {count} album(s) with {tracks} total track(s)"))
                self.root.after(0, lambda: self.log(""))
                
                # Phase 2: Download each album
                successful_albums = 0
                failed_albums = 0
                
                for idx, meta in enumerate(album_metadata):
                    # Check for cancellation
                    if self.is_cancelling:
                        self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                        return
                    
                    # Update current album counter
                    self.current_album = idx
                    album_url = meta["url"]
                    album_name = meta["name"]
                    artist_name = meta["artist"]
                    
                    # Log which album we're starting
                    album_num = idx + 1
                    self.root.after(0, lambda num=album_num, total=self.total_albums, name=album_name, artist=artist_name:
                                  self.log(f"Downloading album {num} of {total}: {artist} - {name}"))
                    self.root.after(0, lambda u=album_url: self.log(f"  URL: {u}"))
                    
                    # Update preview and artwork for current album
                    # Update album_info with metadata we already have
                    self.album_info = {
                        "artist": artist_name or "Artist",
                        "album": album_name or "Album",
                        "title": "Track",
                        "thumbnail_url": None
                    }
                    self.root.after(0, self.update_preview)
                    
                    # Fetch and display album art for this album
                    # Try to get thumbnail from metadata info if available
                    thumbnail_url = None
                    if meta.get("info"):
                        info = meta["info"]
                        # Try to get thumbnail from various locations
                        thumbnail_url = (info.get("thumbnail") or 
                                       info.get("thumbnail_url") or
                                       info.get("artwork_url") or
                                       info.get("cover"))
                        # Try thumbnails list
                        if not thumbnail_url and info.get("thumbnails"):
                            thumbnails = info.get("thumbnails")
                            if thumbnails and len(thumbnails) > 0:
                                if isinstance(thumbnails[0], dict):
                                    thumbnail_url = thumbnails[0].get("url")
                                else:
                                    thumbnail_url = thumbnails[0]
                    
                    # If we have thumbnail, display it; otherwise fetch it
                    if thumbnail_url:
                        self.album_info["thumbnail_url"] = thumbnail_url
                        self.current_thumbnail_url = thumbnail_url
                        self.root.after(0, lambda url=thumbnail_url: self.fetch_and_display_album_art(url))
                    else:
                        # Fetch metadata and artwork (will update preview and artwork)
                        self.fetch_album_metadata(album_url)
                    
                    # Add a small delay between albums in batch mode to avoid rate limiting
                    # (except for the first album)
                    if idx > 0:
                        time.sleep(1.0)  # 1 second delay between albums
                    
                    # Download this album
                    success = self.download_single_album(album_url, album_index=idx, total_albums=len(album_metadata))
                    
                    if success:
                        successful_albums += 1
                        # Add completed tracks from this album
                        if self.total_tracks > 0:
                            self.completed_tracks_all_albums += self.total_tracks
                    else:
                        failed_albums += 1
                        self.root.after(0, lambda num=album_num, name=album_name:
                                      self.log(f"⚠ Failed to download album {num}: {name}"))
                    
                    # Reset track counter for next album
                    self.current_track = 0
                    self.total_tracks = 0
                    self.downloaded_files = set()  # Clear for next album
                
                # Final summary
                if successful_albums > 0:
                    msg = f"Downloaded {successful_albums} album(s)"
                    if failed_albums > 0:
                        msg += f" ({failed_albums} failed)"
                    self.root.after(0, self.download_complete, True, msg + "!")
                else:
                    self.root.after(0, self.download_complete, False,
                                  f"Failed to download any albums. {failed_albums} album(s) failed.")
                return
            
            # Single album mode - download normally
            # Check for cancellation before starting download
            if self.is_cancelling:
                self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                return
            
            success = self.download_single_album(urls[0], album_index=0, total_albums=1)
            if not success:
                # Check if this was a cancellation
                if self.is_cancelling:
                    self.root.after(0, self.download_complete, False, "Download cancelled by user.")
                else:
                    # Error already logged in download_single_album
                    # Still need to restore UI
                    self.root.after(0, self.download_complete, False, "Download failed.")
                return
            
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
    
    def _do_album_download_and_processing(self, album_url, ydl_opts, format_val, base_format, skip_postprocessing, download_path):
        """Helper method to perform the actual download and processing of a single album."""
        # Initialize downloaded_files set for this album (important for batch/discography mode)
        if not hasattr(self, 'downloaded_files'):
            self.downloaded_files = set()
        else:
            # Clear for this new album download
            self.downloaded_files = set()
        
        # Update status before starting download
        # Check if cancellation was requested - if so, show "Cancelling..." instead
        if self.is_cancelling:
            self.root.after(0, lambda: self.progress_var.set("Cancelling..."))
            self.root.after(0, lambda: self.log("Cancelling..."))
        else:
            self.root.after(0, lambda: self.progress_var.set("Starting download..."))
            self.root.after(0, lambda: self.log("Starting download..."))
        
        # Get download path and count existing files before download
        base_path = Path(download_path) if download_path else None
        
        # Count existing audio files before download (to verify files were actually downloaded)
        existing_files_before = set()
        if base_path and base_path.exists():
            for ext in self.FORMAT_EXTENSIONS.get(format_val, []):
                existing_files_before.update(base_path.rglob(f"*{ext}"))
        
        # Download (store instance for cancellation)
        # Track if progress hooks were called (to detect silent failures)
        self.progress_hooks_called = False
        self.progress_hook_call_count = 0
        
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        self.ydl_instance = ydl
        
        # Log download start for debugging
        self.root.after(0, lambda: self.log(f"DEBUG: Starting yt-dlp download for {album_url}"))
        self.root.after(0, lambda: self.log(f"DEBUG: downloaded_files initialized: {hasattr(self, 'downloaded_files')}, count: {len(self.downloaded_files) if hasattr(self, 'downloaded_files') and self.downloaded_files else 0}"))
        
        # Retry download up to 2 times if no progress hooks are called
        max_download_retries = 2
        download_success = False
        
        for download_attempt in range(max_download_retries + 1):
            # Reset progress hook tracking for this attempt
            self.progress_hooks_called = False
            self.progress_hook_call_count = 0
            
            if download_attempt > 0:
                # Wait before retry (exponential backoff)
                retry_delay = 2.0 * download_attempt
                self.root.after(0, lambda delay=retry_delay, attempt=download_attempt: self.log(f"DEBUG: Retrying download after {delay}s delay (attempt {attempt + 1}/{max_download_retries + 1})"))
                time.sleep(retry_delay)
                # Create new yt-dlp instance for retry
                ydl = yt_dlp.YoutubeDL(ydl_opts)
                self.ydl_instance = ydl
            
            try:
                ydl.download([album_url])
                # Log after download completes
                self.root.after(0, lambda attempt=download_attempt: self.log(f"DEBUG: yt-dlp download() returned successfully (attempt {attempt + 1})"))
                self.root.after(0, lambda: self.log(f"DEBUG: progress_hooks_called: {self.progress_hooks_called}, call_count: {self.progress_hook_call_count}"))
                self.root.after(0, lambda: self.log(f"DEBUG: downloaded_files after download: {len(self.downloaded_files) if hasattr(self, 'downloaded_files') and self.downloaded_files else 0}"))
                
                # Check if progress hooks were called (indicates actual download activity)
                if self.progress_hooks_called or len(self.downloaded_files) > 0:
                    download_success = True
                    break
                elif download_attempt < max_download_retries:
                    # No progress hooks called and no files downloaded - retry
                    self.root.after(0, lambda: self.log(f"DEBUG: No progress hooks called, retrying download..."))
                    # Clear any partial state
                    if hasattr(self, 'downloaded_files'):
                        self.downloaded_files = set()
            except KeyboardInterrupt:
                # Check if this was our cancellation or user's Ctrl+C
                if self.is_cancelling:
                    # Our cancellation - exit gracefully
                    self.ydl_instance = None
                    return False
                # User's Ctrl+C - re-raise
                raise
            except yt_dlp.utils.DownloadError as e:
                # If this is a retry attempt, try again
                if download_attempt < max_download_retries:
                    self.root.after(0, lambda err=str(e), attempt=download_attempt: self.log(f"DEBUG: Download error on attempt {attempt + 1}, will retry: {err[:100]}"))
                    continue
                # Final attempt failed
                self.ydl_instance = None
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self.log(f"Download error: {msg}"))
                # Log more details for debugging batch mode issues
                if hasattr(self, 'downloaded_files'):
                    debug_info = f" (downloaded_files count: {len(self.downloaded_files) if self.downloaded_files else 0})"
                    self.root.after(0, lambda info=debug_info: self.log(f"DEBUG: Debug info: {info}"))
                return False
            except Exception as e:
                # If this is a retry attempt, try again
                if download_attempt < max_download_retries:
                    self.root.after(0, lambda err=str(e), attempt=download_attempt: self.log(f"DEBUG: Unexpected error on attempt {attempt + 1}, will retry: {err[:100]}"))
                    continue
                # Final attempt failed
                self.ydl_instance = None
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self.log(f"Unexpected error during download: {msg}"))
                if hasattr(self, 'downloaded_files'):
                    debug_info = f" (downloaded_files count: {len(self.downloaded_files) if self.downloaded_files else 0})"
                    self.root.after(0, lambda info=debug_info: self.log(f"DEBUG: Debug info: {info}"))
                return False
        
        # Check if download succeeded
        if not download_success:
            self.ydl_instance = None
            self.root.after(0, lambda: self.log("DEBUG: Download failed after all retry attempts (no progress hooks called)"))
            return False
        
        # Check if download succeeded
        if not download_success:
            self.ydl_instance = None
            self.root.after(0, lambda: self.log("DEBUG: Download failed after all retry attempts (no progress hooks called)"))
            return False
        
        # Clear instance after download
        self.ydl_instance = None
        
        # Check if cancelled - if so, exit early
        if self.is_cancelling:
            return False
        
        # Verify that files were actually downloaded (with retry logic for batch and discography modes)
        files_downloaded = False
        # Use more retries and longer delays for discography/batch modes (multiple albums in sequence)
        is_multi_album = hasattr(self, 'is_discography_mode') and self.is_discography_mode
        # Original Format or skip_postprocessing mode is much faster (no re-encoding), so files complete quickly
        # Need more time for file system to flush writes
        is_fast_mode = (base_format == "original" or skip_postprocessing)
        max_retries = 5 if is_multi_album else 3  # More retries for multi-album downloads
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            # Small delay to ensure files are fully written to disk
            # Fast modes (Original Format) need slightly longer delay since files complete very quickly
            if attempt > 0:
                time.sleep(retry_delay * attempt)  # Exponential backoff: 0.5s, 1s, 1.5s, 2s, 2.5s
            else:
                if is_multi_album:
                    time.sleep(0.5)  # Multi-album: 0.5s
                elif is_fast_mode:
                    time.sleep(0.4)  # Fast mode (Original Format): 0.4s (slightly longer than normal)
                else:
                    time.sleep(0.3)  # Normal mode: 0.3s
            
            # First, check downloaded_files set (most reliable - tracks files from progress hook)
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                for file_path in self.downloaded_files:
                    file_path_obj = Path(file_path)
                    # Verify file exists, is readable, and has a stable size (fully written)
                    # Pass is_fast_mode flag for Original Format mode
                    if self._verify_file_fully_written(file_path_obj, is_fast_mode=is_fast_mode):
                        files_downloaded = True
                        break
            
            # If downloaded_files check found files, we're done
            if files_downloaded:
                break
            
            # If downloaded_files check didn't find anything, fall back to file system comparison
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
                
                # Check if new files were created and verify they're fully written
                new_files = existing_files_after - existing_files_before
                if len(new_files) > 0:
                    # Verify at least one new file is fully written
                    # Pass is_fast_mode flag for Original Format mode
                    for new_file in new_files:
                        if self._verify_file_fully_written(new_file, is_fast_mode=is_fast_mode):
                            files_downloaded = True
                            break
                    if files_downloaded:
                        break
        
        # If no files were downloaded after retries, it likely requires purchase/login
        if not files_downloaded:
            # Log more details for debugging
            debug_info = []
            if hasattr(self, 'downloaded_files'):
                debug_info.append(f"downloaded_files count: {len(self.downloaded_files) if self.downloaded_files else 0}")
            if base_path and base_path.exists():
                debug_info.append(f"base_path exists: {base_path}")
            debug_msg = "⚠ No files were downloaded. This album may require purchase or login."
            if debug_info:
                debug_msg += f" ({', '.join(debug_info)})"
            self.root.after(0, lambda msg=debug_msg: self.log(msg))
            return False
        
        # Process downloaded files
        if download_path:
            try:
                # For MP3, verify and fix metadata if needed
                if base_format == "mp3":
                    self.verify_and_fix_mp3_metadata(download_path)
                # Process other formats (FLAC, OGG, WAV)
                self.process_downloaded_files(download_path)
                
                # Create playlist file if enabled
                if self.create_playlist_var.get():
                    self.create_playlist_file(download_path, base_format)
                
                # Final cleanup: rename all cover art files to "artist - album" format
                self.final_cover_art_cleanup(download_path)
            except Exception as e:
                self.root.after(0, lambda msg=str(e): self.log(f"⚠ Error during post-processing: {msg}"))
                # Continue anyway - files were downloaded
        
        return True
    
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
        # Mark that progress hooks are being called (for detecting silent failures)
        self.progress_hooks_called = True
        if not hasattr(self, 'progress_hook_call_count'):
            self.progress_hook_call_count = 0
        self.progress_hook_call_count += 1
        
        # Check cancellation first - if cancelled, raise KeyboardInterrupt to stop current track immediately
        if self.is_cancelling:
            raise KeyboardInterrupt("Download cancelled by user")
        
        try:
            status = d.get('status', '')
            
            if status == 'downloading':
                # Detect album changes in discography mode
                if self.is_discography_mode:
                    # Get filename to extract album path
                    filename = d.get('filename', '')
                    current_album_path = None
                    
                    # Extract album folder from filename path
                    if filename:
                        try:
                            from pathlib import Path
                            file_path = Path(filename)
                            # Get the album folder based on folder structure
                            # Structure 1: Root/Track.mp3 (no album folder)
                            # Structure 2: Root/Album/Track.mp3 (parent is album)
                            # Structure 3: Root/Artist/Track.mp3 (parent is artist, no album folder)
                            # Structure 4: Root/Artist/Album/Track.mp3 (parent is album)
                            # Structure 5: Root/Album/Artist/Track.mp3 (parent.parent is album)
                            choice = self._extract_structure_choice(self.folder_structure_var.get())
                            if choice == "2":
                                # Album folder structure: Root/Album/Track
                                current_album_path = str(file_path.parent)
                            elif choice == "4":
                                # Artist/Album structure: Root/Artist/Album/Track
                                # parent is album folder
                                if len(file_path.parts) >= 2:
                                    current_album_path = str(file_path.parent)
                            elif choice == "5":
                                # Album/Artist structure: Root/Album/Artist/Track
                                # parent.parent is album folder
                                if len(file_path.parts) >= 3:
                                    current_album_path = str(file_path.parent.parent)
                            elif choice == "3":
                                # Artist folder structure: Root/Artist/Track
                                # No album folder, but we can use artist folder as identifier
                                if len(file_path.parts) >= 2:
                                    current_album_path = str(file_path.parent)
                        except Exception:
                            pass
                    
                    # Try multiple methods to detect current album
                    current_album_from_meta = d.get('album') or d.get('playlist') or d.get('playlist_title')
                    
                    # Also try to detect from playlist_index (might indicate album number in discography)
                    playlist_index = d.get('playlist_index')
                    
                    # Initialize first album if not set
                    if self.current_album_name is None:
                        # Normalize path for first album
                        normalized_first_path = None
                        if current_album_path:
                            try:
                                path_obj = Path(current_album_path)
                                normalized_first_path = str(path_obj.resolve())
                            except:
                                normalized_first_path = str(Path(current_album_path)).lower().replace('\\', '/')
                        
                        # Try to get album name from path or metadata
                        if normalized_first_path:
                            self.current_album_path = normalized_first_path
                            # Mark first album path as seen
                            self.seen_album_paths.add(normalized_first_path)
                            # Extract album name from path
                            try:
                                album_folder_name = Path(current_album_path).name
                                self.current_album_name = album_folder_name
                            except:
                                pass
                        elif current_album_path:
                            # Fallback: use original path
                            self.current_album_path = current_album_path
                            normalized_path = current_album_path.lower().replace('\\', '/')
                            self.seen_album_paths.add(normalized_path)
                        elif current_album_from_meta:
                            self.current_album_name = current_album_from_meta
                        
                        # Try to find track count for first album
                        if self.current_album_name:
                            for album_info in self.albums_info:
                                if album_info["name"] == self.current_album_name:
                                    self.total_tracks = album_info["tracks"]
                                    break
                            # Log first album
                            if self.total_albums > 0:
                                self.root.after(0, lambda album=self.current_album_name, total=self.total_albums: 
                                              self.log(f"Starting album 1 of {total}: {album}"))
                    
                    # Check if we need to detect album change
                    album_changed = False
                    
                    # Normalize album path for comparison (case-insensitive, resolve to absolute)
                    normalized_current_path = None
                    if current_album_path:
                        try:
                            # Normalize path: resolve to absolute and normalize separators
                            path_obj = Path(current_album_path)
                            normalized_current_path = str(path_obj.resolve())
                        except:
                            # If resolve fails, just normalize the string
                            normalized_current_path = str(Path(current_album_path)).lower().replace('\\', '/')
                    
                    # Method 1: Check if album path changed (most reliable)
                    if normalized_current_path and normalized_current_path != self.current_album_path:
                        # Check if we've already seen this path (prevent duplicate detections)
                        if normalized_current_path not in self.seen_album_paths:
                            album_changed = True
                            # Extract album name from new path
                            try:
                                album_folder_name = Path(current_album_path).name
                                if album_folder_name:
                                    current_album_from_meta = album_folder_name
                            except:
                                pass
                    
                    # Method 2: Check if album name from metadata changed (only if path-based detection didn't trigger)
                    elif current_album_from_meta and current_album_from_meta != self.current_album_name:
                        # Normalize album name for comparison
                        normalized_meta_name = current_album_from_meta.strip().lower()
                        normalized_current_name = (self.current_album_name or "").strip().lower()
                        if normalized_meta_name != normalized_current_name:
                            # Check if we've seen this album name before (use name as fallback identifier)
                            if normalized_meta_name not in [name.strip().lower() for name in [p.split('/')[-1] if '/' in p else p.split('\\')[-1] for p in self.seen_album_paths]]:
                                album_changed = True
                    
                    # Method 3: Check playlist_index reset (heuristic) - only if other methods didn't trigger
                    elif playlist_index is not None and self.last_playlist_index is not None:
                        # If playlist_index resets or jumps back significantly, likely new album
                        # But be more conservative - only if it's a significant reset
                        if playlist_index < self.last_playlist_index - 2:  # More than 2 tracks back
                            album_changed = True
                    
                    if album_changed:
                        # New album detected - reset track counters
                        if self.current_album_name is not None:
                            # Album changed - increment album counter
                            self.current_album += 1
                            # Add completed tracks from previous album
                            # Use total_tracks (which represents tracks in the completed album)
                            if self.total_tracks > 0:
                                self.completed_tracks_all_albums += self.total_tracks
                        
                        # Update total_albums if we've exceeded the initial count
                        # This allows dynamic adjustment when more albums are detected than expected
                        if self.current_album >= self.total_albums:
                            self.total_albums = self.current_album + 1
                        
                        # Update album name and path
                        if current_album_from_meta:
                            self.current_album_name = current_album_from_meta
                        if normalized_current_path:
                            self.current_album_path = normalized_current_path
                            # Mark this path as seen
                            self.seen_album_paths.add(normalized_current_path)
                        elif current_album_path:
                            # Fallback: use original path if normalization failed
                            self.current_album_path = current_album_path
                            self.seen_album_paths.add(current_album_path.lower().replace('\\', '/'))
                        
                        self.current_track = 0
                        self.total_tracks = 0
                        
                        # Try to find track count for current album
                        if current_album_from_meta:
                            for album_info in self.albums_info:
                                if album_info["name"] == current_album_from_meta:
                                    self.total_tracks = album_info["tracks"]
                                    break
                        
                        # Log album change
                        if self.current_album >= 0:
                            album_num = self.current_album + 1
                            album_display = current_album_from_meta or current_album_path or f"Album {album_num}"
                            # Total now dynamically adjusts to match detected albums
                            self.root.after(0, lambda album=album_display, num=album_num, total=self.total_albums: 
                                          self.log(f"Starting album {num} of {total}: {album}"))
                    
                    # Store playlist_index and filename for next comparison
                    if playlist_index is not None:
                        self.last_playlist_index = playlist_index
                    if filename:
                        self.last_filename = filename
                
                # Get track/playlist info
                # Note: playlist_index might only be present at the start of each track
                # We'll use it if available, but rely on incrementing when tracks finish
                playlist_index = d.get('playlist_index')
                if playlist_index is not None and not self.is_discography_mode:
                    # Store 0-based index (0-based internally for consistency)
                    # Only update if it's different (new track started)
                    # In discography mode, playlist_index might refer to albums, so we handle it differently above
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
                if self.is_discography_mode:
                    # Discography mode: show album and track info
                    if self.total_albums > 0 and self.total_tracks > 0:
                        current_album_1based = self.current_album + 1 if self.current_album >= 0 else 1
                        current_track_1based = self.current_track + 1 if self.current_track >= 0 else 1
                        # total_albums dynamically adjusts when more albums are detected than initially expected
                        # Only cap track counter to avoid showing invalid track numbers
                        if current_track_1based > self.total_tracks:
                            current_track_1based = self.total_tracks
                        track_prefix = f"Album {current_album_1based}/{self.total_albums}, Track {current_track_1based}/{self.total_tracks}: "
                    elif self.total_albums > 0:
                        current_album_1based = self.current_album + 1 if self.current_album >= 0 else 1
                        # total_albums dynamically adjusts when more albums are detected than initially expected
                        track_prefix = f"Album {current_album_1based}/{self.total_albums}: "
                elif self.total_tracks > 0:
                    # Single album mode
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
                
                # Calculate overall progress
                overall_percent = None
                if self.is_discography_mode and self.total_tracks_all_albums > 0:
                    # Discography mode: calculate progress across all albums and tracks
                    # completed_tracks_all_albums = tracks from completed albums
                    # current_track = current track in current album (0-based)
                    # current_track_progress = percent / 100.0 (0.0 to 1.0)
                    completed_tracks = self.completed_tracks_all_albums + self.current_track
                    current_track_progress = (percent / 100.0) if percent is not None else 0.0
                    overall_progress = (completed_tracks + current_track_progress) / self.total_tracks_all_albums
                    overall_percent = overall_progress * 100.0
                elif self.total_tracks > 0:
                    # Single album mode
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
                # Update track counter when a track finishes
                filename = d.get('filename', '')
                if filename:
                    # Ensure downloaded_files set exists (should be initialized in download_single_album)
                    if not hasattr(self, 'downloaded_files'):
                        self.downloaded_files = set()
                    self.downloaded_files.add(filename)
                    # Log for debugging batch mode issues
                    self.root.after(0, lambda f=filename: self.log(f"DEBUG: progress_hook 'finished' - added: {Path(f).name if f else 'None'}"))
                    self.root.after(0, lambda: self.log(f"DEBUG: downloaded_files count: {len(self.downloaded_files)}"))
                
                # Detect album changes in discography mode (using filename path)
                album_changed = False
                if self.is_discography_mode and filename:
                    try:
                        from pathlib import Path
                        file_path = Path(filename)
                        current_album_path = None
                        
                        # Extract album folder from filename path (same logic as downloading status)
                        choice = self._extract_structure_choice(self.folder_structure_var.get())
                        if choice == "2":
                            current_album_path = str(file_path.parent)
                        elif choice == "4":
                            if len(file_path.parts) >= 2:
                                current_album_path = str(file_path.parent)
                        elif choice == "5":
                            if len(file_path.parts) >= 3:
                                current_album_path = str(file_path.parent.parent)
                        elif choice == "3":
                            if len(file_path.parts) >= 2:
                                current_album_path = str(file_path.parent)
                        
                        # Normalize path for comparison
                        normalized_finished_path = None
                        if current_album_path:
                            try:
                                path_obj = Path(current_album_path)
                                normalized_finished_path = str(path_obj.resolve())
                            except:
                                normalized_finished_path = str(Path(current_album_path)).lower().replace('\\', '/')
                        
                        # Check if album changed (only if we haven't seen this path before)
                        if normalized_finished_path and normalized_finished_path != self.current_album_path:
                            if normalized_finished_path not in self.seen_album_paths:
                                album_changed = True
                                
                                # New album detected
                                if self.current_album_path is not None:
                                    # Album changed - increment album counter
                                    self.current_album += 1
                                    # Add completed tracks from previous album
                                    if self.total_tracks > 0:
                                        self.completed_tracks_all_albums += self.total_tracks
                                
                                # Update total_albums if we've exceeded the initial count
                                # This allows dynamic adjustment when more albums are detected than expected
                                if self.current_album >= self.total_albums:
                                    self.total_albums = self.current_album + 1
                                
                                self.current_album_path = normalized_finished_path
                                # Mark this path as seen
                                self.seen_album_paths.add(normalized_finished_path)
                                
                                # Extract album name from path
                                try:
                                    album_folder_name = Path(current_album_path).name
                                    self.current_album_name = album_folder_name
                                    
                                    # Try to find track count for current album
                                    for album_info in self.albums_info:
                                        if album_info["name"] == album_folder_name:
                                            self.total_tracks = album_info["tracks"]
                                            break
                                    
                                    # Log album change
                                    if self.current_album >= 0:
                                        album_num = self.current_album + 1
                                        # Total now dynamically adjusts to match detected albums
                                        self.root.after(0, lambda album=album_folder_name, num=album_num, total=self.total_albums: 
                                                      self.log(f"Starting album {num} of {total}: {album}"))
                                except:
                                    pass
                                
                                # Reset track counter for new album (this track is the first of the new album)
                                self.current_track = 0
                    except Exception:
                        pass
                
                # Handle track completion
                if self.is_discography_mode:
                    # In discography mode, increment track counter
                    # If album just changed, current_track is 0, so increment to 1 (first track of new album)
                    # Otherwise, increment normally
                    if album_changed:
                        # This track is the first of the new album
                        self.current_track = 1
                    elif self.total_tracks > 0 and self.current_track < self.total_tracks - 1:
                        self.current_track += 1
                    elif self.total_tracks > 0 and self.current_track >= self.total_tracks - 1:
                        # Last track of current album - increment to show we're done with this album
                        self.current_track += 1
                        # If this is the last album, add completed tracks now
                        # Otherwise, album change detection will handle it
                        if self.current_album >= self.total_albums - 1:
                            # Last album - add completed tracks for this album
                            if self.total_tracks > 0:
                                self.completed_tracks_all_albums += self.total_tracks
                else:
                    # Single album mode - increment track counter
                    # Only increment if we haven't reached the total
                    if self.current_track < self.total_tracks - 1:
                        self.current_track += 1
                
                self.root.after(0, lambda: self.log(f"Processing: {d.get('filename', 'Unknown')}"))
            
            elif status == 'error':
                error_msg = d.get('error', 'Unknown error')
                self.root.after(0, lambda msg=error_msg: self.log(f"Error: {msg}"))
        
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # Log errors in progress hook for debugging (but don't break download)
            import traceback
            error_msg = f"DEBUG: progress_hook exception: {str(e)}"
            self.root.after(0, lambda msg=error_msg: self.log(msg))
            # Log full traceback for debugging
            tb_str = traceback.format_exc()
            self.root.after(0, lambda tb=tb_str: self.log(f"DEBUG: progress_hook traceback: {tb}"))
    
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

