import os
import json
import requests
import zipfile
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
INPUT_FILE = "memories_history.json"
OUTPUT_DIR = "input/memories"
MAX_WORKERS = 6       # Increase for faster downloads
RETRY_LIMIT = 3       # Number of download retries

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_unique_id_from_url(url):
    """Extract a unique ID (prefer MID, fallback to SID) from Snapchat URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    sid = params.get("sid", ["unknown_sid"])[0]
    mid = params.get("mid", [sid])[0]  # fallback if mid missing
    return mid if mid != sid else sid  # prefer MID when different

def get_file_extension(response, url):
    """Determine file extension from headers or URL path."""
    cd = response.headers.get("content-disposition", "")
    if "filename=" in cd:
        filename = cd.split("filename=")[-1].strip('"\'')
        ext = os.path.splitext(filename)[1]
        return ext if ext else ".bin"
    else:
        path_ext = os.path.splitext(urlparse(url).path)[1]
        return path_ext if path_ext else ".bin"

def safe_download(url):
    """Download a file with retry logic."""
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            r = requests.get(url, stream=True, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"⚠️ Attempt {attempt}/{RETRY_LIMIT} failed for {url}: {e}")
    raise Exception(f"Failed to download {url} after {RETRY_LIMIT} retries")

def extract_zip(zip_path, date_tag, unique_id):
    """
    Extract and rename contents of a ZIP file.
    Adds both the date and unique ID prefix to extracted filenames.
    Deletes the ZIP only if extraction succeeded.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                base_name = os.path.basename(member.filename)
                extracted_name = f"{date_tag}_{unique_id}_{base_name}"
                extracted_path = os.path.join(OUTPUT_DIR, extracted_name)

                if os.path.exists(extracted_path):
                    print(f"   ↳ Skipping existing file: {extracted_name}")
                    continue

                with z.open(member) as source, open(extracted_path, "wb") as target:
                    target.write(source.read())
                print(f"   ↳ Extracted: {extracted_name}")

        print(f"✅ Successfully extracted ZIP: {os.path.basename(zip_path)}")
        os.remove(zip_path)
        print(f"🗑️ Deleted ZIP: {os.path.basename(zip_path)}")
        return True
    except Exception as e:
        print(f"❌ Failed to extract {zip_path}: {e}")
        print(f"⚠️ Keeping ZIP for manual review: {os.path.basename(zip_path)}")
        return False

def download_item(item, index):
    """Download and process a single media entry."""
    url = item.get("Media Download Url")
    date_str = item.get("Date", "unknown_date")

    if not url:
        return f"[{index}] ❌ Missing URL."

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %Z")
        date_tag = date_obj.strftime("%Y-%m-%d")
    except Exception:
        date_tag = "unknown_date"

    unique_id = get_unique_id_from_url(url)
    filename_base = f"{date_tag}_{unique_id}"

    # Resume check
    existing = [f for f in os.listdir(OUTPUT_DIR) if f.startswith(filename_base)]
    if existing:
        return f"[{index}] ⏩ Skipping (already exists): {existing[0]}"

    try:
        response = safe_download(url)
        ext = get_file_extension(response, url)
        filepath = os.path.join(OUTPUT_DIR, f"{filename_base}{ext}")

        # Save file
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Handle ZIPs
        if ext.lower() == ".zip":
            print(f"[{index}] 📦 Extracting ZIP: {os.path.basename(filepath)}")
            extract_zip(filepath, date_tag, unique_id)
            return f"[{index}] 📦 Processed ZIP for ID {unique_id}"
        else:
            return f"[{index}] ✅ Saved: {os.path.basename(filepath)}"

    except Exception as e:
        return f"[{index}] ❌ Failed: {e}"

def main():
    # Load JSON
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    media_list = data.get("Saved Media", [])
    print(f"📁 Found {len(media_list)} media items to process.\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_item, item, i + 1): i for i, item in enumerate(media_list)
        }

        for future in as_completed(futures):
            try:
                print(future.result())
            except Exception as e:
                print(f"❌ Unexpected error: {e}")

    print("\n🎉 All downloads, extractions, and resume checks complete.")

if __name__ == "__main__":
    main()

