"""
Bandcamp Downloader - Launcher
Self-contained launcher that bundles Python, ffmpeg, and auto-updates the main script.
"""

# Launcher version (update this when releasing a new launcher.exe)
__version__ = "1.3.3"

import sys
import os
import threading
import time
import runpy
import subprocess
from pathlib import Path
import json
import shutil
import tempfile

# GitHub repository information
REPO_OWNER = "kameryn1811"
REPO_NAME = "Bandcamp-Downloader"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
LAUNCHER_RELEASE_TAG = "Launcher"  # Tag for launcher.exe releases
SCRIPT_NAME = "bandcamp_dl_gui.py"
LAUNCHER_EXE_NAME = "BandcampDownloader.exe"

# Get launcher directory (where launcher.exe is located)
if hasattr(sys, 'frozen'):
    # Running as PyInstaller bundle
    LAUNCHER_DIR = Path(sys.executable).parent
    # In PyInstaller, bundled files are extracted to sys._MEIPASS
    # The script is bundled as a data file, so we need to copy it from _MEIPASS if it doesn't exist
    BUNDLED_SCRIPT = Path(sys._MEIPASS) / SCRIPT_NAME if hasattr(sys, '_MEIPASS') else None
else:
    # Running as script
    LAUNCHER_DIR = Path(__file__).resolve().parent
    BUNDLED_SCRIPT = None

SCRIPT_PATH = LAUNCHER_DIR / SCRIPT_NAME
SETTINGS_FILE = LAUNCHER_DIR / "launcher_settings.json"
UPDATE_STATUS_FILE = LAUNCHER_DIR / "update_status.json"
LAUNCHER_EXE_PATH = Path(sys.executable) if hasattr(sys, 'frozen') else None
LAUNCHER_UPDATE_TEMP = Path(tempfile.gettempdir()) / "BandcampDownloader_new.exe"


def get_launcher_version():
    """Get version of the current launcher executable.
    
    Returns:
        Version string if found, None otherwise
    """
    # If running as script (not frozen), return version from this file
    if not hasattr(sys, 'frozen'):
        return __version__
    
    # If running as exe, try to get version from embedded data or file
    try:
        # Try to read version from launcher.py if it exists in the directory
        launcher_py = LAUNCHER_DIR / "launcher.py"
        if launcher_py.exists():
            with open(launcher_py, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.split('\n'):
                    if '__version__' in line and '=' in line:
                        version = line.split('=')[1].strip().strip('"').strip("'")
                        return version
    except Exception:
        pass
    
    # Fallback: return embedded version (this is the version compiled into the exe)
    # For old launchers that don't have launcher.py in the directory, this will return the old version
    return __version__


def get_local_version():
    """Get version from local script file."""
    if not SCRIPT_PATH.exists():
        return None
    
    try:
        with open(SCRIPT_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            # Look for __version__ = "x.x.x"
            for line in content.split('\n'):
                if '__version__' in line and '=' in line:
                    # Extract version string
                    version = line.split('=')[1].strip().strip('"').strip("'")
                    return version
    except Exception:
        pass
    
    return None


def get_latest_launcher_version():
    """Get latest launcher.exe version from launcher_manifest.json on GitHub.
    
    Returns:
        Tuple of (version_string, download_url, file_size) or (None, None, None) if error
    """
    try:
        import requests
        import json
        
        # Get manifest from GitHub main branch
        manifest_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/launcher_manifest.json"
        response = requests.get(manifest_url, timeout=10)
        response.raise_for_status()
        manifest = json.loads(response.text)
        
        version = manifest.get('version')
        download_url = manifest.get('download_url')
        file_size = manifest.get('file_size', 0)
        
        if not version or not download_url:
            print("Warning: Invalid launcher manifest (missing version or download_url)")
            return None, None, None
        
        # Ensure download URL has dl=1 for direct download
        if 'dl=0' in download_url:
            download_url = download_url.replace('dl=0', 'dl=1')
        
        return version, download_url, file_size
    except ImportError:
        print("Warning: 'requests' library not found. Launcher update checking disabled.")
        return None, None, None
    except json.JSONDecodeError as e:
        print(f"Error parsing launcher manifest: {e}")
        return None, None, None
    except Exception as e:
        print(f"Error checking for launcher updates: {e}")
        return None, None, None


def get_latest_version():
    """Get latest version by reading directly from main branch file (not from releases)."""
    try:
        import requests
        import re
        # Get version directly from main branch file (not from releases)
        # This way we don't depend on releases being created/updated
        download_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{SCRIPT_NAME}"
        response = requests.get(download_url, timeout=10)
        response.raise_for_status()
        file_content = response.text
        
        # Extract version from the file
        version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', file_content)
        if not version_match:
            print("Warning: Could not find version number in main branch file.")
            return None, None, None
        
        latest_version = version_match.group(1)
        
        # Return version, download URL, and None for release_data (not needed anymore)
        return latest_version, download_url, None
    except ImportError:
        print("Warning: 'requests' library not found. Update checking disabled.")
        return None, None, None
    except Exception as e:
        print(f"Error checking for updates: {e}")
        return None, None, None


def compare_versions(version1, version2):
    """Compare two version strings.
    
    Returns:
        -1 if version1 < version2
         0 if version1 == version2
         1 if version1 > version2
    """
    def version_tuple(v):
        parts = []
        for part in v.split('.'):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(0)
        return tuple(parts)
    
    v1_tuple = version_tuple(version1)
    v2_tuple = version_tuple(version2)
    
    max_len = max(len(v1_tuple), len(v2_tuple))
    v1_tuple = v1_tuple + (0,) * (max_len - len(v1_tuple))
    v2_tuple = v2_tuple + (0,) * (max_len - len(v2_tuple))
    
    if v1_tuple < v2_tuple:
        return -1
    elif v1_tuple > v2_tuple:
        return 1
    else:
        return 0


def write_update_status(message, version=None):
    """Write update status to file for GUI to read.
    
    Appends to existing messages if file exists, otherwise creates new.
    """
    try:
        messages = []
        if UPDATE_STATUS_FILE.exists():
            try:
                with open(UPDATE_STATUS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    messages = data.get("messages", [])
            except Exception:
                messages = []
        
        messages.append({
            "message": message,
            "version": version,
            "timestamp": time.time()
        })
        
        status = {
            "messages": messages,
            "latest_version": version
        }
        with open(UPDATE_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f)
    except Exception:
        pass  # Don't fail if we can't write status


def clear_update_status():
    """Clear update status file."""
    try:
        if UPDATE_STATUS_FILE.exists():
            UPDATE_STATUS_FILE.unlink()
    except Exception:
        pass


def download_script(download_url, expected_version=None):
    """Download the latest script from GitHub.
    
    Args:
        download_url: URL to download the script from
        expected_version: Expected version string to verify (optional)
    
    Returns:
        Script content as string, or None if error
    """
    try:
        import requests
        import re
        # Only log if we're actually updating (expected_version provided)
        if expected_version:
            write_update_status(f"Downloading v{expected_version} from GitHub...", expected_version)
        response = requests.get(download_url, timeout=30)
        response.raise_for_status()
        script_content = response.text
        
        # Verify the downloaded file's version if expected_version is provided
        # Only log version mismatch (debug info)
        if expected_version:
            version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', script_content)
            if version_match:
                downloaded_version = version_match.group(1)
                # Only log if versions don't match (debug info)
                if downloaded_version != expected_version:
                    write_update_status(f"DEBUG: Downloaded file version: {downloaded_version}, Expected: {expected_version}", downloaded_version)
                # The downloaded version should be >= the expected version
                if compare_versions(downloaded_version, expected_version) < 0:
                    write_update_status(f"Warning: Downloaded file version ({downloaded_version}) is older than expected ({expected_version})", downloaded_version)
                    # Don't fail, but warn the user
        
        return script_content
    except Exception as e:
        write_update_status(f"Error downloading script: {e}")
        print(f"Error downloading script: {e}")
        return None


def check_and_update_script(silent=False):
    """Check for updates and download if needed.
    
    Args:
        silent: If True, don't print messages (for background check)
    
    Returns:
        True if update was downloaded, False otherwise
    """
    local_version = get_local_version()
    latest_version, download_url, _ = get_latest_version()  # release_data not needed anymore
    
    if not latest_version:
        if not silent:
            print("Could not check for updates.")
        return False
    
    # If no local script, download it
    if not local_version:
        if not silent:
            print(f"Downloading script (v{latest_version})...")
        script_content = download_script(download_url, expected_version=latest_version)
        if script_content:
            SCRIPT_PATH.write_text(script_content, encoding='utf-8')
            write_update_status(f"Successfully updated to v{latest_version}!", latest_version)
            if not silent:
                print(f"Downloaded v{latest_version}")
            return True
        clear_update_status()
        return False
    
    # Compare versions
    if compare_versions(latest_version, local_version) > 0:
        if not silent:
            print(f"Update available: v{local_version} -> v{latest_version}")
        script_content = download_script(download_url, expected_version=latest_version)
        if script_content:
            # Create backup
            backup_path = SCRIPT_PATH.with_suffix('.py.backup')
            if SCRIPT_PATH.exists():
                import shutil
                shutil.copy2(SCRIPT_PATH, backup_path)
            
            # Write new version
            SCRIPT_PATH.write_text(script_content, encoding='utf-8')
            write_update_status(f"Successfully updated to v{latest_version}!", latest_version)
            if not silent:
                print(f"Updated to v{latest_version}")
            return True
        clear_update_status()
    elif not silent:
        print(f"Already up to date (v{local_version})")
        clear_update_status()
    
    return False


def run_script_directly():
    """Run the script directly in the current Python process (self-contained).
    
    This uses the embedded Python that's bundled with PyInstaller.
    """
    if not SCRIPT_PATH.exists():
        return False
    
    try:
        # Set environment variable to indicate launcher mode
        os.environ['BANDCAMP_LAUNCHER'] = '1'
        
        # Add ffmpeg to PATH if bundled
        ffmpeg_path = get_ffmpeg_path()
        if ffmpeg_path:
            current_path = os.environ.get('PATH', '')
            os.environ['PATH'] = f"{LAUNCHER_DIR};{current_path}"
        
        # Change to script directory so relative imports work
        original_cwd = os.getcwd()
        os.chdir(LAUNCHER_DIR)
        
        try:
            # Use runpy.run_path to execute the script properly
            # This handles __name__ == '__main__' blocks correctly
            runpy.run_path(str(SCRIPT_PATH), run_name='__main__')
            return True
        finally:
            # Restore original working directory
            os.chdir(original_cwd)
            
    except Exception as e:
        # If direct execution fails, show error
        try:
            import tkinter.messagebox as messagebox
            import traceback
            error_msg = f"Error launching script:\n{str(e)}\n\n{traceback.format_exc()}"
            messagebox.showerror("Launch Error", error_msg)
        except:
            import traceback
            print(f"Error launching script: {e}")
            traceback.print_exc()
        return False


def get_ffmpeg_path():
    """Get path to bundled ffmpeg.exe.
    
    If ffmpeg.exe is bundled, extract it from the bundle to the launcher directory.
    """
    ffmpeg_path = LAUNCHER_DIR / "ffmpeg.exe"
    
    # If ffmpeg.exe already exists in launcher directory, use it
    if ffmpeg_path.exists():
        return str(ffmpeg_path)
    
    # If running as PyInstaller bundle, try to extract from bundle
    if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
        bundled_ffmpeg = Path(sys._MEIPASS) / "ffmpeg.exe"
        if bundled_ffmpeg.exists():
            # Extract ffmpeg.exe from bundle to launcher directory
            import shutil
            try:
                shutil.copy2(bundled_ffmpeg, ffmpeg_path)
                return str(ffmpeg_path)
            except Exception as e:
                # If extraction fails, try to use from bundle location
                return str(bundled_ffmpeg)
    
    return None


def download_launcher_update(download_url, expected_version, expected_size=0):
    """Download new launcher.exe to temp location.
    
    Args:
        download_url: URL to download launcher.exe from
        expected_version: Expected version string
        expected_size: Expected file size from manifest (0 = don't verify)
    
    Returns:
        True if download successful, False otherwise
    """
    try:
        import requests
        write_update_status(f"Downloading launcher v{expected_version}...", expected_version)
        
        response = requests.get(download_url, timeout=60, stream=True)
        response.raise_for_status()
        
        # Download to temp location
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(LAUNCHER_UPDATE_TEMP, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        # Verify download (check against response header)
        if total_size > 0 and downloaded != total_size:
            write_update_status(f"Warning: Download size mismatch (expected {total_size}, got {downloaded})")
            return False
        
        # Verify against manifest size if provided
        if expected_size > 0:
            actual_size = LAUNCHER_UPDATE_TEMP.stat().st_size
            if actual_size != expected_size:
                write_update_status(f"Warning: File size mismatch (manifest: {expected_size}, actual: {actual_size})")
                # Don't fail, but warn - sizes might differ slightly
        
        # Verify it's actually an exe file (basic check)
        if LAUNCHER_UPDATE_TEMP.stat().st_size < 1000:  # Too small to be a real exe
            write_update_status("Error: Downloaded file appears to be invalid")
            LAUNCHER_UPDATE_TEMP.unlink(missing_ok=True)
            return False
        
        write_update_status(f"Launcher v{expected_version} downloaded successfully. Restart required.", expected_version)
        return True
    except Exception as e:
        write_update_status(f"Error downloading launcher update: {e}")
        LAUNCHER_UPDATE_TEMP.unlink(missing_ok=True)
        return False


def apply_launcher_update(show_dialog=True):
    """Apply downloaded launcher update by replacing old exe and relaunching.
    
    Uses Windows-safe approach: rename old exe first, then move new one, then launch new exe.
    
    Args:
        show_dialog: If True, show confirmation dialog. If False, proceed automatically.
    """
    if not LAUNCHER_UPDATE_TEMP.exists():
        return False
    
    if not LAUNCHER_EXE_PATH or not LAUNCHER_EXE_PATH.exists():
        return False
    
    try:
        # Show user feedback only if requested
        if show_dialog:
            try:
                import tkinter.messagebox as messagebox
                response = messagebox.askyesno(
                    "Apply Launcher Update",
                    "A launcher update is ready to be applied.\n\nThe application will close and restart automatically with the new version.\n\nProceed now?"
                )
                if not response:
                    write_update_status("Launcher update declined by user.")
                    return False
            except Exception:
                pass  # If GUI not available, continue automatically
        
        # Windows-safe approach: can't replace a file that's in use
        # Strategy: rename old exe, then move new one into place
        old_exe_backup = LAUNCHER_EXE_PATH.with_suffix('.exe.old')
        
        # Remove any existing .old file
        if old_exe_backup.exists():
            try:
                old_exe_backup.unlink()
            except Exception:
                pass  # Ignore if can't delete
        
        # Rename current exe to .old (this works even if file is in use on Windows)
        try:
            LAUNCHER_EXE_PATH.rename(old_exe_backup)
        except Exception as e:
            write_update_status(f"Error: Could not rename old exe: {e}")
            return False
        
        # Now move new exe into place (old one is renamed, so this should work)
        shutil.move(LAUNCHER_UPDATE_TEMP, LAUNCHER_EXE_PATH)
        
        # Make sure it's executable (Unix-like systems)
        try:
            os.chmod(LAUNCHER_EXE_PATH, 0o755)
        except:
            pass  # Windows doesn't need chmod
        
        # Clean up old exe and close application
        write_update_status("Launcher updated successfully. Closing application...")
        cleanup_old_exe_and_close(old_exe_backup)
        
        return True
    except Exception as e:
        write_update_status(f"Error applying launcher update: {e}")
        return False


def check_launcher_update(silent=False):
    """Check for launcher.exe updates.
    
    Args:
        silent: If True, don't show dialogs (for background check)
    
    Returns:
        True if update available and downloaded, False otherwise
    """
    if not hasattr(sys, 'frozen'):
        # Not running as exe, skip launcher update check
        return False
    
    try:
        current_version = get_launcher_version()
        latest_version, download_url, file_size = get_latest_launcher_version()
        
        if not latest_version or not download_url:
            if not silent:
                write_update_status(f"Could not check for launcher updates (version: {current_version})")
            return False
        
        # Debug: log version comparison
        if not silent:
            write_update_status(f"Checking launcher update: current={current_version}, latest={latest_version}")
        
        # Compare versions
        comparison = compare_versions(latest_version, current_version)
        if comparison > 0:
            # Update available
            if not silent:
                # Show update dialog
                show_launcher_update_dialog(current_version, latest_version, download_url, file_size)
            else:
                # Silent mode: just download
                return download_launcher_update(download_url, latest_version, file_size)
        elif not silent:
            write_update_status(f"Launcher is up to date (v{current_version})")
        
        return False
    except Exception as e:
        error_msg = f"Error checking for launcher updates: {e}"
        if not silent:
            write_update_status(error_msg)
        return False


def show_launcher_update_dialog(current_version, latest_version, download_url, file_size=0):
    """Show dialog for launcher update, download with progress, then prompt for restart."""
    try:
        import tkinter.messagebox as messagebox
        import tkinter as tk
        
        size_info = ""
        if file_size > 0:
            size_mb = file_size / (1024 * 1024)
            size_info = f"\nFile size: {size_mb:.1f} MB"
        
        # Step 1: Ask if user wants to update
        message = (
            f"A new launcher version is available!\n\n"
            f"Current version: v{current_version}\n"
            f"Latest version: v{latest_version}{size_info}\n\n"
            f"Would you like to download and install the update?\n\n"
            f"The application will close and restart automatically after the update."
        )
        
        response = messagebox.askyesno("Launcher Update Available", message)
        
        if not response:
            # User declined
            manual_response = messagebox.askyesno(
                "Manual Update",
                "Would you like to open the download page in your browser instead?"
            )
            if manual_response:
                import webbrowser
                webbrowser.open(download_url)
            return
        
        # Step 2: Download with progress feedback
        write_update_status(f"Downloading launcher v{latest_version}...", latest_version)
        
        # Show downloading dialog
        download_dialog = tk.Toplevel()
        download_dialog.title("Downloading Update")
        download_dialog.geometry("400x150")
        download_dialog.transient()
        download_dialog.grab_set()
        
        # Center the dialog
        download_dialog.update_idletasks()
        x = (download_dialog.winfo_screenwidth() // 2) - (download_dialog.winfo_width() // 2)
        y = (download_dialog.winfo_screenheight() // 2) - (download_dialog.winfo_height() // 2)
        download_dialog.geometry(f"+{x}+{y}")
        
        label = tk.Label(
            download_dialog,
            text=f"Downloading launcher v{latest_version}...\n\nPlease wait...",
            font=("Segoe UI", 10),
            justify=tk.CENTER
        )
        label.pack(pady=20)
        
        progress_label = tk.Label(
            download_dialog,
            text="",
            font=("Segoe UI", 9),
            fg="gray"
        )
        progress_label.pack()
        
        download_dialog.update()
        
        # Download in background thread to keep UI responsive
        def download_thread():
            try:
                success = download_launcher_update_with_progress(download_url, latest_version, file_size, progress_label, download_dialog)
                download_dialog.after(0, lambda: download_complete(success, latest_version))
            except Exception as e:
                download_dialog.after(0, lambda: download_complete(False, latest_version, str(e)))
        
        threading.Thread(target=download_thread, daemon=True).start()
        
        def download_complete(success, version, error_msg=None):
            download_dialog.destroy()
            
            if not success:
                if error_msg:
                    write_update_status(f"Download failed: {error_msg}")
                messagebox.showerror(
                    "Download Failed",
                    f"Failed to download launcher update.\n\n{error_msg or 'Please try again later or download manually.'}"
                )
                show_manual_update_instructions(download_url, latest_version)
                return
            
            # Step 3: Ask if ready to apply update
            restart_msg = (
                f"Launcher v{version} has been downloaded successfully!\n\n"
                f"The application will now close to apply the update.\n\n"
                f"Please relaunch the application after it closes to finish the update.\n\n"
                f"Ready to apply the update now?"
            )
            
            restart_response = messagebox.askyesno("Update Ready", restart_msg)
            
            if restart_response:
                # Apply update (will close app, user needs to manually restart)
                write_update_status("Applying update...")
                apply_launcher_update(show_dialog=False)
            else:
                write_update_status("Update will be applied on next launch.")
                messagebox.showinfo(
                    "Update Pending",
                    "The update will be applied automatically the next time you start the application."
                )
        
    except Exception as e:
        write_update_status(f"Error in update dialog: {e}")
        show_manual_update_instructions(download_url, latest_version)


def download_launcher_update_with_progress(download_url, expected_version, expected_size, progress_label, dialog):
    """Download launcher update with progress feedback.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        import requests
        
        response = requests.get(download_url, timeout=60, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(LAUNCHER_UPDATE_TEMP, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        size_mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        progress_text = f"{percent:.1f}% ({size_mb:.1f} MB / {total_mb:.1f} MB)"
                    else:
                        size_mb = downloaded / (1024 * 1024)
                        progress_text = f"{size_mb:.1f} MB downloaded"
                    
                    dialog.after(0, lambda t=progress_text: progress_label.config(text=t))
                    dialog.update()
        
        # Verify download
        if total_size > 0 and downloaded != total_size:
            write_update_status(f"Warning: Download size mismatch (expected {total_size}, got {downloaded})")
            return False
        
        # Verify file size
        if LAUNCHER_UPDATE_TEMP.stat().st_size < 1000:
            write_update_status("Error: Downloaded file appears to be invalid")
            LAUNCHER_UPDATE_TEMP.unlink(missing_ok=True)
            return False
        
        write_update_status(f"Launcher v{expected_version} downloaded successfully.", expected_version)
        return True
        
    except Exception as e:
        write_update_status(f"Error downloading launcher update: {e}")
        LAUNCHER_UPDATE_TEMP.unlink(missing_ok=True)
        return False


def show_manual_update_instructions(download_url, latest_version):
    """Show manual update instructions as fallback."""
    try:
        import tkinter.messagebox as messagebox
        import webbrowser
        
        message = (
            f"Automatic update is not available.\n\n"
            f"Please update manually:\n\n"
            f"1. Download the latest launcher (v{latest_version})\n"
            f"2. Close this application\n"
            f"3. Replace the old BandcampDownloader.exe with the new one\n\n"
            f"Would you like to open the download page now?"
        )
        
        response = messagebox.askyesno("Manual Update Required", message)
        if response:
            webbrowser.open(download_url)
    except Exception:
        pass


def launch_script():
    """Launch the main script directly in the current Python process (self-contained)."""
    if not SCRIPT_PATH.exists():
        # Show error in message box instead of console (since console is hidden)
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                "Error",
                f"{SCRIPT_NAME} not found!\n\nPlease ensure the script is downloaded."
            )
        except:
            pass
        return
    
    # Run the script directly in the current embedded Python process
    # This is truly self-contained - no external Python needed
    success = run_script_directly()
    
    # If script completes, exit launcher
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


def create_update_batch_script():
    """Create a batch script to apply launcher update after exe closes.
    
    Returns:
        True if script created, False otherwise
    """
    try:
        batch_script = LAUNCHER_DIR / "apply_update.bat"
        with open(batch_script, 'w') as f:
            f.write(f"""@echo off
timeout /t 2 /nobreak >nul
if exist "{LAUNCHER_UPDATE_TEMP}" (
    if exist "{LAUNCHER_EXE_PATH}" (
        del /f "{LAUNCHER_EXE_PATH}"
    )
    move "{LAUNCHER_UPDATE_TEMP}" "{LAUNCHER_EXE_PATH}"
    if exist "{LAUNCHER_EXE_PATH}" (
        start "" "{LAUNCHER_EXE_PATH}"
    )
)
if exist "{LAUNCHER_EXE_PATH.with_suffix('.exe.old')}" (
    del /f "{LAUNCHER_EXE_PATH.with_suffix('.exe.old')}"
)
del /f "%~f0"
""")
        return True
    except Exception:
        return False


def cleanup_old_exe_and_close(old_exe_path):
    """Clean up old exe file after update is applied and close the application.
    
    Creates a simple batch script to delete the old exe file after the process exits.
    User will need to manually restart the application.
    
    Args:
        old_exe_path: Path to the old exe file that should be deleted
    """
    try:
        # Create a simple batch script to clean up the old exe file
        batch_script = LAUNCHER_DIR / "cleanup_old_exe.bat"
        
        old_exe_escaped = str(old_exe_path)
        
        with open(batch_script, 'w') as f:
            f.write(f"""@echo off
REM Wait for the process to fully exit
timeout /t 3 /nobreak >nul

REM Try to delete old exe file
if exist "{old_exe_escaped}" (
    del /f /q "{old_exe_escaped}" 2>nul
    REM If still exists, try renaming and deleting
    if exist "{old_exe_escaped}" (
        timeout /t 1 /nobreak >nul
        ren "{old_exe_escaped}" "{old_exe_escaped}.delete" 2>nul
        if exist "{old_exe_escaped}.delete" (
            del /f /q "{old_exe_escaped}.delete" 2>nul
        )
    )
)

REM Clean up this batch script
timeout /t 2 /nobreak >nul
del /f /q "%~f0" 2>nul
""")
        
        # Launch the batch script (detached, so it continues after we exit)
        # Use a VBScript wrapper to hide the command window
        if sys.platform == 'win32':
            # Create a VBScript to run the batch file hidden
            vbscript = LAUNCHER_DIR / "cleanup_old_exe.vbs"
            with open(vbscript, 'w') as f:
                f.write(f"""Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "{batch_script}" & chr(34), 0, False
Set WshShell = Nothing
""")
            
            # Launch the VBScript (which will run the batch file hidden)
            subprocess.Popen(
                ['wscript.exe', str(vbscript)],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
            
            # Clean up VBScript after a delay
            def cleanup_vbs():
                time.sleep(10)
                try:
                    if vbscript.exists():
                        vbscript.unlink()
                except:
                    pass
            
            threading.Thread(target=cleanup_vbs, daemon=True).start()
        
        write_update_status("Update applied. Closing application...")
        
        # Force close GUI window if possible (no dialog, just close)
        try:
            import tkinter as tk
            root = tk._default_root
            if root:
                root.quit()
                root.destroy()
        except Exception:
            pass
        
        # Small delay to let GUI close
        time.sleep(0.5)
        
        # Exit current process
        os._exit(0)
        
    except Exception as e:
        write_update_status(f"Error during update: {e}")
        # Still try to exit
        try:
            os._exit(0)
        except:
            sys.exit(0)


def cleanup_old_exe():
    """Clean up old exe file from previous update.
    
    Returns:
        True if an old exe was found and cleaned up (indicating we just updated)
    """
    try:
        old_exe = LAUNCHER_EXE_PATH.with_suffix('.exe.old')
        if old_exe.exists():
            old_exe.unlink()
            return True  # Indicates we just updated
    except Exception:
        pass  # Ignore cleanup errors
    return False


def main():
    """Main launcher entry point."""
    # Clean up old exe from previous update (if any)
    was_updated = cleanup_old_exe()
    
    # Check for pending launcher update first (from previous session)
    if hasattr(sys, 'frozen') and LAUNCHER_UPDATE_TEMP.exists() and LAUNCHER_EXE_PATH:
        try:
            if apply_launcher_update(show_dialog=False):
                # apply_launcher_update() will handle launching the new exe and exiting
                # If we reach here, something went wrong
                write_update_status("Launcher update applied, but failed to launch new version. Please restart manually.")
        except Exception as e:
            write_update_status(f"Error applying launcher update: {e}")
            # Continue with old version
    
    # Show update complete message if we just updated
    # Use after() to show message after GUI is fully initialized (non-blocking)
    if was_updated:
        def show_update_complete():
            try:
                # Wait for GUI to be ready - use a small delay
                time.sleep(0.5)
                import tkinter.messagebox as messagebox
                messagebox.showinfo(
                    "Update Complete",
                    "Launcher has been successfully updated!\n\nThe application is now running the latest version."
                )
            except Exception:
                pass
        
        # Show message in background thread to avoid blocking startup
        threading.Thread(target=show_update_complete, daemon=True).start()
    
    # Extract bundled files to launcher directory if needed (defer to background for faster startup)
    def extract_bundled_files():
        """Extract bundled files in background to avoid blocking startup."""
        if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
            bundle_dir = Path(sys._MEIPASS)
            
            # Extract ffmpeg.exe from bundle if it doesn't exist
            ffmpeg_path = LAUNCHER_DIR / "ffmpeg.exe"
            if not ffmpeg_path.exists():
                bundled_ffmpeg = bundle_dir / "ffmpeg.exe"
                if bundled_ffmpeg.exists():
                    try:
                        shutil.copy2(bundled_ffmpeg, ffmpeg_path)
                    except Exception:
                        pass
            
            # Extract icon.ico from bundle if it doesn't exist
            icon_path = LAUNCHER_DIR / "icon.ico"
            if not icon_path.exists():
                bundled_icon = bundle_dir / "icon.ico"
                if bundled_icon.exists():
                    try:
                        shutil.copy2(bundled_icon, icon_path)
                    except Exception:
                        pass
    
    # Extract files in background thread (non-blocking)
    extraction_thread = threading.Thread(target=extract_bundled_files, daemon=True)
    extraction_thread.start()
    
    # If script doesn't exist, extract immediately (required for app to run)
    if not SCRIPT_PATH.exists() and BUNDLED_SCRIPT and BUNDLED_SCRIPT.exists():
        try:
            shutil.copy2(BUNDLED_SCRIPT, SCRIPT_PATH)
        except Exception:
            pass
    
    # Launch the script immediately (using bundled version if available)
    # Check for updates in background AFTER launching (non-blocking, delayed to not affect startup)
    def check_updates_background():
        # Delay to let app start first (non-blocking, doesn't affect startup performance)
        time.sleep(3)  # Increased delay to ensure app is fully loaded before checking
        # Check for script updates silently
        check_and_update_script(silent=True)
        # Check for launcher updates (show dialog if update available)
        # Use silent=False to show dialog when update is found
        check_launcher_update(silent=False)
        # If updates were downloaded, they will be used on next launch
    
    # Start update check in background (non-blocking, doesn't affect startup)
    update_thread = threading.Thread(target=check_updates_background, daemon=True)
    update_thread.start()
    
    # Also copy icon.ico from parent if it doesn't exist (for development)
    icon_path = LAUNCHER_DIR / "icon.ico"
    if not icon_path.exists():
        parent_icon = LAUNCHER_DIR.parent / "icon.ico"
        if parent_icon.exists():
            try:
                shutil.copy2(parent_icon, icon_path)
            except Exception:
                pass
    
    # Launch the script immediately (uses embedded Python - truly self-contained)
    launch_script()


if __name__ == "__main__":
    main()

