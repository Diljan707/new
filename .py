import base64
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TARGET_PLAYLIST_URL = "https://game.playindia.fun/Jtv/0eZNHe/Playlist.m3u"
MAX_WORKERS = 20


def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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
    output_file = "playlist.m3u"
    if not os.path.exists(output_file):
        return old_cache

    print("[*] Loading old playlist.m3u cache for fallback tokens...")
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


def clean_val(val):
    if not val:
        return ""
    val = val.strip()
    while val and val[-1] in ('"', "'", "}", "]", "~", ","):
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


def b64_to_hex(b64_str):
    b64_str = clean_val(b64_str)
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        return decoded.hex()
    except Exception:
        return b64_str


def extract_direct_clearkey(text_block):
    match = re.search(r'[0-9a-fA-F]{32}:[0-9a-fA-F]{32}', text_block)
    if match:
        return match.group(0)
    return None


def resolve_stream_url(url, session, user_agent, is_hotstar, is_sliv):
    url = clean_val(url)
    if not url:
        return ""
    headers = {
        "User-Agent": user_agent,
        "Referer": "https://game.playindia.fun/",
        "Origin": "https://game.playindia.fun"
    }
    if is_hotstar:
        headers.update({
            "User-Agent": "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)",
            "Origin": "https://www.hotstar.com",
            "Referer": "https://www.hotstar.com/",
            "Accept-Encoding": "identity"
        })
    elif is_sliv:
        headers.update({"Origin": "https://www.sonyliv.com", "Referer": "https://www.sonyliv.com/"})

    try:
        time.sleep(0.1)
        res = session.head(url, headers=headers, allow_redirects=False, timeout=5)
        if res.status_code in (301, 302, 303, 307, 308):
            loc = res.headers.get("Location")
            if loc:
                if not loc.startswith("http"):
                    loc = urljoin(url, loc)
                return clean_val(loc)

        res = session.get(url, headers=headers, allow_redirects=True, stream=True, timeout=7)
        final_url = res.url
        res.close()
        if final_url and "playindia.fun" not in final_url.lower():
            return clean_val(final_url)

    except Exception:
        pass
    return ""


def process_single_channel(idx, i, original_extinf, lines, session, old_cache):
    extinf_line = original_extinf.strip()
    is_live_event = bool(re.search(r'live events', extinf_line, flags=re.IGNORECASE))

    extinf_line = remove_group_title(extinf_line)
    cache_key = get_channel_unique_key(extinf_line)

    if "," in extinf_line:
        prefix_part, title = extinf_line.split(",", 1)
        cleaned_title = clean_channel_title(title)
        extinf_line = f"{prefix_part},{cleaned_title}"

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        candidate_line = clean_val(lines[f])
        if candidate_line.startswith("http"):
            raw_stream_line = candidate_line.split()[0]
            raw_stream_line = clean_val(
                raw_stream_line.split('"')[0].split(",")[0]
            )
            break

    direct_key_found = None
    for b in range(max(0, i - 3), min(len(lines), i + 4)):
        direct_key_found = extract_direct_clearkey(lines[b])
        if direct_key_found:
            break

    lower_text = (extinf_line + raw_stream_line).lower()
    for b in range(max(0, i - 3), min(len(lines), i + 4)):
        lower_text += lines[b].lower()

    is_hotstar = "hotstar" in lower_text or "jhs" in lower_text
    is_sliv = (
        "sliv" in lower_text or "sony" in lower_text or "ten" in lower_text
    )

    channel_lines = [extinf_line]
    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = clean_val(lines[b])
            if "inputstream.adaptive.license_key=" in sub_b:
                potential_val = clean_val(
                    sub_b.split("inputstream.adaptive.license_key=")[1].split('"')[0]
                )
                if ":" in potential_val and not potential_val.startswith("http"):
                    direct_key_found = extract_direct_clearkey(potential_val)
                else:
                    key_url = potential_val

        if is_hotstar:
            user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)"
        elif is_sliv:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Denver1769"

        formatted_license_key = None
        if direct_key_found:
            formatted_license_key = direct_key_found
        elif key_url:
            try:
                key_url = clean_val(key_url.replace('"', "").replace("'", ""))
                key_res = session.get(
                    key_url, headers={"User-Agent": user_agent, "Referer": "https://game.playindia.fun/"}, timeout=5
                )
                if key_res.status_code == 200:
                    try:
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
                        extracted = extract_direct_clearkey(key_res.text)
                        if extracted:
                            formatted_license_key = extracted
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
            return idx, cached_block, is_live_event

        is_mpd_link = ".mpd" in final_stream_url.lower()

        channel_lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        channel_lines.append("#KODIPROP:inputstream.adaptive.manifest_type=" + ("mpd" if is_mpd_link else "hls"))

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
            if is_mpd_link:
                channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
                channel_lines.append("#KODIPROP:inputstream.adaptive.license_key=" + formatted_license_key)
                pipe_headers = f"User-Agent={user_agent}&Accept-Encoding=identity&X-Denver-Secure=true&Host=livetv.hotstar.com&Connection=Keep-Alive&Cookie={cookie_str}"
            else:
                pipe_headers = f"User-Agent={user_agent}&Origin=https://www.hotstar.com&Referer=https://www.hotstar.com/&Cookie={cookie_str}"
            channel_lines.append(clean_val(f"{base_url}|{pipe_headers}"))
        else:
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_key=" + formatted_license_key)
            channel_lines.append(clean_val(final_stream_url) if final_stream_url else clean_val(raw_stream_line))

    except Exception:
        if cache_key in old_cache:
            cached_block = list(old_cache[cache_key])
            cached_block[0] = extinf_line
            return idx, cached_block, is_live_event

        channel_lines = [extinf_line]
        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        channel_lines.append("#KODIPROP:inputstream.adaptive.license_key=null:null")
        channel_lines.append(clean_val(raw_stream_line) if raw_stream_line else "")

    return idx, channel_lines, is_live_event


def generate_playlist():
    session = get_robust_session()
    old_cache = load_old_playlist_cache()

    print(f"[*] Fetching target playlist directly from: {TARGET_PLAYLIST_URL}")
    try:
        res = session.get(TARGET_PLAYLIST_URL, headers={"User-Agent": "Denver1769", "Referer": "https://game.playindia.fun/"}, timeout=40)
        if res.status_code != 200:
            print(f"[-] Failed to fetch playlist, status: {res.status_code}")
            return

        lines = res.text.splitlines()
        all_channels = [(i, line) for i, line in enumerate(lines) if line.strip().startswith("#EXTINF")]
        if not all_channels:
            print("[-] No channels found in playlist.")
            return

        print(f"[+] Total channels found: {len(all_channels)}. Processing all with {MAX_WORKERS} workers...")

        processed_channels = []
        live_events_channels = []

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    process_single_channel, idx, line_idx, lines[line_idx], lines, session, old_cache
                ): idx for idx, (line_idx, _) in enumerate(all_channels)
            }

            for future in as_completed(futures):
                try:
                    idx, res_lines, is_live = future.result()
                    if res_lines:
                        processed_channels.append((idx, res_lines))
                        if is_live:
                            live_events_channels.append((idx, res_lines))
                except Exception as e:
                    print(f"[-] Thread error: {e}")

        print(f"[+] Processing completed in {time.time() - start_time:.2f} seconds!")

        processed_channels.sort(key=lambda x: x[0])
        new_lines = ["#EXTM3U"]
        for _, res_lines in processed_channels:
            new_lines.extend(res_lines)

        output_file = "playlist.m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
        print(f"[✔] Main playlist saved as '{output_file}' ({len(processed_channels)} channels total).")

        live_events_channels.sort(key=lambda x: x[0])
        live_lines = ["#EXTM3U"]
        for _, res_lines in live_events_channels:
            live_lines.extend(res_lines)

        live_output_file = "live_events.m3u"
        with open(live_output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(live_lines))
        print(f"[✔] Live events playlist saved as '{live_output_file}'.")

    except Exception as e:
        print(f"[-] Critical Error: {e}")


if __name__ == "__main__":
    generate_playlist()
