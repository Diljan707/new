from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import os
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL")
IP_MANAGER_URL = "https://game.playindia.fun/Jtv/IP.php?id=qwerty"
LCN_LIST_URL = (
    "https://raw.githubusercontent.com/Diljan707/"
    "Automated-/refs/heads/main/dishtv_lcn_list.txt"
)

MAX_CHANNELS = 2000
MAX_WORKERS = 40

def get_channel_unique_key(extinf_line):
    tvg_id = ""
    if 'tvg-id="' in extinf_line:
        try:
            tvg_id = extinf_line.split('tvg-id="')[1].split('"')[0].lower().strip()
        except Exception:
            pass
    
    title = ""
    if "," in extinf_line:
        _, title = extinf_line.split(",", 1)
    
    clean_t = re.sub(r'\s*\(\d+\)\s*', '', title).lower().strip()
    cleaned_title = re.sub(r'\bdigital\b', '', clean_t, flags=re.IGNORECASE)
    if "star sports" not in cleaned_title:
        cleaned_title = re.sub(r'\bhindi\b', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = " ".join(cleaned_title.split())
    
    if tvg_id:
        return f"{tvg_id}_{cleaned_title}"
    return cleaned_title

def load_old_playlist_cache():
    old_cache = {}
    output_file = ".m3u"
    if not os.path.exists(output_file):
        return old_cache
    
    print("[*] Loading old .m3u cache for fallback tokens...")
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("#EXTINF"):
                    extinf_line = line
                    channel_lines = [extinf_line]
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("#EXTINF") and not lines[i].strip().startswith("#EXTM3U"):
                        channel_lines.append(lines[i].strip())
                        i += 1
                    
                    cache_key = get_channel_unique_key(extinf_line)
                    if cache_key:
                        old_cache[cache_key] = channel_lines
                    continue
                i += 1
        print(f"[+] Loaded {len(old_cache)} channels from old cache!\n")
    except Exception as e:
        print(f"[-] Error loading old cache: {e}")
    return old_cache

def fetch_lcn_dict(session):
    print("[*] Fetching DishTV LCN list...")
    lcn_dict = {}
    try:
        res = session.get(LCN_LIST_URL, timeout=10)
        if res.status_code == 200:
            for line in res.text.splitlines():
                if ":" not in line:
                    continue
                chno, chname = line.split(":", 1)
                chno = chno.strip()
                chname = " ".join(chname.strip().lower().split())
                if chname and chname not in lcn_dict:
                    lcn_dict[chname] = chno
            print(f"[+] Loaded {len(lcn_dict)} LCN mappings!\n")
    except Exception as e:
        print(f"[-] Error fetching LCN list: {e}")
    return lcn_dict

def clean_val(val):
    if not val:
        return ""
    val = val.strip()
    while val and val[-1] in ('"', "'", '}', ']', '}', '~', ','):
        val = val[:-1].strip()
    return val

def remove_group_title(extinf):
    if re.search(r'group-title="[^"]*live events[^"]*"', extinf, flags=re.IGNORECASE):
        return extinf
    
    extinf = re.sub(r'\s*group-title="[^"]*"', '', extinf, flags=re.IGNORECASE)
    extinf = re.sub(r"\s*group-title='[^']*'", '', extinf, flags=re.IGNORECASE)
    extinf = re.sub(r'\s*group-title=[^\s,]+', '', extinf, flags=re.IGNORECASE)
    return extinf

def clean_channel_title(title):
    cleaned = re.sub(r'\bdigital\b', '', title, flags=re.IGNORECASE)
    if "star sports" not in cleaned.lower():
        cleaned = re.sub(r'\bhindi\b', '', cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())

def clear_old_ips(session):
    print("[*] Checking and clearing old IPs from IP Manager...")
    headers = {
        "User-Agent": "Denver1769",
        "Referer": "https://game.playindia.fun/"
    }
    try:
        res = session.get(IP_MANAGER_URL, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        soup = BeautifulSoup(res.text, 'html.parser')
        forms = soup.find_all('form')
        ip_list = []
        for form in forms:
            action_input = form.find('input', {'name': 'action', 'value': 'delete_ip'})
            ip_input = form.find('input', {'name': 'ip'})
            if action_input and ip_input:
                val = ip_input.get('value')
                if val:
                    ip_list.append(val)
        if not ip_list:
            print("[+] No old IPs to clear.\n")
            return
        def delete_single(ip_val):
            data = {'action': 'delete_ip', 'ip': ip_val}
            try:
                session.post(IP_MANAGER_URL, data=data, headers=headers, timeout=5)
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=15) as executor:
            executor.map(delete_single, ip_list)
        print("[+] All old IPs cleared successfully!\n")
    except Exception as e:
        print(f"[-] Error clearing IPs: {e}")

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64_to_hex(b64_str):
    b64_str = clean_val(b64_str)
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += '=' * padding
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        return decoded.hex()
    except Exception:
        return b64_str

def resolve_stream_url(url, session, user_agent, is_hotstar, is_sliv):
    url = clean_val(url)
    if not url:
        return ""
    headers = {"User-Agent": user_agent}
    if is_hotstar:
        headers.update({
            "User-Agent": "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)",
            "Origin": "https://www.hotstar.com",
            "Referer": "https://www.hotstar.com/",
            "Accept-Encoding": "identity"
        })
    else:
        headers.update({
            "Origin": "https://www.jiotv.com",
            "Referer": "https://www.jiotv.com/",
            "Connection": "keep-alive"
        })
    
    try:
        res = session.head(url, headers=headers, allow_redirects=False, timeout=5)
        if res.status_code in (301, 302, 303, 307, 308):
            loc = res.headers.get("Location")
            if loc:
                if not loc.startswith("http"):
                    loc = urljoin(url, loc)
                return clean_val(loc)
                
        res = session.get(url, headers=headers, allow_redirects=False, timeout=5)
        if res.status_code in (301, 302, 303, 307, 308):
            loc = res.headers.get("Location")
            if loc:
                if not loc.startswith("http"):
                    loc = urljoin(url, loc)
                return clean_val(loc)
                
        res = session.get(url, headers=headers, allow_redirects=True, timeout=7)
        if res.history and res.url:
            if "playindia.fun" not in res.url.lower():
                return clean_val(res.url)
        if res.url and "playindia.fun" not in res.url.lower():
            return clean_val(res.url)
            
    except Exception as e:
        print(f"[-] Stream resolution error for {url}: {e}")
        
    return ""

def process_single_channel(i, lines, session, lcn_dict, global_seen_lcn, old_cache):
    extinf_line = lines[i].strip()
    extinf_line = remove_group_title(extinf_line)

    chno = ""
    cache_key = get_channel_unique_key(extinf_line)
    
    if "," in extinf_line:
        prefix_part, title = extinf_line.split(",", 1)
        cleaned_title = clean_channel_title(title)
        channel_title_clean = cleaned_title.lower().strip()
        
        chno = lcn_dict.get(channel_title_clean, "")
        if not chno and channel_title_clean in global_seen_lcn:
            chno = global_seen_lcn[channel_title_clean]

        final_title = cleaned_title
        if chno:
            if f"({chno})" not in final_title:
                final_title = f"{final_title} ({chno})"
            if "tvg-chno=" not in prefix_part:
                prefix_part = (
                    prefix_part.strip() + f' tvg-chno="{chno}" ch-number="{chno}"'
                )
        extinf_line = f"{prefix_part},{final_title}"

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        candidate_line = clean_val(lines[f])
        if candidate_line.startswith("http"):
            raw_stream_line = candidate_line.split()[0]
            raw_stream_line = clean_val(
                raw_stream_line.split('"')[0].split(",")[0]
            )
            break

    lower_text = (extinf_line + raw_stream_line).lower()
    for b in range(max(0, i - 3), min(len(lines), i + 4)):
        lower_text += lines[b].lower()

    is_hotstar = "hotstar" in lower_text or "jhs" in lower_text
    is_sliv = "sliv" in lower_text or "sony" in lower_text or "ten" in lower_text

    channel_lines = [extinf_line]
    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = clean_val(lines[b])
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = clean_val(
                    sub_b.split("inputstream.adaptive.license_key=")[1].split('"')[0]
                )

        if is_hotstar:
            user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)"
        else:
            user_agent = "Denver1769"

        formatted_license_key = None
        if key_url:
            try:
                key_url = clean_val(key_url.replace('"', "").replace("'", ""))
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    key_pairs = []
                    keys_list = key_json.get("base64", {}).get("keys", [])
                    for k_obj in keys_list:
                        kid_b64 = clean_val(k_obj.get("kid", ""))
                        k_b64 = clean_val(k_obj.get("k", ""))
                        if kid_b64 and k_b64:
                            key_pairs.append(f"{b64_to_hex(kid_b64)}:{b64_to_hex(k_b64)}")
                    if key_pairs:
                        formatted_license_key = ",".join(key_pairs)
            except Exception:
                pass

        if not formatted_license_key:
            formatted_license_key = "null:null"

        final_stream_url = raw_stream_line
        if raw_stream_line:
            resolved = resolve_stream_url(raw_stream_line, session, user_agent, is_hotstar, is_sliv)
            if resolved:
                final_stream_url = clean_val(resolved.split('"')[0].split(",")[0])

        is_failed_stream = (not final_stream_url or "playindia.fun" in final_stream_url.lower() or "api failed" in final_stream_url.lower())
        is_missing_license = (".mpd" in final_stream_url.lower() and formatted_license_key == "null:null")
        
        if (is_failed_stream or is_missing_license) and cache_key in old_cache:
            cached_block = list(old_cache[cache_key])
            cached_block[0] = extinf_line
            return chno, cached_block

        is_mpd_link = ".mpd" in final_stream_url.lower()

        channel_lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        channel_lines.append("#KODIPROP:inputstream.adaptive.manifest_type=" + ("mpd" if is_mpd_link else "hls"))
        channel_lines.append("#KODIPROP:inputstream.adaptive.max_bandwidth=0")
        channel_lines.append("#KODIPROP:inputstream.adaptive.stream_selection_type=automatic")
        channel_lines.append("#KODIPROP:inputstream.adaptive.max_buffer_time=1")
        channel_lines.append("#KODIPROP:inputstream.adaptive.buffer_segment_size=1")
        channel_lines.append("#KODIPROP:inputstream.adaptive.live_delay=0")

        if is_hotstar:
            cookie_str = ""
            for check_line in ([raw_stream_line] + lines[max(0, i - 2):min(len(lines), i + 3)]):
                check_line = clean_val(check_line)
                if "hdntl=" in check_line:
                    try:
                        for part in check_line.split("hdntl=")[1:]:
                            candidate = clean_val(part.split()[0].split('"')[0])
                            if "exp=" in candidate:
                                cookie_str = "hdntl=" + clean_val(candidate.split("&")[0])
                                break
                    except Exception:
                        pass
                if cookie_str:
                    break

            if not cookie_str:
                cookie_str = "hdntl=exp=1791763208~acl=%2f*~id=ce6ecdabc53ea306cc7be95fa7a1b49c~data=hdntl~hmac=8a7405e9c3a1f2880ac44abb4e3fee31d750b5c4d6d4bfaa67bac50b175140a1"

            base_url = clean_val(final_stream_url.split("|")[0].split('"')[0])
            pipe_headers = f"User-Agent={user_agent}&Accept-Encoding=identity&X-Denver-Secure=true&Host=livetv.hotstar.com&Connection=Keep-Alive&Cookie={cookie_str}"
            channel_lines.append(clean_val(f"{base_url}|{pipe_headers}"))

        else:
            target_url = final_stream_url if final_stream_url else raw_stream_line
            jio_cookie = ""
            
            if "__hdnea__=" in target_url or "hdnea=" in target_url:
                try:
                    token_key = "__hdnea__=" if "__hdnea__=" in target_url else "hdnea="
                    jio_cookie = token_key + target_url.split(token_key)[1].split("&")[0].split('"')[0]
                    target_url = target_url.split("?")[0]
                except Exception:
                    pass

            if not jio_cookie:
                for check_line in ([raw_stream_line] + lines[max(0, i - 2):min(len(lines), i + 3)]):
                    check_line = clean_val(check_line)
                    if "hdnea=" in check_line or "__hdnea__=" in check_line:
                        try:
                            token_key = "__hdnea__=" if "__hdnea__=" in check_line else "hdnea="
                            for part in check_line.split(token_key)[1:]:
                                candidate = clean_val(part.split()[0])
                                if "exp=" in candidate or "st=" in candidate:
                                    jio_cookie = token_key + clean_val(candidate.split("&")[0])
                                    break
                        except Exception:
                            pass
                    if jio_cookie:
                        break

            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_key=" + formatted_license_key)
            channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

            if jio_cookie:
                # STRICT DEDUPLICATION: Remove any preexisting cookie/exthttp lines to avoid duplicates
                channel_lines = [line for line in channel_lines if not line.startswith("#EXTVLCOPT:http-cookie") and not line.startswith("#EXTHTTP")]
                
                channel_lines.append(f"#EXTVLCOPT:http-cookie={jio_cookie}")
                channel_lines.append(
                    '#EXTHTTP:{"User-Agent":"' + user_agent + '",'
                    '"Origin":"https://www.jiotv.com/",'
                    '"Referer":"https://www.jiotv.com/",'
                    f'"Cookie":"{jio_cookie}",'
                    '"Connection":"keep-alive"}'
                )

            channel_lines.append(clean_val(target_url))

    except Exception as e:
        print(f"[-] Channel processing error at line {i}: {e}")
        if cache_key in old_cache:
            cached_block = list(old_cache[cache_key])
            cached_block[0] = extinf_line
            return chno, cached_block

        channel_lines = [extinf_line]
        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        channel_lines.append("#KODIPROP:inputstream.adaptive.license_key=null:null")
        channel_lines.append(f"#EXTVLCOPT:http-user-agent=Denver1769")
        channel_lines.append(clean_val(raw_stream_line) if raw_stream_line else "")

    return chno, channel_lines

def generate_safe_playlist_1000():
    if not PLAYLIST_URL:
        print("[-] PLAYLIST_URL environment variable is missing.")
        return

    session = get_robust_session()
    clear_old_ips(session)
    lcn_dict = fetch_lcn_dict(session)
    old_cache = load_old_playlist_cache()

    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "Denver1769"}, timeout=30)
        if res.status_code != 200:
            print(f"[-] Playlist HTTP status: {res.status_code}")
            return

        lines = res.text.splitlines()
        all_channels = [
            (i, line) for i, line in enumerate(lines) if line.strip().startswith("#EXTINF")
        ]
        if not all_channels:
            print("[-] No channels found in playlist.")
            return

        target_indices = [item[0] for item in all_channels[:MAX_CHANNELS]]
        
        global_seen_lcn = {}
        for idx in target_indices:
            extinf_line = remove_group_title(lines[idx].strip())
            if "," in extinf_line:
                _, title = extinf_line.split(",", 1)
                cleaned_title = clean_channel_title(title)
                ch_key = cleaned_title.lower().strip()
                if ch_key in lcn_dict and ch_key not in global_seen_lcn:
                    global_seen_lcn[ch_key] = lcn_dict[ch_key]

        print(f"[*] Processing {len(target_indices)} channels...")

        processed_channels = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for idx in target_indices:
                fut = executor.submit(
                    process_single_channel, idx, lines, session, lcn_dict, global_seen_lcn, old_cache
                )
                futures[fut] = idx

            for future in as_completed(futures):
                try:
                    chno, res_lines = future.result()
                    if res_lines:
                        try:
                            sort_key = int(chno)
                        except (ValueError, TypeError):
                            sort_key = 99999
                        processed_channels.append((sort_key, res_lines))
                except Exception as e:
                    print(f"[-] Channel task failed: {e}")

        processed_channels.sort(key=lambda x: x[0])
        new_lines = ["#EXTM3U"]
        for _, res_lines in processed_channels:
            new_lines.extend(res_lines)

        output_file = ".m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"\n[+] Success! Playlist saved as '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
