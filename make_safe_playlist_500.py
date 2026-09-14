from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}
MAX_CHANNELS = 1000
MAX_WORKERS = 100

def get_robust_session():
    """Creates a thread-safe requests session."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def process_channel_block(channel_data):
    """Processes a single channel block concurrently without timeouts."""
    i, lines = channel_data
    extinf_line = lines[i].strip()

    # Extract Key URL / Base string
    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip().replace('"', "")

    # Extract User-Agent and MPD URL
    user_agent = "Denver1769"
    mpd_line = None
    for f in range(i + 1, min(len(lines), i + 4)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
            user_agent = sub_f.split("=", 1)[1].strip()
        elif sub_f.startswith("http") and ".mpd" in sub_f:
            mpd_line = sub_f

    thread_session = get_robust_session()
    json_license_key = None

    if key_url:
        if key_url.startswith("http"):
            try:
                # Timeout removed here
                key_res = thread_session.get(key_url, headers=HEADERS)
                if key_res.status_code == 200:
                    key_data = key_res.json()
                    json_license_key = json.dumps(key_data)
            except Exception:
                pass
        else:
            json_license_key = key_url

    # Build M3U directives using ClearKey JSON format
    channel_lines = ["#KODIPROP:inputstream.adaptive.license_type=clearkey"]
    
    if json_license_key:
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={json_license_key}")
    elif key_url:
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

    channel_lines.append(extinf_line)
    channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

    # Process redirect resolution for MPD URL
    if mpd_line:
        clean_url = mpd_line.strip().split()[0].rstrip("~")
        try:
            channel_headers = {"User-Agent": user_agent}
            # Timeout removed here
            r = thread_session.head(
                mpd_line, headers=channel_headers, allow_redirects=False
            )
            if r.status_code in [301, 302, 303, 307, 308] and "Location" in r.headers:
                clean_url = r.headers["Location"].strip().split()[0].rstrip("~")
        except Exception:
            pass
            
        channel_lines.append(clean_url)

    thread_session.close()
    return i, channel_lines

def generate_safe_playlist():
    print(f"[*] Downloading playlist: {PLAYLIST_URL}")
    main_session = get_robust_session()
    
    try:
        # Timeout removed here
        res = main_session.get(PLAYLIST_URL, headers=HEADERS)
        if res.status_code != 200:
            print(f"[-] Failed to fetch playlist. HTTP Status: {res.status_code}")
            return

        lines = res.text.splitlines()

        target_indices = [
            i for i, line in enumerate(lines) 
            if line.strip().startswith("#EXTINF")
        ][:MAX_CHANNELS]

        if not target_indices:
            print("[-] No channels found in playlist.")
            return

        print(f"[*] Found {len(target_indices)} channels. Processing with {MAX_WORKERS} max workers...")

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_channel_block, (idx, lines)): idx 
                for idx in target_indices
            }
            for future in as_completed(futures):
                try:
                    idx, channel_lines = future.result()
                    channel_results[idx] = channel_lines
                except Exception as e:
                    print(f"[-] Error processing channel block: {e}")

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])

        output_file = "safe_500_channels.m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"\n[+] Success! Exactly {len(channel_results)} channels saved as '{output_file}'.")

    except Exception as e:
        print(f"[-] Critical Error: {e}")
    finally:
        main_session.close()

if __name__ == "__main__":
    generate_safe_playlist()
  pehla batch 500 tak pher 1 minute baad 501 toh 1000 tak pher 1 minute baad 1001 toh 1500 te end te merged . m3u name di playlist aave
