import os
import subprocess
import time
import glob

def run_ascii_slideshow(art_directory="~/OKX-Terminal/ascii_art", interval=15):
    """
    Loops through ASCII art files in the target directory and displays them
    using the terminal 'cat' command in a slideshow format.
    """
    # Expand the tilde (~object) to the absolute path on Termux/Linux
    expanded_dir = os.path.expanduser(art_directory)

    # Grab all files inside the target directory
    search_pattern = os.path.join(expanded_dir, "*.txt")
    art_files = sorted([f for f in glob.glob(search_pattern) if os.path.isfile(f)])

    if not art_files:
        print(f"No ASCII art files found in: '{expanded_dir}'")
        return

    print(f"Loaded {len(art_files)} files. Starting slideshow (Interval: {interval}s)...")
    time.sleep(2)

    try:
        while True:
            for file_path in art_files:
                # Clear the terminal screen for a clean frame transition
                os.system('clear')

                # Use the terminal 'cat' command to output the file contents
                try:
                    subprocess.run(['cat', file_path], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error executing 'cat' on {file_path}: {e}")

                # Wait for the 15-second interval before the next slide
                time.sleep(interval)

    except KeyboardInterrupt:
        print("\nSlideshow terminated.")

if __name__ == "__main__":
    ART_FOLDER = "~/OKX-Terminal/ascii_art"
    run_ascii_slideshow(art_directory=ART_FOLDER, interval=15)

