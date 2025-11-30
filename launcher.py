"""
Bandcamp Downloader - Launcher
Self-contained launcher that bundles Python, ffmpeg, and auto-updates the main script.
"""

# Launcher version (update this when releasing a new launcher.exe)
__version__ = "1.2.7"

import sys
import os
import threading
import time
import runpy
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
    
    # Fallback: return embedded version
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


def apply_launcher_update():
    """Apply downloaded launcher update by replacing old exe.
    
    This should be called on next launch, not during current session.
    """
    if not LAUNCHER_UPDATE_TEMP.exists():
        return False
    
    if not LAUNCHER_EXE_PATH or not LAUNCHER_EXE_PATH.exists():
        return False
    
    try:
        # Create backup
        backup_path = LAUNCHER_EXE_PATH.with_suffix('.exe.backup')
        if LAUNCHER_EXE_PATH.exists():
            shutil.copy2(LAUNCHER_EXE_PATH, backup_path)
        
        # Replace old exe with new one
        shutil.move(LAUNCHER_UPDATE_TEMP, LAUNCHER_EXE_PATH)
        
        # Make sure it's executable (Unix-like systems)
        try:
            os.chmod(LAUNCHER_EXE_PATH, 0o755)
        except:
            pass  # Windows doesn't need chmod
        
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
            return False
        
        # Compare versions
        if compare_versions(latest_version, current_version) > 0:
            if not silent:
                # Show update dialog
                show_launcher_update_dialog(current_version, latest_version, download_url, file_size)
            else:
                # Silent mode: just download
                return download_launcher_update(download_url, latest_version, file_size)
        elif not silent:
            print(f"Launcher is up to date (v{current_version})")
        
        return False
    except Exception as e:
        if not silent:
            print(f"Error checking for launcher updates: {e}")
        return False


def show_launcher_update_dialog(current_version, latest_version, download_url, file_size=0):
    """Show dialog for launcher update with options."""
    try:
        import tkinter.messagebox as messagebox
        
        size_info = ""
        if file_size > 0:
            size_mb = file_size / (1024 * 1024)
            size_info = f"\nFile size: {size_mb:.1f} MB"
        
        message = (
            f"A new launcher version is available!\n\n"
            f"Current version: v{current_version}\n"
            f"Latest version: v{latest_version}{size_info}\n\n"
            f"Would you like to download and install the update?\n\n"
            f"Note: The app will need to restart to apply the update.\n"
            f"If automatic update fails, you can download manually."
        )
        
        response = messagebox.askyesno("Launcher Update Available", message)
        
        if response:
            # Try automatic update
            if download_launcher_update(download_url, latest_version, file_size):
                # Show restart prompt
                restart_msg = (
                    f"Launcher v{latest_version} has been downloaded.\n\n"
                    f"Please close this application and restart it to apply the update.\n\n"
                    f"The update will be applied automatically on next launch."
                )
                messagebox.showinfo("Update Ready", restart_msg)
            else:
                # Automatic update failed, show manual instructions
                show_manual_update_instructions(download_url, latest_version)
        else:
            # User declined, offer manual download option
            manual_response = messagebox.askyesno(
                "Manual Update",
                "Would you like to open the download page in your browser instead?"
            )
            if manual_response:
                import webbrowser
                # Use the download URL (should have dl=1 for direct download)
                webbrowser.open(download_url)
    except Exception as e:
        # Fallback: show manual instructions
        show_manual_update_instructions(download_url, latest_version)


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


def main():
    """Main launcher entry point."""
    # Check for pending launcher update first (from previous session)
    if hasattr(sys, 'frozen') and LAUNCHER_UPDATE_TEMP.exists() and LAUNCHER_EXE_PATH:
        try:
            if apply_launcher_update():
                write_update_status("Launcher updated successfully! Restarting...")
                # Restart with new exe
                try:
                    os.execv(str(LAUNCHER_EXE_PATH), sys.argv)
                except Exception:
                    # If execv fails (Windows), just continue with old version
                    pass
        except Exception as e:
            write_update_status(f"Error applying launcher update: {e}")
            # Continue with old version
    
    # Extract bundled files to launcher directory if needed
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
    
    # If script doesn't exist, try to extract from bundled version first
    if not SCRIPT_PATH.exists() and BUNDLED_SCRIPT and BUNDLED_SCRIPT.exists():
        try:
            shutil.copy2(BUNDLED_SCRIPT, SCRIPT_PATH)
        except Exception:
            pass
    
    # Launch the script immediately (using bundled version if available)
    # Check for updates in background AFTER launching (non-blocking)
    def check_updates_background():
        # Small delay to let app start first
        time.sleep(2)
        # Check for script updates silently
        check_and_update_script(silent=True)
        # Check for launcher updates silently (won't show dialog, just download)
        check_launcher_update(silent=True)
        # If updates were downloaded, they will be used on next launch
    
    # Start update check in background (non-blocking)
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

