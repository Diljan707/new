import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}

key_cache = {}
cache_lock = Lock()

def get_cached_key(key_url):
    if not key_url:
        return None
    if '"' in key_url:
        key_url = key_url.replace('"', "")
        
    with cache_lock:
        if key_url in key_cache:
            return key_cache[key_url]

    embedded_key_data = None
    for _ in range(2):
        try:
            key_res = requests.get(key_url, headers=HEADERS, timeout=6)
            if key_res.status_code == 200:
                embedded_key_data = json.dumps(key_res.json())
                break
        except:
            pass
            
    with cache_lock:
        key_cache[key_url] = embedded_key_data
        
    return embedded_key_data

def process_channel(channel_info):
    extinf_line, key_url, user_agent, mpd_line = channel_info
    embedded_key_data = get_cached_key(key_url)

    final_mpd = mpd_line
    if mpd_line:
        try:
            r = requests.get(mpd_line, headers=HEADERS, allow_redirects=False, timeout=5)
            if r.status_code in [301, 302, 303, 307, 308]:
                final_mpd = r.headers.get('Location', mpd_line)
        except:
            pass
        
        final_mpd = final_mpd.strip().split()[0]
        if final_mpd.endswith("~"):
            final_mpd = final_mpd[:-1]

    lines_to_add = []
    lines_to_add.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
    if embedded_key_data:
        lines_to_add.append(f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}")
    elif key_url:
        lines_to_add.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

    lines_to_add.append(extinf_line)
    lines_to_add.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
    if final_mpd:
        lines_to_add.append(final_mpd)
        
    return lines_to_add

def main():
    print("[*] Downloading base playlist...")
    res = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=30)
    if res.status_code != 200:
        print("[-] Failed to fetch base playlist.")
        return

    lines = res.text.splitlines()
    channels_to_process = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
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

            channels_to_process.append((extinf_line, key_url, user_agent, mpd_line))
        i += 1

    total_channels = len(channels_to_process)
    print(f"[*] Processing {total_channels} channels with 150 Workers...")
    
    new_lines = ["#EXTM3U"]
    completed = 0
    
    with ThreadPoolExecutor(max_workers=150) as executor:
        futures = {executor.submit(process_channel, ch): ch for ch in channels_to_process}
        
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            if result:
                new_lines.extend(result)

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines))

    print("[+] Playlist generated successfully!")

if __name__ == "__main__":
    main()
