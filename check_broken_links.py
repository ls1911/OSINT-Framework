import json
import requests
import argparse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup


def extract_urls(node, path=""):
    """
    Recursively extracts URLs from the nested JSON structure.
    Returns a list of (url_string, path_string).
    """
    urls = []
    if isinstance(node, dict):
        # If this node is a URL node
        if node.get("type") == "url" and "url" in node:
            urls.append((node["url"], path))

        # If this node has children, recurse into them
        if "children" in node and isinstance(node["children"], list):
            for i, child in enumerate(node["children"]):
                # If path is empty, don't prepend "."
                if path == "":
                    subpath = f"children[{i}]"
                else:
                    subpath = f"{path}.children[{i}]"
                urls.extend(extract_urls(child, subpath))

    return urls


def remove_url(data, path):
    """
    Removes a URL entry from the JSON structure based on its path.
    The path is in the form "children[0].children[1]...".
    
    Returns True if removal succeeded, else False.
    """
    keys = path.split(".")
    obj = data
    parent = None
    last_key = None

    for key in keys:
        if key.startswith("children["):
            idx_str = key.split("[", 1)[1].rstrip("]")
            try:
                index = int(idx_str)
            except ValueError:
                return False

            parent = obj
            if "children" not in parent or not isinstance(parent["children"], list):
                return False
            if not (0 <= index < len(parent["children"])):
                return False
            last_key = index
            obj = parent["children"][index]
        else:
            parent = obj
            if key not in parent:
                return False
            last_key = key
            obj = parent[key]

    if isinstance(last_key, int):
        del parent["children"][last_key]
    else:
        del parent[last_key]

    return True


def check_url_head(url, debug):
    """
    Sends an HTTP HEAD request to check if a URL is reachable.
    Returns (url_string, status_code_or_exception_string).
    """
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        status_code = response.status_code
    except requests.RequestException as e:
        status_code = str(e)  # Store the exception message as a string

    # Optional debug output
    if debug:
        if isinstance(status_code, int):
            print(f"Received HTTP {status_code} for {url}")
        else:
            print(f"Exception for {url} => {status_code}")

    return (url, status_code)


def main():
    parser = argparse.ArgumentParser(description="Only remove links with 404 or connection errors.")
    parser.add_argument("json_file", help="Path to the JSON file")
    parser.add_argument("--remove", action="store_true",
                        help="Prompt to remove broken links (HTTP 404 or exception) from the JSON file")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Load the JSON file
    with open(args.json_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    # Extract all URLs
    all_urls = extract_urls(data)
    print(f"\n🔍 Found {len(all_urls)} links in the JSON file.\n")

    print("🔍 Checking URLs (only 404 or connection errors are treated as broken)...\n")

    # Check URLs in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda u: check_url_head(u, args.debug), [x[0] for x in all_urls]))

    # Combine results: {actual_url: (json_path, status_code_or_exception)}
    url_status = {}
    for (original_url, path), (checked_url, code) in zip(all_urls, results):
        url_status[original_url] = (path, code)

    # Identify broken links: either integer == 404 or a RequestException string
    broken_links = []
    for url, (path, code) in url_status.items():
        if isinstance(code, str):
            # code is an exception => broken
            broken_links.append((url, path, code))
        else:
            # code is an int; check if 404
            if code == 404:
                broken_links.append((url, path, code))
            else:
                # 200, 403, 500, etc. => keep as "valid"
                pass

    # Summary counters
    passed = sum(
        1 for (_, (p, c)) in url_status.items()
        if (isinstance(c, int) and c != 404)
    )
    failed = len(broken_links)

    print("\n📌 Broken Links Report (404 or connection errors):\n")
    if broken_links:
        for url, path, code in broken_links:
            print(f"- ❌ {url} (Status: {code})")
    else:
        print("No broken links found!")

    removed = 0

    # If --remove, prompt user to remove each broken link
    if args.remove and broken_links:
        print("\n📢 You will now be prompted to remove each broken link. "
              "Press ENTER (or 'y') to remove, or 'n' to skip.")

        for url, path, code in broken_links:
            response = input(f"\n🗑 Remove {url} (Status: {code}) from the file? [Y/n]: ").strip().lower()
            if response in ("", "y"):
                if remove_url(data, path):
                    print(f"✅ Removed: {url}")
                    removed += 1
                else:
                    print(f"⚠️  Failed to remove: {url}")
            else:
                print(f"⏳ Kept: {url}")

        # Save the JSON if any removals occurred
        if removed > 0:
            with open(args.json_file, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
            print("\n✅ Updated JSON file saved.")

    # Final summary
    print("\n==================== 📊 SUMMARY ====================")
    print(f"🔹 Total URLs Found: {len(all_urls)}")
    print(f"🔹 Total URLs Checked: {len(url_status)}")
    print(f"✅ Working URLs (everything except 404/exception): {passed}")
    print(f"❌ Broken URLs (404 or exception): {failed}")
    if args.remove:
        print(f"🗑 Removed URLs: {removed}")
    print("====================================================\n")


if __name__ == "__main__":
    main()
