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

# Application version (update this when releasing)
__version__ = "1.2.9"

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
import html
from pathlib import Path
from tkinter import (
    Tk, Toplevel, ttk, StringVar, BooleanVar, messagebox, scrolledtext, filedialog, W, E, N, S, LEFT, RIGHT, X, Y, END, WORD, BOTH,
    Frame, Label, Canvas, Checkbutton, Menu, Entry, Button, Listbox, EXTENDED, INSERT, Text, TclError
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
        except (TclError, RuntimeError):
            # Widget may be destroyed or not yet mapped
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
        except (TclError, RuntimeError):
            # Widget may be destroyed
            return False


class ThemeColors:
    """Color palette for application themes."""
    def __init__(self, mode='dark'):
        if mode == 'dark':
            # Dark mode - preserve exact existing colors
            self.bg = '#1E1E1E'  # Very dark background (consistent everywhere)
            self.fg = '#D4D4D4'  # Soft light text
            self.select_bg = '#252526'  # Slightly lighter for inputs only
            self.select_fg = '#FFFFFF'
            self.entry_bg = '#252526'  # Dark input background
            self.entry_fg = '#CCCCCC'  # Light input text
            self.border = '#3E3E42'  # Subtle borders
            self.accent = '#007ACC'  # Blue accent (more modern than green)
            self.success = '#2dacd5'  # Bandcamp blue for success/preview
            self.hover_bg = '#3E3E42'  # Hover state
            self.hover_fg = '#D4D4D4'  # Hover text
            self.disabled_fg = '#808080'  # Disabled text
            self.warning = '#FFA500'  # Orange for warnings
            self.preview_link = '#2dacd5'  # Preview link color
            self.preview_link_hover = '#4FC3F7'  # Preview link hover
        elif mode == 'light':
            # Light mode - modern Windows light mode aesthetic
            self.bg = '#F0F0F0'  # Light gray app background
            self.fg = '#1E1E1E'  # Dark text
            self.select_bg = '#FFFFFF'  # White for section backgrounds
            self.select_fg = '#1E1E1E'  # Dark text
            self.entry_bg = '#F5F5F5'  # Light gray input background
            self.entry_fg = '#1E1E1E'  # Dark input text
            self.border = '#D0D0D0'  # Medium gray borders (consistent for all sections)
            self.accent = '#007ACC'  # Same blue accent (consistent)
            self.success = '#2dacd5'  # Same Bandcamp blue (consistent)
            self.hover_bg = '#E8E8E8'  # Light hover state
            self.hover_fg = '#000000'  # Dark hover text
            self.disabled_fg = '#808080'  # Gray disabled text
            self.warning = '#FF8C00'  # Slightly darker orange for light mode
            self.preview_link = '#005A9E'  # Darker blue for preview links (better contrast in light mode)
            self.preview_link_hover = '#007ACC'  # Lighter blue on hover (still readable)


class BandcampDownloaderGUI:
    # ============================================================================
    # CONSTANTS - UI Configuration
    # ============================================================================
    DEFAULT_WINDOW_WIDTH = 520
    DEFAULT_WINDOW_HEIGHT = 580
    EXPAND_AMOUNT = 150
    URL_TEXT_MAX_HEIGHT_PX = 235
    URL_TEXT_DEFAULT_HEIGHT = 1
    URL_TEXT_MAX_HEIGHT_LINES = 8
    LOG_HISTORY_MAX_SIZE = 10000  # Maximum log messages to keep in memory
    SETTINGS_SAVE_DEBOUNCE_MS = 500  # Debounce time for settings saves
    URL_CHECK_DEBOUNCE_MS = 300  # Debounce time for URL validation
    
    # ============================================================================
    # CONSTANTS - File Formats and Extensions
    # ============================================================================
    FORMAT_EXTENSIONS = {
        "original": [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mpa", ".aac", ".opus"],  # Common audio formats
        "mp3": [".mp3"],
        "flac": [".flac"],
        "ogg": [".ogg", ".oga"],
        "wav": [".wav"],
    }
    THUMBNAIL_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']
    
    # ============================================================================
    # CONSTANTS - Folder Structures
    # ============================================================================
    FOLDER_STRUCTURES = {
        "1": "Root Directory",
        "2": "Album",
        "3": "Artist",
        "4": "Artist / Album",
        "5": "Album / Artist",
    }
    # Folder structure templates (template-based format)
    FOLDER_STRUCTURE_TEMPLATES = {
        "1": {"template": ""},  # Root Directory (empty template)
        "2": {"template": "Album"},
        "3": {"template": "Artist"},
        "4": {"template": "Artist / Album"},
        "5": {"template": "Album / Artist"},
    }
    DEFAULT_STRUCTURE = "4"
    DEFAULT_FORMAT = "Original"
    DEFAULT_NUMBERING = "Track"
    
    # Filename format constants (template-based, no curly brackets needed)
    FILENAME_FORMATS = {
        "Track": {"template": "Track"},
        "01. Track": {"template": "01. Track"},
        "Artist - Track": {"template": "Artist - Track"},
        "01. Artist - Track": {"template": "01. Artist - Track"},
    }
    # Valid tag names (without curly brackets)
    FILENAME_TAG_NAMES = ["01", "1", "Track", "Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
    # Folder structure tag names (no Track/01/1, and "/" is treated as level separator)
    FOLDER_TAG_NAMES = ["Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
    
    # Color palette for URL tags - interesting, varied colors with good contrast, ordered so adjacent colors contrast well
    # Colors are assigned sequentially to minimize duplicates
    TAG_COLORS = [
        '#007ACC',  # Blue (original - keep for consistency)
        '#D97706',  # Warm amber/orange (contrasts with blue)
        '#7C3AED',  # Rich purple (contrasts with orange)
        '#059669',  # Forest green (contrasts with purple)
        '#DC2626',  # Deep red (contrasts with green)
        '#0891B2',  # Ocean cyan (contrasts with red)
        '#CA8A04',  # Golden yellow (contrasts with cyan)
        '#9333EA',  # Vibrant violet (contrasts with yellow)
        '#0D9488',  # Turquoise (contrasts with violet)
        '#EA580C',  # Burnt orange (contrasts with turquoise)
        '#4F46E5',  # Deep indigo (contrasts with orange)
        '#DB2777',  # Rose pink (contrasts with indigo)
        '#16A34A',  # Emerald green (additional variety)
        '#C026D3',  # Magenta (additional variety)
        '#0284C7',  # Sky blue (additional variety)
        '#B91C1C',  # Crimson (additional variety)
    ]
    
    @staticmethod
    def _parse_css_color_scheme(css_content):
        """Parse CSS content to extract color scheme.
        
        Extracts --color-01 through --color-09 from CSS :root variables.
        
        Args:
            css_content: String content of CSS file
            
        Returns:
            List of 9 hex color strings, or None if parsing fails
        """
        import re
        colors = {}
        # Pattern to match --color-XX: #HEX; format (handles both 3 and 6 digit hex)
        # Matches: --color-01: #0077BE; or --color-01: #ABC;
        pattern = r'--color-0([1-9]):\s*(#[0-9A-Fa-f]{3,6})'
        matches = re.findall(pattern, css_content, re.IGNORECASE)
        
        if not matches:
            return None
        
        # Store colors by index
        for match in matches:
            color_num = int(match[0])
            hex_color = match[1]
            # Convert 3-digit hex to 6-digit if needed
            if len(hex_color) == 4:  # #RGB format
                hex_color = f"#{hex_color[1]}{hex_color[1]}{hex_color[2]}{hex_color[2]}{hex_color[3]}{hex_color[3]}"
            colors[color_num] = hex_color.upper()
        
        # Check we have all 9 colors
        if len(colors) != 9 or set(colors.keys()) != set(range(1, 10)):
            return None
        
        # Return as list in order
        return [colors[i] for i in range(1, 10)]
    
    @classmethod
    def _load_color_schemes_from_css(cls):
        """Load all color schemes from CSS files in Color Schemes folder.
        
        Returns:
            Dictionary mapping scheme names to lists of colors
        """
        schemes = {}
        script_dir = Path(__file__).resolve().parent
        css_dir = script_dir / "Color Schemes"
        
        # Add default scheme (current palette)
        schemes["default"] = cls.TAG_COLORS.copy()
        
        if not css_dir.exists():
            return schemes
        
        # Process each CSS file
        for css_file in css_dir.glob("Scheme_*.css"):
            try:
                with open(css_file, 'r', encoding='utf-8') as f:
                    css_content = f.read()
                
                colors = cls._parse_css_color_scheme(css_content)
                if colors:
                    # Extract scheme name from filename
                    # "Scheme_Ocean.css" -> "Ocean"
                    # "Scheme_Rainbowz-EE.css" -> "Rainbowz"
                    scheme_name = css_file.stem.replace("Scheme_", "")
                    # Remove suffixes like "-CE", "-EE"
                    scheme_name = scheme_name.split("-")[0]
                    # Clean up: "Pier_at_Dawn" -> "Pier at Dawn"
                    scheme_name = scheme_name.replace("_", " ")
                    
                    # Expand 9 colors to 16 by cycling (for better variety with many URLs)
                    expanded_colors = []
                    for i in range(16):
                        expanded_colors.append(colors[i % 9])
                    schemes[scheme_name] = expanded_colors
            except Exception:
                # Skip files that can't be parsed
                continue
        
        return schemes
    
    @staticmethod
    def _calculate_luminance(hex_color):
        """Calculate relative luminance of a color (WCAG formula).
        
        Args:
            hex_color: Hex color string (e.g., '#FF0000')
            
        Returns:
            Luminance value between 0.0 (dark) and 1.0 (light)
        """
        # Remove # if present
        hex_color = hex_color.lstrip('#')
        
        # Convert to RGB
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        
        # Apply gamma correction
        def gamma_correct(c):
            if c <= 0.03928:
                return c / 12.92
            return ((c + 0.055) / 1.055) ** 2.4
        
        r = gamma_correct(r)
        g = gamma_correct(g)
        b = gamma_correct(b)
        
        # Calculate relative luminance (WCAG formula)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return luminance
    
    @classmethod
    def _get_text_color_for_background(cls, bg_color):
        """Determine whether to use black or white text for a background color.
        
        Uses WCAG contrast guidelines - if background is light (luminance > 0.5),
        use black text, otherwise use white.
        
        Args:
            bg_color: Hex color string (e.g., '#FF0000')
            
        Returns:
            '#000000' for light backgrounds, '#FFFFFF' for dark backgrounds
        """
        luminance = cls._calculate_luminance(bg_color)
        return '#000000' if luminance > 0.5 else '#FFFFFF'
    
    # Load color schemes (will be populated on first access)
    _TAG_COLOR_SCHEMES = None
    
    @classmethod
    def _get_color_schemes(cls):
        """Get color schemes dictionary, loading from CSS if not already loaded."""
        if cls._TAG_COLOR_SCHEMES is None:
            cls._TAG_COLOR_SCHEMES = cls._load_color_schemes_from_css()
        return cls._TAG_COLOR_SCHEMES
    
    # ============================================================================
    # ERROR HANDLING HELPERS
    # ============================================================================
    @staticmethod
    def _safe_widget_operation(operation, default_return=None):
        """Safely execute a widget operation that might fail.
        
        Args:
            operation: Callable to execute
            default_return: Value to return if operation fails
            
        Returns:
            Result of operation or default_return if it fails
        """
        try:
            return operation()
        except (AttributeError, TclError, RuntimeError):
            # Common Tkinter errors that can be safely ignored
            return default_return
        except Exception:
            # Log unexpected errors in debug mode, but don't crash
            return default_return
    
    @staticmethod
    def _safe_file_operation(operation, default_return=None):
        """Safely execute a file operation that might fail.
        
        Args:
            operation: Callable to execute
            default_return: Value to return if operation fails
            
        Returns:
            Result of operation or default_return if it fails
        """
        try:
            return operation()
        except (FileNotFoundError, PermissionError, OSError, IOError):
            # Common file operation errors
            return default_return
        except Exception:
            return default_return
    
    # ============================================================================
    # TIMER MANAGEMENT
    # ============================================================================
    def _schedule_timer(self, delay_ms, callback):
        """Schedule a timer and track it for cleanup.
        
        Args:
            delay_ms: Delay in milliseconds
            callback: Callable to execute
            
        Returns:
            Timer ID
        """
        timer_id = self.root.after(delay_ms, callback)
        if hasattr(self, '_active_timers'):
            self._active_timers.add(timer_id)
        return timer_id
    
    def _cancel_timer(self, timer_id):
        """Cancel a scheduled timer and remove from tracking.
        
        Args:
            timer_id: Timer ID to cancel
        """
        if timer_id:
            try:
                self.root.after_cancel(timer_id)
            except (AttributeError, TclError):
                pass
            if hasattr(self, '_active_timers'):
                self._active_timers.discard(timer_id)
    
    def _cancel_all_timers(self):
        """Cancel all tracked timers (useful for cleanup)."""
        if hasattr(self, '_active_timers'):
            for timer_id in list(self._active_timers):
                self._cancel_timer(timer_id)
            self._active_timers.clear()
    
    @staticmethod
    def _is_windows_7():
        """Check if running on Windows 7.
        
        Returns:
            True if Windows 7 is detected, False otherwise
        """
        if sys.platform != 'win32':
            return False
        try:
            # Windows 7 is version 6.1
            version = sys.getwindowsversion()
            return version.major == 6 and version.minor == 1
        except (AttributeError, OSError):
            # Fallback: try platform module
            try:
                import platform
                release = platform.release()
                return release == '7'
            except (AttributeError, OSError):
                return False
    
    @classmethod
    def _get_icon(cls, icon_name):
        """Get the appropriate icon based on Windows version.
        
        Args:
            icon_name: String identifier for the icon ('settings', 'pencil', 'trash', 'expand', 'collapse')
            
        Returns:
            Unicode character string for the icon
        """
        is_win7 = cls._is_windows_7()
        
        icons = {
            'settings': '☰' if is_win7 else '⚙',
            'pencil': '✏' if is_win7 else '✏️',
            'trash': '✖' if is_win7 else '🗑️',
            'expand': '⇅' if is_win7 else '⤢',
            'collapse': '⇅' if is_win7 else '⤡',
            'eye': 'N' if is_win7 else '👁',
        }
        
        return icons.get(icon_name, '')
    
    def _extract_format(self, format_val):
        """Extract base format from display value (e.g., 'MP3 (128kbps)' -> 'mp3', 'MP3 (varies)' -> 'mp3')."""
        if format_val == "Original":
            return "original"
        # Handle both old and new MP3 labels (case-insensitive)
        format_lower = format_val.lower()
        if format_lower.startswith("mp3"):
            return "mp3"
        # Handle uppercase format names
        if format_lower == "flac":
            return "flac"
        if format_lower == "ogg":
            return "ogg"
        if format_lower == "wav":
            return "wav"
        return format_val.lower() if format_val else format_val
    
    def _clean_title(self, title, artist=None):
        """
        Clean title to remove artist prefix if present.
        Handles formats like "artist - song" or "artist: song" and returns just "song".
        """
        if not title:
            return title
        
        # If title contains " - " (space-dash-space), split and take the part after
        if " - " in title:
            parts = title.split(" - ", 1)
            if len(parts) == 2:
                # Check if first part matches artist (if provided)
                if artist and parts[0].strip().lower() == artist.lower():
                    return parts[1].strip()
                # Even if artist doesn't match, take the part after " - " as it's likely the song title
                return parts[1].strip()
        
        # If title contains ": " (colon-space), split and take the part after
        if ": " in title:
            parts = title.split(": ", 1)
            if len(parts) == 2:
                if artist and parts[0].strip().lower() == artist.lower():
                    return parts[1].strip()
                # Take the part after ": " as it's likely the song title
                return parts[1].strip()
        
        # Return title as-is if no pattern matches
        return title.strip()
    
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
        
        # Get script directory first (needed for icon path and settings)
        # When launched from launcher, __file__ will be in the launcher directory
        self.script_dir = Path(__file__).resolve().parent
        
        # If launched from launcher, ensure icon.ico is in script directory
        # (launcher copies it, but check parent directory as fallback)
        icon_path = self.script_dir / "icon.ico"
        if not icon_path.exists():
            # Try parent directory (where launcher.exe might be)
            parent_icon = self.script_dir.parent / "icon.ico"
            if parent_icon.exists():
                # Use parent directory for icon lookup
                self.icon_dir = self.script_dir.parent
            else:
                self.icon_dir = self.script_dir
        else:
            self.icon_dir = self.script_dir
        self.ffmpeg_path = None
        self.ydl = None
        
        # Detect if running from launcher.exe
        self.is_launcher_mode = self._is_launcher_mode()
        
        # Check for launcher update status (will log after UI is set up)
        self.pending_update_status = self._check_launcher_update_status()
        
        # Track URL field mode: 'entry' for single-line, 'text' for multi-line
        self.url_field_mode = 'entry'  # Start in single-line mode
        
        # URL tag mapping: stores full URLs for tag positions (tag_id -> full_url)
        self.url_tag_mapping = {}  # {tag_id: full_url}
        # URL tag positions: stores tag positions for deletion protection (tag_id -> (start_pos, end_pos))
        self.url_tag_positions = {}  # {tag_id: (start_pos, end_pos)}
        # URL metadata cache: stores metadata for each URL (url -> {artist, album, etc.})
        self.url_metadata_cache = {}  # {url: {artist, album, title, ...}}
        # URL tag metadata cache: stores only HTML extraction (stage 1) metadata for tags (url -> {artist, album, etc.})
        # This is separate from url_metadata_cache to prevent yt-dlp (stage 2) updates from affecting tags
        self.url_tag_metadata_cache = {}  # {url: {artist, album, title, ...}}
        
        # Variables
        self.url_var = StringVar()
        self.path_var = StringVar()
        # Initialize with saved preference (may be standard or custom)
        # Load settings once and cache for reuse (performance optimization)
        settings = self._load_settings()
        self._cached_settings = settings  # Cache settings to avoid multiple file reads
        saved_structure = settings.get("folder_structure", self.DEFAULT_STRUCTURE)
        # Check if it's a standard structure
        if saved_structure in ["1", "2", "3", "4", "5"]:
            display_value = self.FOLDER_STRUCTURES.get(saved_structure, self.FOLDER_STRUCTURES[self.DEFAULT_STRUCTURE])
        else:
            # It's a custom structure (formatted string)
            # Try to find it in custom_structures (will be loaded later, but check if it exists)
            display_value = saved_structure  # Use the formatted string directly
        # Load custom structures and filename formats before loading numbering (needed for validation)
        # Pass cached settings to avoid re-reading file
        self.custom_structures = self._load_custom_structures(settings=settings)  # List of structure lists (old format)
        self.custom_structure_templates = self._load_custom_structure_templates(settings=settings)  # List of template dicts (new format)
        self.custom_filename_formats = self._load_custom_filename_formats(settings=settings)  # List of format dicts
        
        self.folder_structure_var = StringVar(value=display_value)
        self.format_var = StringVar(value=self.load_saved_format())
        self.numbering_var = StringVar(value=self.load_saved_numbering())
        self.skip_postprocessing_var = BooleanVar(value=self.load_saved_skip_postprocessing())
        self.create_playlist_var = BooleanVar(value=self.load_saved_create_playlist())
        self.download_cover_art_var = BooleanVar(value=self.load_saved_download_cover_art())
        self.download_discography_var = BooleanVar(value=False)  # Always default to off, not persistent
        self.auto_check_updates_var = BooleanVar(value=self.load_saved_auto_check_updates())
        
        # Split album artist display setting
        self.split_album_artist_display_var = StringVar(value=self.load_saved_split_album_artist_display())
        
        # MP3 skip re-encoding setting (default to True)
        self.skip_mp3_reencode_var = BooleanVar(value=self.load_saved_skip_mp3_reencode())
        
        # Color scheme for URL tags
        self.current_tag_color_scheme = self.load_saved_tag_color_scheme()
        schemes = self._get_color_schemes()
        if self.current_tag_color_scheme not in schemes:
            self.current_tag_color_scheme = "default"
        self.current_tag_colors = schemes.get(self.current_tag_color_scheme, schemes["default"])
        # Initialize variable for menu (will be created when menu is first built)
        self.tag_color_scheme_var = StringVar(value=self.current_tag_color_scheme)
        
        # Theme system - load saved theme preference (default to 'dark' for backward compatibility)
        saved_theme = settings.get("theme", "dark")
        self.current_theme = saved_theme if saved_theme in ['dark', 'light'] else 'dark'
        self.theme_colors = ThemeColors(self.current_theme)
        
        # Batch URL mode tracking
        self.batch_mode = False  # Track if we're in batch mode (multiple URLs)
        self.url_entry_widget = None  # Store reference to Entry widget
        self.url_text_widget = None  # Store reference to ScrolledText widget
        self.url_container_frame = None  # Container frame for URL widgets
        
        # Content history for undo/redo functionality (tracks content state, not just pastes)
        self.content_history = []  # List of content states (full field content at each change)
        self.content_history_index = -1  # Current position in history (-1 = most recent)
        self.content_save_timer = None  # Timer for debounced content state saving
        self.auto_expand_timer = None  # Timer for debounced auto-expand height adjustment
        
        # Timer management for cleanup
        self._active_timers = set()  # Track active timer IDs for cleanup
        self._settings_save_timer = None  # Debounce timer for settings saves
        
        # Debug mode flag (default: False)
        self.debug_mode = False
        
        # Store all log messages for debug toggle functionality
        self.log_messages = []  # List of tuples: (message, is_debug)
        self.log_snapshot = None  # Store snapshot before clearing: (log_messages_copy, debug_mode_state, scroll_position)
        
        # Store metadata for preview
        self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None, "first_track_title": None, "first_track_number": None, "track_titles": []}
        self.format_suggestion_shown = False  # Track if format suggestion has been shown for current URL
        self.url_check_timer = None  # For debouncing URL changes
        self.album_art_image = None  # Store reference to prevent garbage collection
        self.preloaded_album_art_image = None  # Cache for preloaded album art (for instant display when switching from hidden)
        self.preloaded_album_art_pil = None  # Store original PIL Image for blur effect
        self.album_art_fetching = False  # Flag to prevent multiple simultaneous fetches
        self.current_thumbnail_url = None  # Track current thumbnail to avoid re-downloading
        self.current_bio_pic_url = None  # Track current bio pic URL to avoid re-downloading
        self.artwork_fetch_id = 0  # Track fetch requests to cancel stale ones
        self.current_url_being_processed = None  # Track URL currently being processed to avoid cancelling valid fetches
        self.album_art_mode = "album_art"  # Track album art panel mode: "album_art", "bio_pic", or "hidden"
        
        # URL text widget resize state
        self.url_text_height = 1  # Default height in lines (collapsed)
        self.url_text_max_height_px = 235  # Maximum height in pixels (reduced by 15px from 240)
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
        self.debug_tag_name = "debug_message"  # Tag name for debug messages (for show/hide)
        
        # Check dependencies first
        if not self.check_dependencies():
            self.root.destroy()
            return
        
        # Apply theme (dark or light based on saved preference)
        self.apply_theme()
        # Load album art state before setting up UI so eye icon can be positioned correctly
        self.load_saved_album_art_state()
        self.setup_ui()
        self.load_saved_path()
        self.update_preview()
        # Initialize URL count and button text
        self.root.after(100, self._update_url_count_and_button)
        # Initialize clear button visibility
        self.root.after(100, self._update_url_clear_button)
        # Initialize expand button icon (should be expand icon ⤢ in single-line mode)
        self.root.after(100, self._update_url_expand_button)
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
        
        # Check for launcher update status and log it (after UI is ready)
        if self.pending_update_status:
            self.root.after(100, lambda: self._log_launcher_update_status())
        
        # Check for updates in background after UI is ready (non-blocking) - only if auto-check is enabled
        if self.auto_check_updates_var.get():
            self.root.after(2000, self._check_for_updates_background)  # Wait 2 seconds after startup
    
    def apply_theme(self):
        """Apply current theme (dark or light) to all UI elements."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Use theme colors (preserves exact dark mode colors when in dark mode)
        colors = self.theme_colors
        bg_color = colors.bg
        fg_color = colors.fg
        select_bg = colors.select_bg
        select_fg = colors.select_fg
        entry_bg = colors.entry_bg
        entry_fg = colors.entry_fg
        border_color = colors.border
        accent_color = colors.accent
        success_color = colors.success
        hover_bg = colors.hover_bg
        
        # Configure root background
        self.root.configure(bg=bg_color)
        
        # Configure styles - all backgrounds use bg_color
        style.configure('TFrame', background=bg_color, borderwidth=0)
        # TLabel uses bg_color (app background) - this is correct for most labels
        style.configure('TLabel', background=bg_color, foreground=fg_color)
        # Settings.TLabel for labels in settings section - matches settings frame background
        # Dark mode: uses bg, Light mode: uses select_bg (white)
        settings_label_bg = select_bg if self.current_theme == 'light' else bg_color
        style.configure('Settings.TLabel', background=settings_label_bg, foreground=fg_color)
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
                       insertcolor=fg_color, lightcolor=border_color, darkcolor=border_color)
        style.map('TEntry', 
                  bordercolor=[('focus', accent_color)],
                  lightcolor=[('focus', border_color), ('!focus', border_color)],
                  darkcolor=[('focus', border_color), ('!focus', border_color)])
        style.configure('TButton', background=select_bg, foreground=fg_color,
                       borderwidth=1, bordercolor=border_color, relief='flat',
                       padding=(10, 5))
        style.map('TButton', 
                 background=[('active', hover_bg), ('pressed', bg_color)],
                 bordercolor=[('active', border_color), ('pressed', border_color)])
        
        # Special style for download button with Bandcamp blue accent
        # Default is darker, hover is brighter/more prominent
        style.configure('Download.TButton', background='#2599b8', foreground='#FFFFFF',
                       borderwidth=0, bordercolor='#2599b8', relief='flat',
                       padding=(12, 6), font=("Segoe UI", 10, "bold"), width=25)
        style.map('Download.TButton',
                 background=[('active', success_color), ('pressed', '#1d7a95')],
                 bordercolor=[('active', success_color), ('pressed', '#1d7a95')])
        
        # Cancel button style - matches download button size but keeps muted default colors
        # Slightly wider to match visual size of download button
        # Cancel button style - match Browse button styling
        # Dark mode: uses select_bg (#252526), Light mode: uses entry_bg (#F5F5F5) to match Browse button
        cancel_bg = entry_bg if self.current_theme == 'light' else select_bg
        style.configure('Cancel.TButton', background=cancel_bg, foreground=fg_color,
                       borderwidth=0, bordercolor=cancel_bg, relief='flat',
                       padding=(15, 10), width=23)  # Slightly wider than download button to match visual size
        style.map('Cancel.TButton',
                 background=[('active', hover_bg), ('pressed', cancel_bg)],
                 bordercolor=[('active', cancel_bg), ('pressed', cancel_bg)])  # Match background to hide borders
        
        # Browse button style - compact with no border
        # Dark mode: uses select_bg (#252526), Light mode: uses entry_bg (#F5F5F5) to match Clear Log
        browse_bg = entry_bg if self.current_theme == 'light' else select_bg
        style.configure('Browse.TButton', background=browse_bg, foreground=fg_color,
                       borderwidth=0, bordercolor=browse_bg, relief='flat',
                       padding=(8, 4))  # Compact padding
        style.map('Browse.TButton',
                 background=[('active', hover_bg), ('pressed', browse_bg)],
                 bordercolor=[('active', browse_bg), ('pressed', browse_bg)])  # Match background to hide borders
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

        # Dark themed vertical scrollbar style (used for URL and log text widgets)
        # Only configure this style when in dark mode to avoid light mode interference
        # Explicitly set all properties to prevent inheritance from TScrollbar style
        if self.current_theme == 'dark':
            style.configure(
                'Dark.Vertical.TScrollbar',
                background=border_color,
                troughcolor=bg_color,
                bordercolor=border_color,
                arrowcolor='#CCCCCC',
                darkcolor=border_color,  # Explicitly set to prevent bright highlights
                lightcolor=border_color,  # Explicitly set to prevent bright highlights
                relief='flat',
                borderwidth=0
            )
            style.map(
                'Dark.Vertical.TScrollbar',
                # Make hover more noticeable - use a lighter gray (#4E4E52) that's clearly visible against border (#3E3E42)
                # This creates a subtle but visible hover effect
                background=[('active', '#4E4E52'), ('pressed', '#5E5E62'), ('!active', border_color)],
                arrowcolor=[('active', '#FFFFFF'), ('!active', '#CCCCCC')],
                # Keep darkcolor, lightcolor, and bordercolor exactly matching background for flat, clean look
                darkcolor=[('active', '#4E4E52'), ('pressed', '#5E5E62'), ('!active', border_color)],
                lightcolor=[('active', '#4E4E52'), ('pressed', '#5E5E62'), ('!active', border_color)],
                bordercolor=[('active', '#4E4E52'), ('pressed', '#5E5E62'), ('!active', border_color)]
            )
        # Progress bar uses Bandcamp blue for a friendly, success-oriented feel
        # Trough color: dark mode uses bg, light mode uses entry_bg (#F5F5F5) to match URL field
        progress_trough = colors.entry_bg if self.current_theme == 'light' else bg_color
        style.configure('TProgressbar', background=success_color, troughcolor=progress_trough,
                        borderwidth=2, bordercolor=border_color, lightcolor=success_color, darkcolor=success_color)
        
        # Menubutton style (shared by all menubuttons - structure, format, numbering)
        # Use theme-appropriate hover color
        hover_menubutton = '#2D2D30' if self.current_theme == 'dark' else colors.hover_bg
        hover_text = '#FFFFFF' if self.current_theme == 'dark' else colors.fg
        arrow_color = '#CCCCCC' if self.current_theme == 'dark' else '#666666'  # Darker arrow for light mode
        
        # Menubutton background: dark mode uses entry_bg, light mode uses select_bg (white) to match settings frame
        menubutton_bg = select_bg if self.current_theme == 'light' else entry_bg
        style.configure('Dark.TMenubutton',
            background=menubutton_bg,
            foreground=entry_fg,
            borderwidth=1,
            bordercolor=border_color,
            relief='solid',
            padding=(0, 0),  # Remove padding to match combobox alignment
            arrowcolor=arrow_color,
            arrowpadding=(0, 0, 8, 0)  # Padding for arrow (left, top, right, bottom)
        )
        style.map('Dark.TMenubutton',
            background=[('active', hover_menubutton), ('!disabled', menubutton_bg)],
            foreground=[('active', hover_text), ('!disabled', entry_fg)],
            borderwidth=[('focus', 1), ('!focus', 1)],
            bordercolor=[('focus', accent_color), ('!focus', border_color)],  # Blue border on focus like combobox
            relief=[('pressed', 'solid'), ('!pressed', 'solid')],
            arrowcolor=[('active', arrow_color), ('!active', arrow_color)]
        )
        
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
        
        # Configure default TScrollbar style (theme-aware)
        if self.current_theme == 'light':
            # Light mode: clean, minimalist scrollbar matching dark mode aesthetic
            # Use subtle gray colors for a clean, minimal look
            light_scrollbar_bg = '#D0D0D0'  # Light gray thumb
            light_scrollbar_trough = '#F5F5F5'  # Very light gray trough
            light_scrollbar_border = '#D0D0D0'  # Border matches thumb
            light_scrollbar_arrow = '#808080'  # Medium gray arrows
            light_scrollbar_hover = '#B0B0B0'  # Slightly darker on hover
            
            style.configure('TScrollbar', 
                           background=light_scrollbar_bg,
                           troughcolor=light_scrollbar_trough,
                           bordercolor=light_scrollbar_border,
                           arrowcolor=light_scrollbar_arrow,
                           darkcolor=light_scrollbar_border,  # Match border for clean look
                           lightcolor=light_scrollbar_border,  # Match border for clean look
                           relief='flat',
                           borderwidth=0)
            style.map('TScrollbar',
                     background=[('active', light_scrollbar_hover), ('pressed', '#999999'), ('!active', light_scrollbar_bg)],
                     arrowcolor=[('active', '#666666'), ('!active', light_scrollbar_arrow)],
                     # Keep darkcolor, lightcolor, and bordercolor exactly matching background for flat, clean look
                     darkcolor=[('active', light_scrollbar_hover), ('pressed', '#999999'), ('!active', light_scrollbar_bg)],
                     lightcolor=[('active', light_scrollbar_hover), ('pressed', '#999999'), ('!active', light_scrollbar_bg)],
                     bordercolor=[('active', light_scrollbar_hover), ('pressed', '#999999'), ('!active', light_scrollbar_bg)])
        else:
            # Dark mode: minimal styling (Dark.Vertical.TScrollbar is used instead)
            style.configure('TScrollbar', background=bg_color, troughcolor=bg_color,
                           bordercolor=bg_color, arrowcolor=fg_color, darkcolor=bg_color,
                           lightcolor=bg_color)
            style.map('TScrollbar',
                     background=[('active', hover_bg)],
                     arrowcolor=[('active', fg_color), ('!active', border_color)])
        
        # Small.TButton style (for Clear Log button)
        # Dark mode: uses select_bg (#252526), Light mode: uses entry_bg (#F5F5F5)
        small_btn_bg = entry_bg if self.current_theme == 'light' else select_bg
        style.configure('Small.TButton', 
                       background=small_btn_bg,
                       foreground=fg_color,
                       borderwidth=0,
                       bordercolor=small_btn_bg,  # Match background to hide borders
                       relief='flat',
                       padding=(6, 2),
                       font=("Segoe UI", 8))
        style.map('Small.TButton',
                 background=[('active', hover_bg), ('pressed', small_btn_bg)],
                 bordercolor=[('active', small_btn_bg), ('pressed', small_btn_bg)])
    
    def toggle_theme(self):
        """Toggle between dark and light mode."""
        # Switch theme
        new_theme = 'light' if self.current_theme == 'dark' else 'dark'
        self.current_theme = new_theme
        self.theme_colors = ThemeColors(new_theme)
        
        # Re-apply theme to all UI elements
        self.apply_theme()
        
        # Refresh all widgets with new theme colors
        self._refresh_all_widgets()
        
        # Update settings menu to reflect new theme
        self._rebuild_settings_menu()
        
        # Save preference
        self._save_theme_preference()
    
    def _save_theme_preference(self):
        """Save current theme preference to settings."""
        settings = self._load_settings()
        settings["theme"] = self.current_theme
        self._save_settings(settings)
    
    def _refresh_all_widgets(self):
        """Refresh all widgets with current theme colors."""
        colors = self.theme_colors
        
        # Helper function to recursively update widget colors
        def update_widget_recursive(widget, depth=0):
            """Recursively update widget and all children."""
            if depth > 10:  # Prevent infinite recursion
                return
            try:
                widget_type = widget.winfo_class()
                if widget_type in ('Frame', 'LabelFrame', 'Toplevel'):
                    widget.configure(bg=colors.bg)
                elif widget_type == 'Label':
                    # Only update if it's not a special label (like preview link)
                    current_bg = widget.cget('bg')
                    if current_bg in ['#1E1E1E', '#252526', '#FFFFFF', '#F5F5F5']:
                        widget.configure(bg=colors.bg, fg=colors.fg)
                elif widget_type == 'Entry':
                    widget.configure(
                        bg=colors.entry_bg,
                        fg=colors.entry_fg,
                        insertbackground=colors.fg,
                        highlightbackground=colors.border,
                        highlightcolor=colors.accent
                    )
                elif widget_type == 'Text':
                    widget.configure(
                        bg=colors.bg if widget == getattr(self, 'log_text', None) else colors.entry_bg,
                        fg=colors.fg,
                        insertbackground=colors.fg,
                        highlightbackground=colors.border,
                        highlightcolor=colors.accent
                    )
                elif widget_type == 'Canvas':
                    widget.configure(bg=colors.bg)
                elif widget_type == 'Checkbutton':
                    widget.configure(
                        bg=colors.bg,
                        fg=colors.fg,
                        selectcolor=colors.bg,
                        activebackground=colors.bg,
                        activeforeground=colors.fg
                    )
                
                # Recursively update children
                try:
                    for child in widget.winfo_children():
                        update_widget_recursive(child, depth + 1)
                except:
                    pass
            except (TclError, AttributeError):
                pass
        
        # Update root background
        if hasattr(self, 'root'):
            self.root.configure(bg=colors.bg)
            # Recursively update all widgets
            try:
                update_widget_recursive(self.root)
            except:
                pass
        
        # Update main frame if it exists
        if hasattr(self, 'url_container_frame'):
            self.url_container_frame.configure(bg=colors.bg)
        
        # Update all Label widgets that we track
        widget_attrs = [
            'url_paste_btn', 'url_clear_btn', 'url_expand_btn',
            'settings_cog_btn', 'show_album_art_btn',
            'preview_label_path', 'format_conversion_warning_label',
            'ogg_warning_label', 'wav_warning_label'
        ]
        
        for attr in widget_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget and isinstance(widget, (Label, Frame, Canvas)):
                    try:
                        # Update background and foreground
                        if attr in ['url_paste_btn', 'url_clear_btn', 'url_expand_btn', 'settings_cog_btn', 'show_album_art_btn']:
                            # Icon buttons use bg and disabled_fg
                            widget.configure(bg=colors.bg, fg=colors.disabled_fg)
                            # Rebind hover handlers with current theme colors
                            widget.unbind('<Enter>')
                            widget.unbind('<Leave>')
                            widget.bind('<Enter>', lambda e, w=widget: w.config(fg=colors.hover_fg))
                            widget.bind('<Leave>', lambda e, w=widget: w.config(fg=colors.disabled_fg))
                        else:
                            widget.configure(bg=colors.bg, fg=colors.fg)
                    except (TclError, AttributeError):
                        pass
        
        # Update Entry widgets
        if hasattr(self, 'url_entry_widget') and self.url_entry_widget:
            try:
                self.url_entry_widget.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    insertbackground=colors.fg,
                    highlightbackground=colors.border,
                    highlightcolor=colors.accent
                )
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'path_entry') and self.path_entry:
            try:
                self.path_entry.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    insertbackground=colors.fg,
                    highlightbackground=colors.border,
                    highlightcolor=colors.accent
                )
            except (TclError, AttributeError):
                pass
        
        # Update Text widgets
        if hasattr(self, 'url_text_widget') and self.url_text_widget:
            try:
                self.url_text_widget.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    insertbackground=colors.fg,
                    highlightbackground=colors.border,
                    highlightcolor=colors.accent
                )
            except (TclError, AttributeError):
                pass
        
        # Update placeholder labels
        if hasattr(self, 'url_text_placeholder_label') and self.url_text_placeholder_label:
            try:
                self.url_text_placeholder_label.configure(
                    bg=colors.entry_bg,
                    fg=colors.disabled_fg
                )
            except (TclError, AttributeError):
                pass
        
        # Update frames - sections: dark mode uses bg, light mode uses select_bg (white)
        # Settings frames: use select_bg in light mode, bg in dark mode
        settings_frame_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        if hasattr(self, 'settings_frame') and self.settings_frame:
            try:
                self.settings_frame.configure(bg=settings_frame_bg, highlightbackground=colors.border)
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'settings_content') and self.settings_content:
            try:
                self.settings_content.configure(bg=settings_frame_bg)
                # Update ttk.Label widgets in settings_content to match frame background
                # ttk.Label widgets use TLabel style which defaults to app bg, need to update style for settings
                style = ttk.Style()
                # Create a custom style for settings labels that matches the frame
                style.configure('Settings.TLabel', background=settings_frame_bg, foreground=colors.fg)
                # Update all ttk.Label widgets in settings_content
                for child in self.settings_content.winfo_children():
                    try:
                        if isinstance(child, ttk.Label):
                            child.configure(style='Settings.TLabel')
                    except (TclError, AttributeError):
                        pass
            except (TclError, AttributeError):
                pass
        
        # Preview frame: use entry_bg in light mode (#F5F5F5), bg in dark mode
        if hasattr(self, 'preview_frame') and self.preview_frame:
            try:
                preview_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.preview_frame.configure(bg=preview_frame_bg, highlightbackground=colors.border)
                # Update preview label prefix background
                if hasattr(self, 'preview_label_prefix') and self.preview_label_prefix:
                    self.preview_label_prefix.configure(bg=preview_frame_bg)
                # Update preview label path background
                if hasattr(self, 'preview_label_path') and self.preview_label_path:
                    self.preview_label_path.configure(bg=preview_frame_bg)
            except (TclError, AttributeError):
                pass
        
        # Log frame: dark mode uses bg, light mode uses entry_bg (#F5F5F5) to match URL field
        if hasattr(self, 'log_frame') and self.log_frame:
            try:
                log_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.log_frame.configure(bg=log_frame_bg, highlightbackground=colors.border)
                # Update status label background
                if hasattr(self, 'log_label') and self.log_label:
                    self.log_label.configure(bg=log_frame_bg)
                # Update word wrap checkbox background - must use entry_bg (#F5F5F5) in light mode
                if hasattr(self, 'word_wrap_toggle') and self.word_wrap_toggle:
                    checkbox_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                    self.word_wrap_toggle.configure(
                        bg=checkbox_bg, 
                        selectcolor=checkbox_bg, 
                        activebackground=checkbox_bg,
                        activeforeground=colors.fg
                    )
                # Update debug checkbox background - must use entry_bg (#F5F5F5) in light mode
                if hasattr(self, 'debug_toggle') and self.debug_toggle:
                    checkbox_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                    self.debug_toggle.configure(
                        bg=checkbox_bg, 
                        selectcolor=checkbox_bg, 
                        activebackground=checkbox_bg,
                        activeforeground=colors.fg
                    )
            except (TclError, AttributeError):
                pass
        
        # Album art frame: dark mode uses bg, light mode uses select_bg (white)
        if hasattr(self, 'album_art_frame') and self.album_art_frame:
            try:
                album_art_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
                self.album_art_frame.configure(bg=album_art_bg, highlightbackground=colors.border)
            except (TclError, AttributeError):
                pass
        
        # Other frames use main bg
        other_frames = ['url_text_frame', 'entry_container']
        for attr in other_frames:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        widget.configure(bg=colors.bg)
                    except (TclError, AttributeError):
                        pass
        
        # Update canvas - album art: dark mode uses bg, light mode uses select_bg (white)
        if hasattr(self, 'album_art_canvas') and self.album_art_canvas:
            try:
                canvas_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
                self.album_art_canvas.configure(bg=canvas_bg)
            except (TclError, AttributeError):
                pass
        
        # Update resize handle
        if hasattr(self, 'url_text_resize_handle') and self.url_text_resize_handle:
            try:
                self.url_text_resize_handle.configure(bg=colors.entry_bg, fg=colors.disabled_fg)
            except (TclError, AttributeError):
                pass
        
        # Update overall progress bar background
        if hasattr(self, 'overall_progress_bar') and self.overall_progress_bar:
            try:
                progress_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.overall_progress_bar.bg_color = progress_bg
                self.overall_progress_bar.canvas.configure(bg=progress_bg)
                # Update trough color
                self.overall_progress_bar.canvas.itemconfig(self.overall_progress_bar.trough, fill=progress_bg)
            except (TclError, AttributeError):
                pass
        
        # Update expand/collapse button - matches log_frame background (entry_bg in light mode)
        if hasattr(self, 'expand_collapse_btn') and self.expand_collapse_btn:
            try:
                expand_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.expand_collapse_btn.configure(bg=expand_bg, fg=colors.disabled_fg)
                # Rebind hover handlers with current theme colors
                self.expand_collapse_btn.unbind('<Enter>')
                self.expand_collapse_btn.unbind('<Leave>')
                self.expand_collapse_btn.bind('<Enter>', lambda e: self.expand_collapse_btn.config(fg=colors.hover_fg))
                self.expand_collapse_btn.bind('<Leave>', lambda e: self.expand_collapse_btn.config(fg=colors.disabled_fg))
            except (TclError, AttributeError):
                pass
        
        # Update edit/delete icon buttons (filename and folder structure)
        # Use settings_frame_bg to match settings content background
        icon_button_attrs = [
            'filename_customize_btn', 'filename_manage_btn',
            'customize_btn', 'manage_btn'
        ]
        for attr in icon_button_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        widget.configure(bg=settings_frame_bg, fg=colors.disabled_fg)
                        # Rebind hover handlers with current theme colors
                        widget.unbind('<Enter>')
                        widget.unbind('<Leave>')
                        # Check if button is enabled (has custom structures/formats)
                        if attr in ['filename_manage_btn', 'manage_btn']:
                            # These buttons may be disabled - check if they have custom items
                            has_custom = False
                            if attr == 'filename_manage_btn':
                                has_custom = hasattr(self, 'custom_filename_formats') and self.custom_filename_formats
                            elif attr == 'manage_btn':
                                has_custom = hasattr(self, 'custom_structures') and self.custom_structures
                            
                            if has_custom:
                                widget.bind('<Enter>', lambda e, w=widget: w.config(fg=colors.hover_fg))
                                widget.bind('<Leave>', lambda e, w=widget: w.config(fg=colors.disabled_fg))
                            else:
                                # Disabled state - no hover
                                disabled_color = colors.disabled_fg if self.current_theme == 'dark' else '#A0A0A0'
                                widget.configure(fg=disabled_color)
                        else:
                            # Always enabled buttons (customize buttons)
                            widget.bind('<Enter>', lambda e, w=widget: w.config(fg=colors.hover_fg))
                            widget.bind('<Leave>', lambda e, w=widget: w.config(fg=colors.disabled_fg))
                    except (TclError, AttributeError):
                        pass
        
        # Update show_album_art_btn to match settings frame
        if hasattr(self, 'show_album_art_btn') and self.show_album_art_btn:
            try:
                self.show_album_art_btn.configure(bg=settings_frame_bg, fg=colors.disabled_fg)
                # Rebind hover handlers with current theme colors
                self.show_album_art_btn.unbind('<Enter>')
                self.show_album_art_btn.unbind('<Leave>')
                self.show_album_art_btn.bind('<Enter>', lambda e: self.show_album_art_btn.config(fg=colors.hover_fg))
                self.show_album_art_btn.bind('<Leave>', lambda e: self.show_album_art_btn.config(fg=colors.disabled_fg))
            except (TclError, AttributeError):
                pass
        
        # Update filename and structure frames to match settings frame background
        frame_attrs = ['filename_frame', 'structure_frame']
        for attr in frame_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        widget.configure(bg=settings_frame_bg)
                    except (TclError, AttributeError):
                        pass
        
        # Force menubuttons to refresh their style (filename and folder structure)
        # This ensures they get the updated Dark.TMenubutton style with correct background
        menubutton_attrs = ['filename_menubutton', 'structure_menubutton']
        for attr in menubutton_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        # Force style refresh by temporarily changing style and changing back
                        current_style = widget.cget('style')
                        widget.configure(style='TMenubutton')  # Reset to base
                        self.root.update_idletasks()
                        widget.configure(style=current_style)  # Apply updated style
                        # Also force update of the widget itself
                        widget.update_idletasks()
                    except (TclError, AttributeError):
                        pass
        
        # Update preview frame and labels - dark mode uses bg, light mode uses select_bg
        if hasattr(self, 'preview_frame') and self.preview_frame:
            try:
                preview_frame_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
                self.preview_frame.configure(bg=preview_frame_bg, highlightbackground=colors.border)
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'preview_label_path') and self.preview_label_path:
            try:
                preview_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.preview_label_path.configure(bg=preview_frame_bg, fg=colors.preview_link)
                # Update hover handlers to use current theme colors
                # Unbind old handlers first
                self.preview_label_path.unbind('<Enter>')
                self.preview_label_path.unbind('<Leave>')
                # Bind new handlers with current theme colors
                self.preview_label_path.bind('<Enter>', lambda e: self.preview_label_path.config(fg=colors.preview_link_hover))
                self.preview_label_path.bind('<Leave>', lambda e: self.preview_label_path.config(fg=colors.preview_link))
            except (TclError, AttributeError):
                pass
        
        # Update warning labels - these are in main_frame, so use bg (app background)
        warning_attrs = ['format_conversion_warning_label', 'ogg_warning_label', 'wav_warning_label']
        for attr in warning_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        widget.configure(bg=colors.bg, fg=colors.warning)
                    except (TclError, AttributeError):
                        pass
        
        # Update checkboxes in settings section - dark mode uses bg, light mode uses select_bg
        checkbox_attrs = [
            'skip_postprocessing_check', 'download_cover_art_check',
            'create_playlist_check', 'download_discography_check'
        ]
        checkbox_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        for attr in checkbox_attrs:
            if hasattr(self, attr):
                widget = getattr(self, attr)
                if widget:
                    try:
                        widget.configure(
                            bg=checkbox_bg,
                            fg=colors.fg,
                            selectcolor=checkbox_bg,
                            activebackground=checkbox_bg,
                            activeforeground=colors.fg
                        )
                    except (TclError, AttributeError):
                        pass
        
        # Update checkboxes in log section - dark mode uses bg, light mode uses entry_bg (#F5F5F5)
        # Note: This is handled in the log_frame section above, but keeping this for any other log checkboxes
        # The word_wrap_toggle and debug_toggle are already updated above with entry_bg in light mode
        
        # Update search frame and widgets
        if hasattr(self, 'search_frame') and self.search_frame:
            try:
                self.search_frame.configure(bg=colors.select_bg, highlightbackground=colors.border)
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'search_entry') and self.search_entry:
            try:
                self.search_entry.configure(
                    bg=colors.entry_bg,
                    fg=colors.entry_fg,
                    insertbackground=colors.fg,
                    highlightbackground=colors.border,
                    highlightcolor=colors.accent
                )
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'search_count_label') and self.search_count_label:
            try:
                self.search_count_label.configure(bg=colors.select_bg, fg=colors.disabled_fg)
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'search_close_btn') and self.search_close_btn:
            try:
                self.search_close_btn.configure(bg=colors.select_bg, fg=colors.disabled_fg)
            except (TclError, AttributeError):
                pass
        
        # Update log text widget - dark mode uses bg, light mode uses select_bg (white)
        if hasattr(self, 'log_text') and self.log_text:
            try:
                log_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.log_text.configure(
                    bg=log_bg,
                    fg=colors.fg,
                    insertbackground=colors.fg
                )
            except (TclError, AttributeError):
                pass
        
        # Update scrollbars: use default style in light mode, custom dark style in dark mode
        scrollbar_style = 'TScrollbar' if self.current_theme == 'light' else 'Dark.Vertical.TScrollbar'
        if hasattr(self, 'url_scrollbar') and self.url_scrollbar:
            try:
                # Force complete style refresh by temporarily setting to default, then to target style
                # This ensures no cached properties from previous theme remain
                current_style = self.url_scrollbar.cget('style')
                if current_style != scrollbar_style:
                    # Only update if style actually changed
                    self.url_scrollbar.configure(style='TScrollbar')  # Reset to base
                    self.root.update_idletasks()  # Force update
                    self.url_scrollbar.configure(style=scrollbar_style)  # Apply new style
            except (TclError, AttributeError):
                pass
        
        if hasattr(self, 'log_scrollbar') and self.log_scrollbar:
            try:
                # Force complete style refresh by temporarily setting to default, then to target style
                current_style = self.log_scrollbar.cget('style')
                if current_style != scrollbar_style:
                    # Only update if style actually changed
                    self.log_scrollbar.configure(style='TScrollbar')  # Reset to base
                    self.root.update_idletasks()  # Force update
                    self.log_scrollbar.configure(style=scrollbar_style)  # Apply new style
            except (TclError, AttributeError):
                pass
        
        # Update preview frame and labels
        if hasattr(self, 'preview_label_path') and self.preview_label_path:
            try:
                # Find parent preview frame
                parent = self.preview_label_path.master
                if parent:
                    preview_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                    parent.configure(bg=preview_frame_bg, highlightbackground=colors.border)
                preview_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
                self.preview_label_path.configure(bg=preview_frame_bg, fg=colors.preview_link)
                # Update hover handlers to use current theme colors
                self.preview_label_path.unbind('<Enter>')
                self.preview_label_path.unbind('<Leave>')
                self.preview_label_path.bind('<Enter>', lambda e: self.preview_label_path.config(fg=colors.preview_link_hover))
                self.preview_label_path.bind('<Leave>', lambda e: self.preview_label_path.config(fg=colors.preview_link))
            except (TclError, AttributeError):
                pass
    
    def _rebuild_settings_menu(self):
        """Rebuild settings menu to reflect current theme."""
        self.settings_menu = None  # Force recreation on next access
    
    def set_icon(self):
        """Set the custom icon for the window from icon.ico."""
        if not hasattr(self, 'root') or not self.root:
            return
        
        # Use icon_dir (which handles launcher mode)
        icon_path = getattr(self, 'icon_dir', self.script_dir) / "icon.ico"
        
        try:
            if icon_path.exists():
                icon_path_str = str(icon_path.resolve())  # Use absolute path
                
                # Method 1: iconbitmap - sets title bar icon (MUST be called first)
                try:
                    self.root.iconbitmap(default=icon_path_str)
                except (TclError, OSError):
                    # If iconbitmap fails, try without default parameter
                    try:
                        self.root.iconbitmap(icon_path_str)
                    except (TclError, OSError):
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
                except (OSError, IOError, ImportError):
                    # PIL not available or image file error
                    pass
                
                # Method 3: Windows API - force set both title bar and taskbar icons
                if sys.platform == 'win32':
                    try:
                        import ctypes
                        from ctypes import wintypes
                        
                        # Wait for window to be fully created
                        self.root.update_idletasks()
                        self.root.update()
                        
                        # Get window handle - winfo_id() returns the HWND on Windows
                        hwnd = self.root.winfo_id()
                        if hwnd:
                            # Constants
                            LR_LOADFROMFILE = 0x0010
                            IMAGE_ICON = 1
                            WM_SETICON = 0x0080
                            ICON_SMALL = 0  # Title bar icon (16x16)
                            ICON_BIG = 1    # Taskbar icon (32x32)
                            
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
                                SendMessageW = ctypes.windll.user32.SendMessageW
                                SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                                SendMessageW.restype = wintypes.LPARAM
                                
                                # Set both small (title bar) and big (taskbar) icons
                                SendMessageW(hwnd, WM_SETICON, ICON_SMALL, icon_handle)
                                SendMessageW(hwnd, WM_SETICON, ICON_BIG, icon_handle)
                                
                                # Force window to redraw
                                self.root.update_idletasks()
                    except (OSError, AttributeError, ctypes.ArgumentError):
                        # Silently fail - other methods should still work
                        pass
        except (OSError, IOError, AttributeError):
            # If icon setting fails, just continue without icon
            pass
    
    def _get_settings_file(self):
        """Get the path to the settings file."""
        return self.script_dir / "settings.json"
    
    def _migrate_old_settings(self):
        """Migrate old individual setting files to unified settings.json."""
        settings = {}
        migrated = False
        
        # Quick check: if no old files exist, skip migration entirely
        old_files = [
            "folder_structure_default.txt",
            "last_download_path.txt",
            "audio_format_default.txt",
            "audio_quality_default.txt",
            "album_art_visible.txt"
        ]
        # Check if any old files exist (single directory listing is faster than multiple exists() calls)
        has_old_files = any((self.script_dir / f).exists() for f in old_files)
        if not has_old_files:
            return  # No migration needed
        
        # Migrate folder structure
        old_file = self.script_dir / "folder_structure_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r', encoding='utf-8') as f:
                    value = f.read().strip()
                    if value in ["1", "2", "3", "4", "5"]:
                        settings["folder_structure"] = value
                        migrated = True
            except (IOError, OSError, UnicodeDecodeError):
                pass
        
        # Migrate download path
        old_file = self.script_dir / "last_download_path.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r', encoding='utf-8') as f:
                    path = f.read().strip()
                    if path and Path(path).exists():
                        settings["download_path"] = path
                        migrated = True
            except (IOError, OSError, UnicodeDecodeError):
                pass
        
        # Migrate audio format
        old_file = self.script_dir / "audio_format_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r', encoding='utf-8') as f:
                    value = f.read().strip()
                    if value in ["mp3", "flac", "ogg", "wav"]:
                        settings["audio_format"] = value
                        migrated = True
            except (IOError, OSError, UnicodeDecodeError):
                pass
        
        # Migrate audio quality
        old_file = self.script_dir / "audio_quality_default.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r', encoding='utf-8') as f:
                    value = f.read().strip()
                    if value in ["128 kbps", "192 kbps", "256 kbps", "320 kbps", "lossless", "best"]:
                        settings["audio_quality"] = value
                        migrated = True
            except (IOError, OSError, UnicodeDecodeError):
                pass
        
        # Migrate album art visibility (old boolean format)
        old_file = self.script_dir / "album_art_visible.txt"
        if old_file.exists():
            try:
                with open(old_file, 'r', encoding='utf-8') as f:
                    value = f.read().strip().lower()
                    # Migrate to new mode format
                    settings["album_art_mode"] = "album_art" if (value == "true") else "hidden"
                    migrated = True
            except (IOError, OSError, UnicodeDecodeError):
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
    
    def _load_settings(self, use_cache=True):
        """Load all settings from settings.json file.
        
        Args:
            use_cache: If True and settings are already cached, return cached version.
        """
        # Return cached settings if available and cache is enabled
        if use_cache and hasattr(self, '_cached_settings'):
            return self._cached_settings
        
        settings_file = self._get_settings_file()
        settings = {}
        
        # Load from unified settings file
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
                # Settings file is corrupted or unreadable - use defaults
                settings = {}
        else:
            # If settings.json doesn't exist, try to migrate old settings
            self._migrate_old_settings()
            # Try loading again after migration
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
                    # Settings file is corrupted or unreadable - use defaults
                    settings = {}
        
        # Cache the settings if we have an instance
        if hasattr(self, 'root'):
            self._cached_settings = settings
        
        return settings
    
    def _save_settings(self, settings=None, debounce=False):
        """Save all settings to settings.json file.
        
        Args:
            settings: Optional settings dict to save. If None, collects from UI.
            debounce: If True, debounce the save operation to batch rapid changes.
        """
        if debounce:
            # Cancel any pending save
            if hasattr(self, '_settings_save_timer') and self._settings_save_timer:
                self._cancel_timer(self._settings_save_timer)
            
            # Schedule debounced save
            def do_save():
                self._settings_save_timer = None
                self._save_settings(settings, debounce=False)
            
            self._settings_save_timer = self._schedule_timer(self.SETTINGS_SAVE_DEBOUNCE_MS, do_save)
            return
        
        # Clear cache when saving to ensure fresh data on next load
        if hasattr(self, '_cached_settings'):
            delattr(self, '_cached_settings')
        
        if settings is None:
            # Get current settings from UI
            structure_choice = self._extract_structure_choice(self.folder_structure_var.get()) or self.DEFAULT_STRUCTURE
            # Format custom structures as string, keep standard as key
            if isinstance(structure_choice, list):
                folder_structure = self._format_custom_structure(structure_choice)
            else:
                folder_structure = structure_choice
            # Handle template-based structures in save
            structure_choice = self._extract_structure_choice(self.folder_structure_var.get()) or self.DEFAULT_STRUCTURE
            if isinstance(structure_choice, dict) and "template" in structure_choice:
                # Template-based structure
                folder_structure = self._format_custom_structure_template(structure_choice)
            elif isinstance(structure_choice, list):
                # Old format structure
                folder_structure = self._format_custom_structure(structure_choice)
            else:
                # Standard structure
                folder_structure = structure_choice
            
            settings = {
                "folder_structure": folder_structure,
                "download_path": self.path_var.get(),
                "audio_format": self.format_var.get(),
                "track_numbering": self.numbering_var.get(),
                "custom_filename_formats": self.custom_filename_formats if hasattr(self, 'custom_filename_formats') else [],
                "custom_structure_templates": self.custom_structure_templates if hasattr(self, 'custom_structure_templates') else [],
                "skip_postprocessing": self.skip_postprocessing_var.get(),
                "create_playlist": self.create_playlist_var.get(),
                "download_cover_art": self.download_cover_art_var.get(),
                # download_discography is intentionally not saved - always defaults to off
                "album_art_mode": self.album_art_mode,
                "word_wrap": self.word_wrap_var.get() if hasattr(self, 'word_wrap_var') else False,
                "auto_check_updates": self.auto_check_updates_var.get() if hasattr(self, 'auto_check_updates_var') else True,
                "split_album_artist_display": self.split_album_artist_display_var.get() if hasattr(self, 'split_album_artist_display_var') else "bandcamp_default",
                "skip_mp3_reencode": self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True,
                "custom_structures": (self.custom_structures if hasattr(self, 'custom_structures') and self.custom_structures else []),
                "custom_structure_templates": (self.custom_structure_templates if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates else []),
                "theme": self.current_theme if hasattr(self, 'current_theme') else 'dark'
            }
        
        settings_file = self._get_settings_file()
        try:
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except (IOError, OSError, PermissionError):
            # Settings file cannot be written - log silently (non-critical)
            pass
    
    def get_default_preference(self):
        """Load saved folder structure preference, default to 4 if not found."""
        settings = self._load_settings()
        folder_structure = settings.get("folder_structure", self.DEFAULT_STRUCTURE)
        if folder_structure in ["1", "2", "3", "4", "5"]:
            return folder_structure
        # Check if it's a custom structure (saved as formatted string)
        # We'll handle this in update_structure_display
        return self.DEFAULT_STRUCTURE
    
    def save_default_preference(self, choice):
        """Save folder structure preference."""
        # If choice is a list (custom structure), save as formatted string
        # Otherwise save as key
        if isinstance(choice, list):
            # Save the formatted string
            formatted = self._format_custom_structure(choice)
            settings = self._load_settings()
            settings["folder_structure"] = formatted
            self._save_settings(settings)
        else:
            # Standard structure - save the key
            self._save_settings()
        return True
    
    def _load_custom_structures(self, settings=None):
        """Load saved custom folder structures from settings.
        Normalizes old format (list of strings) to new format (list of dicts).
        Also loads template-based structures if they exist.
        
        Args:
            settings: Optional pre-loaded settings dict to avoid re-reading file.
        """
        if settings is None:
            settings = self._load_settings()
        custom_structures = settings.get("custom_structures", [])
        # Validate: ensure it's a list
        if isinstance(custom_structures, list):
            # Filter out invalid entries and normalize
            valid_structures = []
            for structure in custom_structures:
                if isinstance(structure, list) and len(structure) > 0:
                    # Normalize to new format
                    normalized = self._normalize_structure(structure)
                    if normalized:
                        # Validate all fields are valid options
                        valid = True
                        all_fields = ["Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
                        for level in normalized:
                            for field in level.get("fields", []):
                                if field not in all_fields:
                                    valid = False
                                    break
                            if not valid:
                                break
                        if valid:
                            valid_structures.append(normalized)
            return valid_structures
        return []
    
    def _load_custom_structure_templates(self, settings=None):
        """Load saved custom folder structure templates from settings.
        New template-based format.
        
        Args:
            settings: Optional pre-loaded settings dict to avoid re-reading file.
        """
        if settings is None:
            settings = self._load_settings()
        custom_templates = settings.get("custom_structure_templates", [])
        if isinstance(custom_templates, list):
            valid_templates = []
            for template_data in custom_templates:
                if isinstance(template_data, dict) and "template" in template_data:
                    template = template_data.get("template", "").strip()
                    if template:
                        valid_templates.append(template_data)
            return valid_templates
        return []
    
    def _save_custom_structures(self):
        """Save custom folder structures to settings."""
        self._save_settings()
    
    # ============================================================================
    # FILENAME FORMAT CUSTOMIZATION (NEW - SEPARATE SYSTEM)
    # ============================================================================
    def _load_custom_filename_formats(self, settings=None):
        """Load saved custom filename formats from settings.
        Migrates old format (fields/separators) to new format (template strings).
        
        Args:
            settings: Optional pre-loaded settings dict to avoid re-reading file.
        """
        if settings is None:
            settings = self._load_settings()
        custom_formats = settings.get("custom_filename_formats", [])
        # Validate: ensure it's a list
        if isinstance(custom_formats, list):
            # Filter out invalid entries and migrate to template format
            valid_formats = []
            for format_data in custom_formats:
                if isinstance(format_data, dict):
                    # Check if it's new template format
                    if "template" in format_data:
                        # Already in template format
                        template = format_data.get("template", "")
                        if template:
                            # Remove curly brackets if present (migrate old format)
                            import re
                            # Replace {tag} with tag
                            template = re.sub(r'\{([^}]+)\}', r'\1', template)
                            valid_formats.append({"template": template})
                    # Check if it's old format (fields/separators) - migrate it
                    elif "fields" in format_data:
                        # Migrate old format to template
                        template = self._migrate_format_to_template(format_data)
                        if template:
                            valid_formats.append({"template": template})
            return valid_formats
        return []
    
    def _save_custom_filename_formats(self):
        """Save custom filename formats to settings."""
        self._save_settings()
    
    def _migrate_format_to_template(self, format_data):
        """Migrate old format (fields/separators) to template string.
        
        Args:
            format_data: Dict with "fields" and "separators"
            
        Returns:
            Template string like "{01}. {Track}" or None if invalid
        """
        if not format_data or not isinstance(format_data, dict):
            return None
        
        fields = format_data.get("fields", [])
        separators = format_data.get("separators", [])
        
        if not fields:
            return None
        
        # Build template string (no curly brackets)
        result_parts = []
        
        # Add prefix separator (before first field)
        prefix_sep = separators[0] if separators and len(separators) > 0 else ""
        if prefix_sep and prefix_sep != "None":
            result_parts.append(prefix_sep)
        
        # Add fields with between separators
        for i, field in enumerate(fields):
            # Use field name directly (no curly brackets)
            result_parts.append(field)
            
            # Add between separator (after each field except last)
            if i < len(fields) - 1:
                between_idx = i + 1
                between_sep = separators[between_idx] if between_idx < len(separators) else " "
                if between_sep == "None" or not between_sep:
                    between_sep = " "
                result_parts.append(between_sep)
        
        # Add suffix separator (after last field)
        suffix_idx = len(fields)
        suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
        if suffix_sep and suffix_sep != "None":
            result_parts.append(suffix_sep)
        
        return "".join(result_parts)
    
    def _normalize_filename_format(self, format_data):
        """Normalize filename format to ensure consistent structure.
        
        Args:
            format_data: Dict with "template" string
            
        Returns:
            Normalized format dict with "template" string
        """
        if not format_data or not isinstance(format_data, dict):
            return None
        
        import copy
        normalized = copy.deepcopy(format_data)
        
        # Ensure template exists
        if "template" not in normalized:
            return None
        
        template = normalized.get("template", "").strip()
        if not template:
            return None
        
        normalized["template"] = template
        return normalized
    
    def _format_custom_filename(self, format_data):
        """Format a custom filename format as display string.
        
        Args:
            format_data: Dict with "template" string
            
        Returns:
            Template string (for display in dropdown)
        """
        if not format_data:
            return ""
        
        normalized = self._normalize_filename_format(format_data)
        if not normalized:
            return ""
        
        return normalized.get("template", "")
    
    def _normalize_structure(self, structure):
        """Convert old format (list of strings) to new format (list of dicts with fields and separators).
        Also handles new format (returns as-is if already normalized).
        Old: ["Artist", "Album", "Year"]
        New: [{"fields": ["Artist"], "separators": []}, {"fields": ["Album"], "separators": []}, {"fields": ["Year"], "separators": []}]
        """
        if not structure:
            return []
        
        normalized = []
        import copy
        for item in structure:
            if isinstance(item, dict) and "fields" in item:
                # Already in new format, but ensure separators list exists
                # Use deep copy to prevent modifying original structure
                normalized_item = copy.deepcopy(item)
                if "separator" in normalized_item:
                    # Convert old single separator to separators list
                    sep = normalized_item.pop("separator")
                    normalized_item["separators"] = [sep] if sep else []
                elif "separators" not in normalized_item:
                    normalized_item["separators"] = []
                normalized.append(normalized_item)
            elif isinstance(item, str):
                # Old format: single string field
                normalized.append({"fields": [item], "separators": []})
            elif isinstance(item, list):
                # Could be old format list of strings, treat as single field
                if item and isinstance(item[0], str):
                    normalized.append({"fields": [item[0]], "separators": []})
        
        return normalized
    
    def _format_custom_structure(self, structure):
        """Format a custom structure as display string.
        Supports both old format (list of strings) and new format (list of dicts).
        Old: ["Artist", "Year", "Album"] -> "Artist / Year / Album"
        New: [{"fields": ["Year"], "separators": []}, {"fields": ["Year", "Album"], "separators": ["-"]}] -> "Year / Year - Album"
        Handles prefix, between-field, and suffix separators correctly.
        """
        if not structure:
            return ""
        
        # Normalize to new format
        normalized = self._normalize_structure(structure)
        if not normalized:
            return ""
        
        # Build display string for each level
        level_strings = []
        for level in normalized:
            fields = level.get("fields", [])
            separators = level.get("separators", [])
            
            if not fields:
                continue
            
            # Build level string with prefix, between, and suffix separators (same logic as preview)
            result_parts = []
            
            # Add prefix separator (before first field)
            prefix_sep = separators[0] if separators and len(separators) > 0 else ""
            if prefix_sep and prefix_sep != "None":
                result_parts.append(prefix_sep)
            
            # Add fields with between separators
            for i, field in enumerate(fields):
                result_parts.append(field)
                
                # Add between separator (after each field except last)
                if i < len(fields) - 1:
                    between_idx = i + 1  # separators[1] after first field, separators[2] after second, etc.
                    between_sep = separators[between_idx] if between_idx < len(separators) else "-"
                    if between_sep == "None" or not between_sep:
                        between_sep = " "  # Default to space if None
                    result_parts.append(between_sep)
            
            # Add suffix separator (after last field)
            suffix_idx = len(fields)  # separators[n] where n = number of fields
            suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
            if suffix_sep and suffix_sep != "None":
                result_parts.append(suffix_sep)
            
            if result_parts:
                level_strings.append("".join(result_parts))
        
        return " / ".join(level_strings)
    
    def _parse_folder_template(self, template):
        """Parse folder template string to extract tags, level separators, and literal text.
        
        Args:
            template: Template string like "Artist / Album - Year" where "/" is level separator
            
        Returns:
            List of level parts, where each level is a list of (type, value) tuples
            Example: [[('tag', 'Artist')], [('tag', 'Album'), ('literal', ' - '), ('tag', 'Year')]]
        """
        if not template:
            return []
        
        import re
        levels = []
        
        # Normalize both "/" and "\" to "/" for splitting (but preserve original in display)
        # We'll treat both "/" and "\" as level separators
        # Replace "\" with "/" for parsing, but we'll handle both in the original template
        normalized_template = template.replace('\\', '/')
        level_strings = normalized_template.split('/')
        
        for level_str in level_strings:
            level_str = level_str.strip()
            if not level_str:
                continue
            
            # Parse this level for tags and literals (similar to filename parsing)
            parts = []
            
            # Sort tag names by length (longest first) to match "Album Artist" before "Album"
            tag_names_sorted = sorted(self.FOLDER_TAG_NAMES, key=len, reverse=True)
            
            # Build regex pattern for whole word matching
            pattern_parts = []
            for tag_name in tag_names_sorted:
                escaped = re.escape(tag_name)
                if ' ' in tag_name:
                    # Multi-word tags like "Album Artist"
                    pattern_parts.append(rf'\b{escaped}\b')
                else:
                    # Single word tags
                    pattern_parts.append(rf'\b{escaped}\b')
            
            # Combine patterns with alternation
            pattern = '|'.join(pattern_parts)
            
            # Find all matches
            all_matches = list(re.finditer(pattern, level_str, re.IGNORECASE))
            
            # Filter out overlapping matches (prefer longer matches)
            valid_matches = []
            used_ranges = []
            for match in sorted(all_matches, key=lambda m: (m.end() - m.start(), m.start()), reverse=True):
                start, end = match.span()
                # Check if this range overlaps with any already used
                overlaps = False
                for used_start, used_end in used_ranges:
                    if not (end <= used_start or start >= used_end):
                        overlaps = True
                        break
                if not overlaps:
                    valid_matches.append(match)
                    used_ranges.append((start, end))
            
            # Sort matches by position
            valid_matches.sort(key=lambda m: m.start())
            
            last_end = 0
            for match in valid_matches:
                # Add literal text before this tag
                if match.start() > last_end:
                    literal = level_str[last_end:match.start()]
                    if literal:
                        parts.append(('literal', literal))
                
                # Add the tag
                tag_name = match.group(0)  # The matched text
                parts.append(('tag', tag_name))
                
                last_end = match.end()
            
            # Add remaining literal text
            if last_end < len(level_str):
                literal = level_str[last_end:]
                if literal:
                    parts.append(('literal', literal))
            
            if parts:
                levels.append(parts)
        
        return levels
    
    def _migrate_structure_to_template(self, structure):
        """Migrate old structure format to template string.
        
        Args:
            structure: Old format list like [{"fields": ["Artist"]}, {"fields": ["Album"]}]
            
        Returns:
            Template string like "Artist / Album"
        """
        if not structure:
            return ""
        
        normalized = self._normalize_structure(structure)
        if not normalized:
            return ""
        
        level_strings = []
        for level in normalized:
            fields = level.get("fields", [])
            separators = level.get("separators", [])
            
            if not fields:
                continue
            
            # Build level string with prefix, between, and suffix separators
            result_parts = []
            
            # Add prefix separator (before first field)
            prefix_sep = separators[0] if separators and len(separators) > 0 else ""
            if prefix_sep and prefix_sep != "None":
                result_parts.append(prefix_sep)
            
            # Add fields with between separators
            for i, field in enumerate(fields):
                result_parts.append(field)
                
                # Add between separator (after each field except last)
                if i < len(fields) - 1:
                    between_idx = i + 1
                    between_sep = separators[between_idx] if between_idx < len(separators) else " "
                    if between_sep == "None" or not between_sep:
                        between_sep = " "  # Default to space if None
                    result_parts.append(between_sep)
            
            # Add suffix separator (after last field)
            suffix_idx = len(fields)
            suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
            if suffix_sep and suffix_sep != "None":
                result_parts.append(suffix_sep)
            
            if result_parts:
                level_strings.append("".join(result_parts))
        
        return " / ".join(level_strings)
    
    def _generate_path_from_template(self, template, metadata=None, preview_mode=False):
        """Generate folder path from template string.
        
        Args:
            template: Template string like "Artist / Album - Year"
            metadata: Dict with metadata values (artist, album, etc.)
            preview_mode: If True, use field names for preview; if False, use actual values
            
        Returns:
            List of folder path parts (for yt-dlp template generation)
        """
        if not template:
            return []
        
        # Parse template into levels
        levels = self._parse_folder_template(template)
        if not levels:
            return []
        
        # Default metadata if not provided
        if metadata is None:
            metadata = {}
        
        # Field to yt-dlp template mapping
        field_templates = {
            "Artist": "%(artist)s",
            "Album": "%(album)s",
            "Year": "%(release_date>%Y)s",
            "Genre": "%(genre)s",
            "Label": "%(publisher)s",
            "Album Artist": "%(album_artist)s",
            "Catalog Number": "%(catalog_number)s"
        }
        
        # Field to preview value mapping (for modal preview - show field names)
        field_preview = {
            "Artist": "Artist",
            "Album": "Album",
            "Year": "Year",
            "Genre": "Genre",
            "Label": "Label",
            "Album Artist": "Album Artist",
            "Catalog Number": "Catalog Number"
        }
        
        # Field to actual value mapping (for main preview with real data)
        # Extract year properly
        year_str = "Year"
        if metadata.get("year"):
            year_str = str(metadata.get("year"))
        elif metadata.get("date"):
            date_val = metadata.get("date")
            if isinstance(date_val, str) and len(date_val) >= 4:
                year_str = date_val[:4]
        
        field_values = {
            "Artist": self.sanitize_filename(metadata.get("artist", "")) or "Artist",
            "Album": self.sanitize_filename(metadata.get("album", "")) or "Album",
            "Year": year_str,
            "Genre": self.sanitize_filename(metadata.get("genre", "")) or "Genre",
            "Label": self.sanitize_filename(metadata.get("label") or metadata.get("publisher", "")) or "Label",
            "Album Artist": self.sanitize_filename(metadata.get("album_artist") or metadata.get("albumartist", "")) or "Album Artist",
            "Catalog Number": self.sanitize_filename(metadata.get("catalog_number") or metadata.get("catalognumber", "")) or "Catalog Number"
        }
        
        path_parts = []
        for level in levels:
            # Build template parts for this level
            template_parts = []
            preview_parts = []
            
            for part_type, part_value in level:
                if part_type == 'tag':
                    # Replace tag with yt-dlp template or preview value
                    if preview_mode:
                        # For modal preview, use field names; for main preview, use actual values
                        # Check if metadata has real values (not just placeholders)
                        if metadata and any(metadata.get(k) not in [None, "", "Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"] for k in ["artist", "album", "year", "genre", "label", "album_artist", "catalog_number"]):
                            # Use actual values for main preview
                            value = field_values.get(part_value, part_value)
                        else:
                            # Use field names for modal preview
                            value = field_preview.get(part_value, part_value)
                        preview_parts.append(value)
                    else:
                        # For yt-dlp, use template format
                        yt_template = field_templates.get(part_value)
                        if yt_template:
                            template_parts.append(yt_template)
                else:
                    # Literal text - keep as-is
                    if preview_mode:
                        preview_parts.append(part_value)
                    else:
                        template_parts.append(part_value)
            
            if preview_mode:
                # For preview, join parts
                if preview_parts:
                    path_parts.append("".join(preview_parts))
            else:
                # For yt-dlp, join template parts
                if template_parts:
                    path_parts.append("".join(template_parts))
        
        return path_parts
    
    def _get_all_structure_options(self):
        """Get all folder structure options including custom structures."""
        # Start with standard options
        options = list(self.FOLDER_STRUCTURES.values())
        # Add custom structures (if they exist)
        if hasattr(self, 'custom_structures') and self.custom_structures:
            for structure in self.custom_structures:
                formatted = self._format_custom_structure(structure)
                if formatted and formatted not in options:
                    options.append(formatted)
        return options
    
    def _create_dark_menu(self, parent):
        """Create a themed menu with consistent styling."""
        colors = self.theme_colors
        menu = Menu(
            parent,
            tearoff=0,
            bg=colors.select_bg,
            fg=colors.fg,
            activebackground=colors.hover_bg,
            activeforeground='#FFFFFF' if self.current_theme == 'dark' else colors.fg,
            selectcolor=colors.accent,
            borderwidth=0,  # No border
            relief='flat',
            activeborderwidth=0  # No border on active items
        )
        return menu
    
    # ============================================================================
    # SHARED UTILITIES (Used by both folder structure and filename format systems)
    # ============================================================================
    def _create_dialog_base(self, title, width, height):
        """Create base dialog with common styling and centering.
        
        Args:
            title: Dialog title
            width: Dialog width in pixels
            height: Dialog height in pixels
            
        Returns:
            Configured Toplevel dialog
        """
        dialog = Toplevel(self.root)
        # Add leading space for nice spacing between icon and title text
        dialog.title(f" {title}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (width // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.resizable(False, False)
        
        # Configure dialog background with theme colors
        colors = self.theme_colors
        dialog.configure(bg=colors.bg)
        
        return dialog
    
    def _create_preview_frame(self, parent, wraplength=530, bg=None):
        """Create preview frame with common styling.
        
        Args:
            parent: Parent widget
            wraplength: Wraplength for preview text
            bg: Optional background color (defaults to theme-appropriate background)
            
        Returns:
            Tuple of (preview_frame, preview_text_label)
        """
        colors = self.theme_colors
        # Use provided bg, or default to theme-appropriate background
        if bg is None:
            # Default: use select_bg for light mode, bg for dark mode (matches dialog pattern)
            preview_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        else:
            preview_bg = bg
        
        preview_frame = Frame(parent, bg=preview_bg, relief='flat', bd=1, 
                             highlightbackground=colors.border, highlightthickness=1)
        preview_frame.pack(fill=X, pady=(0, 5))
        
        # Preview label prefix
        preview_label_prefix = Label(
            preview_frame,
            text="Preview:",
            font=("Consolas", 8),
            bg=preview_bg,
            fg=colors.fg,
            justify='left'
        )
        preview_label_prefix.grid(row=0, column=0, sticky=W, padx=(6, 0), pady=4)
        
        # Preview text
        preview_text = Label(
            preview_frame,
            text="",
            font=("Consolas", 8),
            bg=preview_bg,
            fg=colors.preview_link,
            wraplength=wraplength,
            justify='left',
            anchor='w'
        )
        preview_text.grid(row=0, column=1, sticky=W, padx=(0, 6), pady=4)
        preview_frame.columnconfigure(1, weight=1)
        
        return preview_frame, preview_text
    
    def _show_additional_settings(self):
        """Show Additional Settings dialog with split album artist display option."""
        dialog = self._create_dialog_base("Additional Settings", 580, 290)
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Main container with theme colors
        main_frame = Frame(dialog, bg=main_bg, padx=10, pady=10)
        main_frame.pack(fill=BOTH, expand=True)
        
        # Split Album Artist Display Panel
        split_album_panel = Frame(main_frame, bg=main_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        split_album_panel.pack(fill=X, pady=(0, 15))
        
        # Inner content frame for split album panel
        split_album_content = Frame(split_album_panel, bg=main_bg)
        split_album_content.pack(fill=X, padx=6, pady=(6, 6))
        
        split_album_label = Label(
            split_album_content,
            text="In case of Split Artist (Album and Track Artists differ):",
            font=("Segoe UI", 9),
            bg=main_bg,
            fg=colors.fg
        )
        split_album_label.pack(anchor=W, pady=(0, 5))
        
        # Dropdown for split album artist display (using same menubutton style)
        split_album_options = [
            "Show All Artists (Bandcamp Default)",
            "Use Track Artist",
            "Use Album Artist",
            "Use First Track Artist"
        ]
        split_album_values = [
            "bandcamp_default",
            "track_artist",
            "album_artist",
            "first_track_artist"
        ]
        
        # Create display mapping
        display_map = {
            "bandcamp_default": "Show All Artists (Bandcamp Default)",
            "track_artist": "Use Track Artist",
            "album_artist": "Use Album Artist",
            "first_track_artist": "Use First Track Artist"
        }
        
        split_album_var = StringVar(value=display_map.get(self.split_album_artist_display_var.get(), "Show All Artists (Bandcamp Default)"))
        
        # Update the actual setting when dropdown changes
        def on_split_album_change(value):
            # Find the corresponding value
            index = split_album_options.index(value)
            if index < len(split_album_values):
                # Update the internal setting
                self.split_album_artist_display_var.set(split_album_values[index])
                self.save_split_album_artist_display()
                # Update the dropdown display to show the selected option
                split_album_var.set(value)
                # Update preview in dialog (simulated split album)
                update_preview_in_dialog()
                # Also update main interface preview if it exists
                if hasattr(self, 'update_preview'):
                    self.update_preview()
        
        # Create and pack dropdown right after label (second in order)
        split_album_menubutton, split_album_menu = self._create_menubutton_with_menu(
            split_album_content,
            split_album_var,
            split_album_options,
            40,
            callback=on_split_album_change
        )
        split_album_menubutton.pack(anchor=W, padx=(15, 0), pady=(2, 4))
        
        # Note about how this works with Filename setting (inside split album panel)
        filename_note_label = Label(
            split_album_content,
            text="Note: Works in tandem with Filename setting. Only applies/previews if filename format includes \"Artist\".",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg,
            wraplength=550,
            justify='left'
        )
        filename_note_label.pack(anchor=W, pady=(4, 4))      
        
        # Preview section (inside split album panel)
        preview_frame, preview_text = self._create_preview_frame(split_album_content, wraplength=550, bg=main_bg)
        preview_frame.pack(fill=X, pady=(6, 0))
        
        # MP3 Skip Re-encoding Panel
        mp3_panel = Frame(main_frame, bg=main_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        mp3_panel.pack(fill=X, pady=(0, 15))
        
        # Inner content frame for MP3 panel
        mp3_content = Frame(mp3_panel, bg=main_bg)
        mp3_content.pack(fill=X, padx=6, pady=(6, 6))
        
        # MP3 skip re-encoding checkbox
        mp3_checkbox = Checkbutton(
            mp3_content,
            text="Skip re-encoding if bandcamp file is an MP3 (When using MP3 format)",
            variable=self.skip_mp3_reencode_var,
            command=self._on_skip_mp3_reencode_change,
            font=("Segoe UI", 9),
            bg=main_bg,
            fg=colors.fg,
            activebackground=main_bg,
            activeforeground=colors.fg,
            selectcolor=main_bg,
            anchor='w',
            justify='left',
            wraplength=550
        )
        mp3_checkbox.pack(anchor=W, pady=(0, 0))
        
        # Note explaining MP3 format behavior (similar to split artist note)
        mp3_note_label = Label(
            mp3_content,
            text="Note: When enabled, preserves source bitrate (varies by album). When disabled, always re-encodes to 128kbps.",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg,
            wraplength=550,
            justify='left'
        )
        mp3_note_label.pack(anchor=W, pady=(4, 0))
        
        def generate_split_album_preview():
            """Generate preview filename simulating a split album scenario."""
            # Get current filename format
            numbering_style = self.numbering_var.get()
            if numbering_style == "Original" or numbering_style == "None":
                return "Preview unavailable (Original filename format)"
            
            # Get format data
            format_data = None
            if numbering_style in self.FILENAME_FORMATS:
                format_data = self.FILENAME_FORMATS[numbering_style]
            else:
                if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
                    for custom_format in self.custom_filename_formats:
                        formatted = self._format_custom_filename(custom_format)
                        if formatted == numbering_style:
                            format_data = custom_format
                            break
            
            if not format_data:
                return "Preview unavailable"
            
            template = format_data.get("template", "")
            if not template:
                return "Preview unavailable"
            
            # Check if template includes "Artist"
            template_lower = template.lower()
            has_artist_tag = "artist" in template_lower
            
            if not has_artist_tag:
                return "Preview unavailable (Selected filename format doesn't contain artist)"
            
            # Check if we have real metadata or should use generic placeholders
            has_real_metadata = (
                self.album_info.get("artist") or 
                self.album_info.get("label") or 
                self.album_info.get("first_track_title") or
                self.album_info.get("album")
            )
            
            # Use real metadata if available, otherwise use generic placeholders
            if has_real_metadata:
                # Use real metadata from album_info
                example_label = self.sanitize_filename(self.album_info.get("label") or self.album_info.get("artist") or "Album Artist")
                first_track_title_raw = self.album_info.get("first_track_title") or "Track Title"
                
                # Extract track title (remove artist prefix if present)
                # Pattern: "Artist - Title" -> extract just "Title"
                if " - " in first_track_title_raw:
                    parts = first_track_title_raw.split(" - ", 1)
                    if len(parts) >= 2:
                        example_title = self.sanitize_filename(parts[1].strip())
                    else:
                        example_title = self.sanitize_filename(first_track_title_raw)
                else:
                    example_title = self.sanitize_filename(first_track_title_raw)
                
                if not example_title:
                    example_title = "Track Title"
                example_album = self.sanitize_filename(self.album_info.get("album")) or "Album"
                example_album_artist = self.sanitize_filename(self.album_info.get("label") or self.album_info.get("artist") or "Album Artist")
            else:
                # Use generic placeholders when no metadata
                example_label = "Album Artist"
                example_title = "Track Title"
                example_album = "Album"
                example_album_artist = "Album Artist"
            
            # Try to extract track artists from track titles and album title if available
            example_track_artists = set()
            example_first_track_artist = "Track Artist"
            
            # Method 1: Check if album title contains multiple artists (e.g., "DISTURD / 惡AI意")
            album_title = self.album_info.get("album") or ""
            if album_title and (" / " in album_title or "⧸" in album_title):
                # Split by " / " or "⧸" to get multiple artists
                import re
                # Try both " / " and "⧸" separators
                if " / " in album_title:
                    artists = [a.strip() for a in album_title.split(" / ")]
                elif "⧸" in album_title:
                    artists = [a.strip() for a in album_title.split("⧸")]
                else:
                    artists = []
                
                # Filter out parts that look like album titles (too long, contain quotes, etc.)
                for artist in artists:
                    # Remove common album title suffixes like "split 12"", "split EP", etc.
                    artist_clean = re.sub(r'\s*[-–—]\s*["\'].*$', '', artist)  # Remove "- "title"" suffix
                    artist_clean = re.sub(r'\s+split\s+\d+["\']?$', '', artist_clean, flags=re.IGNORECASE)
                    artist_clean = artist_clean.strip()
                    
                    # Only use if it looks like an artist name (reasonable length, not empty)
                    if artist_clean and len(artist_clean) < 50 and len(artist_clean) > 1:
                        example_track_artists.add(artist_clean)
                        if not example_first_track_artist or example_first_track_artist == "Track Artist":
                            example_first_track_artist = artist_clean
            
            # Method 2: Check if we can extract track artists from track titles
            # Split albums often have format: "Track Artist - Track Title"
            first_track_title_raw = self.album_info.get("first_track_title")
            if first_track_title_raw:
                # Try to extract artist from "Artist - Title" pattern
                parts = first_track_title_raw.split(" - ", 1)
                if len(parts) >= 2:
                    potential_artist = parts[0].strip()
                    # Only use if it looks like an artist name (not too long, not just numbers)
                    if potential_artist and len(potential_artist) < 50 and not potential_artist.isdigit():
                        example_first_track_artist = potential_artist
                        example_track_artists.add(potential_artist)
            
            # If we only have one artist, add a second generic one for split album simulation
            if len(example_track_artists) == 1:
                example_track_artists.add("Track Artist 2")
            elif len(example_track_artists) == 0:
                # No artists extracted, use generic placeholders
                example_track_artists = {"Track Artist", "Track Artist 2"}
                example_first_track_artist = "Track Artist"
            
            # Get current split album setting
            current_setting = self.split_album_artist_display_var.get()
            
            # Special handling for "bandcamp_default" - show original Bandcamp filename format
            if current_setting == "bandcamp_default":
                # Bandcamp default format: "Album Artist - Track Artist - Track Title"
                # But include track number prefix if the template has it
                track_number = self.album_info.get("first_track_number") or 1
                track_prefix = ""
                
                # Check if template contains track number tag (01 or 1)
                # Parse template to see if it starts with a track number tag
                import re
                # Check for "01." or "1." at the start
                if re.match(r'^01\.', template):
                    track_prefix = f"{track_number:02d}. "
                elif re.match(r'^1\.', template):
                    track_prefix = f"{track_number}. "
                # Check for "01 " or "1 " at the start
                elif re.match(r'^01\s', template):
                    track_prefix = f"{track_number:02d} "
                elif re.match(r'^1\s', template):
                    track_prefix = f"{track_number} "
                
                # Add extension
                format_val = self.format_var.get()
                base_format = self._extract_format(format_val)
                ext_map = {
                    "original": ".mp3",
                    "mp3": ".mp3",
                    "flac": ".flac",
                    "ogg": ".ogg",
                    "wav": ".wav"
                }
                ext = ext_map.get(base_format, ".mp3")
                
                # Return Bandcamp default format with optional track prefix: "01. Album Artist - Track Artist - Track Title"
                return f"{track_prefix}{example_label} - {example_first_track_artist} - {example_title}{ext}"
            
            # For other settings, format artist based on setting and apply to user's template
            formatted_artist = self._format_split_album_artist(
                example_first_track_artist,
                example_track_artists,
                setting=current_setting
            )
            
            # If "album_artist" setting returns None, use the album artist
            if formatted_artist is None:
                formatted_artist = example_album_artist
            
            # Build preview metadata (using real metadata if available, otherwise generic)
            preview_metadata = {
                "title": example_title,
                "artist": formatted_artist,
                "album": example_album,
                "year": "2024",
                "genre": "Genre",
                "label": example_label,
                "album_artist": example_album_artist,
                "catalog_number": "CAT001"
            }
            
            # Generate filename
            track_number = self.album_info.get("first_track_number") or 1
            generated_name = self._generate_filename_from_template(
                template, track_number, preview_metadata, preview_mode=False
            )
            
            if generated_name:
                # Add extension
                format_val = self.format_var.get()
                base_format = self._extract_format(format_val)
                ext_map = {
                    "original": ".mp3",
                    "mp3": ".mp3",
                    "flac": ".flac",
                    "ogg": ".ogg",
                    "wav": ".wav"
                }
                ext = ext_map.get(base_format, ".mp3")
                return f"{generated_name}{ext}"
            
            return "Preview unavailable"
        
        def update_preview_in_dialog():
            """Update preview in dialog - always simulates split album scenario."""
            # Generate preview with simulated split album
            preview_filename = generate_split_album_preview()
            preview_text.config(text=preview_filename)
        
        # Store reference to update function so it can be called when metadata changes
        # This allows the preview to update dynamically when URL metadata is fetched
        if not hasattr(self, '_additional_settings_dialogs'):
            self._additional_settings_dialogs = []
        dialog_ref = {'update_func': update_preview_in_dialog, 'dialog': dialog}
        self._additional_settings_dialogs.append(dialog_ref)
        
        # Clean up reference when dialog closes
        def on_dialog_close():
            if hasattr(self, '_additional_settings_dialogs'):
                self._additional_settings_dialogs = [d for d in self._additional_settings_dialogs if d['dialog'] != dialog]
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        # Initial preview update
        update_preview_in_dialog()
        
        # Close button
        button_frame = Frame(main_frame, bg=main_bg)
        button_frame.pack(fill=X, pady=(0, 0))
        
        close_btn = Button(
            button_frame,
            text="Close",
            command=dialog.destroy,
            bg=colors.accent,
            fg='#FFFFFF',
            font=("Segoe UI", 9),
            relief='flat',
            padx=20,
            pady=5,
            cursor='hand2'
        )
        close_btn.pack(side=RIGHT)
        
        # Bind Enter key to close
        dialog.bind('<Return>', lambda e: dialog.destroy())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
    
    def _create_menubutton_with_menu(self, parent, textvariable, values, width, callback=None):
        """Create a menubutton with menu, matching the structure menubutton style.
        
        Args:
            parent: Parent widget
            textvariable: StringVar to bind to
            values: List of string values for the menu
            width: Width of the menubutton
            callback: Optional callback function called when item is selected (receives selected value)
        
        Returns:
            Tuple of (menubutton, menu)
        """
        menubutton = ttk.Menubutton(
            parent,
            textvariable=textvariable,
            width=width,
            direction='below',
            style='Dark.TMenubutton'
        )
        
        menu = self._create_dark_menu(menubutton)
        menubutton['menu'] = menu
        
        # Track menu state for toggle behavior
        menu_open = False
        item_just_selected = False
        
        # Wrap callbacks to track when items are selected
        def wrap_callback(original_callback, value):
            def wrapped():
                nonlocal item_just_selected
                item_just_selected = True
                if original_callback:
                    original_callback(value)
                else:
                    textvariable.set(value)
            return wrapped
        
        # Build menu items with padding
        for value in values:
            # Add padding: left space + text + right spaces
            padded_label = f" {value}      "
            if callback:
                menu.add_command(
                    label=padded_label,
                    command=wrap_callback(callback, value)
                )
            else:
                menu.add_command(
                    label=padded_label,
                    command=wrap_callback(None, value)
                )
        
        def on_menu_post(event=None):
            nonlocal menu_open, item_just_selected
            menu_open = True
            item_just_selected = False  # Reset when menu opens
        
        def on_menu_unpost(event=None):
            nonlocal menu_open
            menu_open = False
        
        menu.bind('<<MenuSelect>>', on_menu_post)
        menu.bind('<<MenuUnpost>>', on_menu_unpost)
        
        # Periodic check function (defined after on_menu_post)
        def periodic_check():
            nonlocal menu_open
            if menu_open:
                # Flag says open - verify it's actually posted
                try:
                    menu.tk.call(menu, 'index', 'active')
                    # Menu is posted - flag is correct, check again soon
                    self.root.after(100, periodic_check)
                except:
                    # Menu is not posted - update flag
                    menu_open = False
        
        # Start periodic checking when menu opens
        original_on_menu_post = on_menu_post
        def on_menu_post_with_check(event=None):
            original_on_menu_post(event)
            # Start periodic checking
            self.root.after(100, periodic_check)
        
        menu.unbind('<<MenuSelect>>')
        menu.bind('<<MenuSelect>>', on_menu_post_with_check)
        
        # Detect when menu closes due to outside Click by monitoring root window focus/Clicks
        # Use a more aggressive approach: check immediately on any root interaction
        def detect_menu_close(event=None):
            nonlocal menu_open
            if menu_open:
                # Flag says menu is open - check immediately if it's actually still posted
                # Don't delay - check right now
                try:
                    menu.tk.call(menu, 'index', 'active')
                    # Menu is still posted - flag is correct, do nothing
                except:
                    # Menu is not posted - it closed, update flag immediately
                    menu_open = False
        
        # Bind to root window events that indicate menu might have closed
        # Focus-in on root: when root gets focus, menu might have closed
        self.root.bind('<FocusIn>', detect_menu_close, add=True)
        # Button-1 on root: when Clicking outside, menu might have closed
        def root_Click_handler(event):
            # Check immediately if Click is not on the menubutton or menu itself
            try:
                widget = event.widget
                # IMPORTANT: If Click is on menubutton, DON'T check - the button Click handler will handle it
                # Only check for Clicks outside the menubutton and menu
                if widget != menubutton and not str(widget).startswith(str(menu)):
                    detect_menu_close(event)
            except:
                pass
        
        self.root.bind('<Button-1>', root_Click_handler, add=True)
        
        # Also periodically check when flag says open (backup detection)
        def periodic_check():
            nonlocal menu_open
            if menu_open:
                # Flag says open - verify it's actually posted
                try:
                    menu.tk.call(menu, 'index', 'active')
                    # Menu is posted - flag is correct
                except:
                    # Menu is not posted - update flag
                    menu_open = False
            # Schedule next check (only if flag says open)
            if menu_open:
                self.root.after(100, periodic_check)
        
        # Start periodic checking when menu opens
        original_on_menu_post = on_menu_post
        def on_menu_post_with_check(event=None):
            original_on_menu_post(event)
            # Start periodic checking
            self.root.after(100, periodic_check)
        
        menu.unbind('<<MenuSelect>>')
        menu.bind('<<MenuSelect>>', on_menu_post_with_check)
        
        # Check menu state on Click - if open, close it; otherwise let default behavior open it
        # Known limitation: Tkinter's Menubutton doesn't reliably notify when menu closes from outside Click.
        # This causes a 2-Click requirement after closing menu by Clicking outside (flag gets stale).
        # This is a fundamental Tkinter limitation - the current implementation is the best we can achieve.
        def on_button_Click(event=None):
            nonlocal menu_open, item_just_selected
            if item_just_selected:
                # Menu was just closed via item selection - don't interfere, let default behavior open it
                item_just_selected = False
                return None  # Let default behavior handle it
            
            # Only close if we're CERTAIN menu is open (both flag and actual state must agree)
            # This prevents false positives that block menu opening
            flag_says_open = menu_open
            actual_state_open = False
            
            # Quick check of actual state
            try:
                menu.tk.call(menu, 'index', 'active')
                actual_state_open = True
            except:
                pass
            
            # Only close if BOTH say open - if either is uncertain, allow opening
            if flag_says_open and actual_state_open:
                # Both confirm menu is open - close it and prevent default posting
                self.root.focus_set()
                menu.unpost()
                menu_open = False
                return "break"  # Prevent default behavior (posting menu)
            else:
                # Not certain menu is open - always allow default behavior to open it
                # Update flag if actual state says closed
                if not actual_state_open:
                    menu_open = False
                return None  # Allow default behavior
        
        menubutton.bind('<Button-1>', on_button_Click, add=True)
        
        return menubutton, menu
    
    def _build_structure_menu(self, menu):
        """Build the structure menu with standard structures, separator, and custom structures (templates and old format)."""
        # Clear existing menu items
        menu.delete(0, END)
        
        # Add standard structures with padding on all sides to match combobox dropdowns
        for key in ["1", "2", "3", "4", "5"]:
            display_value = self.FOLDER_STRUCTURES[key]
            # Add padding: left space + text + right spaces (approximately 50px worth of spaces)
            # Using ~6-7 spaces for right padding to match left indentation visually
            padded_label = f" {display_value}      "  # Left space + text + right spaces
            menu.add_command(
                label=padded_label,
                command=lambda val=key: self._on_structure_menu_select(val)
            )
        
        # Add separator if there are custom structures (templates or old format)
        has_custom = False
        if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
            has_custom = True
        if hasattr(self, 'custom_structures') and self.custom_structures:
            has_custom = True
        
        if has_custom:
            menu.add_separator()
            
            # Add custom structures in order: old format first, then templates (newest at end)
            # Old format structures (will be migrated on use)
            if hasattr(self, 'custom_structures') and self.custom_structures:
                for structure in self.custom_structures:
                    formatted = self._format_custom_structure(structure)
                    if formatted:
                        padded_label = f" {formatted}      "  # Left space + text + right spaces
                        menu.add_command(
                            label=padded_label,
                            command=lambda s=structure: self._on_structure_menu_select(s)
                        )
            
            # Custom template structures (new format) - added after old format, so newest appear at end
            if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
                for template_data in self.custom_structure_templates:
                    formatted = self._format_custom_structure_template(template_data)
                    if formatted:
                        padded_label = f" {formatted}      "  # Left space + text + right spaces
                        menu.add_command(
                            label=padded_label,
                            command=lambda t=template_data: self._on_structure_menu_select(t)
                        )
    
    def _on_structure_menu_select(self, choice):
        """Handle structure menu item selection."""
        if isinstance(choice, str) and choice in ["1", "2", "3", "4", "5"]:
            # Standard structure - set display value
            display_value = self.FOLDER_STRUCTURES[choice]
            self.folder_structure_var.set(display_value)
        elif isinstance(choice, dict) and "template" in choice:
            # Custom template structure (new format) - set formatted string
            display_value = self._format_custom_structure_template(choice)
            self.folder_structure_var.set(display_value)
        else:
            # Custom structure (old format) - set formatted string
            display_value = self._format_custom_structure(choice)
            self.folder_structure_var.set(display_value)
        
        # Trigger the structure change handler
        self.on_structure_change()
    
    def _update_structure_dropdown(self):
        """Update the structure menu with current custom structures."""
        if not hasattr(self, 'structure_menu'):
            return
        # Rebuild the menu - use the rebuild function with tracking if it exists
        if hasattr(self, '_rebuild_structure_menu_with_tracking'):
            self._rebuild_structure_menu_with_tracking()
        else:
            self._build_structure_menu(self.structure_menu)
        # Update manage button state
        if hasattr(self, 'manage_btn'):
            has_custom = (hasattr(self, 'custom_structure_templates') and self.custom_structure_templates) or (hasattr(self, 'custom_structures') and self.custom_structures)
            colors = self.theme_colors
            disabled_color = colors.disabled_fg if self.current_theme == 'dark' else '#A0A0A0'
            if has_custom:
                self.manage_btn.config(fg=colors.disabled_fg, cursor='hand2')
                # Rebind events if they don't exist
                if not hasattr(self.manage_btn, '_bound'):
                    self.manage_btn.bind("<Button-1>", lambda e: self._show_manage_dialog())
                    self.manage_btn.bind("<Enter>", lambda e: self.manage_btn.config(fg=colors.hover_fg))
                    self.manage_btn.bind("<Leave>", lambda e: self.manage_btn.config(fg=colors.disabled_fg))
                    self.manage_btn._bound = True
            else:
                self.manage_btn.config(fg=disabled_color, cursor='arrow')
                # Unbind events when disabled
                try:
                    self.manage_btn.unbind("<Button-1>")
                    self.manage_btn.unbind("<Enter>")
                    self.manage_btn.unbind("<Leave>")
                    if hasattr(self.manage_btn, '_bound'):
                        delattr(self.manage_btn, '_bound')
                except:
                    pass
    
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
        """Load saved audio format preference, default to Original if not found."""
        settings = self._load_settings()
        format_val = settings.get("audio_format", self.DEFAULT_FORMAT)
        # Support old formats and convert to current dynamic format
        # Old formats: "mp3", "mp3 (128kbps)", "flac", "ogg", "wav"
        # New formats: "Original", "MP3 (varies)", "MP3 (128kbps)", "FLAC", "OGG", "WAV"
        base_format = self._extract_format(format_val)
        
        if base_format == "mp3":
            # Use current skip re-encode setting to determine label
            skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
            return "MP3 (varies)" if skip_mp3_reencode else "MP3 (128kbps)"
        elif base_format == "flac":
            return "FLAC"
        elif base_format == "ogg":
            return "OGG"
        elif base_format == "wav":
            return "WAV"
        elif format_val == "Original":
            return "Original"
        return self.DEFAULT_FORMAT
    
    def save_format(self):
        """Save audio format preference."""
        self._save_settings()
    
    def load_saved_album_art_state(self):
        """Load saved album art mode state, default to album_art if not found."""
        settings = self._load_settings()
        # Migrate old boolean to new mode enum
        old_visible = settings.get("album_art_visible")
        if old_visible is not None:
            # Migrate from old boolean format
            self.album_art_mode = "album_art" if old_visible else "hidden"
        else:
            # Use new mode format, default to "album_art"
            mode = settings.get("album_art_mode", "album_art")
            if mode in ["album_art", "bio_pic", "hidden"]:
                self.album_art_mode = mode
            else:
                self.album_art_mode = "album_art"
        # Apply state after UI is set up
        if self.album_art_mode != "album_art":
            self.root.after(100, self._apply_saved_album_art_state)
    
    def _apply_saved_album_art_state(self):
        """Apply saved album art state after UI is set up."""
        if self.album_art_mode == "hidden":
            if hasattr(self, 'album_art_frame'):
                self.album_art_frame.grid_remove()
            if hasattr(self, 'settings_frame'):
                self.settings_frame.grid_configure(columnspan=3)
            if hasattr(self, 'show_album_art_btn'):
                # Show the button by adding it back to grid
                self.show_album_art_btn.grid(row=0, column=2, sticky=E, padx=(4, 0), pady=1)
                self.show_album_art_btn.config(fg='#808080', cursor='hand2')
        else:
            # Album art or bio pic is visible, ensure eye icon is removed from grid
            if hasattr(self, 'album_art_frame'):
                self.album_art_frame.grid()
            if hasattr(self, 'settings_frame'):
                self.settings_frame.grid_configure(columnspan=2)
            if hasattr(self, 'show_album_art_btn'):
                self.show_album_art_btn.grid_remove()
            # Fetch appropriate image based on mode
            if self.album_art_mode == "bio_pic" and hasattr(self, 'current_bio_pic_url') and self.current_bio_pic_url:
                self.root.after(200, lambda: self.fetch_and_display_bio_pic(self.current_bio_pic_url))
    
    def save_album_art_state(self):
        """Save album art visibility state."""
        self._save_settings()
    
    def load_saved_numbering(self):
        """Load saved track numbering preference, default to Track if not found."""
        settings = self._load_settings()
        numbering_val = settings.get("track_numbering", self.DEFAULT_NUMBERING)
        
        # Check if it's "Original" (preserve original filenames)
        if numbering_val == "Original":
            return "Original"
        
        # Check if it's a default format
        valid_options = ["Track", "01. Track", "Artist - Track", "01. Artist - Track"]
        if numbering_val in valid_options:
            return numbering_val
        
        # Check if it's a custom format (match by formatted string)
        if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
            for custom_format in self.custom_filename_formats:
                formatted = self._format_custom_filename(custom_format)
                if formatted == numbering_val:
                    return numbering_val
        
        # If not found, return default
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
    
    def load_saved_auto_check_updates(self):
        """Load saved auto-check for updates preference, default to True if not found."""
        settings = self._load_settings()
        return settings.get("auto_check_updates", True)
    
    def load_saved_split_album_artist_display(self):
        """Load saved split album artist display preference, default to 'bandcamp_default' if not found."""
        settings = self._load_settings()
        return settings.get("split_album_artist_display", "bandcamp_default")
    
    def save_split_album_artist_display(self):
        """Save split album artist display preference."""
        self._save_settings()
    
    def load_saved_skip_mp3_reencode(self):
        """Load saved MP3 skip re-encoding preference, default to True if not found."""
        settings = self._load_settings()
        return settings.get("skip_mp3_reencode", True)  # Default to True
    
    def _get_format_menu_options(self):
        """Get format menu options with dynamic MP3 label based on skip re-encode setting."""
        skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
        mp3_label = "MP3 (varies)" if skip_mp3_reencode else "MP3 (128kbps)"
        return ["Original", mp3_label, "FLAC", "OGG", "WAV"]
    
    def _update_format_menu(self):
        """Update format menu with current options (for dynamic MP3 label)."""
        if not hasattr(self, 'format_menu'):
            return
        
        # Get current selection
        current_selection = self.format_var.get()
        
        # Normalize current selection to base format for comparison
        base_format = self._extract_format(current_selection)
        
        # Get new options
        new_options = self._get_format_menu_options()
        
        # Clear and rebuild menu
        self.format_menu.delete(0, END)
        
        def on_format_select(value):
            self.format_var.set(value)
            self.on_format_change()
            self.update_preview()
        
        # Rebuild menu items
        for value in new_options:
            padded_label = f" {value}      "
            self.format_menu.add_command(
                label=padded_label,
                command=lambda val=value: on_format_select(val)
            )
        
        # Update current selection if it was MP3 (to match new label)
        # Only update if the current selection is an MP3 variant
        if base_format == "mp3":
            # Find the MP3 option in new options
            for option in new_options:
                if option.startswith("MP3"):
                    # Only update if current selection is different
                    if current_selection != option:
                        self.format_var.set(option)
                    break
    
    def _on_skip_mp3_reencode_change(self):
        """Handle skip MP3 re-encode checkbox change."""
        self.save_skip_mp3_reencode()
        self._update_format_menu()
    
    def save_skip_mp3_reencode(self):
        """Save MP3 skip re-encoding preference."""
        self._save_settings()
    
    def save_auto_check_updates(self):
        """Save auto-check for updates preference."""
        self._save_settings()
    
    def on_auto_check_updates_change(self):
        """Handle auto-check for updates checkbox change."""
        self.save_auto_check_updates()
    
    def load_saved_tag_color_scheme(self):
        """Load saved tag color scheme preference."""
        settings = self._load_settings()
        scheme = settings.get("tag_color_scheme", "default")
        # Validate scheme exists
        schemes = self._get_color_schemes()
        if scheme not in schemes:
            return "default"
        return scheme
    
    def save_tag_color_scheme(self):
        """Save tag color scheme preference."""
        settings = self._load_settings()
        settings["tag_color_scheme"] = self.current_tag_color_scheme
        self._save_settings(settings)
    
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
    
    # ============================================================================
    # UI SETUP - Main Interface Creation
    # ============================================================================
    def setup_ui(self):
        """Create the GUI interface."""
        # Main container with compact padding
        main_frame = ttk.Frame(self.root, padding="8")
        main_frame.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # Setup UI sections in order
        self._setup_url_section(main_frame)
        self._setup_path_section(main_frame)
        self._setup_settings_and_album_art_section(main_frame)
        self._setup_preview_section(main_frame)
        self._setup_download_section(main_frame)
        self._setup_log_section(main_frame)
    
    def _setup_url_section(self, main_frame):
        """Setup URL input section with Entry and Text widgets."""
        colors = self.theme_colors
        
        # URL input - supports both single Entry and multi-line ScrolledText
        ttk.Label(main_frame, text="", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky=(W, N), pady=2
        )
        
        # Paste button - positioned to be vertically centered with URL field, right-aligned to mirror X button
        self.url_paste_btn = Label(
            main_frame,
            text="➕",  # Plus icon
            font=("Segoe UI", 10),  # Match X button font size
            bg=colors.bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=1,  # Match X button width
            height=1,  # Match X button height
            padx=0,   # Match X button padding
            pady=0    # Match X button padding
        )
        # Right-align to mirror X button position, vertically centered with URL field
        # Use rowspan=2 to span both rows (URL label row and URL field row) and sticky to center vertically
        self.url_paste_btn.grid(row=0, column=0, rowspan=2, sticky=(E, N, S), pady=2, padx=0)
        self.url_paste_btn.bind("<Button-1>", lambda e: self._handle_paste_button_Click())
        self.url_paste_btn.bind("<Enter>", lambda e: self.url_paste_btn.config(fg=colors.hover_fg))
        self.url_paste_btn.bind("<Leave>", lambda e: self.url_paste_btn.config(fg=colors.disabled_fg))
        
        # Container frame for URL widgets (Entry and ScrolledText)
        # Span rows 0-1 to align with URL label (row 0) and paste button (row 1)
        self.url_container_frame = Frame(main_frame, bg=colors.bg)
        self.url_container_frame.grid(row=0, column=1, columnspan=2, rowspan=2, sticky=(W, E, N), pady=0, padx=(8, 0))
        self.url_container_frame.columnconfigure(0, weight=1)  # URL field expands
        self.url_container_frame.columnconfigure(1, weight=0, minsize=20)  # Clear button fixed width
        self.url_container_frame.columnconfigure(2, weight=0, minsize=20)  # Expand button fixed width
        self.url_container_frame.rowconfigure(0, weight=1)  # Allow vertical expansion for ScrolledText
        
        # Single-line Entry widget (default) - with paste button overlay inside
        # Create a frame to hold the Entry and paste button overlay
        entry_container = Frame(self.url_container_frame, bg=colors.bg)
        entry_container.grid(row=0, column=0, sticky=(W, E), pady=0, padx=(0, 4))
        entry_container.columnconfigure(0, weight=1)
        self.entry_container = entry_container  # Store reference
        
        # Entry widget inside container (regular Entry to match ScrolledText styling)
        url_entry = Entry(
            entry_container,
            textvariable=self.url_var,
            width=45,
            font=("Segoe UI", 9),
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            insertbackground=colors.fg,
            relief='flat',
            borderwidth=1,
            highlightthickness=2,
            highlightbackground=colors.border,
            highlightcolor=colors.accent
        )
        url_entry.grid(row=0, column=0, sticky=(W, E), pady=0, padx=0)
        self.url_entry_widget = url_entry
        
        # Add placeholder text to Entry
        self._set_entry_placeholder(url_entry, "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.")
        
        # Clear button (X) - appears when URL field has content
        # Use smaller font and minimal padding to match entry field height
        self.url_clear_btn = Label(
            self.url_container_frame,
            text="✕",
            font=("Segoe UI", 11),
            bg=colors.bg,
            fg=colors.disabled_fg,
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
        self.url_clear_btn.bind("<Enter>", lambda e: self.url_clear_btn.config(fg=colors.hover_fg))
        self.url_clear_btn.bind("<Leave>", lambda e: self.url_clear_btn.config(fg=colors.disabled_fg))
        # Always visible - no grid_remove()
        
        # Expand/Collapse button - toggles between Entry and ScrolledText modes
        # Shows expand icon (⤢) in Entry mode, collapse icon (⤡) in ScrolledText mode
        self.url_expand_btn = Label(
            self.url_container_frame,
            text=self._get_icon('expand'),  # Default to expand icon
            font=("Segoe UI", 11),
            bg=colors.bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=1,
            height=1,
            padx=2,
            pady=0
        )
        # Use grid_remove to preserve space, sticky='' prevents expansion
        self.url_expand_btn.grid(row=0, column=2, sticky='', pady=0, padx=(2, 0))
        # Repurpose expand/collapse button to toggle URL text height (collapsed/expanded)
        self.url_expand_btn.bind("<Button-1>", self._toggle_url_text_height)
        self.url_expand_btn.bind("<Enter>", lambda e: self.url_expand_btn.config(fg=colors.hover_fg))
        self.url_expand_btn.bind("<Leave>", lambda e: self.url_expand_btn.config(fg=colors.disabled_fg))
        # Always visible - no grid_remove()
        # Set initial icon based on mode (should be ⤢ for entry mode)
        self._update_url_expand_button()
        
        # Bind events for Entry
        # Bind paste events - handle selection replacement and custom append behavior
        url_entry.bind('<<Paste>>', self._handle_entry_paste)  # Virtual paste event (proper way for Entry widgets)
        url_entry.bind('<Control-v>', self._handle_entry_paste)
        url_entry.bind('<Shift-Insert>', self._handle_entry_paste)
        url_entry.bind('<Button-2>', self._handle_entry_paste)  # Middle mouse button paste
        url_entry.bind('<Button-3>', self._handle_right_Click_paste_entry)  # Right mouse button
        url_entry.bind('<KeyRelease>', lambda e: (self.on_url_change(), self._check_entry_for_newlines(), self._update_url_clear_button()))
        url_entry.bind('<Return>', self._handle_entry_return)  # Enter key - expand to multi-line
        # Disable undo/redo for Entry widget (doesn't work well with tags)
        url_entry.bind('<Control-z>', lambda e: "break")  # Disable undo (Ctrl+Z)
        url_entry.bind('<Control-Shift-Z>', lambda e: "break")  # Disable redo (Ctrl+Shift+Z)
        url_entry.bind('<Control-y>', lambda e: "break")  # Disable redo (Ctrl+Y - alternative)
        
        # Multi-line Text widget with custom scrollbar (primary URL input - starts collapsed)
        url_text_frame = Frame(self.url_container_frame, bg=colors.bg)
        url_text_frame.grid(row=0, column=0, sticky=(W, E, N, S), pady=0)
        # Column 0: Text widget, Column 1: vertical scrollbar
        url_text_frame.columnconfigure(0, weight=1)
        url_text_frame.columnconfigure(1, weight=0)
        url_text_frame.rowconfigure(0, weight=1)
        url_text_frame.grid_remove()  # Hidden initially
        self.url_text_frame = url_text_frame  # Store reference for easier access
        
        # Paste button is now outside the URL field (positioned below URL label)
        # No need for separate paste button in text widget mode
        
        # Text widget (replaces ScrolledText) with ttk scrollbar
        url_text = Text(
            url_text_frame,
            width=45,
            height=1,  # Start with 1 line (collapsed)
            font=("Segoe UI", 9),
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            insertbackground=colors.fg,
            relief='flat',
            borderwidth=1,
            highlightthickness=2,
            highlightbackground=colors.border,
            highlightcolor=colors.accent,
            wrap='word',  # Enable word wrapping so tags wrap to multiple lines
            spacing1=6,   # Line spacing above first line (in pixels) - creates gap above tags
            spacing2=10,  # Line spacing between lines (in pixels) - creates clear gaps between tag lines
            spacing3=6    # Line spacing below last line (in pixels) - creates gap below tags
        )
        url_text.grid(row=0, column=0, sticky=(W, E, N, S))
        
        # Dark themed vertical scrollbar bound to the Text widget
        # Scrollbar: use default style in light mode, custom dark style in dark mode
        scrollbar_style = 'TScrollbar' if self.current_theme == 'light' else 'Dark.Vertical.TScrollbar'
        url_scrollbar = ttk.Scrollbar(
            url_text_frame,
            orient='vertical',
            style='TScrollbar',  # Start with base style
            command=url_text.yview
        )
        self.url_scrollbar = url_scrollbar  # Store reference for theme updates
        url_scrollbar.grid(row=0, column=1, sticky=(N, S))
        url_text.configure(yscrollcommand=url_scrollbar.set)
        # Apply the correct style after creation (ensures proper initialization)
        if scrollbar_style != 'TScrollbar':
            self.root.update_idletasks()  # Force update
            url_scrollbar.configure(style=scrollbar_style)

        self.url_text_widget = url_text
        
        # Create resize handle at the bottom of the text widget (thin, minimal space)
        self.url_text_resize_handle = Label(
            url_text_frame,
            text="➖",  # Single large minus for grip icon to indicate draggable
            bg=colors.entry_bg,  # Match text widget background to blend in
            fg=colors.disabled_fg,  # Disabled color for visibility
            cursor='sb_v_double_arrow',  # Vertical resize cursor
            height=4,  # Allow space for 3 lines
            relief='flat',
            borderwidth=0,
            font=("Segoe UI", 11),  # Slightly larger font for better visibility
            anchor='center',  # Center the text
            justify='center',  # Center the lines
            wraplength=50  # Allow text wrapping if needed
        )
        # Use place() to position it just above the bottom edge, centered and narrower
        # Exact width of URL field with adjustments to center placement with no border or scrollbar overlap
        self.url_text_resize_handle.place(relx=0.5, rely=1.0, width=405, anchor='s', height=5, y=-2, x=-9)
        self.url_text_resize_handle.lower()  # Place behind text widget initially
        self.url_text_resize_handle.place_forget()  # Hidden initially, shown when text widget is visible

        # Start directly in multi-line mode (ScrolledText) with compact height.
        # This effectively replaces the single-line Entry as the primary URL input.
        self._expand_to_multiline(initial_content="")
        
        # Bind resize handle events
        self.url_text_resize_handle.bind("<Button-1>", self._start_url_text_resize)
        self.url_text_resize_handle.bind("<B1-Motion>", self._on_url_text_resize)
        self.url_text_resize_handle.bind("<ButtonRelease-1>", self._end_url_text_resize)
        self.url_text_resize_handle.bind("<Double-Button-1>", self._toggle_url_text_height)
        
        # Create placeholder label overlay (ghost text that doesn't interfere with content)
        # This will be positioned over the ScrolledText but won't interfere with editing
        placeholder_label = Label(
            url_text_frame,
            text="Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.",
            font=("Segoe UI", 9),
            bg=colors.entry_bg,
            fg=colors.disabled_fg,
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
        # Allow right-Click on placeholder to directly paste
        placeholder_label.bind('<Button-3>', self._handle_right_Click_paste_text)
        self.url_text_placeholder_label = placeholder_label
        # Initially show placeholder since widget is empty
        self._update_text_placeholder_visibility()
        
        # Create custom context menu for ScrolledText
        context_menu = Menu(url_text, tearoff=0, bg=colors.select_bg, fg=colors.fg, 
                           activebackground=colors.accent, activeforeground='#FFFFFF',
                           selectcolor=colors.accent)
        context_menu.add_command(label="Paste", command=self._handle_right_Click_paste_text)
        self.url_text_context_menu = context_menu
        
        # Bind events for ScrolledText
        url_text.bind('<Control-v>', self._handle_text_paste)
        url_text.bind('<Shift-Insert>', self._handle_text_paste)
        url_text.bind('<Button-2>', self._handle_text_paste)  # Middle mouse button paste
        url_text.bind('<Button-3>', self._show_text_context_menu)  # Right mouse button - directly paste
        url_text.bind('<KeyRelease>', lambda e: (self._on_text_key_release(), self._update_url_clear_button()))
        url_text.bind('<KeyPress>', lambda e: self._hide_text_placeholder())  # Hide on any key press
        url_text.bind('<Button-1>', lambda e: self._hide_text_placeholder())  # Hide on Click
        url_text.bind('<FocusIn>', lambda e: self._on_text_focus_in())
        url_text.bind('<FocusOut>', lambda e: self._on_text_focus_out())
        url_text.bind('<Return>', self._handle_text_return)  # Enter key - save state when new line added
        # Disable undo/redo for Text widget (doesn't work well with tags)
        url_text.bind('<Control-z>', lambda e: "break")  # Disable undo (Ctrl+Z)
        url_text.bind('<Control-Shift-Z>', lambda e: "break")  # Disable redo (Ctrl+Shift+Z)
        url_text.bind('<Control-y>', lambda e: "break")  # Disable redo (Ctrl+Y - alternative)
        # Tag protection: handle backspace/delete to remove entire tags
        url_text.bind('<BackSpace>', self._handle_url_tag_backspace, add='+')
        url_text.bind('<Delete>', self._handle_url_tag_delete, add='+')
    
    def _setup_path_section(self, main_frame):
        """Setup download path section with Browse button and Settings icon."""
        colors = self.theme_colors
        
        # Download path - compact
        # Moved to row 2 to avoid overlap with URL field and paste button (rows 0-1)
        ttk.Label(main_frame, text="Path:", font=("Segoe UI", 9)).grid(
            row=2, column=0, sticky=W, pady=2
        )
        path_entry = Entry(main_frame, textvariable=self.path_var, width=35, font=("Segoe UI", 9), 
                          bg=colors.entry_bg, fg=colors.entry_fg, insertbackground=colors.fg,
                          relief='flat', borderwidth=1, highlightthickness=2,
                          highlightbackground=colors.border, highlightcolor=colors.accent, state='normal')
        path_entry.grid(row=2, column=1, sticky=(W, E), pady=2, padx=(8, 0))
        self.path_entry = path_entry  # Store reference for unfocus handling
        
        # Bind focus out event to deselect text when path entry loses focus
        def on_path_focus_out(event):
            path_entry.selection_clear()
        path_entry.bind('<FocusOut>', on_path_focus_out)
        
        # Container frame for Browse button and Settings cog icon
        # Moved to row 2 to align with path field (row 2)
        browse_container = Frame(main_frame, bg=colors.bg)
        browse_container.grid(row=2, column=2, sticky=(W, E), padx=(4, 0), pady=0)
        browse_container.columnconfigure(0, weight=1, minsize=80)  # Browse button expands with minimum width
        browse_container.columnconfigure(1, weight=0)  # Cog icon fixed width
        
        browse_btn = ttk.Button(browse_container, text="Browse", command=self.browse_folder, cursor='hand2', style='Browse.TButton')
        browse_btn.grid(row=0, column=0, sticky=(W, E))  # Expand to fill available space
        self.browse_btn = browse_btn  # Store reference for unfocus handling
        
        # Settings cog icon button
        self.settings_cog_btn = Label(
            browse_container,
            text=self._get_icon('settings'),
            font=("Segoe UI", 12),
            bg=colors.bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=2,
            padx=4
        )
        self.settings_cog_btn.grid(row=0, column=1, padx=(8, 0))  # Increased left padding to push Browse button left and align with scrollbar
        self.settings_cog_btn.bind("<Button-1>", self._show_settings_menu)
        self.settings_cog_btn.bind("<Enter>", lambda e: self.settings_cog_btn.config(fg=colors.hover_fg))
        self.settings_cog_btn.bind("<Leave>", lambda e: self.settings_cog_btn.config(fg=colors.disabled_fg))
        
        # Create settings menu (will be shown on cog Click)
        self.settings_menu = None
        
        # Bind path changes to update preview
        self.path_var.trace_add('write', lambda *args: self.update_preview())
        self.folder_structure_var.trace_add('write', lambda *args: self.update_preview())
        # Note: URL changes are handled by direct event bindings, not trace_add
        # (trace_add would trigger on placeholder text changes)
    
    def _setup_settings_and_album_art_section(self, main_frame):
        """Setup settings frame and album art panel side by side."""
        colors = self.theme_colors
        
        # Settings section - reduced width to make room for album art panel
        # Moved to row 3 to avoid conflict with path field (row 2)
        # Settings frame: dark mode uses bg, light mode uses select_bg (white)
        settings_frame_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        self.settings_frame = Frame(main_frame, bg=settings_frame_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        self.settings_frame.grid(row=3, column=0, columnspan=2, sticky=(W, E, N), pady=2, padx=0)
        self.settings_frame.grid_propagate(False)
        self.settings_frame.config(height=170)  # Reduced height with equal padding top and bottom
        
        # Inner frame for content
        self.settings_content = Frame(self.settings_frame, bg=settings_frame_bg)
        # Start at row 0 (no separate header row)
        self.settings_content.grid(row=0, column=0, sticky=(W, E), padx=6, pady=(4, 8))  # Balanced padding: less top, more bottom
        self.settings_frame.columnconfigure(0, weight=1)
        # Configure columns: label, combo, button (right-aligned)
        self.settings_content.columnconfigure(1, weight=1)  # Allow combo to expand
        
        # Configure rows for uniform spacing
        self.settings_content.rowconfigure(0, uniform='settings_row', pad=0)
        self.settings_content.rowconfigure(1, uniform='settings_row', pad=0)
        self.settings_content.rowconfigure(2, uniform='settings_row', pad=0)
        
        # Album art panel (separate frame on the right, same height as settings, square for equal padding)
        # Frame background: dark mode uses bg, light mode uses select_bg (white)
        album_art_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        self.album_art_frame = Frame(main_frame, bg=album_art_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        # Moved to row 3 to align with settings_frame (row 3)
        self.album_art_frame.grid(row=3, column=2, sticky=(W, E, N), pady=2, padx=(6, 0))
        self.album_art_frame.grid_propagate(False)
        self.album_art_frame.config(width=170, height=170)  # Square panel matching settings height for equal padding
        # Center content in the frame
        self.album_art_frame.columnconfigure(0, weight=1)
        self.album_art_frame.rowconfigure(0, weight=1)
        
        # Album art canvas with consistent padding all around (10px padding = 150x150 canvas)
        # Canvas background: dark mode uses bg, light mode uses select_bg (white)
        canvas_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        self.album_art_canvas = Canvas(
            self.album_art_frame,
            width=150,
            height=150,
            bg=canvas_bg,
            highlightthickness=0,
            borderwidth=0,
            cursor='hand2'  # Show hand cursor to indicate it's Clickable
        )
        # Center the canvas with equal padding on all sides (10px on each side = 20px total, 150 + 20 = 170)
        self.album_art_canvas.grid(row=0, column=0, padx=5, pady=5)
        
        # Make canvas Clickable to toggle album art
        self.album_art_canvas.bind("<Button-1>", lambda e: self.toggle_album_art())
        
        # Placeholder text on canvas (centered at 75, 75 for 150x150 canvas)
        self.album_art_canvas.create_text(
            75, 75,
            text="Album Art",
            fill=colors.disabled_fg,
            font=("Segoe UI", 8)
        )
        
        # Audio Format (first) - with eye icon button on the right when album art is hidden
        # Use Settings.TLabel style to match settings frame background (white in light mode)
        format_label = ttk.Label(self.settings_content, text="Format:", font=("Segoe UI", 8), style='Settings.TLabel')
        format_label.grid(row=0, column=0, padx=4, sticky=W, pady=1)
        
        def on_format_select(value):
            self.format_var.set(value)
            self.on_format_change()
            self.update_preview()
        
        # Store references for dynamic updates
        format_menubutton, format_menu = self._create_menubutton_with_menu(
            self.settings_content,
            self.format_var,
            self._get_format_menu_options(),
            width=21,
            callback=on_format_select
        )
        format_menubutton.grid(row=0, column=1, padx=4, sticky=W, pady=1)
        self.format_menubutton = format_menubutton  # Store for dynamic updates
        self.format_menu = format_menu  # Store for dynamic updates
        
        # Update format menu to match current skip re-encode setting and saved format
        self.root.after_idle(self._update_format_menu)
        
        # Show album art button (hidden by default, shown when album art is hidden)
        # Placed in the same row as Audio Format, right-aligned
        # Always keep it in grid to prevent layout shifts - just make it invisible when not needed
        # Eye icon for showing album art (Win7 compatible)
        eye_icon = self._get_icon('eye')
        eye_font = ("Webdings", 12) if self._is_windows_7() else ("Segoe UI", 10)
        self.show_album_art_btn = Label(
            self.settings_content,
            text=eye_icon,
            font=eye_font,
            bg=colors.bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=2
        )
        # Only add to grid if album art is hidden (will be shown/hidden by toggle_album_art)
        # If album art is visible by default, don't add to grid initially to save space
        if self.album_art_mode == "hidden":
            self.show_album_art_btn.grid(row=0, column=2, sticky=E, padx=(4, 0), pady=1)
            self.show_album_art_btn.config(fg=colors.disabled_fg, cursor='hand2')
        # Always bind events (they'll work when the button is in grid)
        self.show_album_art_btn.bind("<Button-1>", lambda e: self.toggle_album_art())
        self.show_album_art_btn.bind("<Enter>", lambda e: self.show_album_art_btn.config(fg=colors.hover_fg))
        self.show_album_art_btn.bind("<Leave>", lambda e: self.show_album_art_btn.config(fg=colors.disabled_fg))
        
        # Numbering (second, below Audio Format)
        # Use Settings.TLabel style to match settings frame background
        filename_label = ttk.Label(self.settings_content, text="Filename:", font=("Segoe UI", 8), style='Settings.TLabel')
        filename_label.grid(row=1, column=0, padx=4, sticky=W, pady=1)
        
        # Create frame for dropdown and buttons (similar to folder structure)
        # Use settings_frame_bg to match settings content background
        filename_frame = Frame(self.settings_content, bg=settings_frame_bg, highlightthickness=0, borderwidth=0)
        filename_frame.grid(row=1, column=1, padx=4, sticky=(W, N), pady=1, columnspan=1)
        self.filename_frame = filename_frame  # Store reference for theme updates
        
        # Create filename menubutton with custom menu (similar to folder structure)
        numbering_menubutton = ttk.Menubutton(
            filename_frame,
            textvariable=self.numbering_var,
            width=21,
            direction='below',
            style='Dark.TMenubutton'
        )
        numbering_menubutton.pack(side=LEFT, padx=(0, 6), pady=0, anchor='w')
        
        numbering_menu = self._create_dark_menu(numbering_menubutton)
        numbering_menubutton['menu'] = numbering_menu
        
        self.filename_menubutton = numbering_menubutton  # Store reference
        self.filename_menu = numbering_menu  # Store reference
        
        # Build the menu with standard formats, separator, and custom formats
        self._build_filename_menu(numbering_menu)
        
        # Update edit button state based on initial selection (after button is created)
        # Will be called after button creation below
        
        # Customize button (✏️) - matching folder structure style
        filename_customize_btn = Label(
            filename_frame,
            text=self._get_icon('pencil'),
            font=("Segoe UI", 12),
            bg=settings_frame_bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=2,
            padx=0
        )
        filename_customize_btn.pack(side=LEFT, padx=(0, 0))
        filename_customize_btn.bind("<Button-1>", lambda e: self._show_customize_filename_dialog())
        filename_customize_btn.bind("<Enter>", lambda e: filename_customize_btn.config(fg=colors.hover_fg))
        filename_customize_btn.bind("<Leave>", lambda e: filename_customize_btn.config(fg=colors.disabled_fg))
        self.filename_customize_btn = filename_customize_btn  # Store reference
        
        # Update edit button state based on initial selection
        self.root.after(100, self._update_filename_edit_button)
        
        # Manage button (🗑️) - trash can icon for managing/deleting filename formats
        has_custom_filename = hasattr(self, 'custom_filename_formats') and self.custom_filename_formats
        disabled_color = colors.disabled_fg if self.current_theme == 'dark' else '#A0A0A0'  # Lighter disabled for light mode
        filename_manage_btn = Label(
            filename_frame,
            text=self._get_icon('trash'),
            font=("Segoe UI", 12),
            bg=settings_frame_bg,
            fg=colors.disabled_fg if has_custom_filename else disabled_color,
            cursor='hand2' if has_custom_filename else 'arrow',
            width=3,
            padx=4
        )
        filename_manage_btn.pack(side=LEFT, padx=(2, 0))
        if has_custom_filename:
            filename_manage_btn.bind("<Button-1>", lambda e: self._show_manage_filename_dialog())
            filename_manage_btn.bind("<Enter>", lambda e: filename_manage_btn.config(fg=colors.hover_fg) if has_custom_filename else None)
            filename_manage_btn.bind("<Leave>", lambda e: filename_manage_btn.config(fg=colors.disabled_fg) if has_custom_filename else None)
        self.filename_manage_btn = filename_manage_btn  # Store reference
        
        # Folder Structure (third, below Numbering)
        # Use Settings.TLabel style to match settings frame background
        folder_label = ttk.Label(self.settings_content, text="Folder(s):", font=("Segoe UI", 8), style='Settings.TLabel')
        folder_label.grid(row=2, column=0, padx=4, sticky=W, pady=1)
        
        # Create frame for dropdown and buttons
        # Use settings_frame_bg to match settings content background
        structure_frame = Frame(self.settings_content, bg=settings_frame_bg, highlightthickness=0, borderwidth=0)
        structure_frame.grid(row=2, column=1, padx=4, sticky=(W, N), pady=1, columnspan=1)  # Don't expand to avoid overlap with column 2
        self.structure_frame = structure_frame  # Store reference for theme updates
        
        # Use Menubutton + Menu instead of Combobox for separator support
        # Create structure menubutton (custom menu building for separator support)
        structure_menubutton = ttk.Menubutton(
            structure_frame,
            textvariable=self.folder_structure_var,
            width=21,
            direction='below',
            style='Dark.TMenubutton'
        )
        structure_menubutton.pack(side=LEFT, padx=(0, 6), pady=0, anchor='w')
        
        structure_menu = self._create_dark_menu(structure_menubutton)
        structure_menubutton['menu'] = structure_menu
        
        # Build the menu with standard structures, separator, and custom structures
        self._build_structure_menu(structure_menu)
        
        # Track menu state for toggle behavior
        self.structure_menu_open = False
        self.structure_item_just_selected = False
        
        # Wrap the structure menu select handler to track item selection
        original_on_structure_select = self._on_structure_menu_select
        def wrapped_structure_select(choice):
            self.structure_item_just_selected = True
            original_on_structure_select(choice)
        
        # Rebuild menu with wrapped callbacks
        def rebuild_with_tracking():
            structure_menu.delete(0, END)
            # Add standard structures
            for key in ["1", "2", "3", "4", "5"]:
                display_value = self.FOLDER_STRUCTURES[key]
                padded_label = f" {display_value}      "
                structure_menu.add_command(
                    label=padded_label,
                    command=lambda val=key: wrapped_structure_select(val)
                )
            # Add separator if there are custom structures (templates or old format)
            has_custom = False
            if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
                has_custom = True
            if hasattr(self, 'custom_structures') and self.custom_structures:
                has_custom = True
            
            if has_custom:
                structure_menu.add_separator()
                # Add custom structures in order: old format first, then templates (newest at end)
                # Old format structures
                if hasattr(self, 'custom_structures') and self.custom_structures:
                    for structure in self.custom_structures:
                        formatted = self._format_custom_structure(structure)
                        if formatted:
                            padded_label = f" {formatted}      "
                            structure_menu.add_command(
                                label=padded_label,
                                command=lambda s=structure: wrapped_structure_select(s)
                            )
                # Custom template structures (new format) - added after old format, so newest appear at end
                if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
                    for template_data in self.custom_structure_templates:
                        formatted = self._format_custom_structure_template(template_data)
                        if formatted:
                            padded_label = f" {formatted}      "
                            structure_menu.add_command(
                                label=padded_label,
                                command=lambda t=template_data: wrapped_structure_select(t)
                            )
        
        rebuild_with_tracking()
        
        def on_menu_post(event=None):
            self.structure_menu_open = True
            self.structure_item_just_selected = False  # Reset when menu opens
        
        def on_menu_unpost(event=None):
            self.structure_menu_open = False
        
        structure_menu.bind('<<MenuSelect>>', on_menu_post)
        structure_menu.bind('<<MenuUnpost>>', on_menu_unpost)
        
        # Detect when menu closes due to outside Click by monitoring root window focus/Clicks
        # Use a more aggressive approach: check immediately on any root interaction
        def detect_menu_close(event=None):
            if self.structure_menu_open:
                # Flag says menu is open - check immediately if it's actually still posted
                # Don't delay - check right now
                try:
                    structure_menu.tk.call(structure_menu, 'index', 'active')
                    # Menu is still posted - flag is correct, do nothing
                except:
                    # Menu is not posted - it closed, update flag immediately
                    self.structure_menu_open = False
        
        # Bind to root window events that indicate menu might have closed
        # Focus-in on root: when root gets focus, menu might have closed
        self.root.bind('<FocusIn>', detect_menu_close, add=True)
        # Button-1 on root: when Clicking outside, menu might have closed
        def root_Click_handler(event):
            # Check immediately if Click is not on the menubutton or menu itself
            try:
                widget = event.widget
                # If Click is on menubutton or menu, don't check (menu handles its own Clicks)
                if widget != structure_menubutton and not str(widget).startswith(str(structure_menu)):
                    detect_menu_close(event)
            except:
                pass
        
        self.root.bind('<Button-1>', root_Click_handler, add=True)
        
        # Also periodically check when flag says open (backup detection)
        def periodic_check():
            if self.structure_menu_open:
                # Flag says open - verify it's actually posted
                try:
                    structure_menu.tk.call(structure_menu, 'index', 'active')
                    # Menu is posted - flag is correct, check again soon
                    self.root.after(100, periodic_check)
                except:
                    # Menu is not posted - update flag
                    self.structure_menu_open = False
        
        # Start periodic checking when menu opens
        original_on_menu_post = on_menu_post
        def on_menu_post_with_check(event=None):
            original_on_menu_post(event)
            # Start periodic checking
            self.root.after(100, periodic_check)
        
        structure_menu.unbind('<<MenuSelect>>')
        structure_menu.bind('<<MenuSelect>>', on_menu_post_with_check)
        
        # Check menu state on Click - if open, close it; otherwise let default behavior open it
        # Known limitation: Tkinter's Menubutton doesn't reliably notify when menu closes from outside Click.
        # This causes a 2-Click requirement after closing menu by Clicking outside (flag gets stale).
        # This is a fundamental Tkinter limitation - the current implementation is the best we can achieve.
        def on_button_Click(event=None):
            if self.structure_item_just_selected:
                # Menu was just closed via item selection - don't interfere, let default behavior open it
                self.structure_item_just_selected = False
                return None  # Let default behavior handle it
            
            # Only close if we're CERTAIN menu is open (both flag and actual state must agree)
            # This prevents false positives that block menu opening
            flag_says_open = self.structure_menu_open
            actual_state_open = False
            
            # Quick check of actual state
            try:
                structure_menu.tk.call(structure_menu, 'index', 'active')
                actual_state_open = True
            except:
                pass
            
            # Only close if BOTH say open - if either is uncertain, allow opening
            if flag_says_open and actual_state_open:
                # Both confirm menu is open - close it and prevent default posting
                self.root.focus_set()
                structure_menu.unpost()
                self.structure_menu_open = False
                return "break"  # Prevent default behavior (posting menu)
            else:
                # Not certain menu is open - always allow default behavior to open it
                # Update flag if actual state says closed
                if not actual_state_open:
                    self.structure_menu_open = False
                return None  # Allow default behavior
        
        structure_menubutton.bind('<Button-1>', on_button_Click, add=True)
        
        # Store the rebuild function so _update_structure_dropdown can use it
        self._rebuild_structure_menu_with_tracking = rebuild_with_tracking
        
        # Store references
        self.structure_menubutton = structure_menubutton
        self.structure_menu = structure_menu
        
        # Customize button (✏️) - matching settings cog icon style
        customize_btn = Label(
            structure_frame,
            text=self._get_icon('pencil'),
            font=("Segoe UI", 12),
            bg=settings_frame_bg,
            fg=colors.disabled_fg,
            cursor='hand2',
            width=2,
            padx=0
        )
        customize_btn.pack(side=LEFT, padx=(0, 0))  # spacing between buttons
        customize_btn.bind("<Button-1>", lambda e: self._show_customize_dialog())
        customize_btn.bind("<Enter>", lambda e: customize_btn.config(fg=colors.hover_fg))
        customize_btn.bind("<Leave>", lambda e: customize_btn.config(fg=colors.disabled_fg))
        
        # Manage button (🗑️) - trash can icon for managing/deleting structures
        has_custom = hasattr(self, 'custom_structures') and self.custom_structures
        disabled_color = colors.disabled_fg if self.current_theme == 'dark' else '#A0A0A0'  # Lighter disabled for light mode
        manage_btn = Label(
            structure_frame,
            text=self._get_icon('trash'),
            font=("Segoe UI", 12),
            bg=settings_frame_bg,
            fg=colors.disabled_fg if has_custom else disabled_color,
            cursor='hand2' if has_custom else 'arrow',
            width=3,  # Increased width to give icon more room
            padx=4
        )
        manage_btn.pack(side=LEFT, padx=(2, 0))  # Left padding to prevent icon cutoff
        if has_custom:
            manage_btn.bind("<Button-1>", lambda e: self._show_manage_dialog())
            manage_btn.bind("<Enter>", lambda e: manage_btn.config(fg=colors.hover_fg) if has_custom else None)
            manage_btn.bind("<Leave>", lambda e: manage_btn.config(fg=colors.disabled_fg) if has_custom else None)
        
        # Store references (structure_menubutton and structure_menu already stored above)
        self.customize_btn = customize_btn
        self.manage_btn = manage_btn
        
        # Update dropdown with custom structures and set initial display value
        self._update_structure_dropdown()
        self.update_structure_display()
        
        # Skip post-processing checkbox (below Folder Structure) - only shown if developer flag is enabled
        skip_postprocessing_check = Checkbutton(
            self.settings_content,
            text="Skip post-processing (output original files)",
            variable=self.skip_postprocessing_var,
            font=("Segoe UI", 8),
            bg=settings_frame_bg,
            fg=colors.fg,
            selectcolor=settings_frame_bg,
            activebackground=settings_frame_bg,
            activeforeground=colors.fg,
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
            bg=settings_frame_bg,
            fg=colors.fg,
            selectcolor=settings_frame_bg,
            activebackground=settings_frame_bg,
            activeforeground=colors.fg,
            command=self.on_download_cover_art_change
        )
        download_cover_art_check.grid(row=4, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        self.download_cover_art_check = download_cover_art_check  # Store reference for theme updates
        
        # Create playlist checkbox (below Save copy of cover art)
        create_playlist_check = Checkbutton(
            self.settings_content,
            text="Create playlist file (.m3u)",
            variable=self.create_playlist_var,
            font=("Segoe UI", 8),
            bg=settings_frame_bg,
            fg=colors.fg,
            selectcolor=settings_frame_bg,
            activebackground=settings_frame_bg,
            activeforeground=colors.fg,
            command=self.on_create_playlist_change
        )
        create_playlist_check.grid(row=5, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        self.create_playlist_check = create_playlist_check  # Store reference for theme updates
        
        # Download artist discography checkbox (below Create playlist)
        download_discography_check = Checkbutton(
            self.settings_content,
            text="Download artist discography",
            variable=self.download_discography_var,
            font=("Segoe UI", 8),
            bg=settings_frame_bg,
            fg=colors.fg,
            selectcolor=settings_frame_bg,
            activebackground=settings_frame_bg,
            activeforeground=colors.fg,
            command=self.on_download_discography_change
        )
        download_discography_check.grid(row=6, column=0, columnspan=2, padx=4, sticky=W, pady=1)
        self.download_discography_check = download_discography_check  # Store reference for enabling/disabling
        
        # Configure column weights: label (0), combo (1), button (2)
        self.settings_content.columnconfigure(0, weight=0)  # Label column - fixed width
        self.settings_content.columnconfigure(1, weight=1)  # Combo column - can expand
        self.settings_content.columnconfigure(2, weight=0)  # Button column - fixed width
    
    def _setup_preview_section(self, main_frame):
        """Setup preview section showing download path preview."""
        colors = self.theme_colors
        
        # Preview container (below both settings and album art panels)
        # Moved to row 4 to avoid conflict with settings_frame and album_art_frame (row 3)
        # Preview frame: dark mode uses bg, light mode uses entry_bg (#F5F5F5) to match URL field
        preview_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
        preview_frame = Frame(main_frame, bg=preview_frame_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        preview_frame.grid(row=4, column=0, columnspan=3, sticky=(W, E), pady=(0, 6), padx=0)
        self.preview_frame = preview_frame  # Store reference for theme updates
        
        # Preview display with "Preview: " in white and path in blue
        preview_label_prefix = Label(
            preview_frame,
            text="Preview: ",
            font=("Consolas", 8),
            bg=preview_frame_bg,
            fg=colors.fg,
            justify='left'
        )
        preview_label_prefix.grid(row=0, column=0, sticky=W, padx=(6, 0), pady=0)
        self.preview_label_prefix = preview_label_prefix  # Store reference for theme updates
        
        # Preview path label (blue, left-aligned, Clickable link)
        self.preview_var = StringVar(value="Select a download path")
        preview_label_path = Label(
            preview_frame,
            textvariable=self.preview_var,
            font=("Consolas", 8),
            bg=preview_frame_bg,
            fg=colors.preview_link,
            wraplength=400,  # Reduced to ensure proper wrapping
            justify='left',
            anchor='w',  # Left-align the text
            cursor='hand2'  # Hand cursor to indicate Clickability
        )
        preview_label_path.grid(row=0, column=1, sticky=W, padx=(0, 6), pady=0)
        preview_frame.columnconfigure(1, weight=1)
        self.preview_label_path = preview_label_path  # Store reference for theme updates
        
        # Make preview path Clickable - opens folder in Explorer
        def open_preview_path(event=None):
            preview_path = self.preview_var.get()
            if not preview_path or preview_path == "Select a download path":
                return
            
            try:
                # Check if the full preview path exists (file or directory)
                if os.path.exists(preview_path):
                    # Full path exists - open it
                    if os.path.isfile(preview_path):
                        # It's a file - open the parent directory and select the file
                        parent_dir = os.path.dirname(preview_path)
                        if parent_dir:
                            # Try to open parent directory with file selected
                            try:
                                subprocess.run(['explorer', '/select,', preview_path], check=False)
                            except:
                                # Fallback to just opening the parent directory
                                os.startfile(parent_dir)
                    else:
                        # It's a directory - open it directly
                        os.startfile(preview_path)
                else:
                    # Full path doesn't exist - find the deepest existing directory in the path
                    path_obj = Path(preview_path)
                    
                    # If it's a file path, start from the parent directory
                    if path_obj.suffix:  # Has file extension, so it's a file
                        path_obj = path_obj.parent
                    
                    # Walk up the path to find the deepest existing directory
                    deepest_existing = None
                    current_path = path_obj
                    
                    while current_path and current_path != current_path.parent:
                        if current_path.exists() and current_path.is_dir():
                            deepest_existing = current_path
                            break
                        current_path = current_path.parent
                    
                    if deepest_existing:
                        # Found an existing directory - open it
                        os.startfile(str(deepest_existing))
                    else:
                        # No existing directory found - open the base download path
                        base_path = self.path_var.get().strip()
                        if base_path and os.path.exists(base_path):
                            os.startfile(base_path)
                        elif base_path:
                            # Base path doesn't exist either - try to create it and open
                            try:
                                os.makedirs(base_path, exist_ok=True)
                                os.startfile(base_path)
                            except Exception as e:
                                messagebox.showinfo("Path Not Found", f"Cannot open path:\n{base_path}\n\nPath does not exist and could not be created.")
            except Exception as e:
                messagebox.showerror("Error", f"Could not open path:\n{str(e)}")
        
        preview_label_path.bind('<Button-1>', open_preview_path)
        # Set up hover handlers with current theme colors
        preview_label_path.bind('<Enter>', lambda e: preview_label_path.config(fg=colors.preview_link_hover))
        preview_label_path.bind('<Leave>', lambda e: preview_label_path.config(fg=colors.preview_link))
        # Store reference for theme updates
        self.preview_label_path = preview_label_path
        
        # Format conversion warning (shown below preview when FLAC, OGG, or WAV is selected)
        colors = self.theme_colors
        self.format_conversion_warning_label = Label(
            main_frame,
            text="⚠ Files are converted from 128kbps MP3 stream source. Quality is not improved. For higher quality, purchase/download directly from Bandcamp.",
            font=("Segoe UI", 8),
            bg=colors.bg,
            fg=colors.warning,
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
            bg=colors.bg,
            fg=colors.warning
        )
        self.ogg_warning_label.grid(row=5, column=0, columnspan=3, padx=12, sticky=W, pady=(0, 6))
        self.ogg_warning_label.grid_remove()  # Hidden by default
        
        # WAV warning label (shown when WAV is selected, below preview)
        self.wav_warning_label = Label(
            main_frame,
            text="⚠ Metadata/cover art cannot be embedded for WAV files",
            font=("Segoe UI", 8),
            bg=colors.bg,
            fg=colors.warning
        )
        self.wav_warning_label.grid(row=5, column=0, columnspan=3, padx=12, sticky=W, pady=(0, 2))
        self.wav_warning_label.grid_remove()  # Hidden by default
    
    def _setup_download_section(self, main_frame):
        """Setup download button and progress indicators."""
        # Download button - prominent with Bandcamp blue accent
        self.download_btn = ttk.Button(
            main_frame,
            text="Download Album",
            command=self.start_download,
            style='Download.TButton',
            cursor='hand2'
        )
        self.download_btn.grid(row=6, column=0, columnspan=3, pady=0)
        
        # Track if download button is being Clicked to prevent URL field collapse interference
        self.download_button_Clicked = False
        self.download_btn.bind('<Button-1>', lambda e: setattr(self, 'download_button_Clicked', True), add='+')
        
        # Cancel button (hidden initially, shown during download)
        # Uses same style as download button for consistent size
        self.cancel_btn = ttk.Button(
            main_frame,
            text="Cancel Download",
            command=self.cancel_download,
            state='disabled',
            style='Cancel.TButton',
            cursor='arrow'  # Regular cursor when disabled
        )
        self.cancel_btn.grid(row=6, column=0, columnspan=3, pady=0)
        self.cancel_btn.grid_remove()  # Hidden by default
        
        # Progress bar - compact
        self.progress_var = StringVar(value="Ready")
        self.progress_label = ttk.Label(
            main_frame,
            textvariable=self.progress_var,
            font=("Segoe UI", 8)
        )
        self.progress_label.grid(row=7, column=0, columnspan=3, pady=(2, 2))
        
        # Progress bar - using indeterminate mode for smooth animation
        # Options: 'indeterminate' (animated, no specific progress) or 'determinate' (shows actual %)
        self.progress_bar = ttk.Progressbar(
            main_frame,
            mode='indeterminate',  # Smooth animated progress
            length=350
        )
        self.progress_bar.grid(row=8, column=0, columnspan=3, pady=0, sticky=(W, E))
        
        # Overall album progress bar (custom thin 3px bar using Canvas)
        colors = self.theme_colors
        # Background: dark mode uses bg, light mode uses entry_bg (#F5F5F5) to match URL field
        progress_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
        self.overall_progress_bar = ThinProgressBar(
            main_frame,
            height=3,  # 3px thick as requested
            bg_color=progress_bg,  # Match theme background
            fg_color=colors.success   # Blue color matching main progress bar
        )
        self.overall_progress_bar.config(mode='determinate', maximum=100, value=0)
        # Hide initially - will show when download starts
        self.overall_progress_bar.grid(row=9, column=0, columnspan=3, pady=(2, 2), sticky=(W, E))
        self.overall_progress_bar.grid_remove()
    
    def _setup_log_section(self, main_frame):
        """Setup status log section with controls."""
        colors = self.theme_colors
        
        # Status log - compact (using regular Frame for full control)
        # Reduced bottom padding slightly to make room for expand button
        # Log frame: dark mode uses bg, light mode uses entry_bg (#F5F5F5) to match URL field
        log_frame_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
        self.log_frame = Frame(main_frame, bg=log_frame_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        self.log_frame.grid(row=10, column=0, columnspan=3, sticky=(W, E, N, S), pady=(2, 4), padx=0)
        
        # Label for the frame and controls on same row
        log_label = Label(self.log_frame, text="Status", bg=log_frame_bg, fg=colors.fg, font=("Segoe UI", 9))
        log_label.grid(row=0, column=0, sticky=W, padx=6, pady=(0, 2))
        self.log_label = log_label  # Store reference for theme updates
        
        # Clear log button (between Status label and Debug toggle) - styled like Browse button
        # Use same font size as Debug toggle (8) for consistency in header
        # Create a custom style for the small button (based on TButton but with smaller padding and font)
        style = ttk.Style()
        style.configure('Small.TButton', 
                       background=colors.entry_bg,  # Light gray like URL field
                       foreground=colors.fg,
                       borderwidth=0,
                       bordercolor=colors.entry_bg,  # Match background to hide borders
                       relief='flat',
                       padding=(6, 2),
                       font=("Segoe UI", 8))
        style.map('Small.TButton',
                 background=[('active', colors.hover_bg), ('pressed', colors.entry_bg)],
                 bordercolor=[('active', colors.entry_bg), ('pressed', colors.entry_bg)])
        
        self.clear_log_btn = ttk.Button(
            self.log_frame,
            text="Clear Log",
            command=self._clear_log,
            cursor='arrow',  # Regular cursor when disabled
            style='Small.TButton',
            state='disabled'  # Disabled initially when log is empty
        )
        self.clear_log_btn.grid(row=0, column=1, sticky=E, padx=(0, 6), pady=(0, 0))
        
        # Word wrap toggle checkbox (between Clear Log and Debug)
        settings = self._load_settings()
        word_wrap_default = settings.get("word_wrap", False)
        self.word_wrap_var = BooleanVar(value=word_wrap_default)
        word_wrap_toggle = Checkbutton(
            self.log_frame,
            text="Word wrap",
            variable=self.word_wrap_var,
            bg=log_frame_bg,
            fg=colors.fg,
            selectcolor=log_frame_bg,
            activebackground=log_frame_bg,
            activeforeground=colors.fg,
            font=("Segoe UI", 8),
            command=self._toggle_word_wrap
        )
        word_wrap_toggle.grid(row=0, column=2, sticky=E, padx=(0, 6), pady=(0, 0))
        self.word_wrap_toggle = word_wrap_toggle  # Store reference for theme updates
        
        # Debug toggle checkbox (right-aligned on same row as Status label)
        self.debug_mode_var = BooleanVar(value=False)
        debug_toggle = Checkbutton(
            self.log_frame,
            text="Debug",
            variable=self.debug_mode_var,
            bg=log_frame_bg,
            fg=colors.fg,
            selectcolor=log_frame_bg,
            activebackground=log_frame_bg,
            activeforeground=colors.fg,
            font=("Segoe UI", 8),
            command=self._toggle_debug_mode
        )
        debug_toggle.grid(row=0, column=3, sticky=E, padx=6, pady=(0, 0))
        self.debug_toggle = debug_toggle  # Store reference for theme updates
        
        # Configure column weights so controls stay on the right
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.columnconfigure(1, weight=0)
        self.log_frame.columnconfigure(2, weight=0)
        self.log_frame.columnconfigure(3, weight=0)
        
        # Inner frame for content (spans all columns to stay full width)
        # Search bar will be at the bottom (row=2), log_content at row=1
        log_content = Frame(self.log_frame, bg=log_frame_bg)
        log_content.grid(row=1, column=0, columnspan=4, sticky=(W, E, N, S), padx=6, pady=(0, 6))
        self.log_frame.rowconfigure(1, weight=1)  # Log content row expands
        # Column 0: Text widget, Column 1: vertical scrollbar
        log_content.columnconfigure(0, weight=1)
        log_content.columnconfigure(1, weight=0)
        log_content.rowconfigure(0, weight=1)
        
        # Apply word wrap setting to log text widget
        wrap_mode = WORD if word_wrap_default else 'none'
        
        # Text widget with custom dark-themed ttk scrollbar
        # Log background: dark mode uses bg (#1E1E1E), light mode uses entry_bg (#F5F5F5) to match URL field
        log_bg = colors.entry_bg if self.current_theme == 'light' else colors.bg
        self.log_text = Text(
            log_content,
            height=6,
            width=55,
            font=("Consolas", 8),
            wrap=wrap_mode,
            bg=log_bg,
            fg=colors.fg,
            insertbackground=colors.fg,
            selectbackground='#264F78',
            selectforeground='#FFFFFF',
            borderwidth=0,
            highlightthickness=0,
            relief='flat',
            state='disabled'  # Make read-only to prevent user editing
        )
        self.log_text.grid(row=0, column=0, sticky=(W, E, N, S))

        # Scrollbar: use default style in light mode, custom dark style in dark mode
        scrollbar_style = 'TScrollbar' if self.current_theme == 'light' else 'Dark.Vertical.TScrollbar'
        log_scrollbar = ttk.Scrollbar(
            log_content,
            orient='vertical',
            style='TScrollbar',  # Start with base style
            command=self.log_text.yview
        )
        self.log_scrollbar = log_scrollbar  # Store reference for theme updates
        log_scrollbar.grid(row=0, column=1, sticky=(N, S))
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        # Apply the correct style after creation (ensures proper initialization)
        if scrollbar_style != 'TScrollbar':
            self.root.update_idletasks()  # Force update
            log_scrollbar.configure(style=scrollbar_style)
        
        # Configure search tags for highlighting matches
        # Yellow for all matches
        self.log_text.tag_config(self.search_tag_name, background='#FFD700', foreground='#000000')
        # Green for current/selected match
        self.log_text.tag_config(self.current_match_tag_name, background='#00FF00', foreground='#000000')
        # Configure debug tag for hiding/showing debug messages (initially hidden since debug mode is off by default)
        # Use color matching to hide text (more compatible than elide)
        self.log_text.tag_config(self.debug_tag_name, foreground='#1E1E1E', background='#1E1E1E')  # Hidden by default (matches background)
        
        # Bind Ctrl+F globally to show search (works anywhere in the app)
        # Use Button-1 with add=True to set focus without interfering with text selection
        self.log_text.bind('<Button-1>', lambda e: self._on_log_Click(), add=True)  # Enable focus when Clicking log
        # Use bind_all to ensure Ctrl+F works regardless of which widget has focus
        self.root.bind_all('<Control-f>', lambda e: self._show_search_bar())  # Global Ctrl+F hotkey
        
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
            bg=log_frame_bg,  # Match log_frame background
            fg=colors.disabled_fg,
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
        self.expand_collapse_btn.bind("<Enter>", lambda e: self.expand_collapse_btn.config(fg=colors.hover_fg))
        self.expand_collapse_btn.bind("<Leave>", lambda e: self.expand_collapse_btn.config(fg=colors.disabled_fg))
        
        # Track if window is expanded
        self.is_expanded = False
        
        # Bind Click events to main frame and root to unfocus URL field when Clicking elsewhere
        def unfocus_url_field(event):
            """Unfocus URL field when Clicking on empty areas or non-interactive widgets."""
            # Get the widget that was Clicked
            widget_Clicked = event.widget
            
            # Check if Click is on URL field, path entry, browse button, clear button, expand button, log text, search bar, or any of their parent containers
            current = widget_Clicked
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
            
            # Only unfocus URL field if the Click is NOT on any interactive widget
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
            self.cancel_btn.config(state='disabled', cursor='arrow')  # Regular cursor when disabled
            
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
        # Cancel all pending timers
        self._cancel_all_timers()
        
        try:
            # Close console window
            kernel32 = ctypes.windll.kernel32
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                kernel32.FreeConsole()
        except (AttributeError, OSError):
            pass
        # Close the GUI
        self.root.destroy()
    
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
        """Helper method to extract numeric choice from folder structure string or return custom structure/template."""
        if not choice_str:
            return "4"  # Default
        # Check if it's already a number
        if choice_str in ["1", "2", "3", "4", "5"]:
            return choice_str
        # Try to match by display value
        for key, value in self.FOLDER_STRUCTURES.items():
            if choice_str == value:
                return key
        # Check if it's a custom template structure (new format)
        if hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
            for template_data in self.custom_structure_templates:
                formatted = self._format_custom_structure_template(template_data)
                if formatted == choice_str:
                    return template_data  # Return the template dict
        # Check if it's a custom structure (old format - will be migrated)
        if hasattr(self, 'custom_structures') and self.custom_structures:
            for structure in self.custom_structures:
                if self._format_custom_structure(structure) == choice_str:
                    return structure  # Return the list itself for custom structures
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
        if not hasattr(self, 'structure_menu'):
            return
            
        choice = self._extract_structure_choice(self.folder_structure_var.get())
        
        # Handle custom structures
        if isinstance(choice, list):
            # Old format custom structure
            display_value = self._format_custom_structure(choice)
        elif isinstance(choice, dict) and "template" in choice:
            # New template-based custom structure
            display_value = self._format_custom_structure_template(choice)
        elif isinstance(choice, str) and choice in ["1", "2", "3", "4", "5"]:
            # Default structure - get the display value using class constants
            display_value = self.FOLDER_STRUCTURES.get(choice, self.FOLDER_STRUCTURES[self.DEFAULT_STRUCTURE])
        else:
            # Fallback to default
            display_value = self.FOLDER_STRUCTURES[self.DEFAULT_STRUCTURE]
        
        # Set the StringVar - menu button text is automatically updated via textvariable binding
        self.folder_structure_var.set(display_value)
    
    def on_url_change(self):
        """Handle URL changes - fetch metadata for preview with debouncing."""
        # Get current content to check if it's empty
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            content = self.url_text_widget.get(1.0, END).strip()
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            content = self.url_var.get().strip()
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                content = ""
        else:
            content = ""
        
        # If content is empty, immediately clear preview and artwork (don't wait for debounce)
        if not content:
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
            self.format_suggestion_shown = False
            self.current_thumbnail_url = None
            self.current_bio_pic_url = None
            self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
            self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
            self.album_art_fetching = False
            self.update_preview()
            self.clear_album_art()
            # Cancel any pending timer since we've already handled the empty state
            if self.url_check_timer:
                self.root.after_cancel(self.url_check_timer)
                self.url_check_timer = None
            return
        
        # Process URL tags (convert URLs to styled tags) - reprocess to protect tags
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            self.root.after(50, self._process_url_tags)  # Small delay to let content settle
        
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
        """Update the clear button visibility based on content. Buttons are always visible."""
        if not hasattr(self, 'url_clear_btn'):
            return
        
        # Ensure clear button is always visible
        self.url_clear_btn.grid()
    
    def _update_url_expand_button(self):
        """Update the expand/collapse button icon based on current height."""
        if not hasattr(self, 'url_expand_btn'):
            return
        
        # Determine if URL field is in collapsed (1 line) or expanded state
        is_collapsed = True
        if self.url_text_widget:
            try:
                current_height = int(self.url_text_widget.cget('height'))
                is_collapsed = current_height <= 1
            except Exception:
                pass

        # Always show expand/collapse button and update icon based on current state
        self.url_expand_btn.grid()
        if is_collapsed:
            # Collapsed - show expand icon (⤢) - top-left to bottom-right
            self.url_expand_btn.config(text=self._get_icon('expand'))
        else:
            # Expanded - show collapse icon (⤡) - bottom-right to top-left
            self.url_expand_btn.config(text=self._get_icon('collapse'))
    
    def _toggle_url_field_mode(self):
        """Toggle between Entry (single-line) and ScrolledText (multi-line) modes."""
        if self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Currently in Entry mode - expand to ScrolledText
            content = self.url_var.get().strip()
            # Remove placeholder text if present
            if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                content = ""
            # Expand to multi-line
            self._expand_to_multiline(content)
        elif self.url_text_widget and self.url_text_widget.winfo_viewable():
            # Currently in ScrolledText mode - collapse to Entry
            self._collapse_to_entry()
    
    def _handle_paste_button_Click(self):
        """Handle paste button Click - replace selection if present, otherwise paste at end."""
        # Determine which mode we're in and paste accordingly
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            # ScrolledText mode - paste at next blank line (handles selection internally)
            self._paste_at_end_text()
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Entry mode - use the same handler as keyboard paste (handles selection correctly)
            # Create a dummy event object for the handler
            class DummyEvent:
                def __init__(self, widget):
                    self.widget = widget
            event = DummyEvent(self.url_entry_widget)
            self._handle_entry_paste(event)
    
    def _clear_url_field(self):
        """Clear the URL field and unfocus it."""
        # Cancel any pending URL check timer to prevent race conditions
        if self.url_check_timer:
            self.root.after_cancel(self.url_check_timer)
            self.url_check_timer = None
        
        if self.url_text_widget and self.url_text_widget.winfo_viewable():
            # ScrolledText is visible - clear it
            self.url_text_widget.delete(1.0, END)
            # Clear URL tag mapping and positions
            self.url_tag_mapping.clear()
            self.url_tag_positions.clear()
            self._update_text_placeholder_visibility()
            # Collapse to minimum height when clearing
            try:
                self.url_text_widget.config(height=1)
                self.url_text_height = 1
            except Exception:
                pass
            # Unfocus
            self.root.focus_set()
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Entry is visible - clear it and restore placeholder
            self.url_var.set("")
            self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.")
            # Unfocus
            self.root.focus_set()
        
        # Update clear button visibility
        self._update_url_clear_button()
        
        # Reset metadata and preview immediately
        self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None}
        self.format_suggestion_shown = False  # Reset format suggestion flag
        self.current_thumbnail_url = None
        self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
        self.album_art_fetching = False
        self.update_preview()
        self.clear_album_art()
        
        # Update URL count
        self._update_url_count_and_button()
        
        # Immediately check URL to ensure empty state is processed (this will clear preview/artwork)
        self._check_url()
    
    def _handle_right_Click_paste(self, event):
        """Handle right-Click paste in URL field (Entry widget) - replace selection if present, otherwise paste at end."""
        # Clear placeholder text if present before pasting
        if self.url_entry_widget:
            current_content = self.url_var.get()
            if current_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                # Clear placeholder text
                self.url_entry_widget.delete(0, END)
                self.url_entry_widget.config(foreground='#CCCCCC')  # Normal text color
                # Move cursor to end after clearing placeholder
                self.url_entry_widget.icursor(END)
        # Use the same handler as keyboard paste (handles selection correctly)
        self._handle_entry_paste(event)
    
    def _handle_right_Click_paste_entry(self, event):
        """Handle right-Click paste in Entry widget - directly paste without showing context menu."""
        self._handle_right_Click_paste(event)
        return "break"  # Prevent default context menu
    
    def _show_text_context_menu(self, event):
        """Handle right-Click paste in ScrolledText widget - directly paste without showing context menu."""
        # Directly paste instead of showing context menu
        self._handle_right_Click_paste_text(event)
        return "break"  # Prevent default context menu
    
    def _handle_right_Click_paste_text(self, event=None):
        """Handle right-Click paste in ScrolledText widget - always paste at next blank line."""
        # Save current content state before pasting (so we can undo back to it)
        self._save_content_state()
        # Paste at next blank line instead of at cursor
        self._paste_at_end_text()
    
    def _paste_at_end_entry(self):
        """Paste clipboard content at the end of Entry widget with space separator.
        
        Note: Selection replacement is handled in _handle_entry_paste().
        This function only handles the append-at-end behavior.
        """
        try:
            # Get clipboard content
            clipboard_text = self.root.clipboard_get()
            if not clipboard_text:
                return
            
            # Get current content (don't strip yet - need original for URL check)
            current_content_raw = self.url_var.get()
            current_content = current_content_raw.strip()
            # Skip placeholder text
            if current_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                current_content = ""
                current_content_raw = ""
            
            # Check if there are any URLs in current content
            # If no URLs exist, clear the field first to avoid issues with whitespace
            current_urls = self._extract_urls_from_content(current_content_raw)
            if not current_urls:
                # No URLs in field - clear it first to remove any whitespace that could cause issues
                self.url_var.set("")
                current_content = ""
            
            # Prepare new content: append with space separator if content exists
            if current_content:
                new_content = current_content + " " + clipboard_text.strip()
            else:
                new_content = clipboard_text.strip()
            
            # Set new content
            self.url_var.set(new_content)
            
            # Move cursor to end
            if self.url_entry_widget:
                self.url_entry_widget.icursor(END)
            
            # Check if paste contains newlines - if so, expand to multi-line
            if '\n' in clipboard_text:
                self._expand_to_multiline(new_content)
                # After expansion, save state and trigger URL check
                self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
            else:
                # Save new state after paste, then trigger URL check
                self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_url_clear_button()))
        except Exception:
            # If clipboard is empty or not text, ignore
            pass
    
    def _paste_at_end_text(self):
        """Paste clipboard content - replace selection if present, otherwise paste at next blank line."""
        try:
            # Get clipboard content
            clipboard_text = self.root.clipboard_get()
            if not clipboard_text:
                return
            
            if not self.url_text_widget:
                return
            
            # Hide placeholder immediately when pasting
            self._hide_text_placeholder()
            
            # Check if there's a selection
            try:
                sel_ranges = self.url_text_widget.tag_ranges("sel")
                if sel_ranges:
                    # There's a selection - replace it
                    sel_start = sel_ranges[0]
                    sel_end = sel_ranges[1]
                    
                    # Prepare clipboard content (split by newlines, filter empty)
                    clipboard_lines = clipboard_text.strip().split('\n')
                    text_to_insert = '\n'.join(line.strip() for line in clipboard_lines if line.strip())
                    
                    # Replace selection with clipboard content
                    self.url_text_widget.delete(sel_start, sel_end)
                    self.url_text_widget.insert(sel_start, text_to_insert)
                    
                    # Move cursor to end of pasted content
                    cursor_pos = f"{sel_start}+{len(text_to_insert)}c"
                    self.url_text_widget.mark_set("insert", cursor_pos)
                    
                    # Ensure trailing blank line
                    self._ensure_trailing_newline()
                    
                    # Process URL tags after paste
                    self.root.after(50, self._process_url_tags)
                    
                    # Save new state after paste, then trigger URL check
                    self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
                    return
            except Exception:
                # If selection handling fails, fall through to append behavior
                pass
            
            # No selection - always append to end with proper spacing
            # Extract URLs from clipboard
            import re
            url_pattern = r'(?:https?://)?[^\s]*bandcamp\.com[^\s,;]*'
            clipboard_urls = re.findall(url_pattern, clipboard_text, re.IGNORECASE)
            
            # Get current content
            current_content = self.url_text_widget.get(1.0, END).rstrip('\n')
            
            # Check if there are any URLs in current content
            # If no URLs exist, clear the field first to avoid issues with whitespace
            current_urls = self._extract_urls_from_content(current_content)
            if not current_urls:
                # No URLs in field - clear it first to remove any whitespace that could cause issues
                self.url_text_widget.delete(1.0, END)
                current_content = ""
            
            # If multiple URLs detected, insert them sequentially (one at a time)
            # This ensures auto-expand works correctly for each URL
            if clipboard_urls and len(clipboard_urls) > 1:
                # Sequential paste: insert URLs one at a time
                self._paste_urls_sequentially(clipboard_urls, current_content)
                return
            
            # Single URL or no URLs - use existing behavior
            # Prepare text to append: URLs separated by spaces, on same line if single-line, or new lines if multi-line
            if not current_content.strip():
                # Empty - just add the URLs
                if clipboard_urls:
                    # Add URLs with spaces between them
                    text_to_insert = ' '.join(url.rstrip(' \t,;') for url in clipboard_urls)
                else:
                    # No URLs found, add clipboard text as-is (might be non-URL text)
                    text_to_insert = clipboard_text.strip()
            else:
                # Has content - append with space separator
                if clipboard_urls:
                    # Add space and URLs
                    text_to_insert = ' ' + ' '.join(url.rstrip(' \t,;') for url in clipboard_urls)
                else:
                    # No URLs found, add clipboard text with space
                    text_to_insert = ' ' + clipboard_text.strip()
            
            # Insert at end of content
            self.url_text_widget.insert(END, text_to_insert)
            
            # Ensure trailing blank line
            self._ensure_trailing_newline()
            
            # Move cursor to end of inserted content
            self.url_text_widget.mark_set("insert", "end-1c")
            
            # Process URL tags after paste
            self.root.after(50, self._process_url_tags)
            
            # Save new state after paste, then trigger URL check
            self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        except Exception:
            # If clipboard is empty or not text, ignore
            pass
    
    def _paste_urls_sequentially(self, urls, current_content):
        """Paste multiple URLs one at a time to ensure auto-expand works correctly.
        
        Args:
            urls: List of URL strings to paste
            current_content: Current content in the URL field (before pasting)
        """
        if not urls or not self.url_text_widget:
            return
        
        # Clean URLs
        cleaned_urls = [url.rstrip(' \t,;') for url in urls if url.strip()]
        if not cleaned_urls:
            return
        
        # Determine if we need a separator before first URL
        needs_separator = bool(current_content.strip())
        
        # Insert URLs one at a time with delays
        def insert_next_url(index):
            """Insert the next URL in the sequence."""
            if index >= len(cleaned_urls):
                # All URLs inserted - final cleanup
                self._ensure_trailing_newline()
                self.root.after(50, self._process_url_tags)
                self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
                return
            
            url = cleaned_urls[index]
            
            # Add separator if needed (space before first URL if content exists, or newline for subsequent URLs)
            if index == 0 and needs_separator:
                separator = ' '
            elif index > 0:
                separator = ' '  # Space between URLs on same line
            else:
                separator = ''
            
            # Insert URL with separator
            text_to_insert = separator + url
            self.url_text_widget.insert(END, text_to_insert)
            
            # Move cursor to end
            self.url_text_widget.mark_set("insert", "end-1c")
            
            # Process tags for this URL (will trigger auto-expand)
            self.root.after(50, self._process_url_tags)
            
            # Schedule next URL insertion with delay (100ms between URLs)
            if index + 1 < len(cleaned_urls):
                self.root.after(100, lambda i=index+1: insert_next_url(i))
            else:
                # Last URL - finalize
                self.root.after(100, lambda: (
                    self._ensure_trailing_newline(),
                    self._process_url_tags(),
                    self._save_content_state(),
                    self._check_url(),
                    self._update_url_count_and_button(),
                    self._update_text_placeholder_visibility(),
                    self._update_url_clear_button()
                ))
        
        # Start inserting URLs
        insert_next_url(0)
    
    def _handle_entry_paste(self, event):
        """Handle paste in Entry widget - replace selection if present, otherwise append at end."""
        widget = event.widget if hasattr(event, 'widget') else self.url_entry_widget
        if not widget:
            widget = self.url_entry_widget
        
        # Save current content state before pasting
        self._save_content_state()
        
        # Get clipboard content
        try:
            clipboard_text = self.root.clipboard_get()
        except Exception:
            return "break"
        
        if not clipboard_text:
            return "break"
        
        # Get current cursor position BEFORE checking selection
        try:
            cursor_pos = widget.index("insert")
        except Exception:
            cursor_pos = None
        
        # Try to get and delete selection
        # Entry widgets: selection_range() is a SETTER, not a getter!
        # We need to use selection_present() to check, then get indices another way
        had_selection = False
        try:
            # Check if selection is present first
            if widget.selection_present():
                # Try to get selection indices using index() with "sel.first" and "sel.last"
                # These might work for Entry widgets (they work for Text widgets)
                try:
                    sel_start = widget.index("sel.first")
                    sel_end = widget.index("sel.last")
                    if sel_start is not None and sel_end is not None:
                        if sel_start > sel_end:
                            sel_start, sel_end = sel_end, sel_start
                        if sel_start != sel_end:
                            # Delete the selected text
                            widget.delete(sel_start, sel_end)
                            had_selection = True
                            # Cursor is now at sel_start after delete
                            cursor_pos = sel_start
                except Exception:
                    # "sel.first" and "sel.last" indices not available
                    pass
        except Exception:
            # No selection or selection_present() failed
            pass
        
        if had_selection:
            # There was a selection - insert at cursor position (which is now at sel_start)
            widget.insert("insert", clipboard_text.strip())
        else:
            # No selection - check if cursor is at end
            # widget.index("end") returns position AFTER last character
            # So if content has N chars, "end" is at position N, and cursor at end is at N-1 or N
            try:
                end_pos = widget.index("end")
                current_content = self.url_var.get()
                content_len = len(current_content)
                
                # Check if cursor is at or past the end of content
                # This handles both cursor at last char (end_pos - 1) and after last char (end_pos)
                if cursor_pos is not None:
                    if cursor_pos >= content_len or cursor_pos == end_pos - 1 or cursor_pos == end_pos:
                        # Cursor is at end - use our custom append behavior (adds space separator)
                        self._paste_at_end_entry()
                        return "break"
            except Exception:
                pass
            
            # Cursor is in the middle - insert at cursor position (normal paste behavior, no space)
            widget.insert("insert", clipboard_text.strip())
        
        # Handle newlines and updates
        new_content = self.url_var.get()
        if '\n' in clipboard_text:
            self._expand_to_multiline(new_content)
            self.root.after(10, lambda: (self._ensure_trailing_newline(), self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_text_placeholder_visibility(), self._update_url_clear_button()))
        else:
            self.root.after(10, lambda: (self._save_content_state(), self._check_url(), self._update_url_count_and_button(), self._update_url_clear_button()))
        return "break"  # Prevent default paste (we handled it ourselves)
    
    def _check_entry_paste(self):
        """Check if Entry content has newlines and expand if needed."""
        if self.url_entry_widget:
            content = self.url_var.get()
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                content = ""
            if '\n' in content:
                # Has newlines - expand to multi-line
                self._expand_to_multiline(content)
                # After expansion, trigger URL check (similar to right-Click paste)
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
            if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
                if current_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
        """Handle paste in ScrolledText widget - always paste at next blank line."""
        # Save current content state before pasting (so we can undo back to it)
        self._save_content_state()
        # Prevent default paste behavior
        # Paste at next blank line instead
        self._paste_at_end_text()
        return "break"  # Prevent default paste behavior
    
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
                if not previous_content or not previous_content.strip() or previous_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                    self.url_var.set("")
                    self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.")
                    # Immediately clear preview and artwork
                    self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
                    self.current_thumbnail_url = None
                    self.current_bio_pic_url = None
                    self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
                    self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
            self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.")
            # Immediately clear preview and artwork
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
            self.current_thumbnail_url = None
            self.current_bio_pic_url = None
            self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
            self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
                if not next_content or not next_content.strip() or next_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                    self.url_var.set("")
                    self._set_entry_placeholder(self.url_entry_widget, "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.")
                    # Immediately clear preview and artwork
                    self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
                    self.current_thumbnail_url = None
                    self.current_bio_pic_url = None
                    self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
                    self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
                self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
                self.current_thumbnail_url = None
                self.current_bio_pic_url = None
                self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
                self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
            self.current_thumbnail_url = None
            self.current_bio_pic_url = None
            self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
            self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
                self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
                self.current_thumbnail_url = None
                self.current_bio_pic_url = None
                self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
                self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
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
        
        # Auto-expand height to fit content (debounced to prevent bouncing during typing)
        # Cancel any pending auto-expand timer
        if self.auto_expand_timer:
            self.root.after_cancel(self.auto_expand_timer)
            self.auto_expand_timer = None
        # Set new timer with delay to only expand after user stops typing
        self.auto_expand_timer = self.root.after(250, self._auto_expand_url_text_height)
        
        # Reprocess URL tags to protect them and find new URLs (with debounce)
        self.root.after(100, self._process_url_tags)
        
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
            if hasattr(self, 'url_text_height') and self.url_text_height > 1:
                self.url_text_widget.config(height=self.url_text_height)
            else:
                self.url_text_widget.config(height=1)
            # Restore scroll position if we saved it
            if hasattr(self, '_saved_text_scroll_position'):
                try:
                    # Restore to saved position
                    self.url_text_widget.see(self._saved_text_scroll_position)
                    delattr(self, '_saved_text_scroll_position')
                except Exception:
                    pass
    
    def _on_text_focus_out(self):
        """Handle focus out on ScrolledText - deselect text (auto-collapse disabled to work with auto-expand)."""
        if self.url_text_widget:
            # Deselect any selected text when losing focus
            try:
                self.url_text_widget.tag_remove("sel", "1.0", "end")
            except Exception:
                pass
            
            # Auto-collapse disabled - let auto-expand feature manage the height
            # This prevents conflicts between auto-collapse and auto-expand
            return
    
    def _perform_text_collapse(self):
        """Perform the actual collapse of the text widget."""
        if not self.url_text_widget:
            return
        
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
                if current_height > 1:
                    self.url_text_height = current_height
            except Exception:
                pass
        
        # Collapse height to 1 line (hide extra lines but keep content)
        self.url_text_widget.config(height=1)
        
        # Don't scroll to top - maintain position when focus returns
        # The scroll position will be restored when focus returns
        
        # Update placeholder visibility based on content
        self._update_text_placeholder_visibility()
        
        # Force update to ensure height change is applied
        self.url_text_widget.update_idletasks()
    
    def _expand_to_multiline(self, initial_content=""):
        """Expand from Entry to ScrolledText for multi-line input."""
        # Paste button is now outside the URL field, so it's always visible
        # No need to hide/show it when switching between Entry and Text modes
        if not self.url_text_widget:
            return
        
        # Get content from Entry if not provided
        if not initial_content and self.url_entry_widget:
            initial_content = self.url_var.get()
            # Remove placeholder text if present
            if initial_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
        
        # Hide Entry container first - completely remove it from grid
        if hasattr(self, 'entry_container') and self.entry_container:
            try:
                self.entry_container.grid_forget()
            except:
                pass  # Already removed
        elif self.url_entry_widget:
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
        
        # Set height based on content (min 1, max 8) or use saved height
        if hasattr(self, 'url_text_height') and self.url_text_height > 1:
            height = self.url_text_height
        else:
            content = formatted_content.strip() if formatted_content else ""
            if content:
                lines = content.split('\n')
                line_count = len([line for line in lines if line.strip()])
                height = max(1, min(line_count + 1, 8))
            else:
                height = 1
            self.url_text_height = height
        self.url_text_widget.config(height=height)
        
        # Show resize handle when text widget is visible (place it just above bottom edge, centered)
        if hasattr(self, 'url_text_resize_handle'):
            self.url_text_resize_handle.place(relx=0.5, rely=1.0, width=405, anchor='s', height=5, y=-2, x=-9)
            self.url_text_resize_handle.lift()  # Bring to front so it's draggable
        
        # Paste button is now outside the URL field, so it's always visible
        # No need to hide/show it when switching between Entry and Text modes
        
        # Make sure the widget is actually visible
        self.url_text_widget.update_idletasks()
        text_frame.update_idletasks()
        self.url_container_frame.update_idletasks()
        
        # Focus the text widget
        self.url_text_widget.focus_set()
        
        # Update mode tracking
        self.url_field_mode = 'text'
        
        # Update expand/collapse button icon to collapse (⤡) since we're now in multi-line mode
        self._update_url_expand_button()
        
        # Update URL count and clear button
        self._update_url_count_and_button()
        self._update_url_clear_button()
    
    def _collapse_to_entry(self):
        """Legacy compatibility method.
        
        Previously this switched from ScrolledText back to a single-line Entry.
        Now that the URL field is always the ScrolledText widget, this method
        simply collapses the ScrolledText to its minimum height while keeping
        it visible, so any legacy calls do not break the layout.
        """
        try:
            # Just collapse the URL text widget; do not switch widgets.
            self._perform_text_collapse()
            self._update_url_expand_button()
        except Exception:
            pass
        
        # Trigger URL check
        self.root.after(10, self._check_url)
    
    def _count_urls_in_text(self, text):
        """Count number of bandcamp.com URLs in text (by counting 'bandcamp.com' occurrences)."""
        if not text or not text.strip():
            return 0
        # Skip placeholder text
        if text.strip() == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
            return 0
        # Count occurrences of 'bandcamp.com' (case-insensitive)
        text_lower = text.lower()
        count = text_lower.count('bandcamp.com')
        return count
    
    def _parse_bandcamp_url(self, url):
        """Parse Bandcamp URL into components.
        
        Args:
            url: Bandcamp URL string
            
        Returns:
            Tuple of (artist, name, url_type) or None if invalid
            url_type: 'album', 'track', or 'artist'
        """
        if not url or 'bandcamp.com' not in url.lower():
            return None
        
        try:
            from urllib.parse import urlparse
            import re
            
            # Clean URL (remove trailing whitespace, commas, semicolons)
            url = url.rstrip(' \t,;')
            
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            
            # Extract artist from subdomain
            artist = None
            if ".bandcamp.com" in hostname.lower():
                subdomain = hostname.lower().replace(".bandcamp.com", "")
                # Convert subdomain to readable format (handle hyphens, camelCase)
                if "-" in subdomain:
                    artist = " ".join(word.capitalize() for word in subdomain.split("-"))
                else:
                    # Handle camelCase or all-lowercase
                    words = re.findall(r'[a-z]+|[A-Z][a-z]*', subdomain)
                    if len(words) > 1:
                        artist = " ".join(word.capitalize() for word in words)
                    else:
                        artist = subdomain.capitalize()
            
            if not artist:
                return None
            
            # Extract path components
            path = parsed.path.strip('/')
            path_parts = [p for p in path.split('/') if p]
            
            # Determine type and extract name
            url_type = None
            name = None
            
            if not path_parts:
                # Root domain - artist page
                url_type = 'artist'
                name = None
            elif path_parts[0] == 'album' and len(path_parts) > 1:
                # Album page: /album/album-name
                url_type = 'album'
                name = path_parts[1]
                # Replace hyphens with spaces and capitalize
                name = " ".join(word.capitalize() for word in name.split("-"))
            elif path_parts[0] == 'track' and len(path_parts) > 1:
                # Track page: /track/track-name
                url_type = 'track'
                name = path_parts[1]
                # Replace hyphens with spaces and capitalize
                name = " ".join(word.capitalize() for word in name.split("-"))
            else:
                # Unknown format - treat as artist page
                url_type = 'artist'
                name = None
            
            return (artist, name, url_type)
        except Exception:
            return None
    
    def _get_tag_color_sequential(self, index):
        """Get a color for a URL tag based on sequential index.
        
        Colors are assigned in order to minimize duplicate colors when multiple URLs are present.
        Cycles through the color palette.
        
        Args:
            index: Sequential index (0, 1, 2, ...)
            
        Returns:
            Hex color string (e.g., '#2E4A5C')
        """
        # Use modulo to cycle through colors from current scheme
        color_index = index % len(self.current_tag_colors)
        return self.current_tag_colors[color_index]
    
    def _get_tag_text_color(self, bg_color):
        """Get appropriate text color (black or white) for a background color.
        
        Args:
            bg_color: Hex color string for background
            
        Returns:
            '#000000' or '#FFFFFF' based on background luminance
        """
        return self._get_text_color_for_background(bg_color)
    
    def _get_url_placeholder(self, url):
        """Get placeholder text for a URL tag before metadata is available.
        Uses URL parsing to extract artist/album/track name as a placeholder.
        
        Args:
            url: Full Bandcamp URL
            
        Returns:
            Placeholder display string like "Artist - Album" or "Artist", or None if invalid
        """
        # Use URL parsing to create placeholder immediately
        parsed = self._parse_bandcamp_url(url)
        if not parsed:
            return None
        
        artist, name, url_type = parsed
        
        if url_type == 'artist':
            return artist  # Use parsed artist as-is
        elif url_type == 'album' and name:
            return f"{artist} - {name}"  # Use parsed artist as-is
        elif url_type == 'track' and name:
            return f"{artist} - {name}"  # Use parsed artist as-is
        else:
            return artist  # Use parsed artist as-is
    
    def _url_to_tag_display(self, url):
        """Convert Bandcamp URL to tag display format using metadata when available.
        Uses only HTML extraction (stage 1) metadata for tags, not yt-dlp (stage 2) metadata.
        This prevents tag updates from overriding other URLs when more accurate metadata arrives.
        
        Args:
            url: Full Bandcamp URL
            
        Returns:
            Display string like "Artist - Album" or "Artist", or None if invalid
        """
        # Normalize URL for cache lookup (add protocol if missing, remove trailing slash, lowercase)
        normalized_url = url.rstrip(' \t,;')  # Clean first
        if not normalized_url.startswith(('http://', 'https://')):
            normalized_url = 'https://' + normalized_url
        normalized_url = normalized_url.rstrip('/').lower()
        
        # Check if we have tag metadata for this URL (only HTML extraction, stage 1)
        if normalized_url in self.url_tag_metadata_cache:
            metadata = self.url_tag_metadata_cache[normalized_url]
            artist = metadata.get('artist')
            album = metadata.get('album')
            title = metadata.get('title')
            
            # Determine URL type from metadata or URL structure
            parsed = self._parse_bandcamp_url(url)
            url_type = parsed[2] if parsed else None
            
            if url_type == 'artist' or (not album and not title):
                # Artist page or no album/title
                if artist:
                    return artist  # Use metadata artist as-is (preserves casing like "SHOLTO", "Ladytron", etc.)
                else:
                    # Fallback to URL parsing
                    parsed = self._parse_bandcamp_url(url)
                    if parsed:
                        return parsed[0]  # Use parsed artist as-is
                    return None
            elif url_type == 'album' and album:
                # Album page with metadata
                if artist:
                    return f"{artist} - {album}"  # Use metadata artist as-is
                else:
                    return album
            elif url_type == 'track' and title:
                # Track page with metadata
                if artist:
                    return f"{artist} - {title}"  # Use metadata artist as-is
                else:
                    return title
            elif album:
                # Has album metadata
                if artist:
                    return f"{artist} - {album}"  # Use metadata artist as-is
                else:
                    return album
            elif title:
                # Has title metadata
                if artist:
                    return f"{artist} - {title}"  # Use metadata artist as-is
                else:
                    return title
        
        # No metadata available - fallback to URL parsing
        parsed = self._parse_bandcamp_url(url)
        if not parsed:
            return None
        
        artist, name, url_type = parsed
        
        if url_type == 'artist':
            return artist  # Use parsed artist as-is
        elif url_type == 'album' and name:
            return f"{artist} - {name}"  # Use parsed artist as-is
        elif url_type == 'track' and name:
            return f"{artist} - {name}"  # Use parsed artist as-is
        else:
            return artist  # Use parsed artist as-is
    
    def _process_url_tags(self):
        """Process URLs in the URL text widget and convert them to styled tags.
        Similar to _process_template_tags but for URLs.
        """
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return
        
        # Set flag to prevent re-entry
        if hasattr(self, 'is_processing_url_tags') and self.is_processing_url_tags:
            return
        
        self.is_processing_url_tags = True
        
        try:
            text_widget = self.url_text_widget
            
            # Get current cursor position to restore later
            try:
                cursor_pos = text_widget.index(INSERT)
            except:
                cursor_pos = '1.0'
            
            # Get the current text content
            content = text_widget.get('1.0', END).rstrip('\n')
            
            # Save existing tag mappings before clearing (to preserve them)
            # Track each tag by its position to avoid mixing up URLs when multiple tags exist
            existing_tag_data = []  # List of (start_char_idx, end_char_idx, full_url, tag_display) tuples
            for tag_id, full_url in list(self.url_tag_mapping.items()):
                if tag_id in self.url_tag_positions:
                    start_pos, end_pos = self.url_tag_positions[tag_id]
                    try:
                        # Get the tag display text from widget
                        tag_display = text_widget.get(start_pos, end_pos)
                        # Calculate character indices from widget positions
                        # Get content before start_pos to calculate absolute character index
                        content_before_start = text_widget.get('1.0', start_pos)
                        start_char_idx = len(content_before_start.rstrip('\n'))
                        # Get content up to end_pos
                        content_before_end = text_widget.get('1.0', end_pos)
                        end_char_idx = len(content_before_end.rstrip('\n'))
                        existing_tag_data.append((start_char_idx, end_char_idx, full_url, tag_display))
                    except:
                        pass
            
            # Clear all existing URL tag styling
            for tag_id in list(self.url_tag_mapping.keys()):
                try:
                    text_widget.tag_delete(f"url_tag_{tag_id}")
                except:
                    pass
            self.url_tag_mapping.clear()
            self.url_tag_positions.clear()
            
            # Find all Bandcamp URLs using regex
            import re
            # Pattern matches URLs with or without protocol, containing bandcamp.com
            url_pattern = r'(?:https?://)?[^\s]*bandcamp\.com[^\s,;]*'
            url_matches = list(re.finditer(url_pattern, content, re.IGNORECASE))
            
            # Also check tag mapping for URLs that have been converted to tags
            # Note: Tags are only created/updated when HTML extraction (stage 1) completes
            # They are not updated when yt-dlp (stage 2) metadata arrives to prevent overriding other URLs
            tag_url_matches = []
            for tag_id, full_url in list(self.url_tag_mapping.items()):
                # Normalize URL for lookup
                normalized_tag_url = full_url.rstrip(' \t,;')
                if not normalized_tag_url.startswith(('http://', 'https://')):
                    normalized_tag_url = 'https://' + normalized_tag_url
                normalized_tag_url = normalized_tag_url.rstrip('/').lower()
                
                # Check if we have tag metadata for this URL (only HTML extraction, stage 1)
                if normalized_tag_url in self.url_tag_metadata_cache:
                    # Find where this tag is in the content (by finding the tag display)
                    if tag_id in self.url_tag_positions:
                        start_pos, end_pos = self.url_tag_positions[tag_id]
                        try:
                            tag_display = text_widget.get(start_pos, end_pos)
                            # Find this tag display in content
                            escaped = re.escape(tag_display)
                            for match in re.finditer(escaped, content):
                                # Check if this overlaps with any URL match
                                overlaps = False
                                for url_match in url_matches:
                                    if not (match.end() <= url_match.start() or match.start() >= url_match.end()):
                                        overlaps = True
                                        break
                                if not overlaps:
                                    tag_url_matches.append((match.start(), match.end(), full_url))
                        except:
                            pass
            
            # Combine URL matches and tag URL matches
            matches = url_matches + [re.match(r'.*', content[m.start():m.end()]) for m in tag_url_matches]
            # Actually, let's just use url_matches for now and handle tag updates separately
            matches = url_matches
            
            # Also find existing tag displays that we need to preserve
            # Use position-based matching to ensure each tag keeps its correct URL
            tag_display_matches = []
            for start_char_idx, end_char_idx, full_url, tag_display in existing_tag_data:
                # Check if this position overlaps with any URL match
                overlaps = False
                for url_match in matches:
                    if not (end_char_idx <= url_match.start() or start_char_idx >= url_match.end()):
                        overlaps = True
                        break
                if not overlaps:
                    # Check if the content at this position still matches the tag display
                    try:
                        content_at_pos = content[start_char_idx:end_char_idx]
                        if content_at_pos == tag_display:
                            # Position and content match - preserve this tag
                            tag_display_matches.append((start_char_idx, end_char_idx, full_url, tag_display))
                    except:
                        # If position is out of bounds, skip this tag
                        pass
            
            # Build list of replacements first
            replacements = []
            
            # Process new URLs (convert to tag display)
            # Create placeholder tags immediately, update with metadata when available
            for match in matches:
                start_idx = match.start()
                end_idx = match.end()
                full_url = match.group(0).rstrip(' \t,;')  # Clean trailing punctuation
                
                # Normalize URL for consistent cache lookup (add protocol if missing, normalize)
                normalized_url_for_lookup = full_url.rstrip('/').lower()
                if not normalized_url_for_lookup.startswith(('http://', 'https://')):
                    normalized_url_for_lookup = 'https://' + normalized_url_for_lookup
                normalized_url_for_lookup = normalized_url_for_lookup.rstrip('/').lower()
                
                # Check if HTML extraction metadata is available
                if normalized_url_for_lookup in self.url_tag_metadata_cache:
                    # Convert to tag display format (will use HTML extraction metadata)
                    tag_display = self._url_to_tag_display(full_url)
                    if tag_display:
                        # Add spaces at start and end so spaces are part of the colored background
                        tag_display_with_spaces = f"  {tag_display}  "
                        replacements.append((start_idx, end_idx, full_url, tag_display_with_spaces))
                else:
                    # Metadata not available yet - create placeholder tag immediately
                    # Extract a simple identifier from the URL for the placeholder
                    placeholder_text = self._get_url_placeholder(full_url)
                    if placeholder_text:
                        placeholder_with_spaces = f"  {placeholder_text}  "
                        replacements.append((start_idx, end_idx, full_url, placeholder_with_spaces))
            
            # Add existing tag displays - allow update when HTML extraction (stage 1) completes
            for start_idx, end_idx, full_url, tag_display in tag_display_matches:
                # Check if this overlaps with any URL replacement
                overlaps = False
                for rep_start, rep_end, _, _ in replacements:
                    if not (end_idx <= rep_start or start_idx >= rep_end):
                        overlaps = True
                        break
                if not overlaps:
                    # Check if HTML extraction metadata is available and would give us a better display
                    normalized_url = full_url.rstrip(' \t,;')
                    if not normalized_url.startswith(('http://', 'https://')):
                        normalized_url = 'https://' + normalized_url
                    normalized_url = normalized_url.rstrip('/').lower()
                    
                    if normalized_url in self.url_tag_metadata_cache:
                        # HTML extraction metadata is available - get updated display
                        updated_display = self._url_to_tag_display(full_url)
                        if updated_display and updated_display != tag_display:
                            # HTML extraction gives us a better display - use it (only from stage 1, not stage 2)
                            # Add spaces at start and end so spaces are part of the colored background
                            updated_display_with_spaces = f"  {updated_display}  "
                            replacements.append((start_idx, end_idx, full_url, updated_display_with_spaces))
                        else:
                            # Display is still correct, just needs styling
                            # Add spaces at start and end so spaces are part of the colored background
                            # Strip existing spaces first to avoid double-spacing
                            tag_display_clean = tag_display.strip()
                            tag_display_with_spaces = f"  {tag_display_clean}  "
                            replacements.append((start_idx, end_idx, full_url, tag_display_with_spaces))
                    else:
                        # No HTML extraction metadata yet - preserve existing display
                        # (Tag was likely created from URL parsing, will update when HTML extraction completes)
                        # Add spaces at start and end so spaces are part of the colored background
                        # Strip existing spaces first to avoid double-spacing
                        tag_display_clean = tag_display.strip()
                        tag_display_with_spaces = f"  {tag_display_clean} "
                        replacements.append((start_idx, end_idx, full_url, tag_display_with_spaces))
            
            if not replacements:
                # No URLs or tags found, just restore cursor
                try:
                    text_widget.mark_set(INSERT, cursor_pos)
                    text_widget.see(INSERT)
                except:
                    pass
                return
            
            # Sort by start position (ascending for forward replacement)
            replacements.sort(key=lambda x: x[0])
            
            # Build new content string with all replacements (from start to end)
            # Track cumulative position adjustment
            new_content = content
            cumulative_adjustment = 0
            tag_positions = []  # Store (new_start, new_end, full_url, tag_display) for styling
            
            for start_idx, end_idx, full_url, tag_display in replacements:
                # Calculate adjusted positions
                adjusted_start = start_idx + cumulative_adjustment
                adjusted_end = end_idx + cumulative_adjustment
                
                # Get current text at this position
                current_text = new_content[adjusted_start:adjusted_end]
                
                # Only replace if the text is different (avoid replacing tag displays with themselves)
                if current_text != tag_display:
                    # Replace in string
                    new_content = new_content[:adjusted_start] + tag_display + new_content[adjusted_end:]
                    
                    # Calculate new positions after replacement
                    new_start = adjusted_start
                    new_end = adjusted_start + len(tag_display)
                    
                    # Update cumulative adjustment
                    length_diff = len(tag_display) - (end_idx - start_idx)
                    cumulative_adjustment += length_diff
                else:
                    # Text is already correct (tag display), just calculate positions
                    new_start = adjusted_start
                    new_end = adjusted_end
                    # No adjustment needed since we didn't replace
                
                tag_positions.append((new_start, new_end, full_url, tag_display))
            
            # Replace entire widget content at once
            text_widget.delete('1.0', END)
            text_widget.insert('1.0', new_content)
            
            # All URLs are now converted to tags (either with metadata or as placeholders)
            # No need to hide URLs anymore
            
            # Now apply tags and build mapping
            tag_id_counter = 0
            for new_start, new_end, full_url, tag_display in tag_positions:
                try:
                    # Convert to widget positions
                    start_pos = text_widget.index(f'1.0 + {new_start} chars')
                    end_pos = text_widget.index(f'1.0 + {new_end} chars')
                    
                    # Store tag position and full URL mapping
                    tag_id = f"tag_{tag_id_counter}"
                    tag_id_counter += 1
                    self.url_tag_mapping[tag_id] = full_url
                    self.url_tag_positions[tag_id] = (start_pos, end_pos)
                    
                    # Style the tag text with sequential color assignment
                    tag_color = self._get_tag_color_sequential(tag_id_counter - 1)
                    tag_text_color = self._get_tag_text_color(tag_color)
                    text_widget.tag_add(f"url_tag_{tag_id}", start_pos, end_pos)
                    text_widget.tag_config(f"url_tag_{tag_id}", 
                                         background=tag_color, 
                                         foreground=tag_text_color,
                                         font=("Segoe UI", 9, "bold"),
                                         relief='flat',
                                         borderwidth=0)
                except Exception:
                    # If styling fails, skip this tag (but URL is still in mapping)
                    continue
            
            # Restore cursor position
            try:
                text_widget.mark_set(INSERT, cursor_pos)
                text_widget.see(INSERT)
            except:
                pass
            
            # Auto-expand widget height to fit content (up to max height)
            # Use after() to ensure widget is updated before calculating height
            self.root.after(10, self._auto_expand_url_text_height)
        finally:
            # Clear processing flag
            self.is_processing_url_tags = False
    
    def _remove_url_tag(self, tag_id):
        """Remove a URL tag when backspace/delete is used.
        Similar to _remove_tag_from_template but for URL tags."""
        if tag_id not in self.url_tag_positions:
            return
        
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return
        
        start_pos, end_pos = self.url_tag_positions[tag_id]
        text_widget = self.url_text_widget
        
        # Delete the tag text
        try:
            text_widget.delete(start_pos, end_pos)
        except:
            return
        
        # Clean up references
        if tag_id in self.url_tag_positions:
            del self.url_tag_positions[tag_id]
        if tag_id in self.url_tag_mapping:
            del self.url_tag_mapping[tag_id]
        
        # Set cursor to where tag was
        try:
            text_widget.mark_set(INSERT, start_pos)
            text_widget.see(INSERT)
        except:
            pass
        
        # Reprocess tags to update styling and find any new URLs
        self.root.after(50, self._process_url_tags)
        
        # Update URL count
        self._update_url_count_and_button()
        
        # Focus back to text widget
        text_widget.focus_set()
    
    def _handle_url_tag_backspace(self, event):
        """Handle backspace key - delete entire tag if cursor is in a tag."""
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return None
        
        # Process tags first to ensure positions are current
        # But don't wait - check current positions
        text_widget = self.url_text_widget
        cursor_pos = text_widget.index(INSERT)
        
        # Check if cursor is inside or at the start of a tag
        for tag_id, (start, end) in list(self.url_tag_positions.items()):
            try:
                if text_widget.compare(cursor_pos, ">=", start) and text_widget.compare(cursor_pos, "<=", end):
                    # Cursor is inside the tag, delete the entire tag
                    self._remove_url_tag(tag_id)
                    return "break"
            except:
                pass
        return None
    
    def _handle_url_tag_delete(self, event):
        """Handle delete key - delete entire tag if cursor is in a tag."""
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return None
        
        # Process tags first to ensure positions are current
        # But don't wait - check current positions
        text_widget = self.url_text_widget
        cursor_pos = text_widget.index(INSERT)
        
        # Check if cursor is inside or at the start of a tag
        for tag_id, (start, end) in list(self.url_tag_positions.items()):
            try:
                if text_widget.compare(cursor_pos, ">=", start) and text_widget.compare(cursor_pos, "<=", end):
                    # Cursor is inside the tag, delete the entire tag
                    self._remove_url_tag(tag_id)
                    return "break"
            except:
                pass
        return None
    
    def _extract_urls_from_content(self, content):
        """Extract URLs from content string, handling both single and multi-line input.
        Also handles concatenated URLs (no separator) on the same line.
        If content contains URL tags, reconstructs full URLs from tag mapping."""
        if not content or not content.strip():
            return []
        # Skip placeholder text
        if content.strip() == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
            return []
        
        # Check if we have URL tags (tag mapping exists and has entries)
        if self.url_tag_mapping:
            # Reconstruct URLs from tags
            # Extract URLs from tag mapping (these are the full URLs)
            all_urls = []
            for tag_id, full_url in self.url_tag_mapping.items():
                all_urls.append(full_url)
            # Also check for any non-tagged URLs in content (fallback for URLs that weren't converted)
            import re
            url_pattern = r'(?:https?://)?[^\s]*bandcamp\.com[^\s,;]*'
            remaining_matches = re.findall(url_pattern, content, re.IGNORECASE)
            for match in remaining_matches:
                url = match.rstrip(' \t,;')
                if 'bandcamp.com' in url.lower() and url not in all_urls:
                    all_urls.append(url)
            return all_urls if all_urls else []
        
        # No tags - use existing extraction logic
        import re
        # Split by lines first
        lines = content.split('\n')
        all_urls = []
        
        for line in lines:
            line = line.strip()
            if not line or line == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
                # Single URL (or no URL) - check if it's a valid Bandcamp URL
                # Also handle URLs without protocol
                url = line.rstrip(' \t,;')
                if 'bandcamp.com' in url.lower():
                    all_urls.append(url)
        
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
            if text_content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                return []
            # Split by lines and filter out empty lines and placeholder
            urls = [line.strip() for line in text_content.split('\n') 
                   if line.strip() and line.strip() != "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste."]
            return urls
        elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
            # Fallback to Entry widget
            content = self.url_var.get().strip()
            if not content:
                return []
            # Skip placeholder text
            if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
                return []
            # Check if it has newlines (shouldn't happen in Entry, but handle it)
            if '\n' in content:
                urls = [line.strip() for line in content.split('\n') 
                       if line.strip() and line.strip() != "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste."]
                return urls
            return [content] if content else []
        return []
    
    def _validate_and_clean_urls(self, text):
        """Validate and clean URLs: split multiple URLs per line, remove empty lines, trim."""
        if not text or not text.strip():
            return ""
        
        # Remove placeholder text if present
        if text.strip() == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
            return ""
        
        import re
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip placeholder text
            if line == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
        
        # Classify URLs as tracks or albums
        track_count = 0
        album_count = 0
        for url in unique_urls:
            parsed = self._parse_bandcamp_url(url)
            if parsed:
                url_type = parsed[2]  # url_type is the third element
                if url_type == 'track':
                    track_count += 1
                elif url_type == 'album':
                    album_count += 1
                # For 'artist' type, we'll treat it as album (discography mode)
                else:
                    album_count += 1
        
        # Update batch mode
        self.batch_mode = (url_count > 1)
        
        # Update download button text
        if hasattr(self, 'download_btn'):
            # Check if discography mode is enabled (for single URL or no URL)
            if url_count <= 1 and hasattr(self, 'download_discography_var') and self.download_discography_var.get():
                self.download_btn.config(text="Download Discography")
            elif track_count > 0 and album_count == 0:
                # Only tracks
                if track_count == 1:
                    self.download_btn.config(text="Download Single")
                else:
                    self.download_btn.config(text=f"Download {track_count} Singles")
            elif track_count == 0 and album_count > 0:
                # Only albums
                if album_count == 1:
                    self.download_btn.config(text="Download Album")
                else:
                    self.download_btn.config(text=f"Download {album_count} Albums")
            elif track_count > 0 and album_count > 0:
                # Mixed tracks and albums
                total = track_count + album_count
                if total == 1:
                    self.download_btn.config(text="Download Album")  # Fallback, shouldn't happen
                else:
                    self.download_btn.config(text=f"Download {total} Items")
            else:
                # No valid URLs or unknown types
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
        # Use last URL (most recently pasted) for preview instead of first URL
        url = unique_urls[-1] if unique_urls else ""
        
        # Strip whitespace and check if URL is actually empty
        url = url.strip() if url else ""
        
        # Reset metadata if URL is empty or just whitespace
        if not url or url == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
            # Cancel any in-flight artwork fetches
            self.artwork_fetch_id += 1
            self.current_url_being_processed = None
            self.album_info = {"artist": None, "album": None, "title": None, "thumbnail_url": None, "detected_format": None, "year": None}
            self.format_suggestion_shown = False  # Reset format suggestion flag
            self.current_thumbnail_url = None
            self.current_bio_pic_url = None
            self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
            self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
            self.album_art_fetching = False
            # Clear split album detection state to reset preview formatting
            if hasattr(self, 'download_info'):
                self.download_info = {}
            if hasattr(self, 'downloaded_files'):
                self.downloaded_files = set()
            self.update_preview()
            self.clear_album_art()
            return
        
        # Clear split album detection state when checking a new URL
        # This ensures preview resets to normal format until split album is detected for the new album
        if hasattr(self, 'download_info'):
            self.download_info = {}
        if hasattr(self, 'downloaded_files'):
            self.downloaded_files = set()
        
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
            self.current_bio_pic_url = None
            self.preloaded_album_art_image = None  # Clear preloaded cache when URL is cleared
            self.preloaded_album_art_pil = None  # Clear preloaded PIL image cache
            self.album_art_fetching = False
        
        # Fetch metadata in background thread (only for last URL for preview)
        threading.Thread(target=self.fetch_album_metadata, args=(url,), daemon=True).start()
        
        # Also fetch metadata for all other URLs in the field (for tag display)
        # Fetch all URLs except the last one (which was already fetched for preview above)
        if len(unique_urls) > 1:
            for other_url in unique_urls[:-1]:  # All URLs except the last one (includes first URL at index 0)
                other_url = other_url.strip()
                normalized_other_url = other_url.rstrip('/').lower()
                # Only fetch if we don't already have metadata for this URL
                if normalized_other_url not in self.url_metadata_cache and "bandcamp.com" in other_url.lower():
                    threading.Thread(target=self.fetch_album_metadata, args=(other_url,), daemon=True).start()
    
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
                    html_content = response.read().decode('utf-8', errors='ignore')
                
                artist = None
                album = None
                year = None
                
                # Extract artist - look for various patterns (ordered by reliability)
                artist_patterns = [
                    # Open Graph meta tags (most reliable)
                    r'<meta[^>]*property=["\']og:music:musician["\'][^>]*content=["\']([^"\']+)',
                    r'property=["\']music:musician["\'][^>]*content=["\']([^"\']+)',
                    # Extract from title tag (format: "Album by Artist" or "Album | Artist")
                    r'<title>([^<]+)</title>',
                    # "by Artist" patterns with various HTML structures
                    r'by\s+<a[^>]*>([^<]+)</a>',
                    r'by\s+<span[^>]*>([^<]+)</span>',
                    r'by\s+([A-Z][a-zA-Z\s]+?)(?:\s*</|</a>|</span>|</h)',
                    # More flexible "by" pattern - matches "by Artist" with any HTML structure
                    r'>\s*by\s+([A-Z][a-zA-Z\s]{2,}?)(?:\s*<|</)',
                    # Pattern for heading structures like "### by Sam Webster"
                    r'<h[123][^>]*>\s*by\s+([A-Z][a-zA-Z\s]+?)(?:\s*</h)',
                    # Artist class elements
                    r'<a[^>]*class=["\'][^"]*artist[^"]*["\'][^>]*>([^<]+)</a>',
                    r'<span[^>]*class=["\'][^"]*artist[^"]*["\'][^>]*>([^<]+)',
                    # Heading patterns (h2, h3 with "by")
                    r'<h[23][^>]*>.*?by\s+([A-Z][a-zA-Z\s]+?)(?:</|</h)',
                ]
                
                for pattern in artist_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        artist = match.group(1).strip()
                        # Decode HTML entities (e.g., &#39; -> ', &amp; -> &)
                        artist = html.unescape(artist)
                        # If extracted from title, clean it up
                        if pattern.startswith(r'<title>'):
                            # Title format examples:
                            # "Super Flappy Golf (Game Soundtrack) by Sam Webster"
                            # "Album Name | Artist Name"
                            # "Album Name - Artist Name on Bandcamp"
                            # Extract artist part after "by", "|", or "-"
                            title_text = artist
                            # Try to extract artist from "by Artist" pattern
                            by_match = re.search(r'\s+by\s+([^-|]+?)(?:\s*[-|]|\s+on\s+Bandcamp|$)', title_text, re.IGNORECASE)
                            if by_match:
                                artist = by_match.group(1).strip()
                            else:
                                # Try "| Artist" or "- Artist" pattern
                                pipe_match = re.search(r'[-|]\s*([^-|]+?)(?:\s*on\s+Bandcamp|$)', title_text, re.IGNORECASE)
                                if pipe_match:
                                    artist = pipe_match.group(1).strip()
                                else:
                                    # If no pattern matches, don't use title extraction for artist
                                    artist = None
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
                    match = re.search(pattern, html_content, re.IGNORECASE)
                    if match:
                        album = match.group(1).strip()
                        # Decode HTML entities (e.g., &#39; -> ', &amp; -> &)
                        album = html.unescape(album)
                        # Clean up common suffixes
                        album = re.sub(r'\s*[-|]\s*by\s+.*$', '', album, flags=re.IGNORECASE)
                        album = re.sub(r'\s*on\s+Bandcamp.*$', '', album, flags=re.IGNORECASE)
                        if album:
                            break
                
                # Extract year/release date - look for various patterns
                year_patterns = [
                    r'released\s+[A-Za-z]+\s+\d+,\s+(\d{4})',  # "released June 5, 2025"
                    r'release[^<]*(\d{4})',  # "release ... 2025"
                    r'<meta[^>]*property=["\']music:release_date["\'][^>]*content=["\']([^"\']+)',  # Open Graph release date
                    r'<meta[^>]*property=["\']og:music:release_date["\'][^>]*content=["\']([^"\']+)',  # Open Graph release date
                    r'<time[^>]*datetime=["\']([^"\']+)["\']',  # HTML5 time element
                ]
                
                for pattern in year_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE)
                    if match:
                        date_str = match.group(1).strip()
                        # Extract year from date string (could be YYYY-MM-DD, YYYYMMDD, or just YYYY)
                        year_match = re.search(r'(\d{4})', date_str)
                        if year_match:
                            year = year_match.group(1)
                            break
                
                # Try extracting artist from URL if not found (last resort)
                if not artist and "bandcamp.com" in url.lower():
                    try:
                        parsed = urlparse(url)
                        hostname = parsed.hostname or ""
                        if ".bandcamp.com" in hostname:
                            subdomain = hostname.replace(".bandcamp.com", "")
                            
                            # First try splitting by hyphens (most common)
                            if "-" in subdomain:
                                artist = " ".join(word.capitalize() for word in subdomain.split("-"))
                            else:
                                # Handle camelCase or all-lowercase subdomains
                                import re
                                # Method 1: Split on capital letters (camelCase like "SamWebster")
                                words = re.findall(r'[a-z]+|[A-Z][a-z]*', subdomain)
                                if len(words) > 1:
                                    artist = " ".join(word.capitalize() for word in words)
                                else:
                                    # Method 2: Try to detect word boundaries in all-lowercase strings
                                    # This is heuristic - look for common word patterns
                                    # For subdomains like "samwebster", try to split on common boundaries
                                    # Common patterns: consonant-vowel transitions that might indicate word breaks
                                    # This is imperfect but better than nothing
                                    subdomain_lower = subdomain.lower()
                                    # Try common word separators that might be missing
                                    # For "samwebster", we can't reliably split without context
                                    # So we'll just capitalize it as-is (better than nothing)
                                    # Note: This is a fallback - HTML extraction should catch it first
                                    artist = subdomain.capitalize()
                    except:
                        pass
                
                # Try to extract first track title and number from HTML (fast path)
                first_track_title = None
                first_track_number = None
                
                # Look for track list in HTML - Bandcamp typically has tracks in a list
                # Pattern 1: Look for tracklist items with track numbers (HTML structure)
                tracklist_patterns = [
                    r'<li[^>]*class=["\'][^"]*track[^"]*["\'][^>]*>.*?<span[^>]*class=["\'][^"]*track-number[^"]*["\'][^>]*>(\d+)</span>.*?<span[^>]*class=["\'][^"]*track-title[^"]*["\'][^>]*>([^<]+)</span>',
                    r'<div[^>]*class=["\'][^"]*track[^"]*["\'][^>]*>.*?<span[^>]*class=["\'][^"]*track-number[^"]*["\'][^>]*>(\d+)</span>.*?<span[^>]*class=["\'][^"]*track-title[^"]*["\'][^>]*>([^<]+)</span>',
                    r'data-track-number=["\'](\d+)["\'][^>]*data-track-title=["\']([^"\']+)["\']',
                    r'track_number["\']:\s*(\d+).*?track_title["\']:\s*["\']([^"\']+)["\']',
                ]
                
                for pattern in tracklist_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        try:
                            first_track_number = int(match.group(1))
                            first_track_title = match.group(2).strip()
                            # Decode HTML entities (e.g., &#39; -> ', &amp; -> &)
                            first_track_title = html.unescape(first_track_title)
                            if first_track_title:
                                break
                        except (ValueError, IndexError):
                            continue
                
                # Pattern 2: Look for JavaScript data structures (Bandcamp embeds track data in JS)
                if not first_track_title:
                    # Look for tracklist in JavaScript objects/arrays
                    js_track_patterns = [
                        r'trackinfo["\']?\s*[:=]\s*\[.*?\{[^}]*"title"\s*:\s*["\']([^"\']+)["\']',
                        r'"tracks"\s*:\s*\[.*?\{[^}]*"title"\s*:\s*["\']([^"\']+)["\']',
                        r'trackList["\']?\s*[:=]\s*\[.*?\{[^}]*"title"\s*:\s*["\']([^"\']+)["\']',
                    ]
                    for pattern in js_track_patterns:
                        match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
                        if match:
                            try:
                                first_track_title = match.group(1).strip()
                                # Decode HTML entities (e.g., &#39; -> ', &amp; -> &)
                                first_track_title = html.unescape(first_track_title)
                                if first_track_title:
                                    break
                            except (ValueError, IndexError):
                                continue
                
                # If no track number found but we found a title, try to find track number separately
                if first_track_title and not first_track_number:
                    # Look for first track number in various formats
                    track_num_patterns = [
                        r'<span[^>]*class=["\'][^"]*track-number[^"]*["\'][^>]*>(\d+)</span>',
                        r'data-track-number=["\'](\d+)["\']',
                        r'track_number["\']:\s*(\d+)',
                        r'"track"\s*:\s*(\d+)',  # JavaScript format
                        r'"track_number"\s*:\s*(\d+)',  # JavaScript format
                    ]
                    for pattern in track_num_patterns:
                        match = re.search(pattern, html_content, re.IGNORECASE)
                        if match:
                            try:
                                first_track_number = int(match.group(1))
                                break
                            except (ValueError, IndexError):
                                continue
                
                # Store metadata in cache for this URL (normalize consistently)
                normalized_url = url.rstrip(' \t,;')
                if not normalized_url.startswith(('http://', 'https://')):
                    normalized_url = 'https://' + normalized_url
                normalized_url = normalized_url.rstrip('/').lower()
                metadata = {
                    "artist": artist,
                    "album": album,
                    "title": None,
                    "thumbnail_url": None,
                    "year": year,
                    "first_track_title": first_track_title,
                    "first_track_number": first_track_number
                }
                self.url_metadata_cache[normalized_url] = metadata
                # Also store in tag metadata cache (only HTML extraction, stage 1)
                self.url_tag_metadata_cache[normalized_url] = metadata
                
                # Update preview immediately if we got data from HTML (for first URL)
                if artist or album:
                    self.album_info = {
                        "artist": artist or "Artist",
                        "album": album or "Album",
                        "title": "Track",
                        "thumbnail_url": None,
                        "year": year,  # Store year if found
                        "first_track_title": first_track_title,  # Store first track title if found
                        "first_track_number": first_track_number,  # Store first track number if found
                        "track_titles": [first_track_title] if first_track_title else []  # Store track titles for split album detection
                    }
                    self.root.after(0, self.update_preview)
                    # Also update Additional Settings dialog preview if open
                    if hasattr(self, '_additional_settings_dialogs'):
                        for dialog_ref in self._additional_settings_dialogs:
                            try:
                                if dialog_ref['dialog'].winfo_exists():
                                    dialog_ref['update_func']()
                            except:
                                pass
                    
                    # Update tags to reflect new metadata (only from HTML extraction, stage 1)
                    self.root.after(100, self._process_url_tags)
                    
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
                    
                    # Extract artist, album, and year info
                    artist = None
                    album = None
                    year = None
                    artist_from_metadata = None  # Track if artist came from metadata (not URL fallback)
                    
                    if info:
                        # Track whether artist came from actual metadata (not URL fallback)
                        artist_from_metadata = (info.get("artist") or 
                                               info.get("uploader") or 
                                               info.get("channel") or
                                               info.get("creator"))
                        artist = artist_from_metadata
                        
                        # Try extracting from URL if not found (last resort)
                        # But mark it as URL fallback so we don't overwrite HTML extraction results
                        artist_from_url = None
                        if not artist and "bandcamp.com" in url.lower():
                            try:
                                from urllib.parse import urlparse
                                import re
                                parsed = urlparse(url)
                                hostname = parsed.hostname or ""
                                if ".bandcamp.com" in hostname:
                                    subdomain = hostname.replace(".bandcamp.com", "")
                                    
                                    # First try splitting by hyphens (most common)
                                    if "-" in subdomain:
                                        artist_from_url = " ".join(word.capitalize() for word in subdomain.split("-"))
                                    else:
                                        # Handle camelCase (e.g., "samwebster" -> "Sam Webster")
                                        # Split on capital letters: "samwebster" -> ["sam", "webster"]
                                        words = re.findall(r'[a-z]+|[A-Z][a-z]*', subdomain)
                                        if len(words) > 1:
                                            artist_from_url = " ".join(word.capitalize() for word in words)
                                        else:
                                            # Just capitalize the whole thing as fallback
                                            artist_from_url = subdomain.capitalize()
                            except:
                                pass
                        
                        # Only use URL fallback if we don't have metadata artist
                        if not artist:
                            artist = artist_from_url
                        
                        album = info.get("album") or info.get("title")
                        
                        # Extract year from release_date or upload_date
                        date = info.get("release_date") or info.get("upload_date")
                        if date:
                            # Extract year from date (format: YYYYMMDD or YYYY-MM-DD)
                            try:
                                if len(date) >= 4:
                                    year = date[:4]  # First 4 characters are the year
                            except:
                                pass
                    
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
                    
                    # Extract track titles and numbers from entries if available (for split album detection)
                    first_track_title = None
                    first_track_number = None
                    track_titles = []  # Store multiple track titles for split album detection
                    if info.get("entries"):
                        entries = [e for e in info.get("entries", []) if e]  # Filter out None
                        if entries:
                            first_entry = entries[0]
                            # Get track title
                            raw_title = first_entry.get("title", "")
                            if raw_title:
                                # Get artist for title cleaning
                                entry_artist = first_entry.get("artist") or first_entry.get("uploader") or first_entry.get("creator") or artist
                                first_track_title = self._clean_title(raw_title, entry_artist)
                                # Store raw title (before cleaning) for split album detection
                                track_titles.append(raw_title)
                            
                            # Get track number (yt-dlp uses "track_number" or "track")
                            first_track_number = first_entry.get("track_number") or first_entry.get("track")
                            if first_track_number:
                                try:
                                    # Handle formats like "3/10" or just "3"
                                    if isinstance(first_track_number, str):
                                        import re
                                        track_match = re.search(r'(\d+)', str(first_track_number))
                                        if track_match:
                                            first_track_number = int(track_match.group(1))
                                        else:
                                            first_track_number = None
                                    elif isinstance(first_track_number, (int, float)):
                                        first_track_number = int(first_track_number)
                                    else:
                                        first_track_number = None
                                except (ValueError, TypeError):
                                    first_track_number = None
                            
                            # Extract additional track titles (up to 3) for better split album detection
                            for entry in entries[1:4]:  # Check next 3 tracks
                                raw_title = entry.get("title", "")
                                if raw_title:
                                    track_titles.append(raw_title)
                    
                    # Update album info (keep "Track" as placeholder) - preserve HTML extraction results
                    # Only update artist/album if:
                    # 1. We got it from yt-dlp metadata (not URL fallback), OR
                    # 2. HTML extraction didn't find one (still has placeholder)
                    if artist or album:
                        # Check if HTML extraction already found a good artist (not placeholder)
                        existing_artist = self.album_info.get("artist")
                        has_good_artist = existing_artist and existing_artist != "Artist"
                        
                        # Only use yt-dlp artist if:
                        # - We got it from metadata (not URL fallback), OR
                        # - HTML extraction didn't find one
                        final_artist = artist
                        if has_good_artist:
                            # HTML extraction found artist - only overwrite if yt-dlp got it from metadata
                            if artist_from_metadata:
                                # yt-dlp found it in metadata - use it (might be more accurate)
                                final_artist = artist
                            else:
                                # yt-dlp only found it from URL - keep HTML extraction result
                                final_artist = existing_artist
                        else:
                            # HTML extraction didn't find one - use yt-dlp result (even if from URL)
                            final_artist = artist or existing_artist or "Artist"
                        
                        # Similar logic for album
                        existing_album = self.album_info.get("album")
                        has_good_album = existing_album and existing_album != "Album"
                        final_album = album if (album and not has_good_album) else (existing_album or album or "Album")
                        
                        # Use yt-dlp track info if available (more reliable), otherwise keep HTML extraction result
                        final_first_track_title = first_track_title or self.album_info.get("first_track_title")
                        final_first_track_number = first_track_number if first_track_number is not None else self.album_info.get("first_track_number")
                        
                        # Store track titles list for split album detection
                        existing_track_titles = self.album_info.get("track_titles", [])
                        if track_titles:
                            # Use yt-dlp track titles if available
                            final_track_titles = track_titles
                        else:
                            # Keep existing track titles if available
                            final_track_titles = existing_track_titles
                        
                        # Store metadata in cache for this URL (normalize consistently)
                        normalized_url = url.rstrip(' \t,;')
                        if not normalized_url.startswith(('http://', 'https://')):
                            normalized_url = 'https://' + normalized_url
                        normalized_url = normalized_url.rstrip('/').lower()
                        metadata = {
                            "artist": final_artist,
                            "album": final_album,
                            "title": None,
                            "thumbnail_url": thumbnail_url or self.album_info.get("thumbnail_url"),
                            "year": year or self.album_info.get("year"),
                            "first_track_title": final_first_track_title,
                            "first_track_number": final_first_track_number,
                            "track_titles": final_track_titles  # Store multiple track titles for split album detection
                        }
                        self.url_metadata_cache[normalized_url] = metadata
                        # Don't update tag metadata cache - tags should only use HTML extraction (stage 1) metadata
                        # This prevents tag updates from overriding other URLs when yt-dlp (stage 2) metadata arrives
                        
                        # Store track titles list for split album detection
                        existing_track_titles = self.album_info.get("track_titles", [])
                        if track_titles:
                            # Use yt-dlp track titles if available
                            final_track_titles = track_titles
                        else:
                            # Keep existing track titles if available
                            final_track_titles = existing_track_titles
                        
                        self.album_info = {
                            "artist": final_artist,
                            "album": final_album,
                            "title": "Track",
                            "thumbnail_url": thumbnail_url or self.album_info.get("thumbnail_url"),
                            "year": year or self.album_info.get("year"),  # Store year if found
                            "first_track_title": final_first_track_title,  # Store first track title
                            "first_track_number": final_first_track_number,  # Store first track number
                            "track_titles": final_track_titles  # Store multiple track titles for split album detection
                        }
                        self.root.after(0, self.update_preview)
                        # Also update Additional Settings dialog preview if open
                        if hasattr(self, '_additional_settings_dialogs'):
                            for dialog_ref in self._additional_settings_dialogs:
                                try:
                                    if dialog_ref['dialog'].winfo_exists():
                                        dialog_ref['update_func']()
                                except:
                                    pass
                        
                        # Don't update tags when yt-dlp metadata arrives - tags should only use HTML extraction (stage 1)
                        # This prevents tag updates from overriding other URLs that were pasted
                    
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
                    html_content = response.read().decode('utf-8', errors='ignore')
                
                # Look for album art in various patterns Bandcamp uses
                thumbnail_url = None
                bio_pic_url = None
                
                # Pattern 1: Look for popupImage or main image in data attributes
                patterns = [
                    r'popupImage["\']?\s*:\s*["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'data-popup-image=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<img[^>]*id=["\']tralbum-art["\'][^>]*src=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<img[^>]*class=["\'][^"]*popupImage[^"]*["\'][^>]*src=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'property=["\']og:image["\'][^>]*content=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE)
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
                
                # Look for bio pic in the bio-container section
                # Pattern: <div class="artists-bio-pic"> ... <a class="popupImage" href="..."> or <img class="band-photo" src="...">
                bio_pic_patterns = [
                    r'<div[^>]*class=["\'][^"]*artists-bio-pic[^"]*["\'][^>]*>.*?<a[^>]*class=["\'][^"]*popupImage[^"]*["\'][^>]*href=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<div[^>]*class=["\'][^"]*artists-bio-pic[^"]*["\'][^>]*>.*?<img[^>]*class=["\'][^"]*band-photo[^"]*["\'][^>]*src=["\']([^"\']+\.(jpg|jpeg|png|webp))',
                    r'<a[^>]*class=["\'][^"]*popupImage[^"]*["\'][^>]*href=["\']([^"\']+\.(jpg|jpeg|png|webp))[^>]*>.*?<img[^>]*class=["\'][^"]*band-photo',
                ]
                
                for pattern in bio_pic_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        bio_pic_url = match.group(1)
                        # Make sure it's a full URL
                        if bio_pic_url.startswith('//'):
                            bio_pic_url = 'https:' + bio_pic_url
                        elif bio_pic_url.startswith('/'):
                            # Extract base URL
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            bio_pic_url = f"{parsed.scheme}://{parsed.netloc}{bio_pic_url}"
                        break
                
                # If bio pic not found with popupImage, try finding it in bio-container more broadly
                if not bio_pic_url:
                    # Look for bio-container and then find any image within it
                    bio_container_match = re.search(r'<div[^>]*id=["\']bio-container["\'][^>]*>(.*?)</div>', html_content, re.IGNORECASE | re.DOTALL)
                    if bio_container_match:
                        bio_content = bio_container_match.group(1)
                        # Look for any image URL in the bio container
                        img_match = re.search(r'(?:href|src)=["\']([^"\']+\.(jpg|jpeg|png|webp))', bio_content, re.IGNORECASE)
                        if img_match:
                            bio_pic_url = img_match.group(1)
                            if bio_pic_url.startswith('//'):
                                bio_pic_url = 'https:' + bio_pic_url
                            elif bio_pic_url.startswith('/'):
                                from urllib.parse import urlparse
                                parsed = urlparse(url)
                                bio_pic_url = f"{parsed.scheme}://{parsed.netloc}{bio_pic_url}"
                
                # Store bio pic URL if found
                if bio_pic_url:
                    # Try to get a larger/higher quality size for bio pic
                    high_quality_bio_pic = bio_pic_url
                    if '_' in bio_pic_url or 'bcbits.com' in bio_pic_url:
                        # Try common larger sizes (in order of preference)
                        for size in ['_500', '_300', '_200', '_100', '_64']:
                            if size in bio_pic_url:
                                break
                            test_url = bio_pic_url.replace('_16', size).replace('_32', size).replace('_64', size).replace('_100', size)
                            if test_url != bio_pic_url:
                                high_quality_bio_pic = test_url
                                break
                    self.current_bio_pic_url = high_quality_bio_pic
                
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
                    # Display appropriate image based on current mode
                    if self.album_art_mode == "album_art" or not hasattr(self, 'album_art_mode'):
                        self.root.after(0, lambda url=high_quality_thumbnail: self.fetch_and_display_album_art(url))
                    elif self.album_art_mode == "bio_pic" and self.current_bio_pic_url:
                        self.root.after(0, lambda url=self.current_bio_pic_url: self.fetch_and_display_bio_pic(url))
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
                if content == "Paste one URL or multiple to create a batch.\nPress ➕ Button, Right Click or CTRL+V to Paste.":
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
    
    def fetch_and_display_bio_pic(self, bio_pic_url):
        """Fetch and display bio pic asynchronously (similar to album art)."""
        if not bio_pic_url:
            self.clear_album_art()
            return
        
        # Check if URL field is empty - if so, don't fetch/display artwork
        if self._is_url_field_empty():
            self.clear_album_art()
            return
        
        # Only fetch if we're in bio_pic mode
        if self.album_art_mode != "bio_pic":
            return
        
        # Prevent multiple simultaneous fetches
        if self.album_art_fetching:
            if hasattr(self, '_artwork_fetch_start_time'):
                import time
                if time.time() - self._artwork_fetch_start_time > 30:
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
                    def reset_flag():
                        self.album_art_fetching = False
                    self.root.after(0, reset_flag)
                    return
                
                # Check again before downloading (field might have been cleared or mode changed)
                if self._is_url_field_empty() or self.album_art_mode != "bio_pic":
                    if fetch_id == self.artwork_fetch_id:
                        self.root.after(0, self.clear_album_art)
                    def reset_flag():
                        self.album_art_fetching = False
                        if hasattr(self, '_artwork_fetch_start_time'):
                            del self._artwork_fetch_start_time
                    self.root.after(0, reset_flag)
                    return
                
                import io
                from PIL import Image, ImageTk
                
                # Download the image with retry logic
                image_data = self._fetch_with_retry(bio_pic_url, max_retries=3, timeout=15)
                
                # Check if this fetch was cancelled during download
                if fetch_id != self.artwork_fetch_id or self.album_art_mode != "bio_pic":
                    def reset_flag():
                        self.album_art_fetching = False
                    self.root.after(0, reset_flag)
                    return
                
                # Check again after download
                if self._is_url_field_empty() or self.album_art_mode != "bio_pic":
                    if fetch_id == self.artwork_fetch_id:
                        self.root.after(0, self.clear_album_art)
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
                    if fetch_id != self.artwork_fetch_id or self.album_art_mode != "bio_pic":
                        return
                    
                    # Final check before displaying
                    if self._is_url_field_empty() or self.album_art_mode != "bio_pic":
                        self.clear_album_art()
                        return
                    
                    # Clear canvas
                    self.album_art_canvas.delete("all")
                    
                    # Calculate position to center the image
                    img_width = photo.width()
                    img_height = photo.height()
                    
                    # Create blurred background if image doesn't fill the canvas
                    blurred_bg = self._create_blurred_background(img)
                    if blurred_bg:
                        # Draw blurred background first (fills entire canvas)
                        self.album_art_canvas.create_image(75, 75, image=blurred_bg, anchor='center')
                    
                    # Calculate center position for original image
                    x = (150 - img_width) // 2
                    y = (150 - img_height) // 2
                    
                    # Display original image on top (centered)
                    self.album_art_canvas.create_image(x + img_width // 2, y + img_height // 2, image=photo, anchor='center')
                    
                    # Keep references to prevent garbage collection
                    self.album_art_image = photo
                    if blurred_bg:
                        # Store blurred background reference (will be replaced on next update)
                        if not hasattr(self, '_blurred_bg_image'):
                            self._blurred_bg_image = None
                        self._blurred_bg_image = blurred_bg
                
                if fetch_id == self.artwork_fetch_id:
                    self.root.after(0, update_ui)
                
                # Always reset flag after completion
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
                
            except ImportError:
                # PIL not available
                if fetch_id == self.artwork_fetch_id:
                    self.root.after(0, lambda: self.album_art_canvas.delete("all"))
                    self.root.after(0, lambda: self.album_art_canvas.create_text(
                        75, 75, text="PIL required\nfor bio pic\n\nInstall Pillow:\npip install Pillow", 
                        fill='#808080', font=("Segoe UI", 7), justify='center'
                    ))
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
            except Exception as e:
                # Failed to load image - clear and show placeholder
                if fetch_id == self.artwork_fetch_id:
                    self.root.after(0, self.clear_album_art)
                def reset_flag():
                    self.album_art_fetching = False
                    if hasattr(self, '_artwork_fetch_start_time'):
                        del self._artwork_fetch_start_time
                self.root.after(0, reset_flag)
        
        # Download in background thread
        threading.Thread(target=download_and_display, daemon=True).start()
    
    def fetch_and_display_album_art(self, thumbnail_url):
        """Fetch and display album art asynchronously (second phase - doesn't block preview)."""
        if not thumbnail_url:
            self.clear_album_art()
            return
        
        # Check if URL field is empty - if so, don't fetch/display artwork
        if self._is_url_field_empty():
            self.clear_album_art()
            return
        
        # Only fetch if we're in album_art mode
        if self.album_art_mode != "album_art":
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
                
                # Check again before downloading (field might have been cleared or mode changed)
                if self._is_url_field_empty() or self.album_art_mode != "album_art":
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
                
                # Check if this fetch was cancelled during download or mode changed
                if fetch_id != self.artwork_fetch_id or self.album_art_mode != "album_art":
                    # Reset flag in a thread-safe way
                    def reset_flag():
                        self.album_art_fetching = False
                    self.root.after(0, reset_flag)
                    return
                
                # Check again after download (field might have been cleared or mode changed during download)
                if self._is_url_field_empty() or self.album_art_mode != "album_art":
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
                    # Check if this fetch was cancelled before updating UI or mode changed
                    if fetch_id != self.artwork_fetch_id or self.album_art_mode != "album_art":
                        return
                    
                    # Final check before displaying - field might have been cleared or mode changed
                    if self._is_url_field_empty() or self.album_art_mode != "album_art":
                        self.clear_album_art()
                        return
                    
                    # Clear canvas
                    self.album_art_canvas.delete("all")
                    
                    # Calculate position to center the image
                    img_width = photo.width()
                    img_height = photo.height()
                    
                    # Create blurred background if image doesn't fill the canvas
                    blurred_bg = self._create_blurred_background(img)
                    if blurred_bg:
                        # Draw blurred background first (fills entire canvas)
                        self.album_art_canvas.create_image(75, 75, image=blurred_bg, anchor='center')
                    
                    # Calculate center position for original image
                    x = (150 - img_width) // 2
                    y = (150 - img_height) // 2
                    
                    # Display original image on top (centered)
                    self.album_art_canvas.create_image(x + img_width // 2, y + img_height // 2, image=photo, anchor='center')
                    
                    # Keep references to prevent garbage collection
                    self.album_art_image = photo
                    if blurred_bg:
                        # Store blurred background reference (will be replaced on next update)
                        if not hasattr(self, '_blurred_bg_image'):
                            self._blurred_bg_image = None
                        self._blurred_bg_image = blurred_bg
                
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
    
    def _preload_album_art(self, thumbnail_url):
        """Preload album art in background without displaying (for instant display when switching from hidden)."""
        if not thumbnail_url:
            return
        
        # Check if URL field is empty
        if self._is_url_field_empty():
            return
        
        # Don't preload if already fetching or if we already have a preloaded image for this URL
        if self.album_art_fetching:
            return
        
        def preload():
            try:
                import io
                from PIL import Image, ImageTk
                
                # Download the image with retry logic
                image_data = self._fetch_with_retry(thumbnail_url, max_retries=3, timeout=15)
                
                # Check if URL field was cleared during download
                if self._is_url_field_empty():
                    return
                
                # Open and resize image
                img = Image.open(io.BytesIO(image_data))
                
                # Resize to fit canvas (150x150) while maintaining aspect ratio
                img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage
                photo = ImageTk.PhotoImage(img)
                
                # Cache the preloaded image (only if we're still in hidden mode or album_art mode)
                # Don't cache if mode changed to bio_pic
                def cache_image():
                    if self.album_art_mode in ["hidden", "album_art"] and not self._is_url_field_empty():
                        self.preloaded_album_art_image = photo
                        self.preloaded_album_art_pil = img  # Store PIL Image for blur effect
                        # Keep a reference to prevent garbage collection
                        # We'll transfer this to album_art_image when displaying
                
                self.root.after(0, cache_image)
                
            except Exception:
                # Failed to preload - that's okay, we'll fetch normally when needed
                pass
        
        # Preload in background thread
        threading.Thread(target=preload, daemon=True).start()
    
    def _create_blurred_background(self, img):
        """Create a blurred background version of an image that fills the entire 150x150 canvas.
        
        Args:
            img: PIL Image object (already resized to fit within 150x150)
            
        Returns:
            PhotoImage of the blurred background, or None if image already fills canvas
        """
        try:
            from PIL import Image, ImageFilter, ImageTk
            
            # Check if image already fills the canvas (square and 150x150)
            if img.width == 150 and img.height == 150:
                return None  # No blur needed
            
            # Create a copy and scale to fill the entire canvas (crop center if needed)
            # Use a larger size first to maintain quality, then resize down
            canvas_size = 150
            
            # Calculate scale factor to fill canvas (crop to center)
            scale_w = canvas_size / img.width
            scale_h = canvas_size / img.height
            scale = max(scale_w, scale_h)  # Use larger scale to ensure we fill the canvas
            
            # Resize image to fill canvas (may extend beyond, we'll crop)
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            blurred_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Crop to center 150x150 if needed
            if new_width > canvas_size or new_height > canvas_size:
                left = (new_width - canvas_size) // 2
                top = (new_height - canvas_size) // 2
                blurred_img = blurred_img.crop((left, top, left + canvas_size, top + canvas_size))
            elif new_width < canvas_size or new_height < canvas_size:
                # If smaller, resize to fill (shouldn't happen with max scale, but safety check)
                blurred_img = blurred_img.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS)
            
            # Apply stronger Gaussian blur for a more background-like effect
            # Use a larger radius (12px) for a more pronounced blur that doesn't look like continuation
            blurred_img = blurred_img.filter(ImageFilter.GaussianBlur(radius=12))
            
            # Optionally apply blur a second time for even smoother effect (creates more background-like appearance)
            # This makes it less recognizable as the same image
            blurred_img = blurred_img.filter(ImageFilter.GaussianBlur(radius=8))
            
            # Slightly darken and desaturate to make it more background-like
            # This helps it blend without looking like a continuation of the photo
            from PIL import ImageEnhance
            # Darken slightly (0.85 = 15% darker)
            enhancer = ImageEnhance.Brightness(blurred_img)
            blurred_img = enhancer.enhance(0.85)
            # Slightly desaturate (0.9 = 10% less saturation)
            enhancer = ImageEnhance.Color(blurred_img)
            blurred_img = enhancer.enhance(0.9)
            
            # Convert to PhotoImage
            blurred_photo = ImageTk.PhotoImage(blurred_img)
            return blurred_photo
            
        except Exception:
            # If blur fails, return None (will display without blur)
            return None
    
    def clear_album_art(self):
        """Clear the album art display and show appropriate placeholder."""
        try:
            self.album_art_canvas.delete("all")
            # Show appropriate placeholder text based on current mode
            if self.album_art_mode == "bio_pic":
                placeholder_text = "Artist Bio Pic"
            else:
                placeholder_text = "Album Art"
            self.album_art_canvas.create_text(
                75, 75,
                text=placeholder_text,
                fill='#808080',
                font=("Segoe UI", 8)
            )
            self.album_art_image = None
        except Exception:
            pass
    
    def toggle_album_art(self):
        """Cycle through album art panel modes: album_art → bio_pic → hidden → album_art."""
        # Store previous mode to detect transitions
        previous_mode = self.album_art_mode
        
        # Cycle through states: album_art → bio_pic → hidden → album_art
        if self.album_art_mode == "album_art":
            self.album_art_mode = "bio_pic"
        elif self.album_art_mode == "bio_pic":
            self.album_art_mode = "hidden"
        else:  # hidden
            self.album_art_mode = "album_art"
        
        if self.album_art_mode == "hidden":
            # Hide album art panel
            self.album_art_frame.grid_remove()
            # Update settings frame to span 3 columns (full width)
            self.settings_frame.grid_configure(columnspan=3)
            # Show the show album art button by adding it back to grid
            self.show_album_art_btn.grid(row=0, column=2, sticky=E, padx=(4, 0), pady=1)
            self.show_album_art_btn.config(fg='#808080', cursor='hand2')  # Visible, hand cursor
            
            # If switching from bio_pic to hidden, clear canvas and preload album art
            if previous_mode == "bio_pic":
                # Clear the canvas immediately to remove bio pic
                self.clear_album_art()
                # Preload album art in background for instant display when switching back
                if hasattr(self, 'current_thumbnail_url') and self.current_thumbnail_url:
                    self._preload_album_art(self.current_thumbnail_url)
        else:
            # Show album art panel (either album_art or bio_pic mode)
            self.album_art_frame.grid()
            # Update settings frame to span 2 columns (leaving room for album art)
            self.settings_frame.grid_configure(columnspan=2)
            # Remove the show album art button from grid to free up space
            self.show_album_art_btn.grid_remove()
            
            # Display appropriate image based on mode
            if self.album_art_mode == "bio_pic":
                # Try to fetch and display bio pic if available
                if hasattr(self, 'current_bio_pic_url') and self.current_bio_pic_url:
                    self.fetch_and_display_bio_pic(self.current_bio_pic_url)
                else:
                    # Show placeholder if bio pic not available
                    self.clear_album_art()
            else:  # album_art mode
                # Check if we have a preloaded image first (for instant display)
                if self.preloaded_album_art_image:
                    # Display preloaded image immediately
                    self.album_art_canvas.delete("all")
                    img_width = self.preloaded_album_art_image.width()
                    img_height = self.preloaded_album_art_image.height()
                    
                    # Create blurred background if image doesn't fill the canvas
                    blurred_bg = None
                    if self.preloaded_album_art_pil:
                        blurred_bg = self._create_blurred_background(self.preloaded_album_art_pil)
                    
                    if blurred_bg:
                        # Draw blurred background first (fills entire canvas)
                        self.album_art_canvas.create_image(75, 75, image=blurred_bg, anchor='center')
                    
                    # Calculate center position for original image
                    x = (150 - img_width) // 2
                    y = (150 - img_height) // 2
                    
                    # Display original image on top (centered)
                    self.album_art_canvas.create_image(x + img_width // 2, y + img_height // 2, 
                                                       image=self.preloaded_album_art_image, anchor='center')
                    
                    # Use preloaded image as current image
                    self.album_art_image = self.preloaded_album_art_image
                    if blurred_bg:
                        # Store blurred background reference
                        if not hasattr(self, '_blurred_bg_image'):
                            self._blurred_bg_image = None
                        self._blurred_bg_image = blurred_bg
                    
                    # Clear preloaded cache (will be refreshed if needed)
                    self.preloaded_album_art_image = None
                    self.preloaded_album_art_pil = None
                elif hasattr(self, 'current_thumbnail_url') and self.current_thumbnail_url:
                    # No preloaded image, fetch normally
                    self.fetch_and_display_album_art(self.current_thumbnail_url)
                else:
                    # Show placeholder if album art not available
                    self.clear_album_art()
        
        # Save the state
        self.save_album_art_state()
    
    def sanitize_filename(self, name):
        """Remove invalid filename characters.
        
        Preserves ⧸ (U+29F8) which is valid in Windows filenames.
        Converts / (U+002F) to ⧸ when it appears in artist/title contexts.
        """
        if not name:
            return name
        # Convert / to ⧸ (valid Unicode division slash that works in Windows filenames)
        # This preserves Bandcamp's formatting while making it Windows-compatible
        name = name.replace('/', '⧸')
        # Remove invalid characters for Windows/Linux filenames
        # Note: ⧸ is NOT in this list - we want to preserve it
        invalid_chars = '<>:"\\|?*'
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
        
        # Use first track title if available, otherwise fall back to "Track"
        first_track_title = self.album_info.get("first_track_title")
        if first_track_title:
            title = self.sanitize_filename(first_track_title)
        else:
            title = self.sanitize_filename(self.album_info.get("title")) or "Track"
        
        # Get first track number if available (for preview numbering)
        first_track_number = self.album_info.get("first_track_number")
        
        # Extract metadata values - use real data when available, placeholders otherwise
        # Extract Year - check album_info first (from URL paste), then album_info_stored (from download)
        year_value = "Year"
        
        # First check album_info (populated when URL is pasted)
        year_from_info = self.album_info.get("year")
        if year_from_info:
            year_value = year_from_info
        # Fall back to album_info_stored (from download extraction)
        elif hasattr(self, 'album_info_stored') and self.album_info_stored:
            date = self.album_info_stored.get("date")
            if date:
                # Extract year from date (format: YYYYMMDD or YYYY-MM-DD)
                try:
                    if len(date) >= 4:
                        year_value = date[:4]  # First 4 characters are the year
                except:
                    pass
        
        # Get other metadata fields if available
        genre_value = "Genre"
        label_value = "Label"
        album_artist_value = "Album Artist"
        catalog_number_value = "CAT001"
        
        # Check if we have stored metadata with these fields
        if hasattr(self, 'album_info_stored') and self.album_info_stored:
            # These fields might be in album_info_stored if extracted from yt-dlp
            genre_value = self.album_info_stored.get("genre") or genre_value
            label_value = self.album_info_stored.get("label") or self.album_info_stored.get("publisher") or label_value
            album_artist_value = self.album_info_stored.get("album_artist") or self.album_info_stored.get("albumartist") or album_artist_value
            catalog_number_value = self.album_info_stored.get("catalog_number") or self.album_info_stored.get("catalognumber") or catalog_number_value
        
        # Also check album_info for any metadata that might be there
        genre_value = self.album_info.get("genre") or genre_value
        label_value = self.album_info.get("label") or self.album_info.get("publisher") or label_value
        album_artist_value = self.album_info.get("album_artist") or self.album_info.get("albumartist") or album_artist_value
        catalog_number_value = self.album_info.get("catalog_number") or self.album_info.get("catalognumber") or catalog_number_value
        
        # Apply filename format if selected
        numbering_style = self.numbering_var.get()
        # Skip if "None" (old format, no longer used but handle for backward compatibility)
        if numbering_style == "None":
            pass  # Don't apply any format
        else:
            # Get format data (either from FILENAME_FORMATS or custom_filename_formats)
            format_data = None
            if numbering_style in self.FILENAME_FORMATS:
                format_data = self.FILENAME_FORMATS[numbering_style]
            else:
                # Check custom formats
                if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
                    for custom_format in self.custom_filename_formats:
                        formatted = self._format_custom_filename(custom_format)
                        if formatted == numbering_style:
                            format_data = custom_format
                            break
            
            if format_data:
                # Generate filename using format with real metadata for preview
                # Use actual first track number if available, otherwise default to 1
                track_number = first_track_number if first_track_number is not None else 1
                template = format_data.get("template", "")
                if template:
                    # Check if template includes "Artist" - if not, split album setting doesn't matter
                    template_lower = template.lower()
                    has_artist_tag = "artist" in template_lower
                    
                    # Check for split album scenario and apply artist formatting
                    preview_artist = artist if artist != "Artist" else "Artist"
                    
                    # Only apply split album formatting if Artist is in the template
                    if has_artist_tag:
                        # Try to detect split album from metadata (early detection before download)
                        track_artists = set()
                        first_track_artist = None
                        
                        # Method 1: Check album title for multiple artists (e.g., "DISTURD / 惡AI意")
                        album_title = self.album_info.get("album") or ""
                        if album_title and (" / " in album_title or "⧸" in album_title):
                            # Split by " / " or "⧸" to get multiple artists
                            import re
                            if " / " in album_title:
                                artists = [a.strip() for a in album_title.split(" / ")]
                            elif "⧸" in album_title:
                                artists = [a.strip() for a in album_title.split("⧸")]
                            else:
                                artists = []
                            
                            # Filter out parts that look like album titles (too long, contain quotes, etc.)
                            for artist_candidate in artists:
                                # Remove common album title suffixes like "split 12"", "split EP", etc.
                                artist_clean = re.sub(r'\s*[-–—]\s*["\'].*$', '', artist_candidate)  # Remove "- "title"" suffix
                                artist_clean = re.sub(r'\s+split\s+\d+["\']?$', '', artist_clean, flags=re.IGNORECASE)
                                artist_clean = artist_clean.strip()
                                
                                # Only use if it looks like an artist name (reasonable length, not empty)
                                if artist_clean and len(artist_clean) < 50 and len(artist_clean) > 1:
                                    track_artists.add(artist_clean)
                        
                        # Method 2: Check track titles for "Track Artist - Track Title" pattern
                        # Check first track title
                        first_track_title_raw = self.album_info.get("first_track_title")
                        if first_track_title_raw and " - " in first_track_title_raw:
                            parts = first_track_title_raw.split(" - ", 1)
                            if len(parts) >= 2:
                                potential_artist = parts[0].strip()
                                # Only use if it looks like an artist name (not too long, not just numbers)
                                if potential_artist and len(potential_artist) < 50 and not potential_artist.isdigit():
                                    first_track_artist = potential_artist
                                    track_artists.add(potential_artist)
                        
                        # Check additional track titles from track_titles list for better detection
                        track_titles_list = self.album_info.get("track_titles", [])
                        for track_title_raw in track_titles_list:
                            if track_title_raw and " - " in track_title_raw:
                                parts = track_title_raw.split(" - ", 1)
                                if len(parts) >= 2:
                                    potential_artist = parts[0].strip()
                                    # Only use if it looks like an artist name (not too long, not just numbers)
                                    if potential_artist and len(potential_artist) < 50 and not potential_artist.isdigit():
                                        track_artists.add(potential_artist)
                                        # Use first track's artist for preview if not set
                                        if not first_track_artist:
                                            first_track_artist = potential_artist
                        
                        # Method 3: Check download_info if available (after download starts)
                        if hasattr(self, 'download_info') and self.download_info:
                            for title_key, info in self.download_info.items():
                                track_artist = info.get("artist")
                                if track_artist and track_artist != "Artist":
                                    track_artists.add(track_artist)
                                    if info.get("track_number") == track_number:
                                        if not first_track_artist:
                                            first_track_artist = track_artist
                        
                        # Method 4: Check downloaded_files for original filenames with split album pattern
                        if hasattr(self, 'downloaded_files') and self.downloaded_files:
                            for file_path_str in self.downloaded_files:
                                try:
                                    file_path = Path(file_path_str)
                                    file_stem = file_path.stem
                                    # Check for "Label - Track Artist - Track Title" pattern
                                    parts = file_stem.split(" - ")
                                    if len(parts) >= 3:
                                        track_artist_from_file = parts[1].strip()
                                        if track_artist_from_file and track_artist_from_file != "Artist":
                                            track_artists.add(track_artist_from_file)
                                            # Use first track's artist for preview
                                            if not first_track_artist:
                                                first_track_artist = track_artist_from_file
                                except:
                                    pass
                        
                        # If we detected multiple distinct track artists, it's a split album
                        # Also treat as split album if album title has multiple artists and first track has artist prefix
                        # (even if we only have one track artist so far, the album title indicates it's a split)
                        is_split_album = (
                            len(track_artists) > 1 or  # Multiple track artists detected
                            (len(track_artists) == 1 and first_track_artist and 
                             album_title and (" / " in album_title or "⧸" in album_title))  # Album title has multiple artists
                        )
                        
                        if is_split_album and first_track_artist:
                            # Get current split album display setting
                            current_setting = self.split_album_artist_display_var.get() if hasattr(self, 'split_album_artist_display_var') else "bandcamp_default"
                            
                            # For "bandcamp_default", construct "Label - Track Artist" format
                            if current_setting == "bandcamp_default":
                                # Get label/album artist
                                label_artist = label_value if label_value != "Label" else (artist if artist != "Artist" else "Album Artist")
                                # Construct "Label - Track Artist" format
                                preview_artist = f"{label_artist} - {first_track_artist}"
                            else:
                                # For other settings, use the formatting function
                                preview_artist = self._format_split_album_artist(
                                    first_track_artist,
                                    track_artists if len(track_artists) > 1 else {first_track_artist},  # Ensure at least one artist in set
                                    setting=current_setting
                                )
                                # If "album_artist" setting returns None, use the album artist from metadata
                                if preview_artist is None:
                                    preview_artist = label_value if label_value != "Label" else (artist if artist != "Artist" else "Album Artist")
                    
                    # Build metadata dict from album_info (use real values when available)
                    preview_metadata = {
                        "title": title if title != "Track" else "Track",
                        "artist": preview_artist,
                        "album": album if album != "Album" else "Album",
                        "year": year_value if year_value != "Year" else "Year",
                        "genre": genre_value if genre_value != "Genre" else "Genre",
                        "label": label_value if label_value != "Label" else "Label",
                        "album_artist": album_artist_value if album_artist_value != "Album Artist" else "Album Artist",
                        "catalog_number": catalog_number_value if catalog_number_value != "CAT001" else "Catalog Number"
                    }
                    # Generate filename using template with real metadata (preview_mode=False to use real values)
                    generated_name = self._generate_filename_from_template(
                        template, track_number, preview_metadata, preview_mode=False
                    )
                    if generated_name:
                        title = generated_name
                else:
                    # Fallback to old method if no template
                    dummy_file = Path("dummy.mp3")
                    dummy_dir = Path(path)
                    generated_name = self._generate_filename_from_format(
                        format_data, track_number, title, dummy_file, dummy_dir
                    )
                    if generated_name:
                        title = generated_name
        
        # Get example path based on structure
        base_path = Path(path)
        
        # Handle template-based structures (new format)
        if isinstance(choice, dict) and "template" in choice:
            template = choice.get("template", "").strip()
            if template:
                # Build metadata for preview
                metadata = {
                    "artist": artist,
                    "album": album,
                    "title": title,
                    "year": year_value if year_value != "Year" else "Year",
                    "genre": genre_value if genre_value != "Genre" else "Genre",
                    "label": label_value if label_value != "Label" else "Label",
                    "album_artist": album_artist_value if album_artist_value != "Album Artist" else "Album Artist",
                    "catalog_number": catalog_number_value if catalog_number_value != "CAT001" else "Catalog Number"
                }
                
                # Generate path parts from template
                path_parts = self._generate_path_from_template(template, metadata, preview_mode=True)
                if path_parts:
                    path_parts = [base_path] + path_parts + [f"{title}{ext}"]
                    preview_path = str(Path(*path_parts))
                else:
                    preview_path = str(base_path / f"{title}{ext}")
            else:
                preview_path = str(base_path / f"{title}{ext}")
        # Handle custom structures (old format - will be migrated)
        elif isinstance(choice, list):
            # Normalize to new format (handles both old and new)
            normalized = self._normalize_structure(choice)
            
            # Build path from custom structure
            path_parts = [base_path]
            
            # Metadata values are already extracted above (shared with template-based structures)
            
            # Sanitize all values for filename use
            field_values = {
                "Artist": artist,
                "Album": album,
                "Year": self.sanitize_filename(str(year_value)) if year_value != "Year" else year_value,
                "Genre": self.sanitize_filename(str(genre_value)) if genre_value != "Genre" else genre_value,
                "Label": self.sanitize_filename(str(label_value)) if label_value != "Label" else label_value,
                "Album Artist": self.sanitize_filename(str(album_artist_value)) if album_artist_value != "Album Artist" else album_artist_value,
                "Catalog Number": self.sanitize_filename(str(catalog_number_value)) if catalog_number_value != "CAT001" else catalog_number_value
            }
            
            for level in normalized:
                fields = level.get("fields", [])
                separators = level.get("separators", [])
                
                if not fields:
                    continue
                
                # Build level string with prefix, between, and suffix separators
                result_parts = []
                
                # Add prefix separator (before first field)
                prefix_sep = separators[0] if separators and len(separators) > 0 else ""
                if prefix_sep and prefix_sep != "None":
                    result_parts.append(prefix_sep)
                
                # Add fields with between separators
                level_parts = []
                for field in fields:
                    value = field_values.get(field, "")
                    if value:
                        level_parts.append(value)
                
                for i, field_value in enumerate(level_parts):
                    result_parts.append(field_value)
                    
                    # Add between separator (after each field except last)
                    if i < len(level_parts) - 1:
                        between_idx = i + 1  # separators[1] after first field, separators[2] after second, etc.
                        between_sep = separators[between_idx] if between_idx < len(separators) else "-"
                        if between_sep == "None" or not between_sep:
                            between_sep = " "  # Default to space if None
                        result_parts.append(between_sep)
                
                # Add suffix separator (after last field)
                suffix_idx = len(level_parts)  # separators[n] where n = number of fields
                suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
                if suffix_sep and suffix_sep != "None":
                    result_parts.append(suffix_sep)
                
                if result_parts:
                    path_parts.append("".join(result_parts))
            
            path_parts.append(f"{title}{ext}")
            preview_path = str(Path(*path_parts))
        else:
            # Standard structures (can also use templates now)
            if choice in self.FOLDER_STRUCTURE_TEMPLATES:
                template_data = self.FOLDER_STRUCTURE_TEMPLATES[choice]
                template = template_data.get("template", "").strip()
                if template:
                    # Build metadata for preview
                    metadata = {
                        "artist": artist,
                        "album": album,
                        "title": title,
                        "year": year_value if year_value != "Year" else "Year",
                        "genre": genre_value if genre_value != "Genre" else "Genre",
                        "label": label_value if label_value != "Label" else "Label",
                        "album_artist": album_artist_value if album_artist_value != "Album Artist" else "Album Artist",
                        "catalog_number": catalog_number_value if catalog_number_value != "CAT001" else "Catalog Number"
                    }
                    
                    # Generate path parts from template
                    path_parts = self._generate_path_from_template(template, metadata, preview_mode=True)
                    if path_parts:
                        path_parts = [base_path] + path_parts + [f"{title}{ext}"]
                        preview_path = str(Path(*path_parts))
                    else:
                        # Fallback to old hardcoded
                        examples = {
                            "1": str(base_path / f"{title}{ext}"),
                            "2": str(base_path / album / f"{title}{ext}"),
                            "3": str(base_path / artist / f"{title}{ext}"),
                            "4": str(base_path / artist / album / f"{title}{ext}"),
                            "5": str(base_path / album / artist / f"{title}{ext}"),
                        }
                        preview_path = examples.get(choice, examples["4"])
                else:
                    # Fallback to old hardcoded
                    examples = {
                        "1": str(base_path / f"{title}{ext}"),
                        "2": str(base_path / album / f"{title}{ext}"),
                        "3": str(base_path / artist / f"{title}{ext}"),
                        "4": str(base_path / artist / album / f"{title}{ext}"),
                        "5": str(base_path / album / artist / f"{title}{ext}"),
                    }
                    preview_path = examples.get(choice, examples["4"])
            else:
                # Fallback to old hardcoded
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
    
    def _update_clear_button_state(self):
        """Update clear log button state based on current conditions.
        
        Button should be enabled if:
        - We have log messages AND we're not currently downloading, OR
        - We have an undo snapshot available
        """
        try:
            if not hasattr(self, 'clear_log_btn'):
                return
            
            # Check if we have messages
            has_messages = hasattr(self, 'log_messages') and self.log_messages
            
            # Check if we're downloading (cancel button visible = active download)
            is_downloading = False
            try:
                if hasattr(self, 'cancel_btn'):
                    is_downloading = self.cancel_btn.winfo_viewable()
            except:
                pass
            
            # Check if we have an undo snapshot
            has_undo = hasattr(self, 'log_snapshot') and self.log_snapshot
            
            # Determine button state
            if has_undo:
                # We have an undo snapshot - show undo button
                self.clear_log_btn.config(text="Undo Clear", command=self._undo_clear_log, state='normal', cursor='hand2')
            elif has_messages and not is_downloading:
                # We have messages and we're not downloading - enable clear button
                self.clear_log_btn.config(text="Clear Log", command=self._clear_log, state='normal', cursor='hand2')
            else:
                # No messages and no undo - disable button
                self.clear_log_btn.config(text="Clear Log", command=self._clear_log, state='disabled', cursor='arrow')
        except Exception:
            pass
    
    def _clear_log(self):
        """Clear the status log."""
        # Save snapshot before clearing (only if there's content to save)
        if hasattr(self, 'log_messages') and self.log_messages:
            # Save scroll position (get first visible line)
            try:
                scroll_position = self.log_text.index("@0,0")
            except:
                scroll_position = "1.0"
            
            # Save snapshot: (log_messages_copy, debug_mode_state, scroll_position)
            self.log_snapshot = (self.log_messages.copy(), self.debug_mode, scroll_position)
        else:
            # Nothing to save, no undo available
            self.log_snapshot = None
        
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, END)
        self.log_text.config(state='disabled')
        
        # Clear stored log messages
        if hasattr(self, 'log_messages'):
            self.log_messages = []
        
        # Clear any search highlights
        if hasattr(self, 'search_tag_name'):
            self.log_text.tag_remove(self.search_tag_name, 1.0, END)
        if hasattr(self, 'current_match_tag_name'):
            self.log_text.tag_remove(self.current_match_tag_name, 1.0, END)
        
        # Update button state using the helper method
        self._update_clear_button_state()
    
    def _undo_clear_log(self):
        """Restore the log from snapshot after clearing."""
        if not self.log_snapshot:
            return
        
        log_messages_copy, saved_debug_mode, scroll_position = self.log_snapshot
        
        # Restore log_messages
        self.log_messages = log_messages_copy
        
        # Rebuild log display (respecting current debug mode, not saved one)
        self.log_text.config(state='normal')
        try:
            # Clear current content
            self.log_text.delete(1.0, END)
            
            # Rebuild with filtered messages (using current debug mode)
            for message, is_debug in self.log_messages:
                if not is_debug or self.debug_mode:
                    self.log_text.insert(END, message + "\n")
            
            # Restore scroll position
            try:
                self.log_text.see(scroll_position)
            except:
                # If exact position doesn't exist, try to scroll to end or approximate position
                try:
                    # Try to find a similar line number
                    line_num = int(scroll_position.split('.')[0])
                    if line_num <= len(self.log_messages):
                        # Count visible lines up to that position
                        visible_count = 0
                        for i, (msg, is_debug) in enumerate(self.log_messages[:line_num], 1):
                            if not is_debug or self.debug_mode:
                                visible_count += 1
                        if visible_count > 0:
                            target_line = f"{visible_count}.0"
                            self.log_text.see(target_line)
                except:
                    # Fallback: scroll to end
                    self.log_text.see(END)
        except Exception:
            pass
        self.log_text.config(state='disabled')
        
        # Clear snapshot
        self.log_snapshot = None
        
        # Update button state using the helper method
        self._update_clear_button_state()
    
    def _toggle_word_wrap(self):
        """Toggle word wrap for the status log."""
        word_wrap_enabled = self.word_wrap_var.get()
        
        # Update the log text widget wrap setting
        if word_wrap_enabled:
            self.log_text.config(wrap=WORD)
        else:
            self.log_text.config(wrap='none')
        
        # Save the setting
        settings = self._load_settings()
        settings["word_wrap"] = word_wrap_enabled
        self._save_settings(settings)
    
    def _toggle_debug_mode(self):
        """Toggle debug mode on/off and rebuild log to show/hide existing debug messages."""
        self.debug_mode = self.debug_mode_var.get()
        
        # Rebuild the log content based on debug mode
        if hasattr(self, 'log_text') and hasattr(self, 'log_messages'):
            self.log_text.config(state='normal')
            try:
                # Save current scroll position (get first visible line)
                first_visible = self.log_text.index("@0,0")
                
                # Clear current content
                self.log_text.delete(1.0, END)
                
                # Rebuild with filtered messages
                for message, is_debug in self.log_messages:
                    if not is_debug or self.debug_mode:
                        self.log_text.insert(END, message + "\n")
                
                # Restore scroll position to the same line (if it still exists)
                try:
                    # Try to scroll to the same line index
                    self.log_text.see(first_visible)
                except (ValueError, IndexError, TclError):
                    # If that line doesn't exist anymore (e.g., it was a debug line), 
                    # try to maintain approximate position
                    try:
                        # Get approximate line number from saved position
                        line_num = int(first_visible.split('.')[0])
                        # Count visible lines before that position
                        visible_count = 0
                        for i, (msg, is_debug) in enumerate(self.log_messages[:line_num], 1):
                            if not is_debug or self.debug_mode:
                                visible_count += 1
                        # Scroll to approximately the same position
                        if visible_count > 0:
                            target_line = f"{visible_count}.0"
                            self.log_text.see(target_line)
                    except (ValueError, IndexError, TclError):
                        pass
            except Exception:
                pass
            self.log_text.config(state='disabled')
    
    def log(self, message):
        """Add message to log. Stores messages for debug toggle functionality."""
        # If undo is available, expire it (new log entry means user's chance to undo has passed)
        if hasattr(self, 'log_snapshot') and self.log_snapshot:
            self.log_snapshot = None
            # Button state will be updated by _update_clear_button_state() below
        
        # Check if message is a debug message
        is_debug = message.startswith("DEBUG:")
        
        # Store the message
        if not hasattr(self, 'log_messages'):
            self.log_messages = []
        self.log_messages.append((message, is_debug))
        
        # Limit log history size to prevent memory issues
        if len(self.log_messages) > self.LOG_HISTORY_MAX_SIZE:
            # Remove oldest messages (keep most recent)
            self.log_messages = self.log_messages[-self.LOG_HISTORY_MAX_SIZE:]
        
        # Only display if it's not a debug message, or if debug mode is on
        if not is_debug or self.debug_mode:
            # Temporarily enable widget to insert text, then disable again (read-only)
            self.log_text.config(state='normal')
            self.log_text.insert(END, message + "\n")
            self.log_text.see(END)
            self.log_text.config(state='disabled')
            self.root.update_idletasks()
        
        # Update clear button state using the helper method
        # Try immediately and with delays to handle timing issues
        self._update_clear_button_state()
        self.root.after(10, self._update_clear_button_state)
        self.root.after(50, self._update_clear_button_state)
        self.root.after(200, self._update_clear_button_state)
    
    def _on_log_Click(self):
        """Handle Click on log text to enable Ctrl+F."""
        # Give focus to log_text so Ctrl+F works
        # Don't return "break" - allow default text selection behavior to work
        self.log_text.focus_set()
    
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
        colors = self.theme_colors
        self.search_frame = Frame(self.log_frame, bg=colors.select_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
        
        # Search label
        search_label = Label(self.search_frame, text="Find:", bg=colors.select_bg, fg=colors.fg, font=("Segoe UI", 8))
        search_label.grid(row=0, column=0, sticky=W, padx=(6, 4), pady=4)
        
        # Search entry
        self.search_var = StringVar()
        self.search_entry = Entry(self.search_frame, textvariable=self.search_var, width=25, 
                                 font=("Segoe UI", 8), bg=colors.entry_bg, fg=colors.entry_fg, 
                                 insertbackground=colors.fg, relief='flat', borderwidth=1, 
                                 highlightthickness=1, highlightbackground=colors.border,
                                 highlightcolor=colors.accent)
        self.search_entry.grid(row=0, column=1, sticky=(W, E), padx=(0, 4), pady=4)
        
        # Match count label (shows "X of Y" or "No matches") - between search field and buttons
        self.search_count_label = Label(self.search_frame, text="", bg=colors.select_bg, fg=colors.disabled_fg,
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
        self.search_close_btn = Label(self.search_frame, text="✕", bg=colors.select_bg, fg=colors.disabled_fg,
                                     font=("Segoe UI", 9), cursor='hand2', width=1, height=1)
        self.search_close_btn.grid(row=0, column=5, sticky=E, padx=(4, 6), pady=4)
        
        # Store close button reference and bind properly
        def on_close_Click(event):
            self._hide_search_bar()
            return "break"  # Prevent event propagation
        
        self.search_close_btn.bind("<Button-1>", on_close_Click)
        self.search_close_btn.bind("<Enter>", lambda e: self.search_close_btn.config(fg=colors.hover_fg))
        self.search_close_btn.bind("<Leave>", lambda e: self.search_close_btn.config(fg=colors.disabled_fg))
        
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
        self.search_entry.bind('<Escape>', on_close_Click)
        self.search_entry.bind('<Control-f>', on_close_Click)
        
        # Make search frame and all its children Clickable/interactive
        # This prevents the unfocus handler from stealing focus
        def on_search_frame_Click(event):
            # Allow Clicking on search frame to work normally
            return None  # Don't prevent default
        
        self.search_frame.bind('<Button-1>', on_search_frame_Click)
        
        # Also bind to all children to ensure they're interactive
        # But skip the close button since it has its own handler
        for child in self.search_frame.winfo_children():
            if child != self.search_close_btn:
                child.bind('<Button-1>', lambda e: None)  # Allow Clicks
    
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
        # Use a small delay to allow double-Click detection
        self.url_text_resize_drag_started = False
        self.url_text_resize_start_y = event.y_root
        # Get current widget height in pixels
        self.url_text_resize_start_height = self.url_text_widget.winfo_height()
        # Start drag after a small delay (allows double-Click to cancel it)
        self.root.after(150, lambda: self._actually_start_url_text_resize())
    
    def _actually_start_url_text_resize(self):
        """Actually start the resize drag operation (called after delay to allow double-Click detection)."""
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
    
    def _auto_expand_url_text_height(self):
        """Auto-expand URL text widget height to fit content, up to maximum height."""
        if not self.url_text_widget or not self.url_text_widget.winfo_viewable():
            return
        
        try:
            # Get current content
            content = self.url_text_widget.get('1.0', END).rstrip('\n')
            if not content:
                # Empty content - collapse to minimum
                self.url_text_widget.config(height=1)
                self.url_text_height = 1
                return
            
            # Calculate maximum allowed height in lines (do this first)
            try:
                line_info = self.url_text_widget.dlineinfo('1.0')
                if line_info:
                    pixels_per_line = line_info[3]
                    if pixels_per_line > 0:
                        max_height_lines = int(self.url_text_max_height_px / pixels_per_line)
                    else:
                        max_height_lines = int(self.url_text_max_height_px / 20)  # Fallback: ~20px per line
                else:
                    max_height_lines = int(self.url_text_max_height_px / 20)  # Fallback: ~20px per line
            except Exception:
                max_height_lines = int(self.url_text_max_height_px / 20)  # Fallback: ~20px per line
            
            # Get current height to check if we're already at max
            current_height = self.url_text_widget.cget('height')
            
            # If we're already at or near max height, check if content still fits
            # If content exceeds max, keep it at max (don't collapse)
            if current_height >= max_height_lines:
                # Check if there's a scrollbar (indicates content exceeds visible area)
                # If scrollbar exists, content exceeds max height - keep at max
                try:
                    # Check if we can see the last line by trying to get its bbox
                    last_line_index = self.url_text_widget.index(END + '-1c')
                    bbox = self.url_text_widget.bbox(last_line_index)
                    
                    # If bbox is None, the last line is not visible (scrolled out of view)
                    # This means content exceeds max height - keep at max
                    if bbox is None:
                        # Content exceeds max height - maintain max height
                        if current_height != max_height_lines:
                            self.url_text_widget.config(height=max_height_lines)
                            self.url_text_height = max_height_lines
                        return
                except Exception:
                    # If we can't check, assume content might exceed max - keep at max
                    if current_height != max_height_lines:
                        self.url_text_widget.config(height=max_height_lines)
                        self.url_text_height = max_height_lines
                    return
            
            # Calculate required height based on content
            # Count lines (accounting for word wrapping)
            lines = content.split('\n')
            estimated_lines = len(lines)
            
            # Get actual pixel height needed by checking the last line position
            try:
                # Get the bounding box of the last character
                last_line_index = self.url_text_widget.index(END + '-1c')
                bbox = self.url_text_widget.bbox(last_line_index)
                if bbox:
                    # Calculate pixels from top to bottom of content
                    content_height_px = bbox[1] + bbox[3]  # y position + height of last line
                    
                    # Get line height to calculate lines needed
                    line_info = self.url_text_widget.dlineinfo('1.0')
                    if line_info:
                        pixels_per_line = line_info[3]  # Height of a line including spacing
                        if pixels_per_line > 0:
                            required_lines = int(content_height_px / pixels_per_line) + 1  # +1 for padding
                        else:
                            # Fallback: use estimated lines
                            required_lines = estimated_lines
                    else:
                        required_lines = estimated_lines
                else:
                    # bbox is None - content might be scrollable, use estimated lines
                    # But ensure we don't go below current height if we're already expanded
                    required_lines = max(estimated_lines, current_height)
            except Exception:
                # Fallback: use estimated lines, but don't collapse if already expanded
                required_lines = max(estimated_lines, current_height)
            
            # Set height to required lines, but cap at maximum
            # Ensure we never go below 1 line
            new_height = max(1, min(required_lines, max_height_lines))
            
            # Only update if height changed
            if new_height != current_height:
                self.url_text_widget.config(height=new_height)
                self.url_text_height = new_height
        except Exception:
            pass  # Silently fail if there's an issue
    
    def _toggle_url_text_height(self, event):
        """Toggle URL text widget between minimum and maximum height on double-Click."""
        if not self.url_text_widget:
            return
        
        # Cancel any ongoing drag operation
        self.url_text_resizing = False
        
        try:
            current_height = self.url_text_widget.cget('height')
            
            # If at minimum height (1 line), maximize it
            if current_height <= 1:
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
                self.url_text_widget.config(height=1)
                self.url_text_height = 1
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
    
    def _is_widget_in_hierarchy(self, widget, parent):
        """Check if widget is in the hierarchy of parent widget."""
        if not parent:
            return False
        current = widget
        while current:
            if current == parent:
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
            colors = self.theme_colors
            self.search_count_label.config(text="No matches", fg=colors.disabled_fg)
        else:
            colors = self.theme_colors
            current = self.current_match_index + 1 if self.current_match_index >= 0 else 1
            self.search_count_label.config(text=f"{current} of {match_count}", fg=colors.fg)
    
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
        
        # Handle custom structures (list - can be old or new format)
        if isinstance(choice, list):
            # Normalize to new format
            normalized = self._normalize_structure(choice)
            
            # Build path from custom structure
            path_parts = [base_folder]
            
            # Field to template mapping
            field_templates = {
                "Artist": "%(artist)s",
                "Album": "%(album)s",
                "Year": "%(release_date>%Y)s",  # Extract year from release_date
                "Genre": "%(genre)s",
                "Label": "%(publisher)s",
                "Album Artist": "%(album_artist)s",
                "Catalog Number": "%(catalog_number)s"
            }
            
            for level in normalized:
                fields = level.get("fields", [])
                separators = level.get("separators", [])
                
                if not fields:
                    continue
                
                # Build template parts for this level
                template_parts = []
                for field in fields:
                    if field in field_templates:
                        template_parts.append(field_templates[field])
                
                if template_parts:
                    # Build template with prefix, between, and suffix separators
                    # separators[0] = prefix, separators[1..n-1] = between, separators[n] = suffix
                    result_parts = []
                    
                    # Add prefix separator (before first field)
                    prefix_sep = separators[0] if separators and len(separators) > 0 else ""
                    if prefix_sep and prefix_sep != "None":
                        result_parts.append(prefix_sep)
                    
                    # Add fields with between separators
                    for i, template_part in enumerate(template_parts):
                        result_parts.append(template_part)
                        
                        # Add between separator (after each field except last)
                        if i < len(template_parts) - 1:
                            between_idx = i + 1  # separators[1] after first field, separators[2] after second, etc.
                            between_sep = separators[between_idx] if between_idx < len(separators) else "-"
                            if between_sep == "None" or not between_sep:
                                between_sep = " "  # Default to space if None
                            result_parts.append(between_sep)
                    
                    # Add suffix separator (after last field)
                    suffix_idx = len(template_parts)  # separators[n] where n = number of fields
                    suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
                    if suffix_sep and suffix_sep != "None":
                        result_parts.append(suffix_sep)
                    
                    # Join all parts into single template string (yt-dlp will substitute all variables)
                    joined_template = "".join(result_parts)
                    path_parts.append(joined_template)
            
            path_parts.append("%(title)s.%(ext)s")
            return str(Path(*path_parts))
        
        # Handle template-based structures (new format - check if choice is a template dict)
        if isinstance(choice, dict) and "template" in choice:
            template = choice.get("template", "").strip()
            if template:
                # Generate path parts from template
                path_parts = self._generate_path_from_template(template, preview_mode=False)
                if path_parts:
                    path_parts = [base_folder] + path_parts + ["%(title)s.%(ext)s"]
                    return str(Path(*path_parts))
        
        # Handle standard structures (can also use templates now)
        if choice in self.FOLDER_STRUCTURE_TEMPLATES:
            template_data = self.FOLDER_STRUCTURE_TEMPLATES[choice]
            template = template_data.get("template", "").strip()
            if template:
                # Generate path parts from template
                path_parts = self._generate_path_from_template(template, preview_mode=False)
                if path_parts:
                    path_parts = [base_folder] + path_parts + ["%(title)s.%(ext)s"]
                    return str(Path(*path_parts))
        
        # Fallback to old hardcoded options
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
        # Reset the download button Clicked flag
        if hasattr(self, 'download_button_Clicked'):
            self.download_button_Clicked = False
        
        # Extract URLs - prefer tag mappings if available (preserves tags without modifying content)
        urls = []
        if self.url_tag_mapping:
            # Extract URLs directly from tag mappings (tags remain untouched)
            urls = list(self.url_tag_mapping.values())
        else:
            # No tags - extract from content as fallback
            if self.url_text_widget and self.url_text_widget.winfo_viewable():
                content = self.url_text_widget.get(1.0, END)
            elif self.url_entry_widget and self.url_entry_widget.winfo_viewable():
                # Fallback for legacy entry usage (should not normally be visible)
                content = self.url_var.get()
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
        
        # Don't modify the URL field content - tags remain untouched
        # Just update button states if needed
        if self.url_text_widget:
            try:
                self._update_text_placeholder_visibility()
                self._update_url_count_and_button()
                self._update_url_clear_button()
            except Exception:
                pass

        # Still keep url_var in sync for any legacy logic, but do not show the Entry widget.
        if self.url_entry_widget:
            try:
                flattened_urls = ' '.join(valid_urls)
                self.url_var.set(flattened_urls)
            except Exception:
                pass
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
        self.cancel_btn.config(state='normal', cursor='hand2')  # Hand cursor when enabled
        self.cancel_btn.grid()
        self.is_cancelling = False
        
        # Disable clear log button during download operations
        # Update button state (will be disabled because is_downloading will be True)
        self._update_clear_button_state()
        
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
    
    def _detect_split_album(self, files_to_process):
        """Detect if this is a split album by checking for multiple distinct track artists.
        
        Args:
            files_to_process: List of Path objects for audio files
            
        Returns:
            Tuple of (is_split_album, unique_artists_dict)
            - is_split_album: Boolean indicating if split album detected
            - unique_artists_dict: Dict mapping file paths to their track artists
        """
        unique_artists = {}
        track_artists = set()
        
        for audio_file in files_to_process:
            file_title = audio_file.stem
            extracted_track_artist = None
            
            # Extract track artist from filename if it follows "Label - Track Artist - Track Title" pattern
            parts = file_title.split(" - ")
            if len(parts) >= 3:
                extracted_track_artist = parts[1].strip()
                if extracted_track_artist and extracted_track_artist != "Artist":
                    unique_artists[audio_file] = extracted_track_artist
                    track_artists.add(extracted_track_artist)
        
        # Check if we have multiple distinct track artists
        is_split_album = len(track_artists) > 1
        
        return is_split_album, unique_artists
    
    def _format_split_album_artist(self, track_artist, all_track_artists, setting=None):
        """Format artist name based on split album display setting.
        
        Args:
            track_artist: The artist for the current track
            all_track_artists: Set of all unique track artists in the album
            setting: Split album display setting (defaults to current setting)
            
        Returns:
            Formatted artist string
        """
        if setting is None:
            setting = self.split_album_artist_display_var.get() if hasattr(self, 'split_album_artist_display_var') else "bandcamp_default"
        
        if setting == "bandcamp_default":
            # Show all artists separated by " / "
            all_artists = sorted(list(all_track_artists))
            return " / ".join(all_artists)
        elif setting == "track_artist":
            # Use the track's own artist
            return track_artist
        elif setting == "album_artist":
            # Use album artist (label artist) - this will be handled by metadata
            return None  # Signal to use album artist from metadata
        elif setting == "first_track_artist":
            # Use first track artist (by track number, or alphabetically if not available)
            # Note: first_track_artist should be passed separately, but for backward compatibility
            # we'll use alphabetical order if not provided
            if all_track_artists:
                return sorted(list(all_track_artists))[0]
            return track_artist
        else:
            # Default to track artist
            return track_artist
    
    def _generate_filename_from_format(self, format_data, track_number, track_title, audio_file, dir_path, split_album_info=None):
        """Generate filename from format data using track number and metadata.
        
        Args:
            format_data: Format dict with template string
            track_number: Track number (integer)
            track_title: Cleaned track title (string)
            audio_file: Path to audio file (for getting metadata if needed)
            dir_path: Directory path (for getting metadata if needed)
            split_album_info: Optional tuple of (is_split_album, all_track_artists_set) for split album handling
            
        Returns:
            New filename string (without extension) or None if generation failed
        """
        if not format_data:
            return None
        
        normalized = self._normalize_filename_format(format_data)
        if not normalized:
            return None
        
        template = normalized.get("template", "")
        if not template:
            return None
        
        # Get metadata values (try multiple sources)
        metadata = {}
        
        # Get file title for parsing
        file_title = audio_file.stem
        
        # Extract track artist and label from filename
        # Pattern 1: "Label - Track Artist - Track Title" (3+ parts) - split albums
        # Pattern 2: "Artist - Track Title" (2 parts) - regular albums
        extracted_track_artist = None
        extracted_label_artist = None
        parts = file_title.split(" - ")
        if len(parts) >= 3:
            # First part is label, second part is track artist, rest is title
            extracted_label_artist = parts[0].strip()
            extracted_track_artist = parts[1].strip()
            if not extracted_track_artist or extracted_track_artist == "Artist":
                extracted_track_artist = None
            if not extracted_label_artist or extracted_label_artist == "Artist":
                extracted_label_artist = None
        elif len(parts) == 2:
            # Regular album format: "Artist - Track Title"
            # First part is the artist
            extracted_track_artist = parts[0].strip()
            if not extracted_track_artist or extracted_track_artist == "Artist":
                extracted_track_artist = None
        
        # Try to get from download_info (if it exists)
        if hasattr(self, 'download_info') and self.download_info:
            for title_key, info in self.download_info.items():
                if file_title.lower() in title_key.lower() or title_key.lower() in file_title.lower():
                    metadata = info.copy()
                    # If we extracted a track artist from filename, prefer it over download_info artist
                    # (especially if download_info has "Artist" placeholder or differs)
                    if extracted_track_artist:
                        if not metadata.get("artist") or metadata.get("artist") == "Artist" or extracted_track_artist != metadata.get("artist"):
                            metadata["artist"] = extracted_track_artist
                    break
        
        # If we extracted track artist but don't have metadata yet, or metadata has placeholder, use extracted artist
        if extracted_track_artist:
            if not metadata:
                metadata = {}
            if not metadata.get("artist") or metadata.get("artist") == "Artist":
                metadata["artist"] = extracted_track_artist
        
        # Try to get from album_info_stored
        if not metadata and hasattr(self, 'album_info_stored') and self.album_info_stored:
            metadata.update(self.album_info_stored)
            # If we extracted track artist, use it instead of album artist
            if extracted_track_artist:
                metadata["artist"] = extracted_track_artist
        elif hasattr(self, 'album_info_stored') and self.album_info_stored:
            # Merge album_info_stored but preserve extracted track artist if we have it
            if extracted_track_artist:
                # Save extracted artist before merging
                track_artist = extracted_track_artist
                metadata.update(self.album_info_stored)
                # Restore extracted track artist (don't overwrite with label artist)
                metadata["artist"] = track_artist
            else:
                metadata.update(self.album_info_stored)
        
        # Try to get from directory structure
        if not metadata.get("artist") or not metadata.get("album"):
            try:
                artist, album = self._get_metadata_from_directory(dir_path)
                if artist:
                    metadata["artist"] = artist
                if album:
                    metadata["album"] = album
            except:
                pass
        
        # Try to read metadata directly from audio file if still missing
        if not metadata.get("artist") or not metadata.get("album") or not metadata.get("date"):
            try:
                import subprocess
                import sys
                import json
                
                # Try to use ffprobe to read metadata
                if hasattr(self, 'ffmpeg_path') and self.ffmpeg_path:
                    ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
                    if not ffprobe_path.exists() and hasattr(self, 'script_dir'):
                        ffprobe_path = self.script_dir / "ffprobe.exe"
                    
                    if ffprobe_path.exists() and audio_file.exists():
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
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                            timeout=5
                        )
                        
                        if result.returncode == 0:
                            data = json.loads(result.stdout.decode('utf-8', errors='ignore'))
                            tags = data.get("format", {}).get("tags", {})
                            
                            # Extract artist
                            if not metadata.get("artist"):
                                artist = (tags.get("artist") or tags.get("ARTIST") or 
                                         tags.get("album_artist") or tags.get("ALBUMARTIST") or
                                         tags.get("albumartist") or tags.get("ALBUMARTIST"))
                                if artist:
                                    metadata["artist"] = artist
                            
                            # Extract album
                            if not metadata.get("album"):
                                album = tags.get("album") or tags.get("ALBUM")
                                if album:
                                    metadata["album"] = album
                            
                            # Extract date/year
                            if not metadata.get("date") and not metadata.get("year"):
                                date = (tags.get("date") or tags.get("DATE") or 
                                       tags.get("year") or tags.get("YEAR") or
                                       tags.get("originaldate") or tags.get("ORIGINALDATE"))
                                if date:
                                    metadata["date"] = str(date)
            except Exception:
                pass  # Silently fail if metadata reading doesn't work
        
        # Extract year from date if available
        year_value = None
        if metadata.get("date"):
            date = metadata["date"]
            try:
                if len(date) >= 4:
                    year_value = date[:4]
            except:
                pass
        
        # Add title to metadata
        metadata["title"] = track_title
        
        # Add year if extracted
        if year_value:
            metadata["year"] = year_value
        
        # Handle split album artist formatting if split album detected
        if split_album_info:
            # Unpack split_album_info (may be 2-tuple or 3-tuple for backward compatibility)
            if len(split_album_info) == 3:
                is_split_album, all_track_artists, first_track_artist = split_album_info
            else:
                is_split_album, all_track_artists = split_album_info
                first_track_artist = None
                if all_track_artists:
                    first_track_artist = sorted(list(all_track_artists))[0]  # Fallback to alphabetical
            
            if is_split_album:
                # Get the current track artist
                current_track_artist = extracted_track_artist or metadata.get("artist")
                
                # Get the split album display setting
                setting = self.split_album_artist_display_var.get() if hasattr(self, 'split_album_artist_display_var') else "bandcamp_default"
                
                # Special handling for "bandcamp_default" - preserve original Bandcamp format
                if setting == "bandcamp_default":
                    # Bandcamp default format: "Label - Track Artist - Track Title"
                    # Get label/album artist (prefer extracted from filename, then metadata)
                    label_artist = extracted_label_artist
                    if not label_artist:
                        label_artist = metadata.get("label") or metadata.get("album_artist") or metadata.get("artist")
                    if not label_artist or label_artist == "Artist":
                        # Try to get from album_info_stored
                        if hasattr(self, 'album_info_stored') and self.album_info_stored:
                            label_artist = (self.album_info_stored.get("label") or 
                                          self.album_info_stored.get("artist") or 
                                          "Album Artist")
                        else:
                            label_artist = "Album Artist"
                    
                    # Use the track artist from filename
                    if not current_track_artist or current_track_artist == "Artist":
                        current_track_artist = "Track Artist"
                    
                    # Get track number prefix if template has it
                    track_prefix = ""
                    import re
                    if re.match(r'^01\.', template):
                        track_prefix = f"{track_number:02d}. "
                    elif re.match(r'^1\.', template):
                        track_prefix = f"{track_number}. "
                    elif re.match(r'^01\s', template):
                        track_prefix = f"{track_number:02d} "
                    elif re.match(r'^1\s', template):
                        track_prefix = f"{track_number} "
                    
                    # Return Bandcamp default format with optional track prefix: "01. Label - Track Artist - Track Title"
                    return f"{track_prefix}{self.sanitize_filename(label_artist)} - {self.sanitize_filename(current_track_artist)} - {self.sanitize_filename(track_title)}"
                
                # For other settings, format the artist and apply to template
                if current_track_artist:
                    # For "first_track_artist", use the first track's artist if available
                    if setting == "first_track_artist" and first_track_artist:
                        formatted_artist = first_track_artist
                    else:
                        formatted_artist = self._format_split_album_artist(
                            current_track_artist,
                            all_track_artists,
                            setting=setting
                        )
                    
                    # If "album_artist" setting returns None, use album/label artist
                    if formatted_artist is None:
                        # Prefer extracted label artist from filename, then metadata
                        formatted_artist = extracted_label_artist
                        if not formatted_artist:
                            formatted_artist = metadata.get("label") or metadata.get("album_artist") or metadata.get("artist")
                        if not formatted_artist or formatted_artist == "Artist":
                            if hasattr(self, 'album_info_stored') and self.album_info_stored:
                                formatted_artist = (self.album_info_stored.get("label") or 
                                                   self.album_info_stored.get("artist") or 
                                                   "Album Artist")
                            else:
                                formatted_artist = "Album Artist"
                    
                    # Update metadata with formatted artist
                    metadata["artist"] = formatted_artist
        
        # Generate filename using template
        filename = self._generate_filename_from_template(template, track_number, metadata, preview_mode=False)
        
        return filename
    
    def apply_track_numbering(self, download_path):
        """Apply custom filename format to downloaded files based on user preference.
        Replaces old apply_track_numbering method with new custom format system.
        """
        import re
        import time
        
        numbering_style = self.numbering_var.get()
        # Skip if "Original" - preserve original Bandcamp filenames
        if numbering_style == "Original":
            return
        # Skip if "None" (old format, no longer used but handle for backward compatibility)
        if numbering_style == "None":
            return
        
        # Get format data (either from FILENAME_FORMATS or custom_filename_formats)
        format_data = None
        if numbering_style in self.FILENAME_FORMATS:
            format_data = self.FILENAME_FORMATS[numbering_style]
        else:
            # Check custom formats
            if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
                for custom_format in self.custom_filename_formats:
                    formatted = self._format_custom_filename(custom_format)
                    if formatted == numbering_style:
                        format_data = custom_format
                        break
        
        # If no format data found, skip (shouldn't happen, but safety check)
        if not format_data:
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
                # Detect split album for this directory (only when split album detected)
                is_split_album, unique_artists_dict = self._detect_split_album(dir_files)
                all_track_artists = set(unique_artists_dict.values()) if unique_artists_dict else set()
                
                # For "first_track_artist" setting, we need to find the artist of the first track (by track number)
                # Store mapping of files to their track artists for first track detection
                first_track_artist = None
                if is_split_album and unique_artists_dict:
                    # Find the file with track number 1
                    for audio_file in dir_files:
                        try:
                            # Try to get track number from metadata
                            import subprocess
                            import json
                            ffprobe_path = self.ffmpeg_path.parent / "ffprobe.exe"
                            if not ffprobe_path.exists():
                                ffprobe_path = self.script_dir / "ffprobe.exe"
                            
                            if ffprobe_path.exists():
                                cmd = [
                                    str(ffprobe_path),
                                    "-v", "quiet",
                                    "-print_format", "json",
                                    "-show_format",
                                    "-show_streams",
                                    str(audio_file)
                                ]
                                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                                if result.returncode == 0:
                                    data = json.loads(result.stdout)
                                    # Try to get track number
                                    track_num = None
                                    for stream in data.get("streams", []):
                                        if stream.get("codec_type") == "audio":
                                            tags = stream.get("tags", {})
                                            track_num = tags.get("track") or tags.get("TRACK")
                                            if track_num:
                                                try:
                                                    track_num = int(str(track_num).split("/")[0])
                                                    break
                                                except:
                                                    pass
                                    
                                    if track_num == 1 and audio_file in unique_artists_dict:
                                        first_track_artist = unique_artists_dict[audio_file]
                                        break
                        except:
                            pass
                    
                    # If we couldn't find track 1, use alphabetically first
                    if not first_track_artist and all_track_artists:
                        first_track_artist = sorted(list(all_track_artists))[0]
                
                # Store first_track_artist in split_album_info tuple
                split_album_info = (is_split_album, all_track_artists, first_track_artist) if is_split_album else None
                
                # First, try to get track numbers from metadata for all files in this directory
                files_with_track_numbers = []
                files_without_track_numbers = []
                
                for audio_file in dir_files:
                    file_title = audio_file.stem
                    track_number = None
                    track_title = file_title
                    
                    # Try to find track number from download_info
                    # Use more precise matching to avoid false matches
                    best_match = None
                    best_match_score = 0
                    
                    # Normalize file title for comparison (remove common prefixes, extra spaces)
                    # Also remove "artist - " pattern if present for better matching
                    normalized_file_title = re.sub(r'^\d+[.\-\s]*', '', file_title.lower()).strip()
                    # Try to extract artist and clean title from filename for matching
                    artist_from_filename = None
                    cleaned_file_title = normalized_file_title
                    # Check if filename has "artist - title" pattern
                    artist_match = re.match(r'^([^-]+)\s*-\s*(.+)$', normalized_file_title)
                    if artist_match:
                        artist_from_filename = artist_match.group(1).strip()
                        cleaned_file_title = artist_match.group(2).strip()
                    
                    # Also try matching just the stem without any prefixes
                    # Remove common separators and normalize
                    stem_only = re.sub(r'[^\w\s]', ' ', file_title.lower())
                    stem_only = ' '.join(stem_only.split())  # Normalize whitespace
                    
                    for title_key, info in self.download_info.items():
                        # Normalize title key for comparison
                        normalized_title_key = title_key.lower().strip()
                        # Also try to clean the title key if it has "artist - " pattern
                        cleaned_title_key = normalized_title_key
                        artist_match_key = re.match(r'^([^-]+)\s*-\s*(.+)$', normalized_title_key)
                        if artist_match_key:
                            cleaned_title_key = artist_match_key.group(2).strip()
                        
                        # Also normalize the title key stem
                        title_key_stem = re.sub(r'[^\w\s]', ' ', normalized_title_key)
                        title_key_stem = ' '.join(title_key_stem.split())  # Normalize whitespace
                        
                        # Calculate match score (prefer exact matches, then contains matches)
                        match_score = 0
                        # Try matching cleaned versions first
                        if cleaned_file_title == cleaned_title_key:
                            match_score = 100  # Exact match on cleaned titles
                        elif normalized_file_title == normalized_title_key:
                            match_score = 95  # Exact match on original
                        elif stem_only == title_key_stem:
                            match_score = 90  # Exact match on normalized stems
                        elif cleaned_file_title in cleaned_title_key or cleaned_title_key in cleaned_file_title:
                            # Substring match on cleaned titles - calculate similarity
                            shorter = min(len(cleaned_file_title), len(cleaned_title_key))
                            longer = max(len(cleaned_file_title), len(cleaned_title_key))
                            if shorter > 0:
                                match_score = (shorter / longer) * 50
                        elif stem_only in title_key_stem or title_key_stem in stem_only:
                            # Substring match on normalized stems
                            shorter = min(len(stem_only), len(title_key_stem))
                            longer = max(len(stem_only), len(title_key_stem))
                            if shorter > 0:
                                match_score = (shorter / longer) * 45
                        elif normalized_file_title in normalized_title_key or normalized_title_key in normalized_file_title:
                            # Substring match on original - calculate similarity
                            shorter = min(len(normalized_file_title), len(normalized_title_key))
                            longer = max(len(normalized_file_title), len(normalized_title_key))
                            if shorter > 0:
                                match_score = (shorter / longer) * 40
                        
                        # Only accept matches with high confidence
                        # Require at least 70% similarity for substring matches, or exact matches
                        min_score = 70 if match_score < 90 else 30  # Exact matches (90+) need lower threshold
                        if match_score > best_match_score and match_score >= min_score:
                            best_match_score = match_score
                            best_match = info
                    
                    if best_match:
                        track_number = best_match.get("track_number")
                        raw_title = best_match.get("title", file_title)
                        # Clean title to remove artist prefix if present
                        track_title = self._clean_title(raw_title, best_match.get("artist"))
                    else:
                        # If no match found, try to clean the filename itself
                        # Extract artist from filename if present, or use album artist
                        artist_for_cleaning = artist_from_filename
                        if not artist_for_cleaning:
                            # Try to get artist from album info
                            try:
                                artist_for_cleaning = self.album_info_stored.get("artist")
                            except Exception:
                                pass
                        # Clean the filename title
                        track_title = self._clean_title(file_title, artist_for_cleaning)
                    
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
                                        raw_title = tags.get("title") or tags.get("TITLE") or track_title
                                        # Clean title to remove artist prefix if present
                                        artist_from_tags = tags.get("artist") or tags.get("ARTIST")
                                        track_title = self._clean_title(raw_title, artist_from_tags)
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
                    
                    # Get original filename parts
                    parent_dir = audio_file.parent
                    extension = audio_file.suffix
                    
                    # Generate new filename using format data
                    new_name_base = self._generate_filename_from_format(
                        format_data, track_number, track_title,
                        audio_file, dir_path, split_album_info
                    )
                    
                    if not new_name_base:
                        continue  # Skip if generation failed
                    
                    new_name = new_name_base + extension
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
            
            # If no downloaded files found, use timestamp-based fallback to find recently downloaded files
            # This ensures we only process files from this download session, not existing files
            if not directories_to_search:
                if hasattr(self, 'download_start_time') and self.download_start_time:
                    # Use timestamp-based filtering to find directories with recently downloaded files
                    time_threshold = self.download_start_time - 30
                    audio_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".aac", ".mpa", ".opus"]
                    try:
                        for ext in audio_extensions:
                            for audio_file in base_path.rglob(f"*{ext}"):
                                # Skip temporary files
                                if audio_file.name.startswith('.') or 'tmp' in audio_file.name.lower():
                                    continue
                                # Only include files modified after download started (with buffer)
                                try:
                                    file_mtime = audio_file.stat().st_mtime
                                    if file_mtime >= time_threshold:
                                        directories_to_search.add(audio_file.parent)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                
                # If still no directories found, don't process anything (safety: don't modify existing files)
            
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
            
            # If no downloaded files found, use timestamp-based fallback to find recently downloaded files
            # This ensures we only process files from this download session, not existing files
            if not directories_to_check:
                if hasattr(self, 'download_start_time') and self.download_start_time:
                    # Use timestamp-based filtering to find directories with recently downloaded files
                    time_threshold = self.download_start_time - 30
                    audio_extensions = [".mp3", ".flac", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".aac", ".mpa", ".opus"]
                    try:
                        for ext in audio_extensions:
                            for audio_file in base_path.rglob(f"*{ext}"):
                                # Skip temporary files
                                if audio_file.name.startswith('.') or 'tmp' in audio_file.name.lower():
                                    continue
                                # Only include files modified after download started (with buffer)
                                try:
                                    file_mtime = audio_file.stat().st_mtime
                                    if file_mtime >= time_threshold:
                                        directories_to_check.add(audio_file.parent)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                
                # If still no directories found, don't process anything (safety: don't modify existing files)
                # This ensures we only process files that were definitely downloaded in this session
            
            # Process each directory
            for directory in directories_to_check:
                # Find all cover art files in this directory
                cover_art_files = []
                
                # Only process cover art files that were downloaded in this session
                if hasattr(self, 'download_start_time') and self.download_start_time:
                    time_threshold = self.download_start_time - 30
                    for ext in self.THUMBNAIL_EXTENSIONS:
                        for thumb_file in directory.glob(f"*{ext}"):
                            try:
                                # Only include files modified after download started (with buffer)
                                file_mtime = thumb_file.stat().st_mtime
                                if file_mtime >= time_threshold:
                                    cover_art_files.append(thumb_file)
                            except Exception:
                                pass
                else:
                    # If no timestamp available, only process if we have downloaded_files tracking
                    # Otherwise skip to avoid modifying existing files
                    if hasattr(self, 'downloaded_files') and self.downloaded_files:
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
                                            # Clean title if it contains artist prefix
                                            if metadata.get("title"):
                                                metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
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
                                                # Clean title if it contains artist prefix
                                                if metadata.get("title"):
                                                    metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
                                        except Exception:
                                            pass
                                    
                                    if metadata:
                                        success = self.re_embed_mp3_metadata(audio_file_str, metadata, thumbnail_file)
                                    else:
                                        # Try without metadata, just artwork
                                        cleaned_file_title = self._clean_title(file_title)
                                        success = self.re_embed_mp3_metadata(audio_file_str, {"title": cleaned_file_title}, thumbnail_file)
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
                                        # Clean title if it contains artist prefix
                                        if metadata.get("title"):
                                            metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
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
                                            # Clean title if it contains artist prefix
                                            if metadata.get("title"):
                                                metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
                                    except Exception:
                                        pass
                                
                                # Try to embed artwork (will work for all MP3 types)
                                if metadata:
                                    success = self.re_embed_mp3_metadata(mp3_file_str, metadata, thumbnail_file)
                                else:
                                    # Try without metadata, just artwork
                                    cleaned_file_title = self._clean_title(file_title)
                                    success = self.re_embed_mp3_metadata(mp3_file_str, {"title": cleaned_file_title}, thumbnail_file)
                                
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
                # Clean title if it contains artist prefix
                if tags and tags.get("title"):
                    title = tags.get("title", "")
                    artist = tags.get("artist") or tags.get("ARTIST")
                    cleaned_title = self._clean_title(title, artist)
                    if cleaned_title != title:
                        tags["title"] = cleaned_title
                return tags
            return None
        except Exception:
            return None
    
    def re_embed_audio_metadata(self, audio_file, metadata, thumbnail_file=None):
        """Re-embed metadata into audio file (MP3, M4A, FLAC, OGG) using FFmpeg."""
        try:
            audio_path = Path(audio_file)
            audio_ext = audio_path.suffix.lower()
            temp_output = str(audio_path.with_suffix('.tmp' + audio_path.suffix))
            
            cmd = [
                str(self.ffmpeg_path),
                "-i", str(audio_file),
            ]
            
            # Add thumbnail if provided
            if thumbnail_file and Path(thumbnail_file).exists():
                cmd.extend(["-i", str(thumbnail_file)])
                cmd.extend(["-map", "0:a", "-map", "1"])
                cmd.extend(["-c:a", "copy", "-c:v", "copy"])
                cmd.extend(["-disposition:v:0", "attached_pic"])
            else:
                cmd.extend(["-c:a", "copy"])
            
            # Clean title before embedding (remove artist prefix if present)
            clean_title = metadata.get("title", "")
            if clean_title:
                clean_title = self._clean_title(clean_title, metadata.get("artist"))
            
            # Add metadata
            if clean_title:
                cmd.extend(["-metadata", f"title={clean_title}"])
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
                Path(audio_file).unlink()
                Path(temp_output).rename(audio_file)
                return True
            else:
                if Path(temp_output).exists():
                    Path(temp_output).unlink()
                return False
        except Exception:
            return False
    
    def re_embed_mp3_metadata(self, mp3_file, metadata, thumbnail_file=None):
        """Re-embed metadata into MP3 file using FFmpeg."""
        # Use the generic function for MP3 as well
        return self.re_embed_audio_metadata(mp3_file, metadata, thumbnail_file)
    
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
                
                # If metadata exists but title might have artist prefix, fix it
                if tags and has_title and has_artist:
                    title = tags.get("title", "")
                    artist = tags.get("artist") or tags.get("ARTIST")
                    cleaned_title = self._clean_title(title, artist)
                    if cleaned_title != title:
                        # Title needs cleaning - re-embed with cleaned title
                        metadata = {
                            "title": cleaned_title,
                            "artist": artist,
                            "album": tags.get("album") or tags.get("ALBUM"),
                            "track_number": tags.get("track") or tags.get("TRACK"),
                            "date": tags.get("date") or tags.get("DATE")
                        }
                        thumbnail_file = self.find_thumbnail_file(str(mp3_file))
                        if self.re_embed_mp3_metadata(mp3_file, metadata, thumbnail_file):
                            fixed_count += 1
                            self.root.after(0, lambda f=mp3_file.name: self.log(f"✓ Fixed metadata: {f}"))
                        continue
                
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
                    
                    # Clean title if it contains artist prefix
                    if metadata.get("title"):
                        metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
                    
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
    
    def verify_and_fix_original_format_metadata(self, download_path):
        """Verify and fix metadata/artwork for all formats in Original format (MP3, M4A, FLAC, etc.)."""
        try:
            base_path = Path(download_path)
            if not base_path.exists():
                return
            
            # Supported formats for Original format
            audio_extensions = [".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".oga"]
            audio_files = []
            import time
            
            # Find audio files that were just downloaded
            if hasattr(self, 'downloaded_files') and self.downloaded_files:
                # Check files from downloaded_files set
                for downloaded_file in self.downloaded_files:
                    file_path = Path(downloaded_file)
                    if file_path.exists() and file_path.suffix.lower() in audio_extensions:
                        audio_files.append(file_path)
            
            # If no files tracked, use timestamp-based filtering
            if not audio_files and hasattr(self, 'download_start_time'):
                time_threshold = self.download_start_time - 30
                album_info = getattr(self, 'album_info_stored', None)
                artist_lower = (album_info.get("artist") or "").lower() if album_info else None
                album_lower = (album_info.get("album") or "").lower() if album_info else None
                
                for ext in audio_extensions:
                    for audio_file in base_path.rglob(f"*{ext}"):
                        try:
                            file_mtime = audio_file.stat().st_mtime
                            if file_mtime >= time_threshold:
                                if album_info and (artist_lower or album_lower):
                                    file_path_str = str(audio_file).lower()
                                    if (artist_lower and artist_lower in file_path_str) or \
                                       (album_lower and album_lower in file_path_str):
                                        audio_files.append(audio_file)
                                else:
                                    audio_files.append(audio_file)
                        except Exception:
                            pass
            
            if not audio_files:
                return
            
            # Group by extension for logging
            mp3_files = [f for f in audio_files if f.suffix.lower() == '.mp3']
            other_files = [f for f in audio_files if f.suffix.lower() != '.mp3']
            
            # Process MP3 files (use existing function)
            if mp3_files:
                self.verify_and_fix_mp3_metadata(download_path)
            
            # Process other formats (M4A, FLAC, etc.)
            if other_files:
                self.root.after(0, lambda: self.log(f"Embedding cover art for {len(other_files)} non-MP3 file(s)..."))
                
                # Group files by directory
                files_by_dir = {}
                for audio_file in other_files:
                    dir_path = audio_file.parent
                    if dir_path not in files_by_dir:
                        files_by_dir[dir_path] = []
                    files_by_dir[dir_path].append(audio_file)
                
                processed_count = 0
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
                    
                    # Process each file
                    for audio_file in dir_files:
                        audio_file_str = str(audio_file)
                        audio_file_name = audio_file.name
                        audio_ext = audio_file.suffix.lower()
                        file_title = audio_file.stem
                        
                        # Get metadata from download_info if available
                        metadata = {}
                        for title_key, info in self.download_info.items():
                            if file_title.lower() in title_key.lower() or title_key.lower() in file_title.lower():
                                metadata = info.copy()
                                # Clean title if it contains artist prefix
                                if metadata.get("title"):
                                    metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
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
                                    # Clean title if it contains artist prefix
                                    if metadata.get("title"):
                                        metadata["title"] = self._clean_title(metadata["title"], metadata.get("artist"))
                            except Exception:
                                pass
                        
                        # If still no metadata, use filename as title (cleaned)
                        if not metadata:
                            metadata = {"title": self._clean_title(file_title)}
                        
                        success = False
                        if audio_ext in [".m4a", ".mp4", ".aac"]:
                            # M4A/MP4/AAC: use re_embed_audio_metadata to fix metadata and embed cover art
                            success = self.re_embed_audio_metadata(audio_file_str, metadata, thumbnail_file)
                        elif audio_ext in [".flac", ".ogg", ".oga"]:
                            # FLAC/OGG: use re_embed_audio_metadata to fix metadata and embed cover art
                            success = self.re_embed_audio_metadata(audio_file_str, metadata, thumbnail_file)
                        
                        if success:
                            processed_count += 1
                            self.root.after(0, lambda name=audio_file_name: self.log(f"✓ Fixed metadata and embedded cover art: {name}"))
                        else:
                            self.root.after(0, lambda name=audio_file_name: self.log(f"⚠ Could not fix metadata: {name}"))
                
                if processed_count > 0:
                    self.root.after(0, lambda count=processed_count: self.log(f"Embedded cover art for {count} non-MP3 file(s)"))
        
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Error verifying Original format metadata: {str(e)}"))
    
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
                                raw_title = info.get("title", track_title)
                                # Clean title to remove artist prefix if present
                                track_title = self._clean_title(raw_title, info.get("artist"))
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
                # Check if skip MP3 re-encoding is enabled
                skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
                
                if skip_mp3_reencode:
                    # Skip re-encoding if file is already MP3 - only add metadata
                    # Format selection will prefer MP3 when available to avoid re-encoding
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
                else:
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
            # Format selection: if MP3 skip re-encoding is enabled and format is MP3, prefer MP3 format
            # If skip re-encoding is disabled, avoid MP3 format to force re-encoding
            format_selector = "bestaudio/best"
            if base_format == "mp3":
                skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
                if skip_mp3_reencode:
                    # Prefer MP3 format when available to avoid re-encoding
                    format_selector = "bestaudio[ext=mp3]/bestaudio/best"
                else:
                    # Avoid MP3 format to force re-encoding via postprocessor
                    # This ensures FFmpegExtractAudio will always run
                    format_selector = "bestaudio[ext!=mp3]/bestaudio/best"
            
            ydl_opts = {
                "format": format_selector,
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
            
            # Check if this is a track URL (single track, not album)
            is_track_url = False
            parsed_url = self._parse_bandcamp_url(album_url)
            if parsed_url:
                url_type = parsed_url[2]
                is_track_url = (url_type == 'track')
            
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
                    if quick_info:
                        # For track URLs, the info itself might be the track (no entries)
                        if is_track_url and "entries" not in quick_info:
                            # Single track - treat info as the track
                            self.total_tracks = 1
                            self.root.after(0, lambda: self.log("Found 1 track"))
                            self.root.after(0, lambda: self.progress_var.set("Found 1 track - Fetching track data..."))
                        elif "entries" in quick_info:
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
                        # Store album-level info (including all metadata fields for preview)
                        self.album_info_stored = {
                            "artist": info.get("artist") or info.get("uploader") or info.get("creator"),
                            "album": info.get("album") or info.get("title"),
                            "date": info.get("release_date") or info.get("upload_date"),
                            "genre": info.get("genre"),
                            "label": info.get("label") or info.get("publisher"),
                            "album_artist": info.get("album_artist") or info.get("albumartist"),
                            "catalog_number": info.get("catalog_number") or info.get("catalognumber"),
                        }
                        
                        # Handle track URLs: if no entries, treat info itself as the track
                        entries = []
                        if is_track_url and "entries" not in info:
                            # Single track URL - info itself is the track
                            entries = [info]
                            if self.total_tracks == 0:  # Only update if quick extraction didn't work
                                self.total_tracks = 1
                                self.root.after(0, lambda: self.log("Found 1 track"))
                        elif "entries" in info:
                            entries = [e for e in info.get("entries", []) if e]  # Filter out None entries
                            
                            # Single album mode, entries are tracks
                            if self.total_tracks == 0:  # Only update if quick extraction didn't work
                                self.total_tracks = len(entries)
                                self.root.after(0, lambda count=len(entries): self.log(f"Found {count} track(s)"))
                        
                        # Process entries (tracks)
                        if entries:
                            # Log format/bitrate info from first track (to show what yt-dlp is downloading)
                            # Always show source info so users know what quality they're getting
                            # Also detect format for Original Format mode preview
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
                                raw_title = entry.get("title", "")
                                if raw_title:
                                    # Get artist first (needed for title cleaning)
                                    artist = entry.get("artist") or entry.get("uploader") or entry.get("creator") or self.album_info_stored.get("artist")
                                    # Clean title to remove artist prefix if present
                                    cleaned_title = self._clean_title(raw_title, artist)
                                    
                                    # Also modify the entry itself so yt-dlp uses cleaned title during embedding
                                    if cleaned_title != raw_title:
                                        entry["title"] = cleaned_title
                                    
                                    self.download_info[raw_title.lower()] = {
                                        "title": cleaned_title,  # Use cleaned title (song name only)
                                        "artist": artist,
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
                        if retry_info:
                            # Handle track URLs: if no entries, treat info itself as the track
                            if is_track_url and "entries" not in retry_info:
                                # Single track URL - info itself is the track
                                self.total_tracks = 1
                                self.root.after(0, lambda: self.log("Found 1 track (retry)"))
                                # Add to download_info if not already there
                                if not self.download_info:
                                    raw_title = retry_info.get("title", "")
                                    if raw_title:
                                        artist = retry_info.get("artist") or retry_info.get("uploader") or retry_info.get("creator") or self.album_info_stored.get("artist")
                                        cleaned_title = self._clean_title(raw_title, artist)
                                        self.download_info[raw_title.lower()] = {
                                            "title": cleaned_title,
                                            "artist": artist,
                                            "album": retry_info.get("album") or retry_info.get("title") or self.album_info_stored.get("album"),
                                            "track_number": retry_info.get("track_number") or retry_info.get("track"),
                                            "date": retry_info.get("release_date") or retry_info.get("upload_date") or self.album_info_stored.get("date"),
                                        }
                            elif "entries" in retry_info:
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
                # Check if skip MP3 re-encoding is enabled
                skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
                
                if skip_mp3_reencode:
                    # Skip re-encoding if file is already MP3 - only add metadata
                    # Format selection will prefer MP3 when available to avoid re-encoding
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
                else:
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
            # Format selection: if MP3 skip re-encoding is enabled and format is MP3, prefer MP3 format
            # If skip re-encoding is disabled, avoid MP3 format to force re-encoding
            format_selector = "bestaudio/best"
            if base_format == "mp3":
                skip_mp3_reencode = self.skip_mp3_reencode_var.get() if hasattr(self, 'skip_mp3_reencode_var') else True
                if skip_mp3_reencode:
                    # Prefer MP3 format when available to avoid re-encoding
                    format_selector = "bestaudio[ext=mp3]/bestaudio/best"
                else:
                    # Avoid MP3 format to force re-encoding via postprocessor
                    # This ensures FFmpegExtractAudio will always run
                    format_selector = "bestaudio[ext!=mp3]/bestaudio/best"
            
            ydl_opts = {
                "format": format_selector,
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
                    
                    # Reset download_start_time for this album to ensure timestamp filtering works correctly
                    self.download_start_time = time.time()
                    
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
                                
                                # If still not found, try extracting from URL subdomain (last resort)
                                if not artist_name and "bandcamp.com" in url.lower():
                                    try:
                                        from urllib.parse import urlparse
                                        import re
                                        parsed = urlparse(url)
                                        hostname = parsed.hostname or ""
                                        if ".bandcamp.com" in hostname:
                                            subdomain = hostname.replace(".bandcamp.com", "")
                                            
                                            # First try splitting by hyphens (most common)
                                            if "-" in subdomain:
                                                artist_name = " ".join(word.capitalize() for word in subdomain.split("-"))
                                            else:
                                                # Handle camelCase (e.g., "samwebster" -> "Sam Webster")
                                                # Split on capital letters: "samwebster" -> ["sam", "webster"]
                                                words = re.findall(r'[a-z]+|[A-Z][a-z]*', subdomain)
                                                if len(words) > 1:
                                                    artist_name = " ".join(word.capitalize() for word in words)
                                                else:
                                                    # Just capitalize the whole thing as fallback
                                                    artist_name = subdomain.capitalize()
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
                    
                    # Reset download_start_time for this album to ensure timestamp filtering works correctly
                    self.download_start_time = time.time()
                    
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
            # Check for cancellation before each attempt
            if self.is_cancelling:
                self.ydl_instance = None
                return False
            
            # Reset progress hook tracking for this attempt
            self.progress_hooks_called = False
            self.progress_hook_call_count = 0
            
            if download_attempt > 0:
                # Check for cancellation before retry delay
                if self.is_cancelling:
                    self.ydl_instance = None
                    return False
                
                # Wait before retry (exponential backoff)
                retry_delay = 2.0 * download_attempt
                self.root.after(0, lambda delay=retry_delay, attempt=download_attempt: self.log(f"DEBUG: Retrying download after {delay}s delay (attempt {attempt + 1}/{max_download_retries + 1})"))
                time.sleep(retry_delay)
                
                # Check for cancellation after delay (user might have cancelled during wait)
                if self.is_cancelling:
                    self.ydl_instance = None
                    return False
                
                # Create new yt-dlp instance for retry
                ydl = yt_dlp.YoutubeDL(ydl_opts)
                self.ydl_instance = ydl
            
            try:
                ydl.download([album_url])
                # Log after download completes
                self.root.after(0, lambda attempt=download_attempt: self.log(f"DEBUG: yt-dlp download() returned successfully (attempt {attempt + 1})"))
                self.root.after(0, lambda: self.log(f"DEBUG: progress_hooks_called: {self.progress_hooks_called}, call_count: {self.progress_hook_call_count}"))
                self.root.after(0, lambda: self.log(f"DEBUG: downloaded_files after download: {len(self.downloaded_files) if hasattr(self, 'downloaded_files') and self.downloaded_files else 0}"))
                
                # Check for cancellation after download attempt
                if self.is_cancelling:
                    self.ydl_instance = None
                    return False
                
                # Check if progress hooks were called (indicates actual download activity)
                if self.progress_hooks_called or len(self.downloaded_files) > 0:
                    download_success = True
                    break
                elif download_attempt < max_download_retries:
                    # Check for cancellation before retrying
                    if self.is_cancelling:
                        self.ydl_instance = None
                        return False
                    
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
                # Check for cancellation before retrying on error
                if self.is_cancelling:
                    self.ydl_instance = None
                    return False
                
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
                # For MP3 format, verify and fix metadata if needed
                if base_format == "mp3":
                    self.verify_and_fix_mp3_metadata(download_path)
                # For Original format, verify and fix metadata/artwork for all formats (MP3, M4A, FLAC, etc.)
                elif base_format == "original":
                    self.verify_and_fix_original_format_metadata(download_path)
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
            
            # Clean title metadata to remove artist prefix before embedding
            # This ensures yt-dlp's FFmpegMetadata postprocessor uses the cleaned title
            # Do this for all statuses to catch titles before postprocessing
            if d.get('title'):
                title = d.get('title', '')
                artist = d.get('artist') or d.get('uploader') or d.get('creator')
                cleaned_title = self._clean_title(title, artist)
                if cleaned_title != title:
                    d['title'] = cleaned_title
            
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
    
    def get_version(self):
        """Get current application version."""
        return __version__
    
    def _is_launcher_mode(self):
        """Detect if running from launcher.exe.
        
        Returns True if launched from launcher.exe, False if standalone.
        """
        # Method 1: Environment variable (set by launcher) - fastest check
        if os.environ.get('BANDCAMP_LAUNCHER') == '1':
            return True
        
        # Method 2: Check if launcher.exe exists in same directory
        script_dir = Path(__file__).resolve().parent
        launcher_exe = script_dir / 'launcher.exe'
        if launcher_exe.exists():
            return True
        
        # Method 3: Check parent process name (if psutil available)
        # Cache psutil availability to avoid repeated import attempts
        if not hasattr(self, '_psutil_available'):
            try:
                import psutil
                self._psutil = psutil
                self._psutil_available = True
            except ImportError:
                self._psutil_available = False
                self._psutil = None
        
        if self._psutil_available and self._psutil:
            try:
                parent = self._psutil.Process().parent()
                if parent and 'launcher' in parent.name().lower():
                    return True
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                pass
        
        return False
    
    def _check_launcher_update_status(self):
        """Check for launcher update status file.
        
        Returns:
            List of status messages if found, None otherwise
        """
        if not self.is_launcher_mode:
            return None
        
        try:
            update_status_file = self.script_dir / "update_status.json"
            if update_status_file.exists():
                with open(update_status_file, 'r', encoding='utf-8') as f:
                    status = json.load(f)
                    return status
        except Exception:
            pass
        
        return None
    
    def _log_launcher_update_status(self):
        """Log launcher update status to the GUI log."""
        if not self.pending_update_status:
            return
        
        try:
            status = self.pending_update_status
            messages = status.get("messages", [])
            
            if messages:
                # Log all messages
                for msg_data in messages:
                    message = msg_data.get("message", "")
                    version = msg_data.get("version")
                    
                    if message:
                        if version:
                            self.log(f"{message} (v{version})")
                        else:
                            self.log(message)
                
                # Update clear button state after logging launcher status
                self._update_clear_button_state()
                # Also try with delays to handle timing
                self.root.after(10, self._update_clear_button_state)
                self.root.after(50, self._update_clear_button_state)
            
            # Clear the status file after logging
            update_status_file = self.script_dir / "update_status.json"
            if update_status_file.exists():
                update_status_file.unlink()
            
            # Clear pending status
            self.pending_update_status = None
        except Exception:
            pass
    
    def _check_for_updates_background(self):
        """Check for updates in background (non-blocking, no popup if up to date)."""
        self.check_for_updates(show_if_no_update=False)
    
    def check_for_updates(self, show_if_no_update=True):
        """Check for updates by reading version directly from main branch.
        
        Args:
            show_if_no_update: If True, show message even if no update is available (for manual check)
        """
        def check():
            try:
                try:
                    import requests
                    import re
                except ImportError:
                    if show_if_no_update:
                        self.root.after(0, lambda: messagebox.showerror(
                            "Update Check Failed",
                            "The 'requests' library is required for update checking.\n\n"
                            "Please install it:\n"
                            "python -m pip install requests"
                        ))
                    return
                
                # GitHub repository info
                repo_owner = "kameryn1811"
                repo_name = "Bandcamp-Downloader"
                
                # Get version directly from main branch file (not from releases)
                # This way we don't depend on releases being created/updated
                download_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/bandcamp_dl_gui.py"
                response = requests.get(download_url, timeout=10)
                response.raise_for_status()
                file_content = response.text
                
                # Extract version from the file
                version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', file_content)
                if not version_match:
                    if show_if_no_update:
                        self.root.after(0, lambda: messagebox.showerror(
                            "Update Check Failed",
                            "Could not find version number in main branch file."
                        ))
                    return
                
                latest_version = version_match.group(1)
                current_version = self.get_version()
                
                # Compare versions
                comparison_result = self._compare_versions(latest_version, current_version)
                
                if comparison_result > 0:
                    # Update available - show popup
                    # Log update available (user-visible)
                    if hasattr(self, 'log'):
                        self.root.after(0, lambda: self.log(f"Update available: v{current_version} → v{latest_version}"))
                    
                    # Try to fetch commit message from GitHub API
                    release_notes = self._fetch_commit_message(repo_owner, repo_name, latest_version)
                    
                    # Capture variables in lambda to avoid closure issues
                    self.root.after(0, lambda cv=current_version, lv=latest_version, du=download_url, rn=release_notes: 
                        self._show_update_popup(cv, lv, du, rn))
                else:
                    # Only log version check details in debug mode
                    if hasattr(self, 'log'):
                        self.root.after(0, lambda: self.log(
                            f"DEBUG: Update check: Found version v{latest_version} in main branch, "
                            f"current version: v{current_version}, comparison result: {comparison_result} "
                            f"({'newer' if comparison_result > 0 else 'same' if comparison_result == 0 else 'older'})"
                        ))
                    
                    if show_if_no_update:
                        # User manually checked, show "up to date" message
                        self.root.after(0, lambda: messagebox.showinfo(
                            "Update Check",
                            f"You're running the latest version (v{current_version})"
                        ))
            except requests.exceptions.RequestException as e:
                if show_if_no_update:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Update Check Failed",
                        f"Could not check for updates.\n\nError: {str(e)}\n\nPlease check your internet connection."
                    ))
            except Exception as e:
                if show_if_no_update:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Update Check Failed",
                        f"An error occurred while checking for updates.\n\nError: {str(e)}"
                    ))
        
        # Run in background thread to avoid blocking UI
        threading.Thread(target=check, daemon=True).start()
    
    def _compare_versions(self, version1, version2):
        """Compare two version strings.
        
        Returns:
            -1 if version1 < version2
             0 if version1 == version2
             1 if version1 > version2
        """
        def version_tuple(v):
            # Split version string and convert to integers
            parts = []
            for part in v.split('.'):
                try:
                    parts.append(int(part))
                except ValueError:
                    parts.append(0)
            return tuple(parts)
        
        v1_tuple = version_tuple(version1)
        v2_tuple = version_tuple(version2)
        
        # Pad with zeros to make same length
        max_len = max(len(v1_tuple), len(v2_tuple))
        v1_tuple = v1_tuple + (0,) * (max_len - len(v1_tuple))
        v2_tuple = v2_tuple + (0,) * (max_len - len(v2_tuple))
        
        if v1_tuple < v2_tuple:
            return -1
        elif v1_tuple > v2_tuple:
            return 1
        else:
            return 0
    
    def _fetch_commit_message(self, repo_owner, repo_name, version):
        """Fetch the commit message for the latest commit that modified bandcamp_dl_gui.py."""
        try:
            import requests
            
            # Get the latest commit that modified bandcamp_dl_gui.py on main branch
            api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits"
            params = {
                'path': 'bandcamp_dl_gui.py',
                'sha': 'main',
                'per_page': 1  # Only need the most recent commit
            }
            
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            commits = response.json()
            
            if commits and len(commits) > 0:
                commit_message = commits[0].get('commit', {}).get('message', '')
                # Clean up the commit message (remove version tag if present, keep the actual message)
                # Commit messages often have format: "v1.1.8\n\nActual message here"
                lines = commit_message.strip().split('\n')
                # Skip the first line if it's just a version number
                if len(lines) > 1 and (lines[0].startswith('v') or lines[0] == version):
                    # Join the rest of the lines (the actual commit message)
                    commit_message = '\n'.join(lines[1:]).strip()
                return commit_message
            
            return ""
        except Exception as e:
            # If fetching fails, just return empty string (non-critical)
            if hasattr(self, 'log'):
                self.root.after(0, lambda: self.log(f"Could not fetch commit message: {str(e)}"))
            return ""
    
    def _show_update_popup(self, current_version, latest_version, download_url, release_notes=""):
        """Show update available popup."""
        # Validate inputs
        if not current_version or not latest_version:
            self.log(f"ERROR: Invalid version info - current: {current_version}, latest: {latest_version}")
            messagebox.showerror(
                "Update Error",
                f"Invalid version information detected.\n\n"
                f"Current: {current_version}\n"
                f"Latest: {latest_version}\n\n"
                f"Please check for updates manually."
            )
            return
        
        if not download_url:
            self.log(f"ERROR: No download URL provided")
            messagebox.showerror(
                "Update Error",
                "No download URL available. Please download manually from GitHub."
            )
            return
        
        # Format release notes (first few lines)
        notes_preview = ""
        if release_notes and release_notes.strip():
            # Clean up the commit message - remove empty lines at start/end
            cleaned_notes = release_notes.strip()
            lines = [line for line in cleaned_notes.split('\n') if line.strip()]  # Remove empty lines
            if lines:
                # Show first 8 lines (more than before to show more context)
                preview_lines = lines[:8]
                notes_preview = "\n\n" + "\n".join(preview_lines)
                if len(lines) > 8:
                    notes_preview += "\n..."
        
        # Build message
        message = (
            f"A new version is available!\n\n"
            f"Current version: v{current_version}\n"
            f"Latest version: v{latest_version}"
        )
        
        if notes_preview:
            message += notes_preview
        
        message += (
            f"\n\nWould you like to update now?\n\n"
        )
        
        response = messagebox.askyesno("Update Available", message)
        
        if response:
            self._download_and_apply_update(download_url, latest_version)
        elif self.is_launcher_mode:
            # In launcher mode, update was already applied by launcher before GUI started
            # If user says "No", restore from backup
            self._restore_from_backup_if_exists(current_version, latest_version)
    
    def _download_and_apply_update(self, download_url, new_version):
        """Download and apply the update."""
        if self.is_launcher_mode:
            # In launcher mode, don't try to update ourselves
            # Just notify user to restart launcher
            self._update_complete(new_version)
            return
        
        def download():
            try:
                import requests
                
                # Show downloading message
                self.root.after(0, lambda: self.log(f"Downloading update (v{new_version}) from: {download_url}"))
                
                # Download new version
                response = requests.get(download_url, timeout=30)
                response.raise_for_status()
                new_script_content = response.text
                
                # Verify it's a valid Python script (basic check)
                if "BandcampDownloaderGUI" not in new_script_content:
                    raise ValueError("Downloaded file doesn't appear to be a valid script")
                
                # Verify the downloaded file's version matches or exceeds what we expect
                import re
                version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', new_script_content)
                if version_match:
                    downloaded_version = version_match.group(1)
                    # Log version verification in debug mode only
                    if downloaded_version != new_version:
                        self.root.after(0, lambda: self.log(f"DEBUG: Downloaded file version: {downloaded_version}, Expected: {new_version}"))
                    # The downloaded version should be >= the latest version we detected
                    if self._compare_versions(downloaded_version, new_version) < 0:
                        error_msg = (
                            f"Downloaded file version ({downloaded_version}) is older than expected ({new_version}). "
                            f"This may indicate the file hasn't been updated yet. Please try again later or download manually."
                        )
                        self.root.after(0, lambda: self.log(f"ERROR: {error_msg}"))
                        raise ValueError(error_msg)
                    # Also check if it's the same as current (which would be weird but possible)
                    current_ver = self.get_version()
                    if downloaded_version == current_ver and self._compare_versions(downloaded_version, new_version) < 0:
                        error_msg = (
                            f"Downloaded version ({downloaded_version}) matches current version, but we expected {new_version}. "
                            f"Please check the download URL or try again later."
                        )
                        self.root.after(0, lambda: self.log(f"ERROR: {error_msg}"))
                        raise ValueError(error_msg)
                else:
                    # If we can't find version, this is a problem - don't proceed
                    error_msg = "Could not find version number in downloaded file. This may not be the correct file."
                    self.root.after(0, lambda: self.log(f"ERROR: {error_msg}"))
                    raise ValueError(error_msg)
                
                # Get current script path
                current_script_path = Path(__file__).resolve()
                backup_path = current_script_path.with_suffix('.py.backup')
                
                # Create backup of current version
                if current_script_path.exists():
                    import shutil
                    shutil.copy2(current_script_path, backup_path)
                
                # Write new version
                # Use a temporary file first, then rename to ensure atomic write
                temp_file = current_script_path.with_suffix('.py.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(new_script_content)
                
                # Verify the temp file has the correct version before replacing
                with open(temp_file, 'r', encoding='utf-8') as f:
                    temp_content = f.read()
                    temp_version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', temp_content)
                    if temp_version_match:
                        temp_version = temp_version_match.group(1)
                        if temp_version != downloaded_version:
                            raise ValueError(f"Temp file version mismatch: expected {downloaded_version}, got {temp_version}")
                
                # Now replace the original file atomically
                if current_script_path.exists():
                    current_script_path.unlink()  # Delete old file
                temp_file.replace(current_script_path)  # Rename temp to final
                
                # Verify the final file one more time
                with open(current_script_path, 'r', encoding='utf-8') as f:
                    final_content = f.read()
                    final_version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', final_content)
                    if final_version_match:
                        final_version = final_version_match.group(1)
                        if final_version != downloaded_version:
                            raise ValueError(f"Final file version mismatch: expected {downloaded_version}, got {final_version}")
                
                # Success - show message and restart
                self.root.after(0, lambda: self._update_complete(new_version))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Update Failed",
                    f"Failed to download update.\n\nError: {str(e)}\n\n"
                    f"Please download manually from:\n"
                    f"https://github.com/kameryn1811/Bandcamp-Downloader/releases/latest"
                ))
        
        # Run download in background thread
        threading.Thread(target=download, daemon=True).start()
    
    def _restore_from_backup_if_exists(self, current_version, latest_version):
        """Restore from backup if user declined update in launcher mode.
        
        In launcher mode, the launcher updates the script before launching the GUI.
        If the user declines the update, we restore the previous version from backup.
        """
        if not self.is_launcher_mode:
            return
        
        try:
            current_script_path = Path(__file__).resolve()
            backup_path = current_script_path.with_suffix('.py.backup')
            
            if not backup_path.exists():
                # No backup found, can't restore
                self.log("No backup file found to restore from.")
                return
            
            # Verify backup file and restore it
            # In launcher mode, the file on disk was already updated by launcher
            # But we're still running the old code, so current_version is what we're running (old version)
            # The backup contains the version that was on disk before launcher updated it
            # We want to restore the backup to revert the launcher's update
            import re
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_content = f.read()
                backup_version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', backup_content)
                
                if backup_version_match:
                    backup_version = backup_version_match.group(1)
                    # Check what version is actually in the current file on disk
                    with open(current_script_path, 'r', encoding='utf-8') as f:
                        file_content = f.read()
                        file_version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', file_content)
                        file_version = file_version_match.group(1) if file_version_match else None
                    
                    # If file on disk has newer version than backup, we can safely restore
                    # Or if versions match (backup = what we're running), that's also safe to restore
                    if file_version and self._compare_versions(file_version, backup_version) > 0:
                        # File on disk is newer than backup - safe to restore
                        import shutil
                        shutil.copy2(backup_path, current_script_path)
                        self.log(f"Restored previous version v{backup_version} from backup (update declined).")
                    elif backup_version == current_version:
                        # Backup matches what we're running - safe to restore (ensures file matches running code)
                        import shutil
                        shutil.copy2(backup_path, current_script_path)
                        self.log(f"Restored version v{backup_version} from backup to match running version (update declined).")
                    else:
                        # File version is same or older than backup - something unexpected, don't restore
                        self.log(f"Cannot restore: File version ({file_version}) is not newer than backup ({backup_version}).")
                else:
                    self.log("Could not verify backup file version. Cannot restore safely.")
        except Exception as e:
            self.log(f"Error restoring from backup: {e}")
            messagebox.showerror(
                "Restore Failed",
                f"Failed to restore previous version from backup.\n\n"
                f"Error: {str(e)}\n\n"
                f"You may need to manually restore or reinstall the previous version."
            )
    
    def _update_complete(self, new_version):
        """Handle update completion."""
        if self.is_launcher_mode:
            # Launcher mode: Just notify user to restart launcher
            # Don't try to update ourselves - launcher handles that
            messagebox.showinfo(
                "Update Installed",
                f"Version v{new_version} has been installed!\n\n"
                f"Please close this application and reopen it to launch version v{new_version}.\n\n"
            )
            # Don't restart - let launcher handle updates
        else:
            # Standalone mode: Update complete, ask user to restart
            messagebox.showinfo(
                "Update Complete",
                f"Successfully updated to v{new_version}!\n\n"
                f"Please close this application and restart it to use the new version."
            )
            # Don't auto-restart - let user restart manually (same behavior as launcher)
    
    def _show_settings_menu(self, event):
        """Show settings menu when cog icon is Clicked."""
        if self.settings_menu is None:
            # Use theme colors for settings menu
            colors = self.theme_colors
            # Main container background: dark mode uses entry_bg, light mode uses select_bg (white)
            menu_bg = colors.select_bg if self.current_theme == 'light' else colors.entry_bg
            menu_fg = colors.fg
            
            # Create settings menu
            self.settings_menu = Menu(
                self.root,
                tearoff=0,
                bg=menu_bg,
                fg=menu_fg,
                activebackground=colors.accent,
                activeforeground='#FFFFFF',
                selectcolor=colors.accent,
                borderwidth=1,
                relief='flat'
            )
            
            # Check for Updates
            self.settings_menu.add_command(
                label="Check for Updates",
                command=self.check_for_updates
            )
            
            # Auto-check for updates (checkbox)
            self.settings_menu.add_checkbutton(
                label="Automatically Check for Updates",
                variable=self.auto_check_updates_var,
                command=self.on_auto_check_updates_change
            )
            
            # Separator
            self.settings_menu.add_separator()
            
            # Theme toggle - Switch to Light/Dark Mode
            theme_label = "Switch to Light Mode" if self.current_theme == 'dark' else "Switch to Dark Mode"
            self.settings_menu.add_command(
                label=theme_label,
                command=self.toggle_theme
            )
            
            # URL Tag Color Scheme submenu
            colors = self.theme_colors
            self.color_scheme_menu = Menu(
                self.settings_menu,
                tearoff=0,
                bg=colors.select_bg,
                fg=colors.fg,
                activebackground=colors.accent,
                activeforeground='#FFFFFF',
                selectcolor=colors.accent,
                borderwidth=1,
                relief='flat'
            )
            self.settings_menu.add_cascade(
                label="URL Tag Themes",
                menu=self.color_scheme_menu
            )
            
            # Populate color scheme menu (will be built dynamically)
            # Note: "Get More Themes" is added in _build_color_scheme_menu()
            self._build_color_scheme_menu()
            
            # Separator
            self.settings_menu.add_separator()             
            
            # Additional Settings
            self.settings_menu.add_command(
                label="Additional Settings",
                command=self._show_additional_settings
            )           
            
            # Separator
            self.settings_menu.add_separator()
            
            # About
            self.settings_menu.add_command(
                label="About",
                command=self._show_about_dialog
            )
            
            # Open GitHub Repository
            self.settings_menu.add_command(
                label="GitHub Repository",
                command=lambda: webbrowser.open("https://github.com/kameryn1811/Bandcamp-Downloader")
            )
            
            # Report Issue
            self.settings_menu.add_command(
                label="Report Issue",
                command=lambda: webbrowser.open("https://github.com/kameryn1811/Bandcamp-Downloader/issues")
            )
        
        # Rebuild color scheme menu to show current selection
        try:
            if hasattr(self, 'color_scheme_menu'):
                self._build_color_scheme_menu()
        except Exception:
            # If rebuilding fails, continue anyway - menu should still work
            pass
        
        # Show menu at cursor position
        try:
            self.settings_menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            # If menu fails to show, try to show error
            try:
                messagebox.showerror("Menu Error", f"Could not open settings menu:\n\n{str(e)}")
            except Exception:
                pass
        finally:
            # Make sure to release the grab (Tkinter quirk)
            try:
                self.settings_menu.grab_release()
            except Exception:
                pass
    
    def _create_color_scheme_preview_image(self, scheme_name, colors, num_colors=6):
        """Create a composite preview image with scheme name text and color swatches.
        
        Args:
            scheme_name: Name of the color scheme
            colors: List of hex color strings
            num_colors: Number of colors to show in preview (default 6)
            
        Returns:
            PhotoImage object showing scheme name and colored squares, or None if PIL unavailable
        """
        try:
            # Import PIL modules - ensure all are available
            try:
                from PIL import Image, ImageDraw, ImageFont, ImageTk
            except ImportError:
                # Fallback: try importing individually
                import PIL.Image as Image
                import PIL.ImageDraw as ImageDraw
                import PIL.ImageFont as ImageFont
                import PIL.ImageTk as ImageTk
            
            # Create display name
            if scheme_name == "default":
                display_name = "Default"
            else:
                display_name = scheme_name.title()
            
            # Image dimensions
            square_size = 12
            spacing = 2
            num_to_show = min(num_colors, len(colors))
            squares_width = (square_size * num_to_show) + (spacing * (num_to_show - 1))
            
            # Font loading - more robust for PyInstaller bundles
            font = None
            try:
                # Try Windows system fonts with full paths (works in PyInstaller)
                import sys
                if sys.platform == 'win32':
                    # Try common Windows font paths
                    font_paths = [
                        r"C:\Windows\Fonts\arial.ttf",
                        r"C:\Windows\Fonts\segoeui.ttf",
                        r"C:\Windows\Fonts\calibri.ttf",
                    ]
                    for font_path in font_paths:
                        try:
                            if Path(font_path).exists():
                                font = ImageFont.truetype(font_path, 10)
                                break
                        except:
                            continue
                
                # If Windows paths failed, try direct font name (may work in some cases)
                if font is None:
                    try:
                        font = ImageFont.truetype("arial.ttf", 10)
                    except:
                        try:
                            font = ImageFont.truetype("segoeui.ttf", 10)
                        except:
                            pass
            except:
                pass
            
            # Final fallback to default font (always works)
            if font is None:
                font = ImageFont.load_default()
            
            # Create a temporary image to measure text width
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            text_bbox = temp_draw.textbbox((0, 0), display_name, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # Add padding: text padding + gap + squares
            text_padding = 8  # Left padding for text
            gap = 12  # Gap between text and squares
            total_width = text_padding + text_width + gap + squares_width + 8  # Right padding
            total_height = max(square_size, text_height) + 4  # Add vertical padding
            
            # Use theme colors for preview image
            theme_colors = self.theme_colors
            # Main container background: dark mode uses entry_bg, light mode uses select_bg (white)
            preview_bg = theme_colors.select_bg if self.current_theme == 'light' else theme_colors.entry_bg
            preview_fg = theme_colors.fg
            preview_border = theme_colors.border
            
            # Create image with menu background color
            img = Image.new('RGB', (total_width, total_height), color=preview_bg)
            draw = ImageDraw.Draw(img)
            
            # Draw scheme name text (left side)
            text_x = text_padding
            text_y = (total_height - text_height) // 2
            if font:
                draw.text((text_x, text_y), display_name, fill=preview_fg, font=font)
            else:
                # Fallback: draw text without font (basic rendering)
                draw.text((text_x, text_y), display_name, fill=preview_fg)
            
            # Draw colored squares (right side)
            squares_x = text_padding + text_width + gap
            squares_y = (total_height - square_size) // 2
            
            for i in range(num_to_show):
                color = colors[i]
                # Convert hex to RGB tuple
                hex_color = color.lstrip('#')
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                
                # Draw square
                x1 = squares_x + (i * (square_size + spacing))
                y1 = squares_y
                x2 = x1 + square_size - 1
                y2 = y1 + square_size - 1
                draw.rectangle(
                    [x1, y1, x2, y2],
                    fill=(r, g, b),
                    outline=preview_border,  # Theme-aware border
                    width=1
                )
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(img)
            return photo
        except Exception as e:
            # Log error for debugging (only in debug mode or if logging is available)
            if hasattr(self, 'log'):
                try:
                    self.log(f"DEBUG: Failed to create preview image for {scheme_name}: {str(e)}")
                except:
                    pass
            # Fallback: return None if image creation fails
            return None
    
    def _build_color_scheme_menu(self):
        """Build the color scheme submenu with preview swatches."""
        if not hasattr(self, 'color_scheme_menu'):
            return
        
        try:
            # Clear existing menu items
            self.color_scheme_menu.delete(0, END)
        except Exception:
            # If delete fails, menu might be empty or not initialized properly
            pass
        
        try:
            # Store preview images to prevent garbage collection
            if not hasattr(self, '_color_scheme_preview_images'):
                self._color_scheme_preview_images = []
            self._color_scheme_preview_images.clear()
            
            schemes = self._get_color_schemes()
            # Sort schemes: default first, then alphabetically
            scheme_names = sorted([name for name in schemes.keys() if name != "default"])
            scheme_names.insert(0, "default")
            
            for scheme_name in scheme_names:
                try:
                    colors = schemes[scheme_name]
                    
                    # Create composite preview image with text and colors
                    preview_image = None
                    try:
                        preview_image = self._create_color_scheme_preview_image(scheme_name, colors, num_colors=6)
                        if preview_image:
                            self._color_scheme_preview_images.append(preview_image)  # Keep reference
                    except Exception as e:
                        # If image creation fails, log for debugging and continue without preview
                        if hasattr(self, 'log'):
                            try:
                                self.log(f"DEBUG: Preview image creation failed for {scheme_name}: {str(e)}")
                            except:
                                pass
                        pass
                    
                    # Create display name for fallback
                    if scheme_name == "default":
                        display_name = "Default"
                    else:
                        display_name = scheme_name.title()
                    
                    # Add radiobutton to show current selection
                    def make_callback(name):
                        return lambda: self._change_tag_color_scheme(name)
                    
                    # Add menu item with composite image (text + colors in one image)
                    if preview_image:
                        self.color_scheme_menu.add_radiobutton(
                            label="",  # Empty label since text is in the image
                            image=preview_image,
                            variable=self.tag_color_scheme_var,
                            value=scheme_name,
                            command=make_callback(scheme_name)
                        )
                    else:
                        # Fallback without image - use text with Unicode squares
                        preview_chars = " ".join(["■"] * min(6, len(colors)))
                        label = f"{display_name}  {preview_chars}"
                        self.color_scheme_menu.add_radiobutton(
                            label=label,
                            variable=self.tag_color_scheme_var,
                            value=scheme_name,
                            command=make_callback(scheme_name)
                        )
                except Exception:
                    # Skip this scheme if there's an error
                    continue
            
            # Update variable to reflect current selection
            if hasattr(self, 'tag_color_scheme_var'):
                self.tag_color_scheme_var.set(self.current_tag_color_scheme)
            
            # Add "Get More Themes" separator and menu item
            self.color_scheme_menu.add_separator()
            self.color_scheme_menu.add_command(
                label="Get More Themes...",
                command=self._show_get_more_themes_dialog
            )
            
            # Add refresh option
            self.color_scheme_menu.add_command(
                label="Refresh Themes",
                command=self._refresh_color_schemes
            )
            
            # Add open themes directory option
            self.color_scheme_menu.add_command(
                label="Open Themes Directory",
                command=self._open_themes_directory
            )
        except Exception as e:
            # If building fails completely, at least add a basic menu item
            try:
                self.color_scheme_menu.add_command(
                    label="Error loading themes",
                    state='disabled'
                )
                self.color_scheme_menu.add_separator()
                self.color_scheme_menu.add_command(
                    label="Get More Themes...",
                    command=self._show_get_more_themes_dialog
                )
                self.color_scheme_menu.add_command(
                    label="Refresh Themes",
                    command=self._refresh_color_schemes
                )
                self.color_scheme_menu.add_command(
                    label="Open Themes Directory",
                    command=self._open_themes_directory
                )
            except Exception:
                pass
    
    def _change_tag_color_scheme(self, scheme_name):
        """Change the tag color scheme and reprocess tags.
        
        Args:
            scheme_name: Name of the color scheme to use
        """
        schemes = self._get_color_schemes()
        if scheme_name not in schemes:
            return
        
        # Update current scheme
        self.current_tag_color_scheme = scheme_name
        self.current_tag_colors = schemes[scheme_name]
        
        # Update variable
        if hasattr(self, 'tag_color_scheme_var'):
            self.tag_color_scheme_var.set(scheme_name)
        
        # Save preference
        self.save_tag_color_scheme()
        
        # Reprocess tags to apply new colors
        if self.url_tag_mapping:
            self.root.after(50, self._process_url_tags)
    
    def _refresh_color_schemes(self):
        """Refresh color schemes by clearing cache and rebuilding menu."""
        # Clear cached schemes to force reload from disk (class-level cache)
        # Access the class variable directly
        type(self)._TAG_COLOR_SCHEMES = None
        
        # Force reload by calling the load function directly (bypasses cache)
        schemes = self._load_color_schemes_from_css()
        # Update the cache with fresh data
        type(self)._TAG_COLOR_SCHEMES = schemes
        
        # Reload current scheme
        if self.current_tag_color_scheme not in schemes:
            self.current_tag_color_scheme = "default"
        self.current_tag_colors = schemes.get(self.current_tag_color_scheme, schemes["default"])
        
        # Update variable if it exists
        if hasattr(self, 'tag_color_scheme_var'):
            self.tag_color_scheme_var.set(self.current_tag_color_scheme)
        
        # Rebuild menu
        if hasattr(self, 'color_scheme_menu'):
            self._build_color_scheme_menu()
        
        # Count themes
        theme_count = len([name for name in schemes.keys() if name != "default"])
        messagebox.showinfo(
            "Themes Refreshed", 
            f"Color schemes have been refreshed.\n\n{theme_count} theme(s) are now available in the menu."
        )
    
    def _open_themes_directory(self):
        """Open the Color Schemes directory in Windows Explorer."""
        css_dir = self.script_dir / "Color Schemes"
        
        # Create directory if it doesn't exist
        css_dir.mkdir(exist_ok=True)
        
        try:
            import platform
            
            # Use os.startfile on Windows, or subprocess on other platforms
            if platform.system() == "Windows":
                os.startfile(str(css_dir))
            else:
                # For macOS and Linux
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", str(css_dir)])
                else:  # Linux
                    subprocess.run(["xdg-open", str(css_dir)])
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Could not open themes directory:\n\n{str(e)}\n\n"
                f"Directory location: {css_dir}"
            )
    
    def _fetch_themes_manifest(self):
        """Fetch themes.json manifest from GitHub.
        
        Returns:
            Dictionary with themes data, or None if fetch fails
        """
        try:
            import requests
        except ImportError:
            messagebox.showerror(
                "Missing Dependency",
                "The 'requests' library is required for downloading themes.\n\n"
                "Please install it:\n"
                "python -m pip install requests"
            )
            return None
        
        try:
            repo_owner = "kameryn1811"
            repo_name = "Bandcamp-Downloader"
            manifest_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/Color%20Schemes/themes.json"
            
            response = requests.get(manifest_url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            messagebox.showerror(
                "Download Failed",
                f"Could not fetch themes from GitHub:\n\n{str(e)}\n\n"
                "Please check your internet connection and try again."
            )
            return None
        except json.JSONDecodeError:
            messagebox.showerror(
                "Invalid Manifest",
                "The themes manifest file is invalid or corrupted.\n\n"
                "Please try again later."
            )
            return None
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"An unexpected error occurred:\n\n{str(e)}"
            )
            return None
    
    def _download_theme_file(self, filename):
        """Download a single theme CSS file from GitHub.
        
        Args:
            filename: Name of the CSS file to download
            
        Returns:
            File content as string, or None if download fails
        """
        try:
            import requests
        except ImportError:
            return None
        
        try:
            repo_owner = "kameryn1811"
            repo_name = "Bandcamp-Downloader"
            # URL encode the filename
            from urllib.parse import quote
            encoded_filename = quote(filename)
            file_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/Color%20Schemes/{encoded_filename}"
            
            response = requests.get(file_url, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception:
            return None
    
    def _get_theme_preview_colors(self, filename):
        """Get preview colors from a theme CSS file (quick fetch for preview).
        
        Args:
            filename: Name of the CSS file
            
        Returns:
            List of 6 hex color strings, or empty list if fetch fails
        """
        try:
            # Try to download just enough to get colors (first 500 chars should be enough)
            content = self._download_theme_file(filename)
            if content:
                colors = self._parse_css_color_scheme(content)
                if colors:
                    return colors[:6]  # Return first 6 colors
        except Exception:
            pass
        return []
    
    def _show_get_more_themes_dialog(self):
        """Show dialog to browse and download themes from GitHub."""
        # Fetch themes manifest
        manifest = self._fetch_themes_manifest()
        if not manifest:
            return
        
        themes = manifest.get("themes", [])
        if not themes:
            messagebox.showinfo(
                "No Themes Available",
                "No themes are currently available for download."
            )
            return
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Show loading dialog first
        loading_dialog = self._create_dialog_base("Loading Themes", 400, 120)
        loading_frame = Frame(loading_dialog, bg=main_bg)
        loading_frame.pack(fill=BOTH, expand=True, padx=20, pady=20)
        
        loading_label = Label(
            loading_frame,
            text="Loading theme previews...",
            font=("Segoe UI", 10),
            bg=main_bg,
            fg=colors.fg
        )
        loading_label.pack(pady=(0, 10))
        
        loading_dialog.update()
        
        # Create main dialog (hidden initially)
        dialog = self._create_dialog_base("Get More Themes", 650, 500)
        dialog.withdraw()  # Hide until ready
        
        # Filter themes first (before fetching previews)
        # Get existing schemes and normalize to lowercase for comparison
        existing_schemes_raw = self._get_color_schemes().keys()
        existing_schemes = set()
        for scheme in existing_schemes_raw:
            if scheme != "default":
                # Normalize to lowercase for comparison (same as how we extract from filenames)
                existing_schemes.add(scheme.lower())
        
        available_themes = []
        for theme in themes:
            # Extract and normalize scheme name the same way as _load_color_schemes_from_css does
            scheme_name = theme["filename"].replace("Scheme_", "").replace(".css", "")
            scheme_name = scheme_name.split("-")[0]  # Remove suffixes like "-CE", "-EE"
            scheme_name = scheme_name.replace("_", " ").lower()  # Normalize to lowercase
            
            # Check if this theme is already installed (case-insensitive comparison)
            if scheme_name not in existing_schemes:
                available_themes.append(theme)
        
        if not available_themes:
            loading_dialog.destroy()
            dialog.destroy()  # Also destroy the hidden main dialog
            messagebox.showinfo(
                "All Themes Installed",
                "All available themes are already installed!\n\n"
                "You can create custom themes by adding CSS files to the Color Schemes folder."
            )
            return
        
        # Show dialog immediately with placeholder colors (lazy loading)
        loading_dialog.destroy()
        dialog.deiconify()  # Show dialog immediately
        
        # Placeholder colors for unloaded themes (neutral gray tones, not colorful)
        placeholder_colors = ['#404040', '#505050', '#606060', '#505050', '#404040', '#505050']
        
        # Store preview frame references for updating
        preview_frames = {}  # filename -> preview_frame widget
        loaded_previews = set()  # Track which previews have been loaded
        loading_queue = []  # Queue of themes to load
        
        def build_dialog_ui():
            """Build the dialog UI with placeholder colors (lazy loading)."""
            
            # Main container
            main_frame = Frame(dialog, bg=main_bg)
            main_frame.pack(fill=BOTH, expand=True, padx=8, pady=8)
            
            # Title
            title_label = Label(
                main_frame,
                text="Available Themes",
                font=("Segoe UI", 11, "bold"),
                bg=main_bg,
                fg=colors.fg
            )
            title_label.pack(pady=(0, 5))
            
            # Description - more compact
            desc_label = Label(
                main_frame,
                text="Select themes to download. Your custom themes will be preserved.",
                font=("Segoe UI", 8),
                bg=main_bg,
                fg=colors.disabled_fg,
                wraplength=630
            )
            desc_label.pack(pady=(0, 8))
            
            # Scrollable frame for theme list
            list_container = Frame(main_frame, bg=main_bg)
            list_container.pack(fill=BOTH, expand=True, pady=(0, 10))
            
            canvas = Canvas(list_container, bg=main_bg, highlightthickness=0)
            # Use theme-appropriate scrollbar style
            scrollbar_style = 'TScrollbar' if self.current_theme == 'light' else 'Dark.Vertical.TScrollbar'
            scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview, style=scrollbar_style)
            scrollable_frame = Frame(canvas, bg=main_bg)
            
            def on_frame_configure(event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            
            scrollable_frame.bind("<Configure>", on_frame_configure)
            
            canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            
            def on_canvas_configure(event):
                canvas_width = event.width
                canvas.itemconfig(canvas_frame, width=canvas_width)
            
            # Store original configure handler
            canvas.configure(yscrollcommand=scrollbar.set)
            
            
            # Pack canvas and scrollbar
            canvas.pack(side=LEFT, fill=BOTH, expand=True)
            scrollbar.pack(side=RIGHT, fill=Y)
            
            # Store theme data and checkboxes
            dialog.theme_checkboxes = {}
            dialog.theme_data = {}
            
            # Theme item background: use entry_bg for a slightly different shade
            item_bg = colors.entry_bg if self.current_theme == 'light' else colors.entry_bg
            
            # Create theme items
            for theme in available_themes:
                theme_frame = Frame(scrollable_frame, bg=item_bg, relief='flat', borderwidth=1, highlightbackground=colors.border, highlightthickness=1)
                theme_frame.pack(fill=X, padx=4, pady=3)
                
                # Checkbox
                var = BooleanVar(value=True)  # Default to selected
                checkbox = Checkbutton(
                    theme_frame,
                    variable=var,
                    bg=item_bg,
                    fg=colors.fg,
                    activebackground=item_bg,
                    activeforeground=colors.fg,
                    selectcolor=main_bg
                )
                checkbox.pack(side=LEFT, padx=6, pady=6)
                dialog.theme_checkboxes[theme["filename"]] = var
                
                # Color preview frame (store reference for lazy loading)
                preview_frame = Frame(theme_frame, bg=item_bg)
                preview_frame.pack(side=LEFT, padx=(0, 8), pady=6)
                preview_frames[theme["filename"]] = preview_frame  # Store for updating
                
                # Start with placeholder colors (will be updated when loaded)
                for i, color in enumerate(placeholder_colors[:6]):
                    try:
                        color_label = Label(
                            preview_frame,
                            bg=color,
                            width=1,
                            height=1,
                            relief='flat',
                            borderwidth=0,
                            highlightthickness=0
                        )
                        color_label.pack(side=LEFT, padx=0.5)
                    except Exception:
                        pass
                
                # Theme info frame
                info_frame = Frame(theme_frame, bg=item_bg)
                info_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 6), pady=6)
                
                # Theme name and description
                theme_name = theme.get("name", theme["filename"].replace("Scheme_", "").replace(".css", ""))
                description = theme.get("description", "")
                name_text = f"{theme_name} - {description}" if description else theme_name
                
                name_label = Label(
                    info_frame,
                    text=name_text,
                    font=("Segoe UI", 9),
                    bg=item_bg,
                    fg=colors.fg,
                    anchor='w',
                    wraplength=400
                )
                name_label.pack(anchor='w', fill=X)
                
                # Make entire row Clickable to toggle checkbox
                def make_toggle_callback(checkbox_var):
                    def toggle_checkbox(event):
                        checkbox_var.set(not checkbox_var.get())
                    return toggle_checkbox
                
                toggle_callback = make_toggle_callback(var)
                for widget in [theme_frame, preview_frame, info_frame]:
                    widget.bind("<Button-1>", toggle_callback)
                    for child in widget.winfo_children():
                        try:
                            child.bind("<Button-1>", toggle_callback)
                        except:
                            pass
                
                dialog.theme_data[theme["filename"]] = {"theme": theme, "conflict": False}
            
            # Buttons frame
            buttons_frame = Frame(main_frame, bg=main_bg)
            buttons_frame.pack(fill=X, pady=(8, 0))
            
            # Select All / Deselect All buttons
            def select_all():
                for var in dialog.theme_checkboxes.values():
                    var.set(True)
            
            def deselect_all():
                for var in dialog.theme_checkboxes.values():
                    var.set(False)
            
            select_all_btn = ttk.Button(
                buttons_frame,
                text="Select All",
                command=select_all
            )
            select_all_btn.pack(side=LEFT, padx=(0, 5))
            
            deselect_all_btn = ttk.Button(
                buttons_frame,
                text="Deselect All",
                command=deselect_all
            )
            deselect_all_btn.pack(side=LEFT, padx=(0, 8))
            
            # Install Selected button
            def install_selected():
                selected = [fname for fname, var in dialog.theme_checkboxes.items() if var.get()]
                if not selected:
                    messagebox.showwarning("No Selection", "Please select at least one theme to install.")
                    return
                self._install_themes(dialog, selected)
            
            install_btn = ttk.Button(
                buttons_frame,
                text="Install Selected",
                command=install_selected,
                style='Download.TButton'
            )
            install_btn.pack(side=LEFT, padx=(0, 8))
            
            # Cancel button
            cancel_btn = ttk.Button(
                buttons_frame,
                text="Cancel",
                command=dialog.destroy
            )
            cancel_btn.pack(side=RIGHT)
            
            # Function to update a single theme's preview colors
            def update_theme_preview(filename, colors):
                """Update preview colors for a specific theme."""
                if filename not in preview_frames:
                    return
                
                # If no colors were fetched, keep placeholder and mark as loaded
                if not colors:
                    loaded_previews.add(filename)
                    return  # Don't update - keep the placeholder
                
                preview_frame = preview_frames[filename]
                # Clear existing color labels
                for widget in preview_frame.winfo_children():
                    widget.destroy()
                
                # Create new color swatches with actual colors
                # Use item_bg for the label background (matches preview_frame background)
                for i, color in enumerate(colors[:6]):
                    try:
                        color_label = Label(
                            preview_frame,
                            bg=color,  # The actual theme color
                            width=1,
                            height=1,
                            relief='flat',
                            borderwidth=0,
                            highlightthickness=0
                        )
                        color_label.pack(side=LEFT, padx=0.5)
                    except Exception:
                        pass
                
                loaded_previews.add(filename)
            
            # Function to get visible theme indices based on scroll position
            def get_visible_themes():
                """Get indices of themes currently visible in the viewport."""
                try:
                    # Get canvas viewport bounds
                    canvas_top = canvas.canvasy(0)
                    canvas_bottom = canvas.canvasy(canvas.winfo_height())
                    
                    visible_indices = []
                    for i, theme in enumerate(available_themes):
                        # Get theme frame position
                        theme_frame = preview_frames[theme["filename"]].master
                        frame_y = canvas.canvasy(theme_frame.winfo_y())
                        frame_height = theme_frame.winfo_height()
                        frame_bottom = frame_y + frame_height
                        
                        # Check if frame is visible (with some padding)
                        if frame_bottom >= canvas_top - 50 and frame_y <= canvas_bottom + 50:
                            visible_indices.append(i)
                    
                    return visible_indices
                except Exception:
                    # Fallback: return first 8
                    return list(range(min(8, len(available_themes))))
            
            # Function to load previews for specific themes
            def load_preview_batch(theme_indices):
                """Load preview colors for a batch of themes."""
                for idx in theme_indices:
                    if idx >= len(available_themes):
                        continue
                    theme = available_themes[idx]
                    filename = theme["filename"]
                    
                    # Skip if already loaded or loading
                    if filename in loaded_previews or filename in loading_queue:
                        continue
                    
                    # Add to loading queue
                    loading_queue.append(filename)
                    
                    # Fetch in background thread
                    def fetch_and_update(fname=filename):
                        colors = self._get_theme_preview_colors(fname)
                        # Update UI in main thread (even if colors is empty)
                        self.root.after(0, lambda f=fname, c=colors: update_theme_preview(f, c))
                        if fname in loading_queue:
                            loading_queue.remove(fname)
                    
                    import threading
                    threading.Thread(target=fetch_and_update, daemon=True).start()
            
            # Function to check scroll and load more previews
            def on_scroll_or_resize(event=None):
                """Load previews for visible themes when scrolling."""
                try:
                    visible = get_visible_themes()
                    if visible:
                        # Load visible themes plus a buffer (next 4 below visible area)
                        max_visible = max(visible) if visible else 0
                        to_load = visible + [i for i in range(max_visible + 1, max_visible + 5) if i < len(available_themes)]
                        load_preview_batch(to_load)
                except Exception:
                    pass  # Silently fail if calculation errors occur
            
            # Enable mouse wheel scrolling with lazy loading
            def on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                # Trigger lazy loading after scroll
                self.root.after(50, on_scroll_or_resize)
            
            def bind_mousewheel(event):
                canvas.bind_all("<MouseWheel>", on_mousewheel)
            def unbind_mousewheel(event):
                canvas.unbind_all("<MouseWheel>")
            canvas.bind("<Enter>", bind_mousewheel)
            canvas.bind("<Leave>", unbind_mousewheel)
            
            # Bind scroll events to trigger lazy loading
            def on_scroll(event=None):
                self.root.after(50, on_scroll_or_resize)
            
            canvas.bind('<Button-1>', on_scroll)
            canvas.bind('<B1-Motion>', on_scroll)
            scrollbar.bind('<Button-1>', on_scroll)
            
            # Update configure handler to also trigger lazy loading
            original_configure_handler = on_canvas_configure
            def enhanced_configure(event):
                original_configure_handler(event)
                self.root.after(100, on_scroll_or_resize)
            canvas.bind('<Configure>', enhanced_configure)
            
            # Load initial batch (first 8 visible themes)
            dialog.update()  # Ensure layout is complete
            self.root.after(100, lambda: load_preview_batch(get_visible_themes()))
            
            # Fallback: Load ALL themes after a delay to ensure nothing is missed
            # This handles cases where visibility detection might miss some themes
            def load_all_remaining():
                """Load previews for any themes that haven't been loaded yet."""
                for i, theme in enumerate(available_themes):
                    filename = theme["filename"]
                    if filename not in loaded_previews and filename not in loading_queue:
                        load_preview_batch([i])
            
            # Load all remaining themes after 2 seconds (gives initial batch time to start)
            self.root.after(2000, load_all_remaining)
        
        # Build dialog immediately
        build_dialog_ui()
    
    def _resolve_theme_conflicts(self, parent_dialog, conflicts, all_selected):
        """Show dialog to resolve theme conflicts.
        
        Args:
            parent_dialog: Parent themes browser dialog
            conflicts: List of conflicting theme filenames
            all_selected: All selected themes to install
        """
        conflict_dialog = self._create_dialog_base("Theme Conflicts", 500, 300)
        
        main_frame = Frame(conflict_dialog, bg='#1E1E1E')
        main_frame.pack(fill=BOTH, expand=True, padx=15, pady=15)
        
        # Title
        title_label = Label(
            main_frame,
            text="Theme Conflicts Detected",
            font=("Segoe UI", 11, "bold"),
            bg='#1E1E1E',
            fg='#D4D4D4'
        )
        title_label.pack(pady=(0, 10))
        
        # Description
        desc_text = (
            "The following themes are already installed:\n\n" +
            "\n".join([f"• {parent_dialog.theme_data[fname]['theme'].get('name', fname)}" for fname in conflicts]) +
            "\n\nHow would you like to handle these conflicts?"
        )
        desc_label = Label(
            main_frame,
            text=desc_text,
            font=("Segoe UI", 9),
            bg='#1E1E1E',
            fg='#CCCCCC',
            justify=LEFT,
            wraplength=470
        )
        desc_label.pack(pady=(0, 20))
        
        # Store resolution choice
        conflict_dialog.resolution = None
        
        # Buttons
        buttons_frame = Frame(main_frame, bg='#1E1E1E')
        buttons_frame.pack(fill=X, pady=(10, 0))
        
        def choose_overwrite():
            conflict_dialog.resolution = "overwrite"
            conflict_dialog.destroy()
            self._install_themes(parent_dialog, all_selected, conflict_resolution="overwrite")
        
        def choose_rename():
            conflict_dialog.resolution = "rename"
            conflict_dialog.destroy()
            self._install_themes(parent_dialog, all_selected, conflict_resolution="rename")
        
        def choose_skip():
            conflict_dialog.resolution = "skip"
            conflict_dialog.destroy()
            # Remove conflicts from selection
            selected_without_conflicts = [fname for fname in all_selected if fname not in conflicts]
            if selected_without_conflicts:
                self._install_themes(parent_dialog, selected_without_conflicts)
            else:
                messagebox.showinfo("Installation Complete", "All selected themes were skipped due to conflicts.")
                parent_dialog.destroy()
        
        overwrite_btn = ttk.Button(
            buttons_frame,
            text="Overwrite",
            command=choose_overwrite
        )
        overwrite_btn.pack(side=LEFT, padx=(0, 10))
        
        rename_btn = ttk.Button(
            buttons_frame,
            text="Rename",
            command=choose_rename
        )
        rename_btn.pack(side=LEFT, padx=(0, 10))
        
        skip_btn = ttk.Button(
            buttons_frame,
            text="Skip",
            command=choose_skip
        )
        skip_btn.pack(side=LEFT, padx=(0, 10))
        
        cancel_btn = ttk.Button(
            buttons_frame,
            text="Cancel",
            command=conflict_dialog.destroy
        )
        cancel_btn.pack(side=RIGHT)
    
    def _install_themes(self, parent_dialog, selected_themes, conflict_resolution="overwrite"):
        """Download and install selected themes.
        
        Args:
            parent_dialog: Parent themes browser dialog
            selected_themes: List of theme filenames to install
            conflict_resolution: How to handle conflicts ("overwrite", "rename", or "skip")
        """
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Create progress dialog
        progress_dialog = self._create_dialog_base("Installing Themes", 400, 150)
        progress_frame = Frame(progress_dialog, bg=main_bg)
        progress_frame.pack(fill=BOTH, expand=True, padx=20, pady=20)
        
        status_label = Label(
            progress_frame,
            text="Downloading themes...",
            font=("Segoe UI", 9),
            bg=main_bg,
            fg=colors.fg
        )
        status_label.pack(pady=(0, 10))
        
        progress_var = StringVar(value="0 / 0")
        progress_label = Label(
            progress_frame,
            textvariable=progress_var,
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg
        )
        progress_label.pack()
        
        progress_dialog.update()
        
        # Get Color Schemes directory
        css_dir = self.script_dir / "Color Schemes"
        css_dir.mkdir(exist_ok=True)
        
        installed_count = 0
        skipped_count = 0
        error_count = 0
        error_details = []  # Track error details
        
        # Process each theme
        for i, filename in enumerate(selected_themes, 1):
            status_label.config(text=f"Downloading {filename}...")
            progress_var.set(f"{i} / {len(selected_themes)}")
            progress_dialog.update()
            
            # Check for conflict
            theme_data = parent_dialog.theme_data.get(filename, {})
            theme = theme_data.get("theme", {})
            theme_name = theme.get("name", filename.replace("Scheme_", "").replace(".css", ""))
            # Extract scheme name the same way as _load_color_schemes_from_css does
            scheme_name = filename.replace("Scheme_", "").replace(".css", "")
            # Remove suffixes like "-CE", "-EE"
            scheme_name = scheme_name.split("-")[0]
            # Clean up: "Pier_at_Dawn" -> "Pier at Dawn" then back to lowercase for comparison
            scheme_name = scheme_name.replace("_", " ").lower()
            
            existing_schemes = self._get_color_schemes()
            has_conflict = scheme_name in existing_schemes and scheme_name != "default"
            
            if has_conflict:
                if conflict_resolution == "skip":
                    skipped_count += 1
                    continue
                elif conflict_resolution == "rename":
                    # Find a unique filename
                    counter = 1
                    base_name = filename.replace("Scheme_", "").replace(".css", "")
                    new_filename = f"Scheme_{base_name}_{counter}.css"
                    new_scheme_name = f"{base_name} {counter}".lower().replace("_", " ")
                    
                    while new_scheme_name in existing_schemes or (css_dir / new_filename).exists():
                        counter += 1
                        new_filename = f"Scheme_{base_name}_{counter}.css"
                        new_scheme_name = f"{base_name} {counter}".lower().replace("_", " ")
                    
                    filename = new_filename
            
            # Download theme file
            content = self._download_theme_file(filename)
            if not content:
                error_count += 1
                error_details.append(f"{theme_name}: Download failed")
                if hasattr(self, 'log'):
                    self.log(f"ERROR: Failed to download theme {filename}")
                continue
            
            # Validate it's a valid CSS file with colors
            colors = self._parse_css_color_scheme(content)
            if not colors:
                error_count += 1
                error_details.append(f"{theme_name}: Invalid CSS (missing colors)")
                if hasattr(self, 'log'):
                    self.log(f"ERROR: Theme {filename} is invalid (missing or invalid color definitions)")
                continue
            
            # Save to file
            file_path = css_dir / filename
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                installed_count += 1
                if hasattr(self, 'log'):
                    self.log(f"Installed theme: {theme_name}")
            except Exception as e:
                error_count += 1
                error_details.append(f"{theme_name}: {str(e)}")
                if hasattr(self, 'log'):
                    self.log(f"ERROR: Failed to save theme {filename}: {str(e)}")
        
        progress_dialog.destroy()
        
        # Clear cached schemes to force reload
        self._TAG_COLOR_SCHEMES = None
        
        # Rebuild menu
        if hasattr(self, 'color_scheme_menu'):
            self._build_color_scheme_menu()
        
        # Show completion message
        message_parts = []
        if installed_count > 0:
            message_parts.append(f"✓ Installed: {installed_count}")
        if skipped_count > 0:
            message_parts.append(f"⊘ Skipped: {skipped_count}")
        if error_count > 0:
            message_parts.append(f"✗ Errors: {error_count}")
            if error_details:
                message_parts.append("")
                message_parts.append("Error details:")
                for detail in error_details[:5]:  # Show first 5 errors
                    message_parts.append(f"  • {detail}")
                if len(error_details) > 5:
                    message_parts.append(f"  ... and {len(error_details) - 5} more")
        
        message = "\n".join(message_parts) if message_parts else "No themes were installed."
        messagebox.showinfo("Installation Complete", message)
        
        parent_dialog.destroy()
        
        # Auto-refresh themes after installation
        self._refresh_color_schemes()
    
    def _show_about_dialog(self):
        """Show About dialog."""
        about_text = f"""Bandcamp Downloader GUI
Version {__version__}

A Python-based GUI application for downloading Bandcamp albums with full metadata and cover art support.

Features:
• Download albums, tracks, and artist discographies
• Automatic metadata embedding
• Cover art support
• Multiple audio format options
• Batch download support
• Customizable folder structures

Requirements:
• Python 3.11+
• yt-dlp
• ffmpeg.exe

GitHub: https://github.com/kameryn1811/Bandcamp-Downloader

This tool downloads the freely available 128 kbps MP3 streams from Bandcamp. For high-quality audio, please purchase albums directly from Bandcamp to support the artists."""
        
        messagebox.showinfo("About", about_text)
    
    def _show_customize_dialog(self, force_new=False):
        """Show modal dialog to customize folder structure using template system.
        
        Args:
            force_new: If True, open in "new structure" mode regardless of current selection.
        """
        dialog = self._create_dialog_base("Customize Folder Structure", 580, 350)
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Main container for all content
        main_container = Frame(dialog, bg=main_bg)
        main_container.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # Title
        title_label = Label(
            main_container,
            text="Customize Folder Structure",
            font=("Segoe UI", 10, "bold"),
            bg=main_bg,
            fg=colors.fg
        )
        title_label.pack(pady=(3, 2))
        
        # Instructions
        instructions = Label(
            main_container,
            text="Type a template using tags like Artist, Album, etc. Use / to separate folder levels",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg
        )
        instructions.pack(pady=(0, 5))
        
        # Template input section
        template_frame = Frame(main_container, bg=main_bg)
        template_frame.pack(fill=X, pady=(0, 5))
        
        # Label row (horizontal frame for label + warning)
        label_row = Frame(template_frame, bg=main_bg)
        label_row.pack(anchor=W, pady=(0, 3))
        
        # Label for template input
        template_label = Label(
            label_row,
            text="Folder structure:",
            font=("Segoe UI", 9),
            bg=main_bg,
            fg=colors.fg
        )
        template_label.pack(side=LEFT)
        
        # Template input field (Text widget for tag visualization)
        template_text = Text(
            template_frame,
            font=("Segoe UI", 9),
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            insertbackground=colors.fg,
            relief='flat',
            borderwidth=1,
            highlightthickness=2,
            highlightbackground=colors.border,
            highlightcolor=colors.accent,
            height=3,
            wrap=WORD,
            padx=5,
            pady=5
        )
        template_text.pack(fill=X, pady=(0, 8))
        dialog.template_text = template_text
        
        # Add character filtering for folder (blocks: : * ? " < > |, allows \ /)
        self._setup_folder_character_filter(dialog, template_text, template_frame)
        
        # Configure tag styling - use accent color (blue) for tags
        template_text.tag_configure("tag", background=colors.accent, foreground='#FFFFFF', 
                                   relief='flat', borderwidth=0, 
                                   font=("Segoe UI", 9))
        template_text.tag_configure("tag_bg", background=colors.accent, foreground='#FFFFFF')
        
        # Store tag positions for deletion handling
        dialog.tag_positions = {}  # {tag_id: (start, end)}
        
        # Content history for undo/redo functionality
        dialog.template_history = []  # List of content states
        dialog.template_history_index = -1  # Current position in history (-1 = most recent)
        dialog.template_save_timer = None  # Timer for debounced content state saving
        
        # Save initial state
        initial_content = template_text.get('1.0', END).rstrip('\n')
        dialog.template_history = [initial_content]
        dialog.template_history_index = 0
        
        # Tag buttons section
        tags_label = Label(
            template_frame,
            text="Quick insert:",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg
        )
        tags_label.pack(anchor=W, pady=(0, 3))
        
        # Container for tag buttons (will wrap using grid)
        tags_container = Frame(template_frame, bg=main_bg)
        tags_container.pack(fill=X, pady=(0, 5))
        
        # Create tag buttons with wrapping (folder tags + "/" for level separator)
        tag_order = ["Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number", "/"]
        dialog.tag_buttons = []
        max_cols = 4  # Number of buttons per row
        for idx, tag in enumerate(tag_order):
            row = idx // max_cols
            col = idx % max_cols
            # Special styling for "/" separator button
            if tag == "/":
                tag_btn = ttk.Button(
                    tags_container,
                    text=tag,
                    width=4,
                    command=lambda t=tag: self._insert_folder_tag_into_template(dialog, t)
                )
            else:
                tag_btn = ttk.Button(
                    tags_container,
                    text=tag,
                    width=len(tag) + 2,
                    command=lambda t=tag: self._insert_folder_tag_into_template(dialog, t)
                )
            tag_btn.grid(row=row, column=col, padx=2, pady=2, sticky=W)
            dialog.tag_buttons.append(tag_btn)
        
        # Live preview section
        preview_frame, preview_text = self._create_preview_frame(main_container, wraplength=550)
        dialog.preview_text = preview_text
        
        # Store dialog state
        dialog.editing_structure_index = None  # Track which structure is being edited (None = new structure)
        dialog.editing_default_structure = False  # Track if editing a default structure
        
        # Load current structure if it's a custom one (unless force_new is True)
        current_value = self.folder_structure_var.get()
        initial_template = None  # Initialize to None, not empty string
        
        # Check if it's a default structure
        found_default = False
        if current_value in self.FOLDER_STRUCTURES.values():
            # Find the key for this default
            for key, value in self.FOLDER_STRUCTURES.items():
                if value == current_value:
                    if key in self.FOLDER_STRUCTURE_TEMPLATES:
                        template_data = self.FOLDER_STRUCTURE_TEMPLATES[key]
                        initial_template = template_data.get("template", "")  # Can be "" for Root Directory
                        dialog.editing_default_structure = True
                        found_default = True
                        break
        
        # Check custom structures (old format - will be migrated)
        # Only check if we haven't found a default structure yet
        if not found_default and not force_new and hasattr(self, 'custom_structures') and self.custom_structures:
            if current_value not in self.FOLDER_STRUCTURES.values():
                # This is a custom structure, find it
                structure_choice = self._extract_structure_choice(current_value)
                if isinstance(structure_choice, list):
                    # Migrate old format to template
                    initial_template = self._migrate_structure_to_template(structure_choice)
                    # Find index for editing
                    for idx, structure in enumerate(self.custom_structures):
                        if structure is structure_choice or self._normalize_structure(structure) == self._normalize_structure(structure_choice):
                            dialog.editing_structure_index = idx
                            break
        
        # Check custom structure templates (new format)
        # Only check if we haven't found anything yet
        if not found_default and initial_template is None and not force_new and hasattr(self, 'custom_structure_templates') and self.custom_structure_templates:
            if current_value not in self.FOLDER_STRUCTURES.values():
                # This is a custom template structure, find it
                for idx, template_data in enumerate(self.custom_structure_templates):
                    formatted = self._format_custom_structure_template(template_data)
                    if formatted == current_value:
                        initial_template = template_data.get("template", "")
                        dialog.editing_structure_index = idx
                        break
        
        # Set initial template
        # initial_template can be None (not found), "" (Root Directory), or a string (other defaults/custom)
        if initial_template is not None:  # None means not found, "" or string means found
            template_text.insert('1.0', initial_template)
        else:
            # Default template (only if not editing a default and not found)
            if not getattr(dialog, 'editing_default_structure', False):
                template_text.insert('1.0', "Artist / Album")
        
        # Process initial template to detect and style tags
        self._process_folder_template_tags(dialog)
        
        # Debounce tag processing to avoid cursor issues
        dialog.tag_process_timer = None
        dialog.is_processing_tags = False
        
        def on_template_change(event=None):
            # Don't process if we're already processing
            if dialog.is_processing_tags:
                return
            
            # Save content state for undo/redo immediately (for granular character-by-character undo)
            self._save_folder_template_state(dialog, immediate=True)
            
            # Cancel previous timer
            if dialog.tag_process_timer:
                dialog.after_cancel(dialog.tag_process_timer)
            
            # Update preview immediately (doesn't need tag processing)
            self._update_folder_preview(dialog)
            self._check_folder_structure_changes(dialog)
            
            # Schedule tag processing after user stops typing (keep this debounced for performance)
            dialog.tag_process_timer = dialog.after(300, lambda: self._process_folder_template_tags(dialog))
        
        template_text.bind('<KeyRelease>', on_template_change)
        template_text.bind('<Button-1>', lambda e: dialog.after(200, lambda: self._process_folder_template_tags(dialog)))
        
        # Bind undo/redo keyboard shortcuts
        template_text.bind('<Control-z>', lambda e: self._handle_folder_template_undo(dialog, e))
        template_text.bind('<Control-Shift-Z>', lambda e: self._handle_folder_template_redo(dialog, e))
        template_text.bind('<Control-y>', lambda e: self._handle_folder_template_redo(dialog, e))
        
        # Create right-Click context menu for tag deletion
        tag_context_menu = Menu(template_text, tearoff=0, bg=colors.entry_bg, fg=colors.fg,
                                activebackground=colors.hover_bg, activeforeground=colors.select_fg)
        
        def show_tag_context_menu(event):
            """Show context menu when right-Clicking on a tag."""
            # Find which tag was Clicked (if any)
            Click_pos = template_text.index(f"@{event.x},{event.y}")
            Clicked_tag_id = None
            
            for tag_id, (start_pos, end_pos) in dialog.tag_positions.items():
                try:
                    if template_text.compare(Click_pos, ">=", start_pos) and template_text.compare(Click_pos, "<=", end_pos):
                        Clicked_tag_id = tag_id
                        break
                except:
                    pass
            
            # Clear existing menu items
            tag_context_menu.delete(0, END)
            
            if Clicked_tag_id:
                # Add delete option for the Clicked tag
                tag_context_menu.add_command(
                    label="Delete Tag",
                    command=lambda tid=Clicked_tag_id: self._remove_folder_tag_from_template(dialog, tid)
                )
                tag_context_menu.post(event.x_root, event.y_root)
        
        template_text.bind('<Button-3>', show_tag_context_menu)  # Right-Click
        
        # Handle backspace/delete to remove entire tags
        def handle_backspace(event):
            # Process tags first to ensure positions are current
            self._process_folder_template_tags(dialog)
            
            cursor_pos = template_text.index(INSERT)
            # Check if cursor is inside or at the start of a tag
            for tag_id, (start, end) in list(dialog.tag_positions.items()):
                try:
                    if template_text.compare(cursor_pos, ">=", start) and template_text.compare(cursor_pos, "<=", end):
                        # Cursor is inside the tag, delete the entire tag
                        self._remove_folder_tag_from_template(dialog, tag_id)
                        return "break"
                except:
                    pass
            return None
        
        def handle_delete(event):
            # Process tags first to ensure positions are current
            self._process_folder_template_tags(dialog)
            
            cursor_pos = template_text.index(INSERT)
            # Check if cursor is inside or at the start of a tag
            for tag_id, (start, end) in list(dialog.tag_positions.items()):
                try:
                    if template_text.compare(cursor_pos, ">=", start) and template_text.compare(cursor_pos, "<=", end):
                        # Cursor is inside the tag, delete the entire tag
                        self._remove_folder_tag_from_template(dialog, tag_id)
                        return "break"
                except:
                    pass
            return None
        
        template_text.bind('<BackSpace>', handle_backspace, add='+')
        template_text.bind('<Delete>', handle_delete, add='+')
        
        # Initial preview update
        self._update_folder_preview(dialog)
        
        # Buttons frame
        buttons_frame = Frame(main_container, bg=main_bg)
        buttons_frame.pack(pady=(3, 5))
        
        # Show different buttons when editing existing structure vs creating new
        if dialog.editing_structure_index is not None:
            # Editing existing structure - show multiple options
            # Update Existing button (primary action) - initially disabled
            update_btn = ttk.Button(
                buttons_frame,
                text="Overwrite Existing",
                command=lambda: self._save_custom_folder_structure_from_dialog(dialog, update_existing=True),
                state='disabled'
            )
            update_btn.pack(side=LEFT, padx=5)
            dialog.update_btn = update_btn
            
            # Save As New button - initially disabled
            save_as_new_btn = ttk.Button(
                buttons_frame,
                text="Save As New",
                command=lambda: self._save_custom_folder_structure_from_dialog(dialog, update_existing=False),
                state='disabled'
            )
            save_as_new_btn.pack(side=LEFT, padx=5)
            dialog.save_as_new_btn = save_as_new_btn
        else:
            # Creating new structure or editing default - show simple Save button
            # If editing default, disable until changes are made
            save_btn_state = 'disabled' if getattr(dialog, 'editing_default_structure', False) else 'normal'
            save_btn = ttk.Button(
                buttons_frame,
                text="Save Structure",
                command=lambda: self._save_custom_folder_structure_from_dialog(dialog, update_existing=False),
                state=save_btn_state
            )
            save_btn.pack(side=LEFT, padx=5)
            dialog.save_btn = save_btn  # Store reference for enabling/disabling
        
        # Cancel button (always shown)
        cancel_btn = ttk.Button(
            buttons_frame,
            text="Cancel",
            command=dialog.destroy
        )
        cancel_btn.pack(side=LEFT, padx=5)
        
        # Store initial template state for change detection (after dialog is fully set up)
        if dialog.editing_structure_index is not None or getattr(dialog, 'editing_default_structure', False):
            dialog.initial_template = template_text.get('1.0', END).strip()
        
        # Close on ESC
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        # Focus template text
        template_text.focus_set()
        
        # Monitor changes to enable/disable buttons
        dialog.after(100, lambda: self._check_folder_structure_changes(dialog))
    
    def _process_folder_template_tags(self, dialog):
        """Process folder template text to detect and style tags.
        Similar to _process_template_tags but uses FOLDER_TAG_NAMES.
        """
        if not hasattr(dialog, 'template_text'):
            return
        
        # Set flag to prevent re-entry
        if hasattr(dialog, 'is_processing_tags') and dialog.is_processing_tags:
            return
        
        dialog.is_processing_tags = True
        
        try:
            text_widget = dialog.template_text
            
            # Get current cursor position to restore later
            try:
                cursor_pos = text_widget.index(INSERT)
            except:
                cursor_pos = '1.0'
            
            # Get the current text content
            content = text_widget.get('1.0', END).rstrip('\n')
            
            # Clear all existing tag styling
            for tag_id in list(dialog.tag_positions.keys()):
                try:
                    text_widget.tag_delete(f"tag_{tag_id}")
                except:
                    pass
            dialog.tag_positions.clear()
            
            # Find all tags by matching known tag names (without curly brackets)
            # Also match "/" and "\" as separator tags
            # Match whole words only to avoid partial matches
            import re
            matches = []
            
            # Sort tag names by length (longest first) to match "Album Artist" before "Album"
            tag_names_sorted = sorted(self.FOLDER_TAG_NAMES, key=len, reverse=True)
            
            # Build regex pattern for whole word matching
            pattern_parts = []
            for tag_name in tag_names_sorted:
                escaped = re.escape(tag_name)
                if ' ' in tag_name:
                    pattern_parts.append(rf'\b{escaped}\b')
                else:
                    pattern_parts.append(rf'\b{escaped}\b')
            
            # Add separator characters as tags (escape them for regex)
            pattern_parts.append(r'/')  # Forward slash
            pattern_parts.append(r'\\')  # Backslash (escaped)
            
            # Combine patterns with alternation
            pattern = '|'.join(pattern_parts)
            
            # Find all matches
            all_matches = list(re.finditer(pattern, content, re.IGNORECASE))
            
            # Filter out overlapping matches (prefer longer matches)
            valid_matches = []
            used_ranges = []
            for match in sorted(all_matches, key=lambda m: (m.end() - m.start(), m.start()), reverse=True):
                start, end = match.span()
                overlaps = False
                for used_start, used_end in used_ranges:
                    if not (end <= used_start or start >= used_end):
                        overlaps = True
                        break
                if not overlaps:
                    valid_matches.append(match)
                    used_ranges.append((start, end))
            
            # Sort matches by position
            valid_matches.sort(key=lambda m: m.start())
            matches = valid_matches
            
            if not matches:
                # No tags found, just restore cursor
                try:
                    text_widget.mark_set(INSERT, cursor_pos)
                    text_widget.see(INSERT)
                except:
                    pass
                return
            
            # Process matches and style them
            for match in matches:
                start_idx = match.start()
                end_idx = match.end()
                tag_text = match.group(0)
                tag_name = tag_text
                
                # Convert character positions to line.column format
                start_pos = text_widget.index(f'1.0 + {start_idx} chars')
                end_pos = text_widget.index(f'1.0 + {end_idx} chars')
                
                # Store tag position
                tag_id = f"{start_idx}_{end_idx}"
                dialog.tag_positions[tag_id] = (start_pos, end_pos)
                
                # Style the tag text
                text_widget.tag_add(f"tag_{tag_id}", start_pos, end_pos)
                text_widget.tag_config(f"tag_{tag_id}", 
                                     background='#007ACC', 
                                     foreground='#FFFFFF',
                                     font=("Segoe UI", 9, "bold"),
                                     relief='flat',
                                     borderwidth=0)
            
            # Restore cursor position
            try:
                text_widget.mark_set(INSERT, cursor_pos)
                text_widget.see(INSERT)
            except:
                pass
        finally:
            # Clear processing flag
            dialog.is_processing_tags = False
    
    def _insert_folder_tag_into_template(self, dialog, tag):
        """Insert a tag into the folder template text at cursor position."""
        if not hasattr(dialog, 'template_text'):
            return
        
        text_widget = dialog.template_text
        cursor_pos = text_widget.index(INSERT)
        
        # Get text before and after cursor to check if we need a space
        text_before = text_widget.get('1.0', cursor_pos)
        text_after = text_widget.get(cursor_pos, END)
        
        # For "/" separator, add spaces around it
        if tag == "/":
            space_before = " " if text_before and not text_before[-1].isspace() else ""
            space_after = " " if text_after and len(text_after) > 1 and not text_after[0].isspace() else ""
            insert_text = space_before + tag + space_after
        else:
            # For regular tags, add space before if needed
            space_before = " " if text_before and not text_before[-1].isspace() and text_before[-1] != "/" else ""
            space_after = " " if text_after and len(text_after) > 1 and not text_after[0].isspace() and text_after[0] != "/" else ""
            insert_text = space_before + tag + space_after
        
        # Insert tag with proper spacing
        text_widget.insert(cursor_pos, insert_text)
        
        # Move cursor after inserted tag
        new_cursor_pos = text_widget.index(f"{cursor_pos} + {len(insert_text)} chars")
        text_widget.mark_set(INSERT, new_cursor_pos)
        text_widget.see(INSERT)
        
        # Save content state before inserting tag
        self._save_folder_template_state(dialog, immediate=True)
        
        # Process tags immediately to style the new one
        self._process_folder_template_tags(dialog)
        
        # Update preview
        self._update_folder_preview(dialog)
        
        # Check for changes to enable/disable save button
        self._check_folder_structure_changes(dialog)
    
    def _remove_folder_tag_from_template(self, dialog, tag_id):
        """Remove a tag from the folder template when backspace/delete is used or right-Click delete."""
        if tag_id not in dialog.tag_positions:
            return
        
        start_pos, end_pos = dialog.tag_positions[tag_id]
        text_widget = dialog.template_text
        
        # Delete the tag text
        try:
            text_widget.delete(start_pos, end_pos)
        except:
            return
        
        # Clean up references
        if tag_id in dialog.tag_positions:
            del dialog.tag_positions[tag_id]
        
        # Set cursor to where tag was
        try:
            text_widget.mark_set(INSERT, start_pos)
            text_widget.see(INSERT)
        except:
            pass
        
        # Reprocess tags to update styling
        self._process_folder_template_tags(dialog)
        self._update_folder_preview(dialog)
        self._check_folder_structure_changes(dialog)
        
        # Focus back to text widget
        text_widget.focus_set()
    
    def _save_folder_template_state(self, dialog, immediate=False, debounce_ms=50):
        """Save current folder template content state to history for undo/redo."""
        if not hasattr(dialog, 'template_text') or not hasattr(dialog, 'template_history'):
            return
        
        def save_state():
            try:
                # Get current content
                current_content = dialog.template_text.get('1.0', END).rstrip('\n')
                
                # Only save if content is different from current history position
                if (dialog.template_history_index < 0 or 
                    dialog.template_history_index >= len(dialog.template_history) or
                    dialog.template_history[dialog.template_history_index] != current_content):
                    
                    # Remove any future history (if we're not at the end)
                    if dialog.template_history_index < len(dialog.template_history) - 1:
                        dialog.template_history = dialog.template_history[:dialog.template_history_index + 1]
                    
                    # Add new state
                    dialog.template_history.append(current_content)
                    dialog.template_history_index = len(dialog.template_history) - 1
                    
                    # Limit history size (keep last 100 states)
                    if len(dialog.template_history) > 100:
                        dialog.template_history = dialog.template_history[-100:]
                        dialog.template_history_index = len(dialog.template_history) - 1
            except Exception:
                pass
        
        if immediate:
            # Cancel any pending timer and save immediately
            if dialog.template_save_timer:
                dialog.after_cancel(dialog.template_save_timer)
                dialog.template_save_timer = None
            save_state()
        else:
            # Debounce the save
            if dialog.template_save_timer:
                dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = dialog.after(debounce_ms, save_state)
    
    def _handle_folder_template_undo(self, dialog, event):
        """Handle undo (Ctrl+Z) in folder template Text widget."""
        if event.state & 0x1:  # Shift key is pressed
            return self._handle_folder_template_redo(dialog, event)
        
        if not hasattr(dialog, 'template_history') or not dialog.template_history or not hasattr(dialog, 'template_text'):
            return "break"
        
        # Cancel any pending timers
        if dialog.tag_process_timer:
            dialog.after_cancel(dialog.tag_process_timer)
            dialog.tag_process_timer = None
        if dialog.template_save_timer:
            dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = None
        
        # Save current content to history before undoing
        self._save_folder_template_state(dialog, immediate=True)
        
        # Move back in history
        if dialog.template_history_index > 0:
            dialog.template_history_index -= 1
            previous_content = dialog.template_history[dialog.template_history_index]
            
            # Replace current content with previous state
            dialog.template_text.delete(1.0, END)
            dialog.template_text.insert(1.0, previous_content)
            
            # Process tags and update preview
            self._process_folder_template_tags(dialog)
            self._update_folder_preview(dialog)
            self._check_folder_structure_changes(dialog)
        else:
            # At the beginning of history
            if dialog.template_history and dialog.template_history[0] != "":
                dialog.template_history.insert(0, "")
                dialog.template_history_index = 0
            elif not dialog.template_history:
                dialog.template_history = [""]
                dialog.template_history_index = 0
            
            # Clear the field
            dialog.template_text.delete(1.0, END)
            self._process_folder_template_tags(dialog)
            self._update_folder_preview(dialog)
            self._check_folder_structure_changes(dialog)
        
        return "break"
    
    def _handle_folder_template_redo(self, dialog, event):
        """Handle redo (Ctrl+Shift+Z or Ctrl+Y) in folder template Text widget."""
        if not hasattr(dialog, 'template_history') or not dialog.template_history or not hasattr(dialog, 'template_text'):
            return "break"
        
        # Cancel any pending timers
        if dialog.tag_process_timer:
            dialog.after_cancel(dialog.tag_process_timer)
            dialog.tag_process_timer = None
        if dialog.template_save_timer:
            dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = None
        
        # Save current content to history before redoing
        self._save_folder_template_state(dialog, immediate=True)
        
        # Move forward in history
        if dialog.template_history_index < len(dialog.template_history) - 1:
            dialog.template_history_index += 1
            next_content = dialog.template_history[dialog.template_history_index]
            
            # Replace current content with next state
            dialog.template_text.delete(1.0, END)
            dialog.template_text.insert(1.0, next_content)
            
            # Process tags and update preview
            self._process_folder_template_tags(dialog)
            self._update_folder_preview(dialog)
            self._check_folder_structure_changes(dialog)
        
        return "break"
    
    def _update_folder_preview(self, dialog):
        """Update preview text in folder dialog."""
        if not hasattr(dialog, 'preview_text') or not hasattr(dialog, 'template_text'):
            return
        
        template = dialog.template_text.get('1.0', END).strip()
        if not template:
            dialog.preview_text.config(text="")
            return
        
        # Generate preview using template (preview_mode=True shows field names)
        base_path = Path(self.path_var.get() if self.path_var.get() else "Downloads")
        path_parts = self._generate_path_from_template(template, preview_mode=True)
        if path_parts:
            path_parts = [str(base_path)] + path_parts + ["Track.mp3"]
            preview_path = "\\".join(path_parts)
        else:
            preview_path = str(base_path / "Track.mp3")
        
        dialog.preview_text.config(text=preview_path)
    
    def _check_folder_structure_changes(self, dialog):
        """Check if folder structure template has changed and enable/disable save buttons accordingly."""
        if not hasattr(dialog, 'template_text'):
            return
        
        current_template = dialog.template_text.get('1.0', END).strip()
        initial_template = getattr(dialog, 'initial_template', "")
        
        has_changes = current_template != initial_template
        
        # Enable/disable buttons based on changes
        if hasattr(dialog, 'update_btn') and hasattr(dialog, 'save_as_new_btn'):
            # Editing existing structure
            if has_changes:
                dialog.update_btn.config(state='normal')
                dialog.save_as_new_btn.config(state='normal')
            else:
                dialog.update_btn.config(state='disabled')
                dialog.save_as_new_btn.config(state='disabled')
        elif hasattr(dialog, 'save_btn'):
            # Creating new or editing default
            if has_changes or not getattr(dialog, 'editing_default_structure', False):
                dialog.save_btn.config(state='normal')
            else:
                dialog.save_btn.config(state='disabled')
    
    def _format_custom_structure_template(self, template_data):
        """Format a custom folder structure template for display."""
        if not isinstance(template_data, dict) or "template" not in template_data:
            return ""
        template = template_data.get("template", "").strip()
        if not template:
            return ""
        # For display, just return the template as-is (it's already readable)
        return template
    
    def _save_custom_folder_structure_from_dialog(self, dialog, update_existing=False):
        """Save the custom folder structure from the dialog (template-based)."""
        if not hasattr(dialog, 'template_text'):
            return
        
        template = dialog.template_text.get('1.0', END).strip()
        # Allow empty template for Root Directory (empty string is valid)
        # Only reject if template is None (shouldn't happen) or if it's not a default being edited
        if template is None:
            messagebox.showwarning("Invalid Structure", "Please enter a folder structure template.")
            return
        
        # Create template data structure
        template_data = {"template": template}
        
        # Format for display
        formatted = self._format_custom_structure_template(template_data)
        
        # Check for duplicates (compare against all existing structures)
        # First check default structures (but allow if editing a default - user can create a custom copy)
        is_editing_default = getattr(dialog, 'editing_default_structure', False)
        if not is_editing_default:
            for key, default_template_data in self.FOLDER_STRUCTURE_TEMPLATES.items():
                if default_template_data.get("template", "").strip() == template:
                    messagebox.showwarning("Duplicate Structure", f"This structure already exists as a default option.")
                    return
        
        # Check custom structure templates
        if hasattr(self, 'custom_structure_templates'):
            for existing_template_data in self.custom_structure_templates:
                if existing_template_data.get("template", "").strip() == template:
                    if not update_existing or dialog.editing_structure_index is None:
                        messagebox.showwarning("Duplicate Structure", f"This structure already exists.\n\nPlease create a different structure.")
                        return
        
        # Determine if we should update existing or save as new
        editing_index = getattr(dialog, 'editing_structure_index', None)
        
        if update_existing and editing_index is not None and hasattr(self, 'custom_structure_templates') and 0 <= editing_index < len(self.custom_structure_templates):
            # Update existing template structure
            self.custom_structure_templates[editing_index] = template_data
        else:
            # Create new template structure
            if not hasattr(self, 'custom_structure_templates'):
                self.custom_structure_templates = []
            self.custom_structure_templates.append(template_data)
        
        # Save settings
        self._save_custom_structure_templates()
        
        # Update dropdown
        self._update_structure_dropdown()
        
        # Select this structure in dropdown
        self.folder_structure_var.set(formatted)
        
        # Save the selection to persist it across sessions
        self._save_settings()
        
        # Update preview
        self.update_preview()
        
        # Close dialog (always close, even if there were errors above)
        try:
            dialog.destroy()
        except:
            pass
    
    def _save_custom_structure_templates(self):
        """Save custom folder structure templates to settings."""
        settings = self._load_settings()
        if hasattr(self, 'custom_structure_templates'):
            settings["custom_structure_templates"] = self.custom_structure_templates
        else:
            settings["custom_structure_templates"] = []
        self._save_settings(settings)
    
    def _create_level_slot(self, dialog, parent_frame, slot_index, initial_value=None):
        """Create a level slot - either filled with a level or empty with + Add Level button."""
        slot_frame = Frame(parent_frame, bg='#1E1E1E', relief='flat', bd=1, highlightbackground='#3E3E42', highlightthickness=1)
        slot_frame.pack(fill=X, pady=2, padx=5, anchor='nw')
        slot_frame.slot_index = slot_index
        slot_frame.is_filled = initial_value is not None
        
        dialog.level_slots.append(slot_frame)
        
        if initial_value:
            # Create filled level
            self._fill_level_slot(dialog, slot_frame, initial_value)
        else:
            # Create empty slot with + Add Level button (same height as filled slots)
            add_btn = ttk.Button(
                slot_frame,
                text="+ Add Level",
                command=lambda: self._add_level_to_slot(dialog, slot_frame)
            )
            add_btn.pack(side=LEFT, padx=5, pady=2)  # Match padding of filled slot widgets
            slot_frame.add_btn = add_btn
    
    def _fill_level_slot(self, dialog, slot_frame, initial_value):
        """Fill a slot with a multi-field level.
        initial_value can be:
        - Old format: string like "Artist"
        - New format: dict like {"fields": ["Artist"], "separator": None}
        """
        # Clear any existing content
        for widget in slot_frame.winfo_children():
            widget.destroy()
        
        slot_frame.is_filled = True
        
        # Add to custom_levels FIRST so it's included in filtering
        if slot_frame not in dialog.custom_levels:
            dialog.custom_levels.append(slot_frame)
        
        # Normalize initial_value to new format
        if isinstance(initial_value, str):
            # Old format: single field
            level_data = {"fields": [initial_value], "separators": []}
        elif isinstance(initial_value, dict) and "fields" in initial_value:
            # New format: ensure separators list exists
            level_data = initial_value.copy()
            if "separator" in level_data:
                # Convert old single separator to separators list
                sep = level_data.pop("separator")
                level_data["separators"] = [sep] if sep else []
            elif "separators" not in level_data:
                level_data["separators"] = []
        else:
            # Default: start with first available field
            available = self._get_all_available_fields(dialog, slot_frame)
            level_data = {"fields": [available[0]] if available else ["Artist"], "separators": []}
        
        # Store level data
        slot_frame.level_data = level_data
        
        # Container for fields and separators
        fields_container = Frame(slot_frame, bg='#1E1E1E')
        fields_container.pack(side=LEFT, fill=X, expand=True, padx=5)
        
        # Drag handle (⋮⋮)
        drag_handle = Label(
            slot_frame,
            text="⋮⋮",
            font=("Segoe UI", 10),
            bg='#1E1E1E',
            fg='#808080',
            cursor='fleur',
            width=3
        )
        drag_handle.pack(side=LEFT, padx=5)
        
        # Bind drag events
        drag_handle.bind("<Button-1>", lambda e: self._start_drag_level(dialog, slot_frame, e))
        drag_handle.bind("<B1-Motion>", lambda e: self._drag_level(dialog, slot_frame, e))
        drag_handle.bind("<ButtonRelease-1>", lambda e: self._end_drag_level(dialog, slot_frame, e))
        
        # Store references
        slot_frame.drag_handle = drag_handle
        slot_frame.fields_container = fields_container
        slot_frame.field_widgets = []  # List of (field_combo, separator_combo) tuples
        
        # Build UI for existing fields
        self._rebuild_level_fields_ui(dialog, slot_frame)
        
        # Remove button (X) - clears the slot
        remove_btn = ttk.Button(
            slot_frame,
            text="X",
            width=3,
            command=lambda: self._clear_level_slot(dialog, slot_frame)
        )
        remove_btn.pack(side=LEFT, padx=5)
        slot_frame.remove_btn = remove_btn
        
        # Update all dropdowns to filter duplicates
        self._update_all_level_options(dialog)
        # Update preview
        self._update_preview(dialog)
    
    def _get_all_available_fields(self, dialog, exclude_slot=None):
        """Get all available fields (strict duplicate prevention - no duplicates anywhere).
        Returns list of field names that are not used in any level.
        """
        # Get all used fields across all levels
        used_fields = set()
        for level_frame in dialog.custom_levels:
            if level_frame == exclude_slot:
                continue
            if hasattr(level_frame, 'level_data'):
                fields = level_frame.level_data.get("fields", [])
                used_fields.update(fields)
        
        # All possible fields
        all_fields = ["Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
        
        # Return available fields
        return [f for f in all_fields if f not in used_fields]
    
    def _get_available_fields_for_slot(self, dialog, slot_frame, exclude_field=None):
        """Get available fields for a specific slot (allows current field + unused fields)."""
        # Get all used fields across all levels (excluding this slot and exclude_field)
        used_fields = set()
        for level_frame in dialog.custom_levels:
            if level_frame == slot_frame:
                continue
            if hasattr(level_frame, 'level_data'):
                fields = level_frame.level_data.get("fields", [])
                used_fields.update(fields)
        
        # Also exclude exclude_field if specified
        if exclude_field:
            used_fields.add(exclude_field)
        
        # All possible fields
        all_fields = ["Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
        
        # Return available fields (including current field if it's not exclude_field)
        available = []
        for field in all_fields:
            if field not in used_fields or (exclude_field and field == exclude_field):
                available.append(field)
        
        return available
    
    def _create_separator_entry(self, parent, separator_var, dialog, slot_frame, separator_index, is_prefix=False):
        """Create a separator text entry widget with dark mode styling and validation."""
        separator_entry = Entry(
            parent,
            textvariable=separator_var,
            width=5,
            font=("Segoe UI", 8),
            bg='#2D2D30',  # Dark background
            fg='#D4D4D4',  # Light text
            insertbackground='#D4D4D4',  # Light cursor
            relief='flat',
            bd=1,
            highlightbackground='#3E3E42',
            highlightcolor='#007ACC',
            highlightthickness=1
        )
        separator_entry.pack(side=LEFT, padx=2)
        
        # Limit to 5 characters using validatecommand
        vcmd = (separator_entry.register(lambda P: len(P) <= 5), '%P')
        separator_entry.config(validate='key', validatecommand=vcmd)
        
        # Update preview in real-time using StringVar trace (fires on every change)
        def update_preview_realtime(*args, sep_idx=separator_index):
            # Update preview immediately as separator changes
            self._on_separator_change(dialog, slot_frame, sep_idx, separator_var)
        
        separator_var.trace_add('write', update_preview_realtime)
        
        # Validate on key release - check invalid characters
        def validate_separator(event, sep_idx=separator_index):
            self._validate_separator_input(dialog, slot_frame, sep_idx, separator_var, separator_entry)
        
        separator_entry.bind("<KeyRelease>", validate_separator)
        separator_entry.bind("<FocusOut>", lambda e, sep_idx=separator_index: self._on_separator_change(dialog, slot_frame, sep_idx, separator_var))
        
        return separator_entry
    
    def _rebuild_level_fields_ui(self, dialog, slot_frame):
        """Rebuild the UI for fields and separators in a level."""
        # Clear existing field widgets
        if hasattr(slot_frame, 'fields_container'):
            for widget in slot_frame.fields_container.winfo_children():
                widget.destroy()
        
        slot_frame.field_widgets = []
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        separators = level_data.get("separators", [])
        
        if not fields:
            # No fields, add one
            fields = [self._get_all_available_fields(dialog, slot_frame)[0] if self._get_all_available_fields(dialog, slot_frame) else "Artist"]
            level_data["fields"] = fields
        
        # Ensure separators list matches: prefix + between fields + suffix (fields + 1 total)
        # separators[0] = prefix (before first field)
        # separators[1..n-1] = between fields
        # separators[n] = suffix (after last field)
        num_separators = len(fields) + 1
        while len(separators) < num_separators:
            separators.append("")  # Default empty (no separator)
        separators = separators[:num_separators]  # Trim if too many
        level_data["separators"] = separators
        
        # Build UI: [Prefix Sep] [Field1 ▼] [Between Sep] [Field2 ▼] [Between Sep] [Field3 ▼] [Suffix Sep] [+ Add Field]
        for i, field in enumerate(fields):
            # Prefix separator (before first field)
            if i == 0:
                prefix_separator = separators[0] if separators else ""
                prefix_var = StringVar(value=prefix_separator if prefix_separator else "")
                prefix_entry = self._create_separator_entry(
                    slot_frame.fields_container, prefix_var, dialog, slot_frame, 0, is_prefix=True
                )
            else:
                prefix_entry = None
                prefix_var = None
            
            # Field dropdown
            field_var = StringVar(value=field)
            available_fields = self._get_available_fields_for_slot(dialog, slot_frame, field)
            field_combo = ttk.Combobox(
                slot_frame.fields_container,
                textvariable=field_var,
                values=available_fields,
                state="readonly",
                width=12
            )
            field_combo.pack(side=LEFT, padx=2)
            field_combo.bind("<<ComboboxSelected>>", lambda e, idx=i: self._on_field_change(dialog, slot_frame, idx))
            
            # Between-fields separator (after each field except last)
            separator_entry = None
            separator_var = None
            if i < len(fields) - 1:
                # Get separator for this gap (index i+1 in separators list)
                gap_separator = separators[i + 1] if i + 1 < len(separators) else "-"
                if gap_separator == "None" or gap_separator is None:
                    gap_separator = "-"
                separator_var = StringVar(value=gap_separator)
                separator_entry = self._create_separator_entry(
                    slot_frame.fields_container, separator_var, dialog, slot_frame, i + 1, is_prefix=False
                )
            
            # Suffix separator (after last field)
            suffix_entry = None
            suffix_var = None
            if i == len(fields) - 1:
                suffix_separator = separators[-1] if separators else ""
                suffix_var = StringVar(value=suffix_separator if suffix_separator else "")
                suffix_entry = self._create_separator_entry(
                    slot_frame.fields_container, suffix_var, dialog, slot_frame, len(separators) - 1, is_prefix=False
                )
            
            # Store widgets: (field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var)
            slot_frame.field_widgets.append((
                field_combo, prefix_entry, separator_entry, suffix_entry,
                field_var, prefix_var, separator_var, suffix_var
            ))
        
        # + Add Field button (max 3 fields)
        if len(fields) < 3:
            add_field_btn = ttk.Button(
                slot_frame.fields_container,
                text="+ Add Field",
                command=lambda: self._add_field_to_level(dialog, slot_frame)
            )
            add_field_btn.pack(side=LEFT, padx=2)
            slot_frame.add_field_btn = add_field_btn
        elif hasattr(slot_frame, 'add_field_btn'):
            slot_frame.add_field_btn.destroy()
            delattr(slot_frame, 'add_field_btn')
    
    def _on_field_change(self, dialog, slot_frame, field_index):
        """Handle field dropdown change."""
        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = slot_frame.field_widgets[field_index]
        new_field = field_var.get()
        
        # Update level data
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        if field_index < len(fields):
            fields[field_index] = new_field
            level_data["fields"] = fields
        
        # Rebuild UI to update all dropdowns
        self._rebuild_level_fields_ui(dialog, slot_frame)
        self._update_all_level_options(dialog)
        self._update_preview(dialog)
        
        # Check for changes and update button states
        self._check_structure_changes(dialog)
    
    def _on_separator_change(self, dialog, slot_frame, separator_index, separator_var=None):
        """Handle separator text entry change."""
        if separator_var is None:
            # Fallback: find separator_var from separator_index
            # separator_index 0 = prefix (first field), 1+ = between (field at index-1), last = suffix (last field)
            level_data = slot_frame.level_data
            fields = level_data.get("fields", [])
            if separator_index == 0 and slot_frame.field_widgets:
                # Prefix separator
                _, _, _, _, _, separator_var, _, _ = slot_frame.field_widgets[0]
            elif separator_index == len(fields) and slot_frame.field_widgets:
                # Suffix separator
                _, _, _, _, _, _, _, separator_var = slot_frame.field_widgets[-1]
            elif separator_index > 0 and separator_index < len(fields):
                # Between separator
                _, _, separator_var, _, _, _, _, _ = slot_frame.field_widgets[separator_index - 1]
            else:
                return
        
        new_separator = separator_var.get()  # Don't strip - preserve spaces
        
        # Update level data
        level_data = slot_frame.level_data
        separators = level_data.get("separators", [])
        
        # Ensure separators list is long enough (fields + 1: prefix + between + suffix)
        num_separators = len(level_data.get("fields", [])) + 1
        while len(separators) < num_separators:
            separators.append("")
        separators = separators[:num_separators]
        
        # Empty string means use space (None in our system), but preserve actual spaces
        if not new_separator:
            separators[separator_index] = None
        else:
            separators[separator_index] = new_separator  # Preserve spaces as-is
        
        level_data["separators"] = separators
        
        # Update appropriate preview based on dialog type
        # Filename dialog has editing_format_index, folder dialog has level_slots
        if hasattr(dialog, 'editing_format_index'):
            # Filename format dialog
            self._update_filename_preview(dialog)
        else:
            # Folder structure dialog
            self._update_preview(dialog)
        
        # Check for changes and update button states
        if hasattr(dialog, 'editing_format_index'):
            # Filename format dialog
            self._check_filename_changes(dialog)
        else:
            # Folder structure dialog
            self._check_structure_changes(dialog)
    
    def _validate_separator_input(self, dialog, slot_frame, separator_index, separator_var, separator_entry):
        """Validate separator input: max 5 chars, no invalid Windows filesystem characters."""
        current_text = separator_var.get()
        
        # Limit to 5 characters
        if len(current_text) > 5:
            separator_var.set(current_text[:5])
            current_text = current_text[:5]
        
        # Check for invalid Windows filesystem characters: < > : " / \ | ? *
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        found_invalid = [char for char in current_text if char in invalid_chars]
        
        if found_invalid:
            # Remove invalid characters
            cleaned_text = ''.join(char for char in current_text if char not in invalid_chars)
            separator_var.set(cleaned_text)
            
            # Show warning
            messagebox.showwarning(
                "Invalid Characters",
                f"The following characters are not allowed in separators: {', '.join(set(found_invalid))}\n\nThey have been removed."
            )
    
    def _add_field_to_level(self, dialog, slot_frame):
        """Add a new field to a level (max 3 fields)."""
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        
        if len(fields) >= 3:
            return  # Max 3 fields
        
        # Get first available field
        available = self._get_all_available_fields(dialog, slot_frame)
        if not available:
            return  # No available fields
        
        # Add new field
        fields.append(available[0])
        level_data["fields"] = fields
        
        # Add default separator for the new gap (between the new field and previous)
        # Structure: prefix + between + suffix, so insert before suffix
        separators = level_data.get("separators", [])
        # Insert new between separator before suffix (at index len(fields) - 1)
        insert_index = len(fields) - 1  # This is where the new between separator goes
        separators.insert(insert_index, "-")  # Default separator
        # Ensure we have the right number: fields + 1 (prefix + between + suffix)
        while len(separators) < len(fields) + 1:
            separators.append("")  # Add empty suffix if needed
        separators = separators[:len(fields) + 1]  # Trim to correct length
        level_data["separators"] = separators
        
        # Rebuild UI
        self._rebuild_level_fields_ui(dialog, slot_frame)
        self._update_all_level_options(dialog)
        self._update_preview(dialog)
        
        # Check for changes and update button states
        self._check_structure_changes(dialog)
    
    def _remove_field_from_level(self, dialog, slot_frame, field_index):
        """Remove a field from a level."""
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        
        if len(fields) <= 1:
            # Can't remove last field, clear entire level instead
            self._clear_level_slot(dialog, slot_frame)
            return
        
        # Remove field
        fields.pop(field_index)
        level_data["fields"] = fields
        
        # Rebuild UI
        self._rebuild_level_fields_ui(dialog, slot_frame)
        self._update_all_level_options(dialog)
        self._update_preview(dialog)
        
        # Check for changes and update button states
        self._check_structure_changes(dialog)
    
    def _update_preview(self, dialog):
        """Update the live preview of the folder structure."""
        if not hasattr(dialog, 'preview_text'):
            return
        
        # Build structure from all filled slots - read current values from UI widgets
        structure = []
        for slot_frame in dialog.level_slots:
            if slot_frame.is_filled and hasattr(slot_frame, 'level_data'):
                # Get current values from UI widgets (more reliable than stored data)
                level_data = slot_frame.level_data.copy()
                if hasattr(slot_frame, 'field_widgets'):
                    # Read current field values from UI
                    current_fields = []
                    current_separators = []
                    for i, widget_tuple in enumerate(slot_frame.field_widgets):
                        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = widget_tuple
                        current_fields.append(field_var.get())
                        
                        # Prefix separator (first field only)
                        if i == 0 and prefix_entry is not None:
                            prefix_value = prefix_var.get() if prefix_var else ""
                            current_separators.append(None if not prefix_value else prefix_value)
                        
                        # Between separator (after each field except last)
                        if separator_entry is not None:
                            sep_value = separator_var.get() if separator_var else ""  # Don't strip - preserve spaces
                            current_separators.append(None if not sep_value else sep_value)
                        
                        # Suffix separator (last field only)
                        if i == len(slot_frame.field_widgets) - 1 and suffix_entry is not None:
                            suffix_value = suffix_var.get() if suffix_var else ""
                            current_separators.append(None if not suffix_value else suffix_value)
                    
                    level_data["fields"] = current_fields
                    level_data["separators"] = current_separators
                structure.append(level_data)
        
        if not structure:
            dialog.preview_text.config(text="(No levels added)")
            return
        
        # Example metadata (simplified - no "Example" prefix)
        example_metadata = {
            "artist": "Artist",
            "album": "Album",
            "release_date": "2024",
            "genre": "Genre",
            "publisher": "Label",
            "album_artist": "Album Artist",
            "catalog_number": "CAT123",
            "title": "Song",
            "ext": "mp3"
        }
        
        # Build preview path
        base_path = Path(self.path_var.get() if self.path_var.get() else "Downloads")
        path_parts = [str(base_path)]
        
        field_values = {
            "Artist": example_metadata["artist"],
            "Album": example_metadata["album"],
            "Year": "Year",  # Show field name instead of example year
            "Genre": example_metadata["genre"] or "",
            "Label": example_metadata["publisher"] or "",
            "Album Artist": example_metadata["album_artist"] or "",
            "Catalog Number": example_metadata["catalog_number"] or ""
        }
        
        for level in structure:
            fields = level.get("fields", [])
            separators = level.get("separators", [])
            
            if not fields:
                continue
            
            # Build level string
            level_parts = []
            for field in fields:
                value = field_values.get(field, "")
                if value:
                    level_parts.append(value)
            
            if level_parts:
                # Build level string with prefix, between, and suffix separators
                # separators[0] = prefix, separators[1..n-1] = between, separators[n] = suffix
                result_parts = []
                
                # Add prefix separator (before first field)
                prefix_sep = separators[0] if separators and len(separators) > 0 else ""
                if prefix_sep and prefix_sep != "None":
                    result_parts.append(prefix_sep)
                
                # Add fields with between separators
                for i, field_value in enumerate(level_parts):
                    result_parts.append(field_value)
                    
                    # Add between separator (after each field except last)
                    if i < len(level_parts) - 1:
                        between_idx = i + 1  # separators[1] after first field, separators[2] after second, etc.
                        between_sep = separators[between_idx] if between_idx < len(separators) else "-"
                        if between_sep == "None" or not between_sep:
                            between_sep = " "  # Default to space if None
                        result_parts.append(between_sep)
                
                # Add suffix separator (after last field)
                suffix_idx = len(level_parts)  # separators[n] where n = number of fields
                suffix_sep = separators[suffix_idx] if suffix_idx < len(separators) else ""
                if suffix_sep and suffix_sep != "None":
                    result_parts.append(suffix_sep)
                
                path_parts.append("".join(result_parts))
        
        # Add filename
        path_parts.append(f"{example_metadata['title']}.{example_metadata['ext']}")
        
        # Format preview text - use backslashes like Windows paths (no spaces)
        preview_path = "\\".join(path_parts)
        dialog.preview_text.config(text=preview_path)
    
    def _add_level_to_slot(self, dialog, slot_frame):
        """Add a level to an empty slot."""
        # Get first available field (strict duplicate prevention)
        available = self._get_all_available_fields(dialog, slot_frame)
        default_field = available[0] if available else "Artist"
        
        # Create level with single field
        level_data = {"fields": [default_field], "separator": None}
        self._fill_level_slot(dialog, slot_frame, level_data)
        
        # Check for changes and update button states
        self._check_structure_changes(dialog)
    
    def _clear_level_slot(self, dialog, slot_frame):
        """Clear a filled slot, making it empty again."""
        if slot_frame in dialog.custom_levels:
            dialog.custom_levels.remove(slot_frame)
        
        # Clear all widgets
        for widget in slot_frame.winfo_children():
            widget.destroy()
        
        slot_frame.is_filled = False
        
        # Create + Add Level button (same height as filled slots)
        add_btn = ttk.Button(
            slot_frame,
            text="+ Add Level",
            command=lambda: self._add_level_to_slot(dialog, slot_frame)
        )
        add_btn.pack(side=LEFT, padx=5, pady=2)  # Match padding of filled slot widgets
        slot_frame.add_btn = add_btn
        
        # Update all dropdowns
        self._update_all_level_options(dialog)
        # Update preview
        self._update_preview(dialog)
        
        # Check for changes and update button states
        self._check_structure_changes(dialog)
    
    def _update_all_level_options(self, dialog):
        """Update all level field dropdowns to filter out selected options (strict duplicate prevention)."""
        # Rebuild UI for all levels to update dropdowns
        for level_frame in dialog.custom_levels:
            if hasattr(level_frame, 'level_data') and hasattr(level_frame, 'fields_container'):
                self._rebuild_level_fields_ui(dialog, level_frame)
    
    def _start_drag_level(self, dialog, slot_frame, event):
        """Start dragging a level."""
        dialog.dragging = slot_frame
        dialog.drag_start_y = event.y_root
        dialog.drag_start_index = dialog.level_slots.index(slot_frame)
        
        # Store original cursor and set drag cursor on dialog window
        dialog.original_cursor = dialog.cget('cursor')
        dialog.config(cursor='fleur')
        
        # Enhanced visual feedback - make dragged slot stand out
        slot_frame.config(
            highlightbackground='#00A8FF',  # Brighter blue
            highlightthickness=3,
            bg='#2D4A5C'  # Slightly lighter background
        )
    
    def _drag_level(self, dialog, slot_frame, event):
        """Handle dragging a level - show clear visual feedback of target position."""
        if not dialog.dragging or dialog.dragging != slot_frame:
            return
        
        # Find which slot we're over
        current_y = event.y_root
        target_slot = None
        target_index = None
        
        # Find target position based on mouse Y position
        for i, other_slot in enumerate(dialog.level_slots):
            if other_slot == slot_frame:
                continue
            slot_y = other_slot.winfo_rooty()
            slot_height = other_slot.winfo_height()
            slot_center = slot_y + slot_height // 2
            
            # Check if mouse is over this slot
            if slot_y <= current_y <= slot_y + slot_height:
                target_slot = other_slot
                # Determine if we're in the upper or lower half
                if current_y < slot_center:
                    target_index = i
                else:
                    target_index = i + 1
                break
        
        # If no target found, check if we're at the top or bottom
        if target_slot is None:
            if current_y < dialog.level_slots[0].winfo_rooty():
                target_index = 0
            else:
                target_index = len(dialog.level_slots) - 1
        
        # Store target for end_drag
        dialog.drag_target_index = target_index
        
        # Enhanced visual feedback - make dragged slot more prominent
        slot_frame.config(
            highlightbackground='#00A8FF',  # Brighter blue
            highlightthickness=3,
            bg='#2D4A5C'  # Slightly lighter background
        )
        
        # Highlight target position with a different color
        for i, other_slot in enumerate(dialog.level_slots):
            if other_slot == slot_frame:
                continue
            if i == target_index:
                # Target position - show where it will drop
                other_slot.config(
                    highlightbackground='#00FF88',  # Green for drop target
                    highlightthickness=3,
                    bg='#2D4A5C'
                )
            else:
                other_slot.config(
                    highlightbackground='#3E3E42',
                    highlightthickness=1,
                    bg='#1E1E1E'
                )
    
    def _end_drag_level(self, dialog, slot_frame, event):
        """End dragging and reorder levels by moving slot to target position."""
        if not dialog.dragging or dialog.dragging != slot_frame:
            return
        
        # Restore original cursor
        if hasattr(dialog, 'original_cursor'):
            dialog.config(cursor=dialog.original_cursor)
        
        # Get target index from drag
        target_index = getattr(dialog, 'drag_target_index', None)
        if target_index is None:
            # Fallback: find target based on final mouse position
            current_y = event.y_root
            target_index = len(dialog.level_slots) - 1
            for i, other_slot in enumerate(dialog.level_slots):
                if other_slot == slot_frame:
                    continue
                slot_y = other_slot.winfo_rooty()
                slot_height = other_slot.winfo_height()
                slot_center = slot_y + slot_height // 2
                if slot_y <= current_y <= slot_y + slot_height:
                    if current_y < slot_center:
                        target_index = i
                    else:
                        target_index = i + 1
                    break
        
        # Clamp target_index
        target_index = max(0, min(target_index, len(dialog.level_slots) - 1))
        
        # Get current index
        current_index = dialog.level_slots.index(slot_frame)
        
        # If position changed, reorder slots
        if target_index != current_index:
            # Remove from current position
            slot_frame.pack_forget()
            
            # Reorder the list
            dialog.level_slots.remove(slot_frame)
            dialog.level_slots.insert(target_index, slot_frame)
            
            # Repack all slots in new order
            for slot in dialog.level_slots:
                slot.pack_forget()
            for slot in dialog.level_slots:
                slot.pack(fill=X, pady=2, padx=5, anchor='nw')
            
            dialog.update_idletasks()
            # Update preview after reordering
            self._update_preview(dialog)
            
            # Check for changes and update button states
            self._check_structure_changes(dialog)
        
        # Reset highlights
        for slot in dialog.level_slots:
            slot.config(
                highlightbackground='#3E3E42',
                highlightthickness=1,
                bg='#1E1E1E'
            )
        
        dialog.dragging = None
        dialog.drag_start_index = None
        dialog.drag_original_y = None
        dialog.drag_target_index = None
    
    def _create_new_structure_in_dialog(self, dialog):
        """Close current dialog and open a fresh one for creating a new structure."""
        # Close the current dialog
        dialog.destroy()
        
        # Use after() to ensure the dialog is fully destroyed before opening a new one
        # Open a fresh customize dialog in "new structure" mode (force_new=True)
        self.root.after(100, lambda: self._show_customize_dialog(force_new=True))
    
    def _get_structure_from_dialog(self, dialog):
        """Get the current structure from the dialog without saving.
        
        Args:
            dialog: The customize dialog
            
        Returns:
            List of level data dictionaries (normalized structure)
        """
        structure = []
        
        for slot_frame in dialog.level_slots:
            if slot_frame.is_filled and hasattr(slot_frame, 'level_data'):
                level_data = slot_frame.level_data.copy()
                
                # Read current field values from UI widgets (not from level_data)
                # This ensures field changes are captured even if level_data wasn't updated
                fields = []
                if hasattr(slot_frame, 'field_widgets') and slot_frame.field_widgets:
                    for field_widget_tuple in slot_frame.field_widgets:
                        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = field_widget_tuple
                        if field_var is not None:
                            field_value = field_var.get()
                            if field_value:
                                fields.append(field_value)
                else:
                    # Fallback to level_data if widgets don't exist
                    fields = level_data.get("fields", [])
                
                if not fields:
                    continue
                
                # Update level_data with current field values
                level_data["fields"] = fields
                
                # Read current separator values from UI widgets
                # This ensures separator changes are captured even if _on_separator_change wasn't called
                if hasattr(slot_frame, 'field_widgets') and slot_frame.field_widgets:
                    separators = []
                    num_fields = len(fields)
                    
                    # Read separators from widgets: prefix + between + suffix
                    # separators[0] = prefix, separators[1..n-1] = between, separators[n] = suffix
                    for i, field_widget_tuple in enumerate(slot_frame.field_widgets):
                        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = field_widget_tuple
                        
                        # Prefix separator (first field only, index 0)
                        if i == 0 and prefix_var is not None:
                            prefix_sep = prefix_var.get()  # Don't strip - preserve spaces
                            separators.append(prefix_sep if prefix_sep else None)
                        
                        # Between-field separator (after each field except last)
                        # Field i's separator_var goes to separators[i+1]
                        if i < num_fields - 1 and separator_var is not None:
                            between_sep = separator_var.get()  # Don't strip - preserve spaces
                            separators.append(between_sep if between_sep else None)
                        
                        # Suffix separator (last field only, index num_fields)
                        if i == num_fields - 1 and suffix_var is not None:
                            suffix_sep = suffix_var.get()  # Don't strip - preserve spaces
                            separators.append(suffix_sep if suffix_sep else None)
                    
                    # Ensure separators list has correct length (fields + 1)
                    while len(separators) < num_fields + 1:
                        separators.append(None)
                    separators = separators[:num_fields + 1]
                    
                    # Update level_data with current separator values
                    level_data["separators"] = separators
                
                structure.append(level_data)
        
        # Normalize the structure for comparison
        return self._normalize_structure(structure)
    
    def _check_structure_changes(self, dialog):
        """Check if structure has changed and enable/disable save buttons accordingly."""
        if not hasattr(dialog, 'editing_structure_index') or dialog.editing_structure_index is None:
            return  # Not editing, no need to check
        
        if not hasattr(dialog, 'initial_structure'):
            return  # No initial structure stored
        
        if not hasattr(dialog, 'update_btn') or not hasattr(dialog, 'save_as_new_btn'):
            return  # Buttons not created yet
        
        # Get current structure
        current_structure = self._get_structure_from_dialog(dialog)
        initial_structure = dialog.initial_structure
        
        # Compare structures (normalized)
        has_changes = current_structure != initial_structure
        
        # Enable/disable buttons based on changes
        if has_changes:
            dialog.update_btn.config(state='normal')
            dialog.save_as_new_btn.config(state='normal')
        else:
            dialog.update_btn.config(state='disabled')
            dialog.save_as_new_btn.config(state='disabled')
    
    def _save_custom_structure_from_dialog(self, dialog, update_existing=None):
        """Save the custom structure from the dialog.
        
        Args:
            dialog: The customize dialog
            update_existing: If True, update the existing structure. If False, save as new.
                            If None, determine automatically based on editing_structure_index.
        """
        # Build structure list from filled slots (in order) - new format
        structure = []
        all_fields_used = set()
        
        for slot_frame in dialog.level_slots:
            if slot_frame.is_filled and hasattr(slot_frame, 'level_data'):
                level_data = slot_frame.level_data.copy()
                fields = level_data.get("fields", [])
                
                if not fields:
                    continue
        
                # Check for duplicates (strict: no duplicates anywhere)
                for field in fields:
                    if field in all_fields_used:
                        messagebox.showwarning(
                            "Duplicate Fields",
                            f"Each field can only be used once.\n\nDuplicate field found: {field}\n\nPlease remove duplicates before saving."
                        )
                        return
                    all_fields_used.add(field)
                
                # Read current separator values from UI widgets before saving
                # This ensures separator changes are captured even if _on_separator_change wasn't called
                if hasattr(slot_frame, 'field_widgets') and slot_frame.field_widgets:
                    separators = []
                    num_fields = len(fields)
                    
                    # Read separators from widgets: prefix + between + suffix
                    # separators[0] = prefix, separators[1..n-1] = between, separators[n] = suffix
                    for i, field_widget_tuple in enumerate(slot_frame.field_widgets):
                        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = field_widget_tuple
                        
                        # Prefix separator (first field only, index 0)
                        if i == 0 and prefix_var is not None:
                            prefix_sep = prefix_var.get()  # Don't strip - preserve spaces
                            separators.append(prefix_sep if prefix_sep else None)
                        
                        # Between-field separator (after each field except last)
                        # Field i's separator_var goes to separators[i+1]
                        if i < num_fields - 1 and separator_var is not None:
                            between_sep = separator_var.get()  # Don't strip - preserve spaces
                            separators.append(between_sep if between_sep else None)
                        
                        # Suffix separator (last field only, index num_fields)
                        if i == num_fields - 1 and suffix_var is not None:
                            suffix_sep = suffix_var.get()  # Don't strip - preserve spaces
                            separators.append(suffix_sep if suffix_sep else None)
                    
                    # Ensure separators list has correct length (fields + 1)
                    while len(separators) < num_fields + 1:
                        separators.append(None)
                    separators = separators[:num_fields + 1]
                    
                    # Update level_data with current separator values
                    level_data["separators"] = separators
                
                structure.append(level_data)
        
        # Validate structure
        if not structure:
            messagebox.showwarning("Invalid Structure", "Please add at least one level with at least one field.")
            return
        
        # Format for display
        formatted = self._format_custom_structure(structure)
        
        # Determine if we should update existing or save as new
        editing_index = getattr(dialog, 'editing_structure_index', None)
        
        # If update_existing is None, determine automatically based on editing_index
        if update_existing is None:
            update_existing = (editing_index is not None and 0 <= editing_index < len(self.custom_structures))
        
        if update_existing and editing_index is not None and 0 <= editing_index < len(self.custom_structures):
            # We're updating an existing structure - replace it
            self.custom_structures[editing_index] = structure
        else:
            # We're creating a new structure - check if it already exists to avoid duplicates
            structure_exists = False
            normalized_structure = self._normalize_structure(structure)
            for existing in self.custom_structures:
                normalized_existing = self._normalize_structure(existing)
                # Compare normalized structures
                if normalized_structure == normalized_existing:
                    structure_exists = True
                    break
            
            # Add to custom structures if new
            if not structure_exists:
                self.custom_structures.append(structure)
        
        # Save settings
        self._save_custom_structures()
        
        # Update dropdown
        self._update_structure_dropdown()
        
        # Select this structure in dropdown
        self.folder_structure_var.set(formatted)
        # Menu button text is automatically updated via textvariable binding
        
        # Save the selection to persist it across sessions
        self._save_settings()
        
        # Update preview
        self.update_preview()
        
        # Close dialog
        dialog.destroy()
    
    def _show_manage_dialog(self):
        """Show modal dialog to manage custom folder structures (templates and old format)."""
        has_templates = hasattr(self, 'custom_structure_templates') and self.custom_structure_templates
        has_old_structures = hasattr(self, 'custom_structures') and self.custom_structures
        
        if not has_templates and not has_old_structures:
            messagebox.showinfo("No Custom Structures", "No custom folder structures have been saved yet.\n\nCreate one using the Customize button (🎨).")
            return
        
        dialog = Toplevel(self.root)
        dialog.title(" Delete Custom Folder Structures")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"400x300+{x}+{y}")
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Configure dialog background
        dialog.configure(bg=main_bg)
        
        # Title
        title_label = Label(
            dialog,
            text="Delete Custom Folder Structures",
            font=("Segoe UI", 10, "bold"),
            bg=main_bg,
            fg=colors.fg
        )
        title_label.pack(pady=(10, 10))
        
        # Container for structure list
        list_frame = Frame(dialog, bg=main_bg)
        list_frame.pack(pady=10, padx=20, fill=BOTH, expand=True)
        
        # Create list of structures with delete buttons
        # Order matches dropdown menu: old format first, then templates (newest at end)
        # First show old format structures
        if has_old_structures:
            for structure in self.custom_structures:
                structure_frame = Frame(list_frame, bg=main_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
                structure_frame.pack(fill=X, pady=2, padx=5)
                
                # Structure label
                formatted = self._format_custom_structure(structure)
                structure_label = Label(
                    structure_frame,
                    text=formatted,
                    font=("Segoe UI", 9),
                    bg=main_bg,
                    fg=colors.fg,
                    anchor=W
                )
                structure_label.pack(side=LEFT, padx=10, fill=X, expand=True)
                
                # Delete button
                delete_btn = ttk.Button(
                    structure_frame,
                    text="X",
                    width=3,
                    command=lambda s=structure: self._delete_custom_structure(dialog, s)
                )
                delete_btn.pack(side=RIGHT, padx=5)
        
        # Then show template structures (new format) - newest at end
        if has_templates:
            for template_data in self.custom_structure_templates:
                structure_frame = Frame(list_frame, bg=main_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
                structure_frame.pack(fill=X, pady=2, padx=5)
                
                # Structure label
                formatted = self._format_custom_structure_template(template_data)
                structure_label = Label(
                    structure_frame,
                    text=formatted,
                    font=("Segoe UI", 9),
                    bg=main_bg,
                    fg=colors.fg,
                    anchor=W
                )
                structure_label.pack(side=LEFT, padx=10, fill=X, expand=True)
                
                # Delete button
                delete_btn = ttk.Button(
                    structure_frame,
                    text="X",
                    width=3,
                    command=lambda t=template_data: self._delete_custom_folder_structure_template(dialog, t)
                )
                delete_btn.pack(side=RIGHT, padx=5)
        
        # Close button
        close_btn = ttk.Button(
            dialog,
            text="Close",
            command=dialog.destroy
        )
        close_btn.pack(pady=10)
        
        # Close on ESC
        dialog.bind('<Escape>', lambda e: dialog.destroy())
    
    def _delete_custom_structure(self, dialog, structure):
        """Delete a custom structure."""
        if structure in self.custom_structures:
            # Check if this is the currently selected structure
            formatted = self._format_custom_structure(structure)
            current_value = self.folder_structure_var.get()
            
            # Remove from list
            self.custom_structures.remove(structure)
            
            # Save settings
            self._save_custom_structures()
            
            # Update dropdown
            self._update_structure_dropdown()
            
            # If deleted structure was selected, switch to default
            if current_value == formatted:
                default_display = self.FOLDER_STRUCTURES.get(self.DEFAULT_STRUCTURE, "Artist / Album")
                self.folder_structure_var.set(default_display)
                # Menu button text is automatically updated via textvariable binding
                self.update_preview()
            
            # Rebuild dialog if structures remain, otherwise close
            has_remaining = (hasattr(self, 'custom_structure_templates') and self.custom_structure_templates) or self.custom_structures
            if has_remaining:
                dialog.destroy()
                self._show_manage_dialog()  # Reopen with updated list
            else:
                dialog.destroy()
    
    def _delete_custom_folder_structure_template(self, dialog, template_data):
        """Delete a custom folder structure template."""
        if hasattr(self, 'custom_structure_templates') and template_data in self.custom_structure_templates:
            # Check if this is the currently selected structure
            formatted = self._format_custom_structure_template(template_data)
            current_value = self.folder_structure_var.get()
            
            # Remove from list
            self.custom_structure_templates.remove(template_data)
            
            # Save settings
            self._save_custom_structure_templates()
            
            # Update dropdown
            self._update_structure_dropdown()
            
            # If deleted structure was selected, switch to default
            if current_value == formatted:
                default_display = self.FOLDER_STRUCTURES.get(self.DEFAULT_STRUCTURE, "Artist / Album")
                self.folder_structure_var.set(default_display)
                # Menu button text is automatically updated via textvariable binding
                self.update_preview()
            
            # Rebuild dialog if structures remain, otherwise close
            has_remaining = (hasattr(self, 'custom_structure_templates') and self.custom_structure_templates) or (hasattr(self, 'custom_structures') and self.custom_structures)
            if has_remaining:
                dialog.destroy()
                self._show_manage_dialog()  # Reopen with updated list
            else:
                dialog.destroy()
    
    # ============================================================================
    # FILENAME FORMAT DIALOG METHODS
    # ============================================================================
    def _show_customize_filename_dialog(self, force_new=False):
        """Show modal dialog to customize filename format using template system.
        
        Args:
            force_new: If True, open in "new format" mode regardless of current selection.
        """
        dialog = self._create_dialog_base("Customize Filename Format", 580, 350)
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Main container for all content
        main_container = Frame(dialog, bg=main_bg)
        main_container.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # Title
        title_label = Label(
            main_container,
            text="Customize Filename Format",
            font=("Segoe UI", 10, "bold"),
            bg=main_bg,
            fg=colors.fg
        )
        title_label.pack(pady=(3, 2))
        
        # Instructions
        instructions = Label(
            main_container,
            text="Type a template using tags like 01, Track, Artist, etc. (tags are automatically detected)",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg
        )
        instructions.pack(pady=(0, 5))
        
        # Template input section
        template_frame = Frame(main_container, bg=main_bg)
        template_frame.pack(fill=X, pady=(0, 5))
        
        # Label row (horizontal frame for label + warning)
        label_row = Frame(template_frame, bg=main_bg)
        label_row.pack(anchor=W, pady=(0, 3))
        
        # Label for template input
        template_label = Label(
            label_row,
            text="Filename format:",
            font=("Segoe UI", 9),
            bg=main_bg,
            fg=colors.fg
        )
        template_label.pack(side=LEFT)
        
        # Template input field (Text widget for tag visualization)
        template_text = Text(
            template_frame,
            font=("Segoe UI", 9),
            bg=colors.entry_bg,
            fg=colors.entry_fg,
            insertbackground=colors.fg,
            relief='flat',
            borderwidth=1,
            highlightthickness=2,
            highlightbackground=colors.border,
            highlightcolor=colors.accent,
            height=3,
            wrap=WORD,
            padx=5,
            pady=5
        )
        template_text.pack(fill=X, pady=(0, 8))
        dialog.template_text = template_text
        
        # Add character filtering for filename (blocks: \ / : * ? " < > |)
        self._setup_filename_character_filter(dialog, template_text, template_frame)
        
        # Configure tag styling - use accent color (blue) for tags
        template_text.tag_configure("tag", background=colors.accent, foreground='#FFFFFF', 
                                   relief='flat', borderwidth=0, 
                                   font=("Segoe UI", 9))
        template_text.tag_configure("tag_bg", background=colors.accent, foreground='#FFFFFF')
        
        # Store tag positions for deletion handling
        dialog.tag_positions = {}  # {tag_id: (start, end)}
        
        # Content history for undo/redo functionality
        dialog.template_history = []  # List of content states
        dialog.template_history_index = -1  # Current position in history (-1 = most recent)
        dialog.template_save_timer = None  # Timer for debounced content state saving
        
        # Save initial state
        initial_content = template_text.get('1.0', END).rstrip('\n')
        dialog.template_history = [initial_content]
        dialog.template_history_index = 0
        
        # Tag buttons section
        tags_label = Label(
            template_frame,
            text="Quick insert:",
            font=("Segoe UI", 8),
            bg=main_bg,
            fg=colors.disabled_fg
        )
        tags_label.pack(anchor=W, pady=(0, 3))
        
        # Container for tag buttons (will wrap using grid)
        tags_container = Frame(template_frame, bg=main_bg)
        tags_container.pack(fill=X, pady=(0, 5))
        
        # Create tag buttons with wrapping (no curly brackets)
        tag_order = ["01", "1", "Track", "Artist", "Album", "Year", "Genre", "Label", "Album Artist", "Catalog Number"]
        dialog.tag_buttons = []
        max_cols = 5  # Number of buttons per row
        for idx, tag in enumerate(tag_order):
            row = idx // max_cols
            col = idx % max_cols
            tag_btn = ttk.Button(
                tags_container,
                text=tag,
                width=len(tag) + 2,
                command=lambda t=tag: self._insert_tag_into_template(dialog, t)
            )
            tag_btn.grid(row=row, column=col, padx=2, pady=2, sticky=W)
            dialog.tag_buttons.append(tag_btn)
        
        # Live preview section
        preview_frame, preview_text = self._create_preview_frame(main_container, wraplength=550)
        dialog.preview_text = preview_text
        
        # Store dialog state
        dialog.editing_format_index = None  # Track which format is being edited (None = new format)
        dialog.editing_default_format = False  # Track if editing a default format
        
        # Load current format if it's a custom one (unless force_new is True)
        current_value = self.numbering_var.get()
        initial_template = ""
        if not force_new and hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
            # Check if current selection is a custom format (not a standard format)
            if current_value not in ["Track", "01. Track", "Artist - Track", "01. Artist - Track"]:
                # This is a custom format, find it
                for idx, format_data in enumerate(self.custom_filename_formats):
                    formatted = self._format_custom_filename(format_data)
                    if formatted == current_value:
                        normalized = self._normalize_filename_format(format_data)
                        if normalized:
                            initial_template = normalized.get("template", "")
                            dialog.editing_format_index = idx
                            break
        
        # If no custom format found, check if it's a default format
        if not initial_template and current_value in self.FILENAME_FORMATS:
            format_data = self.FILENAME_FORMATS[current_value]
            if format_data:
                initial_template = format_data.get("template", "")
                dialog.editing_default_format = True  # Mark that we're editing a default format
        
        # Set initial template
        if initial_template:
            # Remove curly brackets if present (for backward compatibility)
            import re
            initial_template = re.sub(r'\{([^}]+)\}', r'\1', initial_template)
            template_text.insert('1.0', initial_template)
        else:
            # Default template (no curly brackets)
            template_text.insert('1.0', "01. Track")
        
        # Process initial template to detect and style tags
        self._process_template_tags(dialog)
        
        # Debounce tag processing to avoid cursor issues
        dialog.tag_process_timer = None
        dialog.is_processing_tags = False
        
        def on_template_change(event=None):
            # Don't process if we're already processing
            if dialog.is_processing_tags:
                return
            
            # Save content state for undo/redo immediately (for granular character-by-character undo)
            # Save immediately to capture each character change precisely
            self._save_template_state(dialog, immediate=True)
            
            # Cancel previous timer
            if dialog.tag_process_timer:
                dialog.after_cancel(dialog.tag_process_timer)
            
            # Update preview immediately (doesn't need tag processing)
            self._update_filename_preview(dialog)
            self._check_filename_changes(dialog)
            
            # Schedule tag processing after user stops typing (keep this debounced for performance)
            dialog.tag_process_timer = dialog.after(300, lambda: self._process_template_tags(dialog))
        
        template_text.bind('<KeyRelease>', on_template_change)
        template_text.bind('<Button-1>', lambda e: dialog.after(200, lambda: self._process_template_tags(dialog)))
        
        # Bind undo/redo keyboard shortcuts
        template_text.bind('<Control-z>', lambda e: self._handle_template_undo(dialog, e))
        template_text.bind('<Control-Shift-Z>', lambda e: self._handle_template_redo(dialog, e))
        template_text.bind('<Control-y>', lambda e: self._handle_template_redo(dialog, e))
        
        # Create right-Click context menu for tag deletion
        tag_context_menu = Menu(template_text, tearoff=0, bg=colors.entry_bg, fg=colors.fg,
                                activebackground=colors.hover_bg, activeforeground=colors.select_fg)
        
        def show_tag_context_menu(event):
            """Show context menu when right-Clicking on a tag."""
            # Find which tag was Clicked (if any)
            Click_pos = template_text.index(f"@{event.x},{event.y}")
            Clicked_tag_id = None
            
            for tag_id, (start_pos, end_pos) in dialog.tag_positions.items():
                try:
                    if template_text.compare(Click_pos, ">=", start_pos) and template_text.compare(Click_pos, "<=", end_pos):
                        Clicked_tag_id = tag_id
                        break
                except:
                    pass
            
            # Clear existing menu items
            tag_context_menu.delete(0, END)
            
            if Clicked_tag_id:
                # Add delete option for the Clicked tag
                tag_context_menu.add_command(
                    label="Delete Tag",
                    command=lambda tid=Clicked_tag_id: self._remove_tag_from_template(dialog, tid)
                )
                tag_context_menu.post(event.x_root, event.y_root)
        
        template_text.bind('<Button-3>', show_tag_context_menu)  # Right-Click
        
        # Handle backspace/delete to remove entire tags
        def handle_backspace(event):
            # Process tags first to ensure positions are current
            self._process_template_tags(dialog)
            
            cursor_pos = template_text.index(INSERT)
            # Check if cursor is inside or at the start of a tag
            for tag_id, (start, end) in list(dialog.tag_positions.items()):
                # Compare positions: check if cursor is between start and end
                try:
                    if template_text.compare(cursor_pos, ">=", start) and template_text.compare(cursor_pos, "<=", end):
                        # Cursor is inside the tag, delete the entire tag
                        self._remove_tag_from_template(dialog, tag_id)
                        return "break"
                except:
                    pass
            return None
        
        def handle_delete(event):
            # Process tags first to ensure positions are current
            self._process_template_tags(dialog)
            
            cursor_pos = template_text.index(INSERT)
            # Check if cursor is inside or at the start of a tag
            for tag_id, (start, end) in list(dialog.tag_positions.items()):
                # Compare positions: check if cursor is between start and end
                try:
                    if template_text.compare(cursor_pos, ">=", start) and template_text.compare(cursor_pos, "<=", end):
                        # Cursor is inside the tag, delete the entire tag
                        self._remove_tag_from_template(dialog, tag_id)
                        return "break"
                except:
                    pass
            return None
        
        template_text.bind('<BackSpace>', handle_backspace, add='+')
        template_text.bind('<Delete>', handle_delete, add='+')
        
        # Initial preview update
        self._update_filename_preview(dialog)
        
        # Buttons frame
        buttons_frame = Frame(main_container, bg=main_bg)
        buttons_frame.pack(pady=(3, 5))
        
        # Show different buttons when editing existing format vs creating new
        if dialog.editing_format_index is not None:
            # Editing existing format - show multiple options
            # Update Existing button (primary action) - initially disabled
            update_btn = ttk.Button(
                buttons_frame,
                text="Overwrite Existing",
                command=lambda: self._save_custom_filename_from_dialog(dialog, update_existing=True),
                state='disabled'
            )
            update_btn.pack(side=LEFT, padx=5)
            dialog.update_btn = update_btn
            
            # Save As New button - initially disabled
            save_as_new_btn = ttk.Button(
                buttons_frame,
                text="Save As New",
                command=lambda: self._save_custom_filename_from_dialog(dialog, update_existing=False),
                state='disabled'
            )
            save_as_new_btn.pack(side=LEFT, padx=5)
            dialog.save_as_new_btn = save_as_new_btn
        else:
            # Creating new format or editing default - show simple Save button
            # If editing default, disable until changes are made
            save_btn_state = 'disabled' if getattr(dialog, 'editing_default_format', False) else 'normal'
            save_btn = ttk.Button(
                buttons_frame,
                text="Save Format",
                command=lambda: self._save_custom_filename_from_dialog(dialog, update_existing=False),
                state=save_btn_state
            )
            save_btn.pack(side=LEFT, padx=5)
            dialog.save_btn = save_btn  # Store reference for enabling/disabling
        
        # Cancel button (always shown)
        cancel_btn = ttk.Button(
            buttons_frame,
            text="Cancel",
            command=dialog.destroy
        )
        cancel_btn.pack(side=LEFT, padx=5)
        
        # Store initial format state for change detection (after dialog is fully set up)
        # Store for both custom formats and default formats
        if dialog.editing_format_index is not None or getattr(dialog, 'editing_default_format', False):
            dialog.initial_template = template_text.get('1.0', END).strip()
        
        # Close on ESC
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        # Focus template text
        template_text.focus_set()
        
        # Monitor changes to enable/disable buttons
        dialog.after(100, lambda: self._check_filename_changes(dialog))
    
    def _process_template_tags(self, dialog):
        """Process template text to detect and style tags.
        Simplified approach: Just style the tag text, no embedded widgets.
        """
        if not hasattr(dialog, 'template_text'):
            return
        
        # Set flag to prevent re-entry
        if hasattr(dialog, 'is_processing_tags') and dialog.is_processing_tags:
            return
        
        dialog.is_processing_tags = True
        
        try:
            text_widget = dialog.template_text
            
            # Get current cursor position to restore later
            try:
                cursor_pos = text_widget.index(INSERT)
            except:
                cursor_pos = '1.0'
            
            # Get the current text content
            content = text_widget.get('1.0', END).rstrip('\n')
            
            # Clear all existing tag styling
            for tag_id in list(dialog.tag_positions.keys()):
                try:
                    text_widget.tag_delete(f"tag_{tag_id}")
                except:
                    pass
            dialog.tag_positions.clear()
            
            # Find all tags by matching known tag names (without curly brackets)
            # Match whole words only to avoid partial matches
            import re
            matches = []
            
            # Sort tag names by length (longest first) to match "Album Artist" before "Album"
            tag_names_sorted = sorted(self.FILENAME_TAG_NAMES, key=len, reverse=True)
            
            # Build regex pattern for whole word matching
            # Escape special regex characters and match word boundaries
            pattern_parts = []
            for tag_name in tag_names_sorted:
                # Escape special regex characters
                escaped = re.escape(tag_name)
                # For multi-word tags like "Album Artist", match as a phrase
                if ' ' in tag_name:
                    # Match the phrase with word boundaries on both sides
                    pattern_parts.append(rf'\b{escaped}\b')
                else:
                    # Single word tags - match with word boundaries
                    pattern_parts.append(rf'\b{escaped}\b')
            
            # Combine patterns with alternation
            pattern = '|'.join(pattern_parts)
            
            # Find all matches
            all_matches = list(re.finditer(pattern, content, re.IGNORECASE))
            
            # Filter out overlapping matches (prefer longer matches)
            valid_matches = []
            used_ranges = []
            for match in sorted(all_matches, key=lambda m: (m.end() - m.start(), m.start()), reverse=True):
                start, end = match.span()
                # Check if this range overlaps with any already used
                overlaps = False
                for used_start, used_end in used_ranges:
                    if not (end <= used_start or start >= used_end):
                        overlaps = True
                        break
                if not overlaps:
                    valid_matches.append(match)
                    used_ranges.append((start, end))
            
            # Sort matches by position
            valid_matches.sort(key=lambda m: m.start())
            matches = valid_matches
            
            if not matches:
                # No tags found, just restore cursor
                try:
                    text_widget.mark_set(INSERT, cursor_pos)
                    text_widget.see(INSERT)
                except:
                    pass
                return
            
            # Process matches and style them
            for match in matches:
                start_idx = match.start()
                end_idx = match.end()
                tag_text = match.group(0)  # The matched tag name
                tag_name = tag_text  # Same as tag_text now (no braces)
                
                # Convert character positions to line.column format
                start_pos = text_widget.index(f'1.0 + {start_idx} chars')
                end_pos = text_widget.index(f'1.0 + {end_idx} chars')
                
                # Check if we need to add padding spaces around the tag
                # Get characters before and after the tag
                char_before = content[start_idx - 1] if start_idx > 0 else ''
                char_after = content[end_idx] if end_idx < len(content) else ''
                
                # Add padding spaces if needed (only for visual display, we'll handle in getter)
                padding_before = ' ' if start_idx > 0 and not char_before.isspace() and char_before not in ['(', '[', '{'] else ''
                padding_after = ' ' if end_idx < len(content) and not char_after.isspace() and char_after not in [')', ']', '}', '.', ',', ';', ':'] else ''
                
                # Store tag position (with padding consideration)
                tag_id = f"{start_idx}_{end_idx}"
                dialog.tag_positions[tag_id] = (start_pos, end_pos)
                
                # Style the tag text with rounded appearance
                # Note: We can't add true padding, but we can style the text itself
                text_widget.tag_add(f"tag_{tag_id}", start_pos, end_pos)
                text_widget.tag_config(f"tag_{tag_id}", 
                                     background='#007ACC', 
                                     foreground='#FFFFFF',
                                     font=("Segoe UI", 9, "bold"),
                                     relief='flat',
                                     borderwidth=0)
            
            # Restore cursor position
            try:
                text_widget.mark_set(INSERT, cursor_pos)
                text_widget.see(INSERT)
            except:
                pass
        finally:
            # Clear processing flag
            dialog.is_processing_tags = False
    
    def _remove_tag_from_template(self, dialog, tag_id):
        """Remove a tag from the template when backspace/delete is used or right-Click delete."""
        if tag_id not in dialog.tag_positions:
            return
        
        start_pos, end_pos = dialog.tag_positions[tag_id]
        text_widget = dialog.template_text
        
        # Delete the tag text
        try:
            text_widget.delete(start_pos, end_pos)
        except:
            return
        
        # Clean up references
        if tag_id in dialog.tag_positions:
            del dialog.tag_positions[tag_id]
        
        # Set cursor to where tag was
        try:
            text_widget.mark_set(INSERT, start_pos)
            text_widget.see(INSERT)
        except:
            pass
        
        # Reprocess tags to update styling
        self._process_template_tags(dialog)
        self._update_filename_preview(dialog)
        self._check_filename_changes(dialog)
        
        # Focus back to text widget
        text_widget.focus_set()
    
    def _insert_tag_into_template(self, dialog, tag):
        """Insert a tag into the template text at cursor position."""
        if not hasattr(dialog, 'template_text'):
            return
        
        text_widget = dialog.template_text
        cursor_pos = text_widget.index(INSERT)
        
        # Get text before and after cursor to check if we need a space
        text_before = text_widget.get('1.0', cursor_pos)
        text_after = text_widget.get(cursor_pos, END)
        
        # Add space before tag if cursor is not at start and previous char is not space
        space_before = ""
        if text_before and not text_before[-1].isspace():
            space_before = " "
        
        # Add space after tag if next char is not space
        space_after = " "
        if text_after and len(text_after) > 1:
            next_char = text_after[0]
            if next_char.isspace():
                space_after = ""
        
        # Insert tag with proper spacing
        text_widget.insert(cursor_pos, space_before + tag + space_after)
        
        # Move cursor after inserted tag
        new_cursor_pos = text_widget.index(f"{cursor_pos} + {len(space_before + tag + space_after)} chars")
        text_widget.mark_set(INSERT, new_cursor_pos)
        text_widget.see(INSERT)
        
        # Store the full template text for later retrieval
        if not hasattr(dialog, 'last_template_text'):
            dialog.last_template_text = ""
        dialog.last_template_text = text_widget.get('1.0', END).rstrip('\n')
        
        # Save content state before inserting tag
        self._save_template_state(dialog, immediate=True)
        
        # Process tags immediately to style the new one (don't wait for debounce)
        self._process_template_tags(dialog)
        
        # Update preview
        self._update_filename_preview(dialog)
        
        # Check for changes to enable/disable save button
        self._check_filename_changes(dialog)
    
    def _save_template_state(self, dialog, immediate=False, debounce_ms=300):
        """Save current template content state to history for undo/redo.
        
        Args:
            dialog: The customize dialog
            immediate: If True, save immediately. If False, debounce the save.
            debounce_ms: Debounce delay in milliseconds (default 300ms, use 50ms for granular undo)
        """
        if not hasattr(dialog, 'template_text') or not hasattr(dialog, 'template_history'):
            return
        
        def save_state():
            try:
                # Get current content
                current_content = dialog.template_text.get('1.0', END).rstrip('\n')
                
                # Only save if content is different from current history position
                if (dialog.template_history_index < 0 or 
                    dialog.template_history_index >= len(dialog.template_history) or
                    dialog.template_history[dialog.template_history_index] != current_content):
                    # Remove any future history if we're not at the end
                    if dialog.template_history_index < len(dialog.template_history) - 1:
                        dialog.template_history = dialog.template_history[:dialog.template_history_index + 1]
                    # Add new content state to history
                    dialog.template_history.append(current_content)
                    dialog.template_history_index = len(dialog.template_history) - 1
                    # Limit history size to 50 items
                    if len(dialog.template_history) > 50:
                        dialog.template_history = dialog.template_history[-50:]
                        dialog.template_history_index = len(dialog.template_history) - 1
            except Exception:
                pass
        
        if immediate:
            # Cancel any pending timer and save immediately
            if dialog.template_save_timer:
                dialog.after_cancel(dialog.template_save_timer)
                dialog.template_save_timer = None
            save_state()
        else:
            # Debounce the save (use provided debounce_ms, default 300ms)
            if dialog.template_save_timer:
                dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = dialog.after(debounce_ms, save_state)
    
    def _handle_template_undo(self, dialog, event):
        """Handle undo (Ctrl+Z) in template Text widget - cycle to previous content state."""
        # Check if Shift is pressed (Ctrl+Shift+Z = redo)
        if event.state & 0x1:  # Shift key is pressed
            return self._handle_template_redo(dialog, event)
        
        if not hasattr(dialog, 'template_history') or not dialog.template_history or not hasattr(dialog, 'template_text'):
            return "break"  # No history, prevent default behavior
        
        # Cancel any pending timers
        if dialog.tag_process_timer:
            dialog.after_cancel(dialog.tag_process_timer)
            dialog.tag_process_timer = None
        if dialog.template_save_timer:
            dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = None
        
        # Save current content to history before undoing (so we can redo back to it)
        self._save_template_state(dialog, immediate=True)
        
        # Move back in history
        if dialog.template_history_index > 0:
            dialog.template_history_index -= 1
            previous_content = dialog.template_history[dialog.template_history_index]
            
            # Replace current content with previous state
            dialog.template_text.delete(1.0, END)
            dialog.template_text.insert(1.0, previous_content)
            
            # Process tags and update preview
            self._process_template_tags(dialog)
            self._update_filename_preview(dialog)
            self._check_filename_changes(dialog)
        else:
            # At the beginning of history - insert empty state at position 0 so we can redo
            if dialog.template_history and dialog.template_history[0] != "":
                dialog.template_history.insert(0, "")
                dialog.template_history_index = 0
            elif not dialog.template_history:
                dialog.template_history = [""]
                dialog.template_history_index = 0
            
            # Clear the field
            dialog.template_text.delete(1.0, END)
            self._process_template_tags(dialog)
            self._update_filename_preview(dialog)
            self._check_filename_changes(dialog)
        
        return "break"  # Prevent default undo behavior
    
    def _handle_template_redo(self, dialog, event):
        """Handle redo (Ctrl+Shift+Z or Ctrl+Y) in template Text widget - cycle to next content state."""
        if not hasattr(dialog, 'template_history') or not dialog.template_history or not hasattr(dialog, 'template_text'):
            return "break"  # No history, prevent default behavior
        
        # Cancel any pending timers
        if dialog.tag_process_timer:
            dialog.after_cancel(dialog.tag_process_timer)
            dialog.tag_process_timer = None
        if dialog.template_save_timer:
            dialog.after_cancel(dialog.template_save_timer)
            dialog.template_save_timer = None
        
        # Save current content to history before redoing (so we can undo back to it)
        self._save_template_state(dialog, immediate=True)
        
        # Move forward in history
        if dialog.template_history_index < len(dialog.template_history) - 1:
            dialog.template_history_index += 1
            next_content = dialog.template_history[dialog.template_history_index]
            
            # Replace current content with next state
            dialog.template_text.delete(1.0, END)
            dialog.template_text.insert(1.0, next_content)
            
            # Process tags and update preview
            self._process_template_tags(dialog)
            self._update_filename_preview(dialog)
            self._check_filename_changes(dialog)
        
        return "break"  # Prevent default redo behavior
    
    def _create_filename_slot(self, dialog, parent_frame, initial_value=None):
        """Create a filename format slot with fields and separators.
        
        Args:
            dialog: The customize dialog
            parent_frame: Parent frame for the slot
            initial_value: Initial format data dict or None
        """
        slot_frame = Frame(parent_frame, bg='#1E1E1E', relief='flat', bd=1, 
                          highlightbackground='#3E3E42', highlightthickness=1)
        slot_frame.pack(fill=X, pady=2, padx=5, anchor='nw')
        
        # Normalize initial value
        if initial_value:
            level_data = self._normalize_filename_format(initial_value)
        else:
            # Default: start with "01" and "Track"
            level_data = {"fields": ["01", "Track"], "separators": ["", ". ", ""]}
        
        slot_frame.level_data = level_data
        slot_frame.is_filled = True
        
        # Fields container
        fields_container = Frame(slot_frame, bg='#1E1E1E')
        fields_container.pack(fill=X, padx=5, pady=5)
        slot_frame.fields_container = fields_container
        dialog.fields_container = fields_container  # Store reference
        
        # Rebuild UI for fields
        self._rebuild_filename_fields_ui(dialog, slot_frame)
    
    def _rebuild_filename_fields_ui(self, dialog, slot_frame):
        """Rebuild the UI for fields and separators in filename format."""
        # Clear existing field widgets
        if hasattr(slot_frame, 'fields_container'):
            for widget in slot_frame.fields_container.winfo_children():
                widget.destroy()
        
        slot_frame.field_widgets = []
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        separators = level_data.get("separators", [])
        
        if not fields:
            # No fields, add default
            fields = ["01", "Track"]
            level_data["fields"] = fields
        
        # Ensure separators list matches: prefix + between fields + suffix (fields + 1 total)
        num_separators = len(fields) + 1
        while len(separators) < num_separators:
            separators.append("")
        separators = separators[:num_separators]
        level_data["separators"] = separators
        
        # Build UI: [Prefix Sep] [Field1 ▼] [Between Sep] [Field2 ▼] ... [Suffix Sep] [+ Add Field]
        for i, field in enumerate(fields):
            # Prefix separator (before first field)
            if i == 0:
                prefix_separator = separators[0] if separators else ""
                prefix_var = StringVar(value=prefix_separator if prefix_separator else "")
                prefix_entry = self._create_separator_entry(
                    slot_frame.fields_container, prefix_var, dialog, slot_frame, 0, is_prefix=True
                )
            else:
                prefix_entry = None
                prefix_var = None
            
            # Field dropdown
            field_var = StringVar(value=field)
            available_fields = self._get_available_filename_fields_for_slot(dialog, slot_frame, field)
            field_combo = ttk.Combobox(
                slot_frame.fields_container,
                textvariable=field_var,
                values=available_fields,
                state="readonly",
                width=12
            )
            field_combo.pack(side=LEFT, padx=2)
            field_combo.bind("<<ComboboxSelected>>", lambda e, idx=i: self._on_filename_field_change(dialog, slot_frame, idx))
            
            # Between-fields separator (after each field except last)
            separator_entry = None
            separator_var = None
            if i < len(fields) - 1:
                gap_separator = separators[i + 1] if i + 1 < len(separators) else " "
                if gap_separator == "None" or gap_separator is None:
                    gap_separator = " "
                separator_var = StringVar(value=gap_separator)
                separator_entry = self._create_separator_entry(
                    slot_frame.fields_container, separator_var, dialog, slot_frame, i + 1, is_prefix=False
                )
            
            # Suffix separator (after last field)
            suffix_entry = None
            suffix_var = None
            if i == len(fields) - 1:
                suffix_separator = separators[len(fields)] if len(fields) < len(separators) else ""
                suffix_var = StringVar(value=suffix_separator if suffix_separator else "")
                suffix_entry = self._create_separator_entry(
                    slot_frame.fields_container, suffix_var, dialog, slot_frame, len(fields), is_prefix=False
                )
            
            # Store widget references
            slot_frame.field_widgets.append((
                field_combo, prefix_entry, separator_entry, suffix_entry,
                field_var, prefix_var, separator_var, suffix_var
            ))
        
        # Add Field button (if under max)
        if len(fields) < 4:
            add_field_btn = ttk.Button(
                slot_frame.fields_container,
                text="+ Add Field",
                command=lambda: self._add_filename_field(dialog, slot_frame)
            )
            add_field_btn.pack(side=LEFT, padx=5)
            slot_frame.add_field_btn = add_field_btn
        
        # Update preview
        self._update_filename_preview(dialog)
    
    def _get_available_filename_fields_for_slot(self, dialog, slot_frame, exclude_field=None):
        """Get available fields for filename format (allows current field + unused fields)."""
        # All filename field options
        all_fields = self.FILENAME_FIELD_OPTIONS.copy()
        
        # Get used fields (excluding current field)
        used_fields = set()
        if hasattr(slot_frame, 'field_widgets'):
            for field_combo, _, _, _, field_var, _, _, _ in slot_frame.field_widgets:
                current_field = field_var.get()
                if current_field != exclude_field:
                    used_fields.add(current_field)
        
        # Return available fields (including current field if it's not exclude_field)
        available = []
        for field in all_fields:
            if field not in used_fields or (exclude_field and field == exclude_field):
                available.append(field)
        
        return available
    
    def _on_filename_field_change(self, dialog, slot_frame, field_index):
        """Handle filename field dropdown change."""
        field_combo, prefix_entry, separator_entry, suffix_entry, field_var, prefix_var, separator_var, suffix_var = slot_frame.field_widgets[field_index]
        
        # Update level data
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        if field_index < len(fields):
            fields[field_index] = field_var.get()
        
        # Rebuild UI to update available fields
        self._rebuild_filename_fields_ui(dialog, slot_frame)
        
        # Update preview after field change
        self._update_filename_preview(dialog)
    
    def _add_filename_field(self, dialog, slot_frame):
        """Add a new field to filename format (max 4 fields)."""
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        
        if len(fields) >= 4:
            return  # Max 4 fields
        
        # Get available fields
        available = self._get_available_filename_fields_for_slot(dialog, slot_frame)
        if available:
            new_field = available[0]
            fields.append(new_field)
            
            # Add separator for new field
            separators = level_data.get("separators", [])
            # Insert separator before new field (between previous last field and new field)
            separators.insert(len(fields) - 1, " ")  # Default space separator
            # Ensure suffix separator exists
            while len(separators) < len(fields) + 1:
                separators.append("")
            level_data["separators"] = separators[:len(fields) + 1]
        
        # Rebuild UI
        self._rebuild_filename_fields_ui(dialog, slot_frame)
        
        # Update preview after adding field
        self._update_filename_preview(dialog)
    
    def _remove_filename_field(self, dialog, slot_frame, field_index):
        """Remove a field from filename format."""
        level_data = slot_frame.level_data
        fields = level_data.get("fields", [])
        separators = level_data.get("separators", [])
        
        if len(fields) <= 1:
            return  # Must have at least one field
        
        # Remove field
        fields.pop(field_index)
        
        # Remove corresponding separators
        # Remove separator before field (if not first field) and separator after field
        if field_index > 0:
            # Remove separator before this field
            separators.pop(field_index)
        else:
            # First field - remove prefix separator
            if separators:
                separators.pop(0)
        
        # Ensure separators list is correct length
        num_separators = len(fields) + 1
        while len(separators) < num_separators:
            separators.append("")
        separators = separators[:num_separators]
        level_data["separators"] = separators
        
        # Rebuild UI
        self._rebuild_filename_fields_ui(dialog, slot_frame)
        
        # Update preview after removing field
        self._update_filename_preview(dialog)
    
    def _update_filename_preview(self, dialog):
        """Update preview text in filename dialog."""
        if not hasattr(dialog, 'preview_text') or not hasattr(dialog, 'template_text'):
            return
        
        template = dialog.template_text.get('1.0', END).strip()
        if not template:
            dialog.preview_text.config(text="")
            return
        
        # Generate preview using template
        preview = self._generate_filename_from_template(template, track_number=1, preview_mode=True)
        dialog.preview_text.config(text=preview)
    
    def _parse_template(self, template):
        """Parse template string to extract tags and literal text.
        
        Args:
            template: Template string like "01 - Artist - Track" (no curly brackets)
            
        Returns:
            List of tuples: (type, value) where type is 'tag' or 'literal'
        """
        if not template:
            return []
        
        import re
        parts = []
        
        # Sort tag names by length (longest first) to match "Album Artist" before "Album"
        tag_names_sorted = sorted(self.FILENAME_TAG_NAMES, key=len, reverse=True)
        
        # Build regex pattern for whole word matching
        pattern_parts = []
        for tag_name in tag_names_sorted:
            escaped = re.escape(tag_name)
            if ' ' in tag_name:
                # Multi-word tags like "Album Artist"
                pattern_parts.append(rf'\b{escaped}\b')
            else:
                # Single word tags
                pattern_parts.append(rf'\b{escaped}\b')
        
        # Combine patterns with alternation
        pattern = '|'.join(pattern_parts)
        
        # Find all matches
        all_matches = list(re.finditer(pattern, template, re.IGNORECASE))
        
        # Filter out overlapping matches (prefer longer matches)
        valid_matches = []
        used_ranges = []
        for match in sorted(all_matches, key=lambda m: (m.end() - m.start(), m.start()), reverse=True):
            start, end = match.span()
            # Check if this range overlaps with any already used
            overlaps = False
            for used_start, used_end in used_ranges:
                if not (end <= used_start or start >= used_end):
                    overlaps = True
                    break
            if not overlaps:
                valid_matches.append(match)
                used_ranges.append((start, end))
        
        # Sort matches by position
        valid_matches.sort(key=lambda m: m.start())
        
        last_end = 0
        for match in valid_matches:
            # Add literal text before this tag
            if match.start() > last_end:
                literal = template[last_end:match.start()]
                if literal:
                    parts.append(('literal', literal))
            
            # Add the tag
            tag_name = match.group(0)  # The matched text
            parts.append(('tag', tag_name))
            
            last_end = match.end()
        
        # Add remaining literal text
        if last_end < len(template):
            literal = template[last_end:]
            if literal:
                parts.append(('literal', literal))
        
        return parts
    
    def _generate_filename_from_template(self, template, track_number=1, metadata=None, preview_mode=False):
        """Generate filename from template string.
        
        Args:
            template: Template string like "{01} - {Artist} - {Track}"
            track_number: Track number (integer)
            metadata: Dict with metadata values (artist, album, etc.)
            preview_mode: If True, use field names for preview; if False, use actual values
            
        Returns:
            Generated filename string
        """
        if not template:
            return ""
        
        # Parse template
        parts = self._parse_template(template)
        if not parts:
            return ""
        
        # Default metadata if not provided
        if metadata is None:
            metadata = {}
        
        # Tag to value mapping
        if preview_mode:
            # Use field names for preview
            tag_values = {
                "01": f"{track_number:02d}",
                "1": str(track_number),
                "Track": "Track",
                "Artist": "Artist",
                "Album": "Album",
                "Year": "Year",
                "Genre": "Genre",
                "Label": "Label",
                "Album Artist": "Album Artist",
                "Catalog Number": "Catalog Number"
            }
        else:
            # Use actual values for file renaming
            tag_values = {
                "01": f"{track_number:02d}",
                "1": str(track_number),
                "Track": self.sanitize_filename(metadata.get("title", "") or "Track"),
                "Artist": self.sanitize_filename(metadata.get("artist", "") or "Artist"),
                "Album": self.sanitize_filename(metadata.get("album", "") or "Album"),
                "Year": str(metadata.get("year", "") or "Year"),
                "Genre": self.sanitize_filename(metadata.get("genre", "") or "Genre"),
                "Label": self.sanitize_filename(metadata.get("label") or metadata.get("publisher", "") or "Label"),
                "Album Artist": self.sanitize_filename(metadata.get("album_artist") or metadata.get("albumartist", "") or "Album Artist"),
                "Catalog Number": self.sanitize_filename(metadata.get("catalog_number") or metadata.get("catalognumber", "") or "Catalog Number")
            }
        
        # Build result
        result_parts = []
        for part_type, part_value in parts:
            if part_type == 'tag':
                # Replace tag with value (part_value is the tag name without curly brackets)
                value = tag_values.get(part_value, part_value)  # Keep unknown tags as-is
                result_parts.append(value)
            else:
                # Literal text - keep as-is
                result_parts.append(part_value)
        
        result = "".join(result_parts)
        
        # Sanitize the entire result (in case tags introduced invalid chars)
        if not preview_mode:
            result = self.sanitize_filename(result)
        
        return result
    
    def _generate_filename_preview(self, format_data, track_number=1):
        """Generate preview filename from format data.
        
        Args:
            format_data: Format dict with "template" string
            track_number: Track number to use in preview
            
        Returns:
            Preview filename string
        """
        normalized = self._normalize_filename_format(format_data)
        if not normalized:
            return ""
        
        template = normalized.get("template", "")
        if not template:
            return ""
        
        # Generate preview using template
        return self._generate_filename_from_template(template, track_number, preview_mode=True)
    
    def _get_filename_from_dialog(self, dialog):
        """Get the current filename format from the dialog without saving.
        
        Args:
            dialog: The customize dialog
            
        Returns:
            Format dict with template string (normalized)
        """
        if not hasattr(dialog, 'template_text'):
            return None
        
        # Get text content, removing any widget markers
        template = dialog.template_text.get('1.0', END).strip()
        if not template:
            return None
        
        # Remove any widget placeholders (they appear as empty strings in the text)
        # The actual tag text should remain
        format_data = {"template": template}
        return self._normalize_filename_format(format_data)
    
    def _check_filename_changes(self, dialog):
        """Check if filename format has changed and enable/disable save buttons accordingly."""
        # Check if we're editing (either custom format or default format)
        is_editing_custom = hasattr(dialog, 'editing_format_index') and dialog.editing_format_index is not None
        is_editing_default = getattr(dialog, 'editing_default_format', False)
        
        if not is_editing_custom and not is_editing_default:
            return  # Not editing, no need to check
        
        if not hasattr(dialog, 'initial_template'):
            return  # Initial template not set yet
        
        if not hasattr(dialog, 'template_text'):
            return
        
        current_template = dialog.template_text.get('1.0', END).strip()
        initial_template = dialog.initial_template.strip()
        
        # Compare templates
        has_changes = current_template != initial_template
        
        # Enable/disable buttons based on changes
        if has_changes:
            if hasattr(dialog, 'update_btn'):
                dialog.update_btn.config(state='normal')
            if hasattr(dialog, 'save_as_new_btn'):
                dialog.save_as_new_btn.config(state='normal')
            if hasattr(dialog, 'save_btn'):
                dialog.save_btn.config(state='normal')
        else:
            if hasattr(dialog, 'update_btn'):
                dialog.update_btn.config(state='disabled')
            if hasattr(dialog, 'save_as_new_btn'):
                dialog.save_as_new_btn.config(state='disabled')
            if hasattr(dialog, 'save_btn'):
                dialog.save_btn.config(state='disabled')
    
    def _create_new_filename_in_dialog(self, dialog):
        """Create new filename format from current dialog (clears editing state)."""
        dialog.editing_format_index = None
        dialog.initial_format = None
        
        # Hide update buttons, show save button
        for widget in dialog.winfo_children():
            if isinstance(widget, Frame):
                for child in widget.winfo_children():
                    if isinstance(child, Frame):  # buttons_frame
                        for btn in child.winfo_children():
                            if isinstance(btn, ttk.Button):
                                btn.destroy()
        
        # Recreate buttons frame with just Save and Cancel
        buttons_frame = Frame(dialog.winfo_children()[0], bg='#1E1E1E')
        buttons_frame.pack(pady=(3, 5))
        
        save_btn = ttk.Button(
            buttons_frame,
            text="Save Format",
            command=lambda: self._save_custom_filename_from_dialog(dialog, update_existing=False)
        )
        save_btn.pack(side=LEFT, padx=5)
        
        cancel_btn = ttk.Button(
            buttons_frame,
            text="Cancel",
            command=dialog.destroy
        )
        cancel_btn.pack(side=LEFT, padx=5)
    
    def _save_custom_filename_from_dialog(self, dialog, update_existing=None):
        """Save filename format from dialog to custom_filename_formats.
        
        Args:
            dialog: The customize dialog
            update_existing: If True, update existing format. If False, create new. If None, determine automatically.
        """
        format_data = self._get_filename_from_dialog(dialog)
        if not format_data:
            messagebox.showerror("Error", "Invalid filename format. Please enter a template.")
            return
        
        template = format_data.get("template", "").strip()
        if not template:
            messagebox.showerror("Error", "Template cannot be empty.")
            return
        
        editing_index = getattr(dialog, 'editing_format_index', None)
        
        # If update_existing is None, determine automatically based on editing_index
        if update_existing is None:
            update_existing = (editing_index is not None and 0 <= editing_index < len(self.custom_filename_formats))
        
        if update_existing and editing_index is not None and 0 <= editing_index < len(self.custom_filename_formats):
            # We're updating an existing format - replace it
            self.custom_filename_formats[editing_index] = format_data
        else:
            # We're creating a new format - check if it already exists to avoid duplicates
            format_exists = False
            formatted_new = self._format_custom_filename(format_data)
            
            # Check against custom formats
            for existing in self.custom_filename_formats:
                formatted_existing = self._format_custom_filename(existing)
                if formatted_new == formatted_existing:
                    format_exists = True
                    break
            
            # Also check against default formats
            if not format_exists:
                for default_key, default_data in self.FILENAME_FORMATS.items():
                    if default_data and default_data.get("template") == template:
                        format_exists = True
                        break
            
            if format_exists:
                messagebox.showwarning("Duplicate Format", "A filename format with this configuration already exists.")
                return
            
            # Add new format
            self.custom_filename_formats.append(format_data)
        
        # Save to settings
        self._save_custom_filename_formats()
        
        # Update dropdown
        self._update_filename_dropdown()
        
        # Set current selection to the saved format
        formatted = self._format_custom_filename(format_data)
        self.numbering_var.set(formatted)
        self.on_numbering_change()
        self.update_preview()
        
        # Close dialog
        dialog.destroy()
    
    def _show_manage_filename_dialog(self):
        """Show modal dialog to manage custom filename formats."""
        if not hasattr(self, 'custom_filename_formats') or not self.custom_filename_formats:
            messagebox.showinfo("No Custom Formats", "No custom filename formats have been saved yet.\n\nCreate one using the Customize button (✏️).")
            return
        
        dialog = Toplevel(self.root)
        dialog.title(" Delete Custom Filename Formats")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"400x300+{x}+{y}")
        
        # Use theme colors
        colors = self.theme_colors
        # Main container background: dark mode uses bg, light mode uses select_bg (white)
        main_bg = colors.select_bg if self.current_theme == 'light' else colors.bg
        
        # Configure dialog background
        dialog.configure(bg=main_bg)
        
        # Title
        title_label = Label(
            dialog,
            text="Delete Custom Filename Formats",
            font=("Segoe UI", 10, "bold"),
            bg=main_bg,
            fg=colors.fg
        )
        title_label.pack(pady=(10, 10))
        
        # Container for format list
        list_frame = Frame(dialog, bg=main_bg)
        list_frame.pack(pady=10, padx=20, fill=BOTH, expand=True)
        
        # Create list of formats with delete buttons
        for format_data in self.custom_filename_formats:
            format_frame = Frame(list_frame, bg=main_bg, relief='flat', bd=1, highlightbackground=colors.border, highlightthickness=1)
            format_frame.pack(fill=X, pady=2, padx=5)
            
            # Format label
            formatted = self._format_custom_filename(format_data)
            format_label = Label(
                format_frame,
                text=formatted,
                font=("Segoe UI", 9),
                bg=main_bg,
                fg=colors.fg,
                anchor=W
            )
            format_label.pack(side=LEFT, padx=10, fill=X, expand=True)
            
            # Delete button
            delete_btn = ttk.Button(
                format_frame,
                text="X",
                width=3,
                command=lambda f=format_data: self._delete_custom_filename(dialog, f)
            )
            delete_btn.pack(side=RIGHT, padx=5)
        
        # Close button
        close_btn = ttk.Button(
            dialog,
            text="Close",
            command=dialog.destroy
        )
        close_btn.pack(pady=10)
        
        # Close on ESC
        dialog.bind('<Escape>', lambda e: dialog.destroy())
    
    def _delete_custom_filename(self, dialog, format_data):
        """Delete a custom filename format."""
        if format_data in self.custom_filename_formats:
            # Check if this is the currently selected format
            formatted = self._format_custom_filename(format_data)
            current_value = self.numbering_var.get()
            
            # Remove from list
            self.custom_filename_formats.remove(format_data)
            
            # Save settings
            self._save_custom_filename_formats()
            
            # Update dropdown
            self._update_filename_dropdown()
            
            # Update manage button state
            self._update_filename_manage_button()
            
            # If deleted format was selected, switch to default
            if current_value == formatted:
                self.numbering_var.set(self.DEFAULT_NUMBERING)
                self.on_numbering_change()
                self.update_preview()
            
            # Rebuild dialog if formats remain, otherwise close
            if self.custom_filename_formats:
                dialog.destroy()
                self._show_manage_filename_dialog()  # Reopen with updated list
            else:
                dialog.destroy()
    
    def _update_filename_edit_button(self):
        """Update filename edit button state based on current selection."""
        if hasattr(self, 'filename_customize_btn'):
            numbering_style = self.numbering_var.get()
            colors = self.theme_colors
            # Disable edit button when "Original" is selected (nothing to customize)
            if numbering_style == "Original":
                disabled_color = '#404040' if self.current_theme == 'dark' else '#A0A0A0'
                self.filename_customize_btn.config(fg=disabled_color, cursor='arrow')
                # Unbind events
                try:
                    self.filename_customize_btn.unbind("<Button-1>")
                    self.filename_customize_btn.unbind("<Enter>")
                    self.filename_customize_btn.unbind("<Leave>")
                except:
                    pass
            else:
                # Enable edit button for other formats
                self.filename_customize_btn.config(fg=colors.disabled_fg, cursor='hand2')
                # Rebind events
                self.filename_customize_btn.bind("<Button-1>", lambda e: self._show_customize_filename_dialog())
                self.filename_customize_btn.bind("<Enter>", lambda e: self.filename_customize_btn.config(fg=colors.hover_fg))
                self.filename_customize_btn.bind("<Leave>", lambda e: self.filename_customize_btn.config(fg=colors.disabled_fg))
    
    def _update_filename_manage_button(self):
        """Update filename manage button state based on whether custom formats exist."""
        if hasattr(self, 'filename_manage_btn'):
            colors = self.theme_colors
            has_custom = hasattr(self, 'custom_filename_formats') and self.custom_filename_formats
            if has_custom:
                self.filename_manage_btn.config(fg=colors.disabled_fg, cursor='hand2')
                # Rebind events
                self.filename_manage_btn.bind("<Button-1>", lambda e: self._show_manage_filename_dialog())
                self.filename_manage_btn.bind("<Enter>", lambda e: self.filename_manage_btn.config(fg=colors.hover_fg))
                self.filename_manage_btn.bind("<Leave>", lambda e: self.filename_manage_btn.config(fg=colors.disabled_fg))
            else:
                disabled_color = '#404040' if self.current_theme == 'dark' else '#A0A0A0'
                self.filename_manage_btn.config(fg=disabled_color, cursor='arrow')
                # Unbind events
                try:
                    self.filename_manage_btn.unbind("<Button-1>")
                    self.filename_manage_btn.unbind("<Enter>")
                    self.filename_manage_btn.unbind("<Leave>")
                except:
                    pass
    
    def _get_all_filename_options(self):
        """Get all filename format options including custom formats."""
        # Start with standard options
        options = ["Track", "01. Track", "Artist - Track", "01. Artist - Track"]
        # Add custom formats (if they exist)
        if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
            for format_data in self.custom_filename_formats:
                formatted = self._format_custom_filename(format_data)
                if formatted and formatted not in options:
                    options.append(formatted)
        return options
    
    def _build_filename_menu(self, menu):
        """Build filename menu with standard and custom formats."""
        menu.delete(0, END)
        
        # Add "Original" option first (preserves original Bandcamp filenames)
        menu.add_command(
            label=" Original      ",
            command=lambda: self._on_filename_menu_select("Original")
        )
        
        # Add separator after Original
        menu.add_separator()
        
        # Add standard formats
        for format_key in ["Track", "01. Track", "Artist - Track", "01. Artist - Track"]:
            padded_label = f" {format_key}      "
            menu.add_command(
                label=padded_label,
                command=lambda val=format_key: self._on_filename_menu_select(val)
            )
        
        # Add separator if there are custom formats
        if hasattr(self, 'custom_filename_formats') and self.custom_filename_formats:
            menu.add_separator()
            # Add custom formats
            for format_data in self.custom_filename_formats:
                formatted = self._format_custom_filename(format_data)
                if formatted:
                    padded_label = f" {formatted}      "
                    menu.add_command(
                        label=padded_label,
                        command=lambda f=format_data: self._on_filename_menu_select(f)
                    )
    
    def _on_filename_menu_select(self, choice):
        """Handle filename format menu selection.
        
        Args:
            choice: Either a string key ("Original", "01. Track", etc.) or a format dict
        """
        if isinstance(choice, str):
            # Standard format (including "Original")
            self.numbering_var.set(choice)
        elif isinstance(choice, dict):
            # Custom format
            formatted = self._format_custom_filename(choice)
            if formatted:
                self.numbering_var.set(formatted)
        
        # Update edit button state based on selection
        self._update_filename_edit_button()
        
        # Save the selection and update preview
        self.on_numbering_change()
        self.update_preview()
    
    def _update_filename_dropdown(self):
        """Update filename dropdown menu to include custom formats."""
        if hasattr(self, 'filename_menu'):
            self._build_filename_menu(self.filename_menu)
        
        # Update button states
        self._update_filename_edit_button()
        self._update_filename_manage_button()
    
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
            self.cancel_btn.config(state='disabled', cursor='arrow')  # Regular cursor when disabled
        except:
            pass
        self.download_btn.config(state='normal')
        self.download_btn.grid()
        
        # Update clear log button state after download/cancel operations complete
        self._update_clear_button_state()
        
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
    
    def _setup_filename_character_filter(self, dialog, text_widget, parent_frame):
        """Setup character filtering for filename customizer.
        Blocks: \ / : * ? " < > |
        """
        # Illegal characters for filenames
        illegal_chars = set('\\/:*?"<>|')
        
        # Find the label row frame (should be the first Frame in parent_frame)
        label_row = None
        for widget in parent_frame.winfo_children():
            if isinstance(widget, Frame):
                label_row = widget
                break
        
        # Create warning label (initially hidden) - single line, inline with label
        warning_label = Label(
            label_row if label_row else parent_frame,
            text="Invalid characters: \\ / : * ? \" < > |",
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#17a0c4'
        )
        warning_label.pack_forget()  # Hidden initially
        dialog.warning_label = warning_label
        dialog.warning_timer = None
        
        def show_warning():
            """Show warning label briefly."""
            # Show the warning label if not already visible
            if not warning_label.winfo_viewable():
                if label_row:
                    warning_label.pack(side=LEFT, padx=(8, 0))
                else:
                    warning_label.pack(anchor=W, pady=(0, 5))
            # Hide after 4 seconds
            if dialog.warning_timer:
                dialog.after_cancel(dialog.warning_timer)
            dialog.warning_timer = dialog.after(4000, lambda: warning_label.pack_forget())
        
        def filter_key(event):
            """Filter illegal characters on key press."""
            # Allow special keys (backspace, delete, arrows, etc.)
            if len(event.char) == 0 or event.keysym in ['BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Tab']:
                return None
            
            # Check if character is illegal
            if event.char in illegal_chars:
                show_warning()
                return "break"  # Prevent insertion
            return None
        
        def filter_paste(event):
            """Filter illegal characters from pasted content."""
            try:
                # Get clipboard content
                clipboard_text = dialog.clipboard_get()
                # Filter out illegal characters
                filtered = ''.join(c for c in clipboard_text if c not in illegal_chars)
                if filtered != clipboard_text:
                    # Some characters were filtered, show warning
                    show_warning()
                    # Insert filtered content
                    text_widget.insert(INSERT, filtered)
                    return "break"  # Prevent default paste
            except:
                pass
            return None
        
        # Bind key press and paste events
        text_widget.bind('<KeyPress>', filter_key)
        text_widget.bind('<Control-v>', filter_paste)
        text_widget.bind('<Shift-Insert>', filter_paste)
        # Note: Right-Click paste is handled by the system menu, which we can't easily intercept
        # Users will see the warning if they paste illegal characters via right-Click
    
    def _setup_folder_character_filter(self, dialog, text_widget, parent_frame):
        """Setup character filtering for folder customizer.
        Blocks: : * ? " < > |
        Allows: \ / (used as folder separators)
        """
        # Illegal characters for folders (excluding \ and / which are allowed)
        illegal_chars = set(':*?"<>|')
        
        # Find the label row frame (should be the first Frame in parent_frame)
        label_row = None
        for widget in parent_frame.winfo_children():
            if isinstance(widget, Frame):
                label_row = widget
                break
        
        # Create warning label (initially hidden) - single line, inline with label
        warning_label = Label(
            label_row if label_row else parent_frame,
            text="Invalid characters: : * ? \" < > |",
            font=("Segoe UI", 8),
            bg='#1E1E1E',
            fg='#17a0c4'
        )
        warning_label.pack_forget()  # Hidden initially
        dialog.warning_label = warning_label
        dialog.warning_timer = None
        
        def show_warning():
            """Show warning label briefly."""
            # Show the warning label if not already visible
            if not warning_label.winfo_viewable():
                if label_row:
                    warning_label.pack(side=LEFT, padx=(8, 0))
                else:
                    warning_label.pack(anchor=W, pady=(0, 5))
            # Hide after 4 seconds
            if dialog.warning_timer:
                dialog.after_cancel(dialog.warning_timer)
            dialog.warning_timer = dialog.after(4000, lambda: warning_label.pack_forget())
        
        def filter_key(event):
            """Filter illegal characters on key press."""
            # Allow special keys (backspace, delete, arrows, etc.)
            if len(event.char) == 0 or event.keysym in ['BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Home', 'End', 'Tab']:
                return None
            
            # Check if character is illegal
            if event.char in illegal_chars:
                show_warning()
                return "break"  # Prevent insertion
            return None
        
        def filter_paste(event):
            """Filter illegal characters from pasted content."""
            try:
                # Get clipboard content
                clipboard_text = dialog.clipboard_get()
                # Filter out illegal characters (but keep \ and /)
                filtered = ''.join(c for c in clipboard_text if c not in illegal_chars)
                if filtered != clipboard_text:
                    # Some characters were filtered, show warning
                    show_warning()
                    # Insert filtered content
                    text_widget.insert(INSERT, filtered)
                    return "break"  # Prevent default paste
            except:
                pass
            return None
        
        # Bind key press and paste events
        text_widget.bind('<KeyPress>', filter_key)
        text_widget.bind('<Control-v>', filter_paste)
        text_widget.bind('<Shift-Insert>', filter_paste)
        # Note: Right-Click paste is handled by the system menu, which we can't easily intercept
        # Users will see the warning if they paste illegal characters via right-Click


def main():
    """Main entry point."""
    root = Tk()
    app = BandcampDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

