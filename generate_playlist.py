import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"

# ਬ੍ਰਾਊਜ਼ਰ ਵਾਲੇ ਸਹੀ ਹੈਡਰਜ਼ ਜੋ 403/404 ਐਰਰ ਤੋਂ ਬਚਾਉਣਗੇ
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://game.playindia.fun/",
    "Accept": "*/*"
}

def process_single_channel(channel_info):
    i, lines = channel_info
    extinf_line = lines[i]

    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()
            if '"' in key_url:
                key_url = key_url.replace('"', "")

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
            key_res = requests.get(key_url, headers=HEADERS, timeout=8)
            if key_res.status_code == 200:
                key_json = key_res.json()
                embedded_key_data = json.dumps(key_json)
        except:
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
        clean_url = mpd_line.strip().split()[0]
        final_url = clean_url
        
        # ਹਰ ਲਿੰਕ ਨੂੰ ਰੀਡਾਇਰੈਕਟ ਕਰਵਾ ਕੇ ਅਸਲੀ (Final) URL ਪ੍ਰਾਪਤ ਕਰਨਾ
        try:
            response = requests.get(clean_url, headers=HEADERS, allow_redirects=True, timeout=8)
            if response.url:
                final_url = response.url.strip().split()[0]
        except:
            pass
        
        if final_url.endswith("~"):
            final_url = final_url[:-1]
        channel_lines.append(final_url)

    return i, channel_lines

def main():
    print("[*] Downloading playlist and fully resolving all links to actual URLs...")
    try:
        res = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=20)
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()
        channel_indices = []

        i = 0
        while i < len(lines):
            if lines[i].strip().startswith("#EXTINF"):
                channel_indices.append((i, lines))
            i += 1

        total_channels = len(channel_indices)
        print(f"[*] Found {total_channels} channels. Resolving all redirects...")

        results = {}
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(process_single_channel, ch): ch for ch in channel_indices}
            for future in as_completed(futures):
                res_tuple = future.result()
                if res_tuple:
                    idx, res_lines = res_tuple
                    results[idx] = res_lines

        new_lines = ["#EXTM3U"]
        for idx in sorted(results.keys()):
            new_lines.extend(results[idx])

        output_file = "all_channels_fully_resolved.m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"[+] Success! All channels fully resolved and saved to {output_file}")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    main()
                
