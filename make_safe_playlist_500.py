from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"

# Browser/LG webTV user-agent setup
HEADERS = {
    "User-Agent": "Mozilla/5.0 (WebOS; Linux; LG TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36"
}

MAX_WORKERS = 100
BATCH_SIZE = 500  # Number of channels to process per batch
TOTAL_CHANNELS_TO_PROCESS = 1500  # Total channels you want to cover across batches

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

session = get_robust_session()

def process_channel_block(channel_data):
    """Processes a single channel block concurrently without timeouts."""
    i, lines = channel_data
    line = lines[i].strip()
    extinf_line = line

    key_url = None
    for b in range(max(0, i - 3), i):
        sub_b = lines[b].strip()
        if "inputstream.adaptive.license_key=" in sub_b:
            key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    user_agent = HEADERS["User-Agent"]
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
            key_res = session.get(key_url, headers=HEADERS)
            if key_res.status_code == 200:
                key_json = key_res.json()
                embedded_key_data = json.dumps(key_json)
        except Exception:
            pass

    channel_lines = []
    channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
    if embedded_key_data:
        channel_lines.append(
            f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}"
        )
    elif key_url:
        channel_lines.append(
            f"#KODIPROP:inputstream.adaptive.license_key={key_url}"
        )

    channel_lines.append(extinf_line)
    channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

    if mpd_line:
        try:
            channel_headers = {"User-Agent": user_agent}
            r = session.get(
                mpd_line, headers=channel_headers, allow_redirects=False
            )

            real_url = (  
                r.headers.get("Location")  
                if r.status_code in [301, 302, 303, 307, 308]  
                else mpd_line  
            )  
            clean_url = real_url.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            channel_lines.append(clean_url)  
        except Exception:  
            clean_url = mpd_line.strip().split()[0]  
            if clean_url.endswith("~"):  
                clean_url = clean_url[:-1]  
            channel_lines.append(clean_url)

    return i, channel_lines

def generate_batched_playlists():
    print("[*] Downloading target playlist...")
    try:
        res = session.get(PLAYLIST_URL, headers=HEADERS)
        if res.status_code != 200:
            print(f"[-] Failed to fetch playlist. Status code: {res.status_code}")
            return

        lines = res.text.splitlines()  

        # Find all #EXTINF indices in the entire playlist
        all_target_indices = []  
        for i, line in enumerate(lines):  
            if line.strip().startswith("#EXTINF"):  
                all_target_indices.append(i)  

        if not all_target_indices:  
            print("[-] No channels found in playlist.")  
            return  

        print(f"[*] Total channels available in playlist: {len(all_target_indices)}")

        created_batch_files = []
        
        # Process in chunks (Batches of BATCH_SIZE)
        start_idx = 0
        while start_idx < len(all_target_indices) and start_idx < TOTAL_CHANNELS_TO_PROCESS:
            end_idx = min(start_idx + BATCH_SIZE, len(all_target_indices), TOTAL_CHANNELS_TO_PROCESS)
            batch_indices = all_target_indices[start_idx:end_idx]
            
            batch_num_start = start_idx + 1
            batch_num_end = end_idx
            
            print(f"\n--- Processing Batch: Channels {batch_num_start} to {batch_num_end} ---")
            
            channel_results = {}  
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:  
                futures = {  
                    executor.submit(process_channel_block, (idx, lines)): idx  
                    for idx in batch_indices  
                }  
                for future in as_completed(futures):  
                    try:  
                        idx, channel_lines = future.result()  
                        channel_results[idx] = channel_lines  
                    except Exception as e:  
                        print(f"[-] Error processing a channel in batch: {e}")  

            new_lines = ["#EXTM3U"]  
            for idx in batch_indices:  
                if idx in channel_results:  
                    new_lines.extend(channel_results[idx])  

            output_file = f"channels_batch_{batch_num_start}_{batch_num_end}.m3u"  
            with open(output_file, "w", encoding="utf-8") as f:  
                f.write("\n".join(new_lines))  

            print(f"[+] Batch saved successfully as '{output_file}' ({len(channel_results)} channels processed).")
            
            created_batch_files.append(output_file)
            start_idx = end_idx

        # Merge all created batch files into a single master playlist
        if created_batch_files:
            print("\n[*] Merging all batch files into a single master playlist...")
            master_output_file = "all_channels_master.m3u"
            master_lines = ["#EXTM3U"]
            
            for file_name in created_batch_files:
                with open(file_name, "r", encoding="utf-8") as bf:
                    content = bf.read().splitlines()
                    for line in content:
                        # Skip extra #EXTM3U headers from individual batch files
                        if line.strip() != "#EXTM3U":
                            master_lines.append(line)
                            
            with open(master_output_file, "w", encoding="utf-8") as mf:
                mf.write("\n".join(master_lines))
                
            print(f"[+] Success! All batches merged into '{master_output_file}'.")

        print("\n[+] All requested batches processed and merged successfully!")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_batched_playlists()
    
