import requests
import shutil
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}
MAX_CHANNELS = 1700  # Total 1700 channels
MAX_WORKERS = 1700   # Saare 1700 channels ikko vaari parallel run honge!

def process_channel_block(channel_data):
    """Processes a single channel block concurrently."""
    i, lines = channel_data
    line = lines[i].strip()
    
    extinf_line = line
    
    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    user_agent = "Denver1769"
    mpd_line = None
    for f in range(i + 1, min(len(lines), i + 4)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
            user_agent = sub_f.split("=")[1].strip()
        if sub_f.startswith("http") and ".mpd" in sub_f:
            mpd_line = sub_f

    embedded_key_data = None
    if key_url:
        try:
            if '"' in key_url:
                key_url = key_url.replace('"', "")
            key_res = requests.get(key_url, headers=HEADERS, timeout=10)
            if key_res.status_code == 200:
                key_json = key_res.json()
                embedded_key_data = json.dumps(key_json)
        except Exception as e:
            pass

    channel_lines = []
    channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
    if embedded_key_data:
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}")
    elif key_url:
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

    channel_lines.append(extinf_line)
    channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

    if mpd_line:
        try:
            r = requests.get(mpd_line, headers=HEADERS, allow_redirects=False, timeout=10)
            real_url = r.headers.get('Location') if r.status_code in [301, 302, 303, 307, 308] else mpd_line
            clean_url = real_url.strip().split()[0]
            if clean_url.endswith("~"):
                clean_url = clean_url[:-1]
            channel_lines.append(clean_url)
        except:
            clean_url = mpd_line.strip().split()[0]
            if clean_url.endswith("~"):
                clean_url = clean_url[:-1]
            channel_lines.append(clean_url)

    return i, channel_lines

def generate_safe_playlist_1700():
    print(f"[*] Downloading playlist and processing all {MAX_CHANNELS} channels with {MAX_WORKERS} workers simultaneously...")
    try:
        res = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=20)
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()
        
        target_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                target_indices.append(i)
                if len(target_indices) >= MAX_CHANNELS:
                    break

        if not target_indices:
            print("[-] No channels found in playlist.")
            return

        print(f"[*] Found {len(target_indices)} channels. Launching 1700 parallel threads...")

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_channel_block, (idx, lines)): idx for idx in target_indices}
            for future in as_completed(futures):
                try:
                    idx, channel_lines = future.result()
                    channel_results[idx] = channel_lines
                except Exception as e:
                    print(f"[-] Error processing a channel: {e}")

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])

        output_file = "safe_1700_channels.m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"\n[+] Success! Exactly {len(channel_results)} channels saved as '{output_file}'.")
        
        # Safe copy block for GitHub vs Termux/Android
        download_dir = "/storage/emulated/0/Download"
        if os.path.exists(download_dir):
            shutil.copy(output_file, f"{download_dir}/{output_file}")
            print("[+] Copied safely to Android Download folder!")
        else:
            print("[+] Running on GitHub Actions cloud. File saved locally in workspace repository.")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1700()
                                          
