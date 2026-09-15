from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
MAX_CHANNELS = 1000  # Standard 1000 channels limit
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

# Additional channels jo sab ton pehla (top te) aunge
ADDITIONAL_CHANNELS = ["Star Sports", "PTC Music", "Disney"]

counter_lock = threading.Lock()
processed_count = 0

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def process_single_channel(i, lines, session):
    line = lines[i].strip()
    extinf_line = line

    channel_lines = [extinf_line]
    user_agent = "Denver 1760"  # Sabhi channels te Denver user-agent fix hai
    key_url = None
    license_type = "clearkey"
    ext_http_line = None
    mpd_line = None
    raw_stream_line = ""

    # Scan upcoming lines for configuration options
    for f in range(i + 1, min(len(lines), i + 8)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTINF") or sub_f.startswith("#EXTM3U"):
            break
        
        if "inputstream.adaptive.license_key=" in sub_f:
            key_url = sub_f.split("inputstream.adaptive.license_key=")[1].strip()
        if "inputstream.adaptive.license_type=" in sub_f:
            license_type = sub_f.split("inputstream.adaptive.license_type=")[1].strip()
        if sub_f.startswith("#EXTHTTP:"):
            ext_http_line = sub_f
        if sub_f.startswith("http") and (".mpd" in sub_f or ".m3u8" in sub_f):
            mpd_line = sub_f
        elif sub_f.startswith("http") and not raw_stream_line:
            raw_stream_line = sub_f.split()[0]

    # Check for license key in preceding lines if not found below
    if not key_url:
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    try:
        # 1. Clear Key URL nu redirect karwa ke final link / JSON fetch karna
        resolved_key_url = key_url
        if key_url:
            if '"' in key_url:
                key_url = key_url.replace('"', "")
            try:
                k_res = session.get(key_url, headers={"User-Agent": user_agent}, allow_redirects=True, timeout=4)
                if k_res.status_code == 200:
                    try:
                        key_json = k_res.json()
                        resolved_key_url = json.dumps(key_json)
                    except Exception:
                        # Je redirect hoke nawa URL bnya hai taan ohi chak lao
                        if k_res.url and k_res.url != key_url:
                            resolved_key_url = k_res.url
                        elif k_res.text and not k_res.text.strip().startswith("<"):
                            resolved_key_url = k_res.text.strip()
                elif k_res.url:
                    resolved_key_url = k_res.url
            except Exception:
                pass

        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_type={license_type}")
        if resolved_key_url:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={resolved_key_url}")

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

        if ext_http_line:
            channel_lines.append(ext_http_line)

        # 2. Stream URL (MPD / m3u8) nu allow_redirects=True karke resolve karna
        url_added = False
        target_url = mpd_line if mpd_line else raw_stream_line

        if target_url:
            if target_url.endswith("~"):
                target_url = target_url[:-1]
            
            try:
                channel_headers = {"User-Agent": user_agent}
                r = session.get(target_url, headers=channel_headers, allow_redirects=True, timeout=4)

                if r.status_code == 200:
                    # Check if response body has the direct stream link
                    final_text = r.text.strip()
                    if final_text.startswith("http") and not final_text.startswith("<") and len(final_text) < 500:
                        channel_lines.append(final_text.split()[0])
                        url_added = True
                    elif r.url and r.url != target_url:
                        channel_lines.append(r.url.split()[0])
                        url_added = True
                    else:
                        channel_lines.append(target_url)
                        url_added = True
                else:
                    if r.url:
                        channel_lines.append(r.url.split()[0])
                        url_added = True
                    elif raw_stream_line:
                        channel_lines.append(raw_stream_line)
                        url_added = True
                    else:
                        channel_lines.append(target_url)
                        url_added = True
            except Exception:
                channel_lines.append(target_url)
                url_added = True

        if not url_added:
            channel_lines.append("http://dummy-link-to-prevent-break")

    except Exception:
        if raw_stream_line:
            channel_lines.append(raw_stream_line)
        else:
            channel_lines.append("http://dummy-link-to-prevent-break")

    return channel_lines

def generate_safe_playlist_ordered():
    global processed_count
    processed_count = 0
    print(f"[*] Downloading playlist and processing additional channels first, followed by up to {MAX_CHANNELS} channels...")
    session = get_robust_session()
    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "Denver 1760"})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        # 1. Additional Channels labho taaki oh top te rakhe ja sakan
        additional_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                for add_ch in ADDITIONAL_CHANNELS:
                    if add_ch.lower() in line.lower():
                        if i not in additional_indices:
                            additional_indices.append(i)

        # 2. Baaki standard 1000 channels labho
        standard_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                standard_indices.append(i)
                if len(standard_indices) >= MAX_CHANNELS:
                    break

        # 3. Combine: Additional pehla, te standard channels us ton baad (duplication avoid karke)
        target_indices = []
        for idx in additional_indices:
            if idx not in target_indices:
                target_indices.append(idx)

        for idx in standard_indices:
            if idx not in target_indices:
                target_indices.append(idx)

        if not target_indices:  
            print("[-] No channels found in playlist.")  
            return  

        print(f"[*] Total combined channels: {len(target_indices)}. Processing with multithreading...\n")  

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_single_channel, idx, lines, session): idx
                for idx in target_indices
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    channel_results[idx] = future.result()
                except Exception:
                    fallback_lines = [lines[idx].strip(), "http://dummy-link-to-prevent-break"]
                    channel_results[idx] = fallback_lines

                with counter_lock:
                    processed_count += 1
                    print(f"[*] Progress: {processed_count}/{len(target_indices)} channels processed...", end="\r")

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])
            else:
                new_lines.append(lines[idx].strip())
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n\n[+] Success! {len(target_indices)} channels saved as '{output_file}' with forced redirects.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_ordered()
        
