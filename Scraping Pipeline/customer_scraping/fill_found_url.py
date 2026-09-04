import json
import re
import os

def clean_text(text: str) -> set:
    """Normalize text into a set of clean words."""
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
    words = set(text.split())
    stopwords = {'by', 'and', 'amp', 'the', 'hotel', 'id', 'com', 'booking', 'www', 'html'}
    return {w.rstrip('s') for w in words if w not in stopwords}

def extract_slug_words(url: str) -> set:
    """Extract clean words from booking.com URL slug."""
    slug = url.split('/')[-1].replace('.html', '')
    slug = re.sub(r'[^a-zA-Z0-9]', ' ', slug.lower())
    words = set(slug.split())
    stopwords = {'by', 'and', 'amp', 'the', 'hotel', 'id', 'com', 'booking', 'www', 'html', 'oyo', 'capital', 'o'}
    return {w.rstrip('s') for w in words if w not in stopwords}

def calc_score(prop_name: str, url: str) -> float:
    """Calculate string match score between property name and URL slug."""
    p_words = clean_text(prop_name)
    u_words = extract_slug_words(url)
    if not p_words or not u_words:
        return 0.001
    inter = p_words.intersection(u_words)
    if not inter:
        return 0.001
    score_p = len(inter) / len(p_words)
    score_u = len(inter) / len(u_words)
    return max(score_p, score_u, 2 * len(inter) / (len(p_words) + len(u_words)))

def match_urls(manual_search_path: str, seen_url_path: str, output_path: str):
    with open(manual_search_path, 'r', encoding='utf-8') as f:
        manual_search = json.load(f)
        
    with open(seen_url_path, 'r', encoding='utf-8') as f:
        seen_urls_data = json.load(f)
        urls = list(seen_urls_data.keys())

    n_props = len(manual_search)
    n_urls = len(urls)

    # Dynamic Programming Matrix for Monotonic Sequence Alignment
    # dp[i][j]: max score aligning first j URLs to a subset of first i properties ending at property i-1
    dp = [[-1e9] * (n_urls + 1) for _ in range(n_props + 1)]
    parent = [[-1] * (n_urls + 1) for _ in range(n_props + 1)]

    for i in range(n_props + 1):
        dp[i][0] = 0.0

    for j in range(1, n_urls + 1):
        best_prev_score = -1e9
        best_prev_i = -1
        for i in range(1, n_props + 1):
            if dp[i - 1][j - 1] > best_prev_score:
                best_prev_score = dp[i - 1][j - 1]
                best_prev_i = i - 1
            if best_prev_score > -1e8:
                score = calc_score(manual_search[i - 1]['properties_name'], urls[j - 1])
                dp[i][j] = best_prev_score + score
                parent[i][j] = best_prev_i

    best_final_i = max(range(n_urls, n_props + 1), key=lambda i: dp[i][n_urls])

    # Backtrack alignment
    prop_to_url_map = {}
    curr_i = best_final_i
    for j in range(n_urls, 0, -1):
        prev_i = parent[curr_i][j]
        prop_idx = curr_i - 1
        prop_to_url_map[prop_idx] = urls[j - 1]
        curr_i = prev_i

    # Construct final result
    found_urls = []
    matched_count = 0
    for idx, item in enumerate(manual_search):
        matched_url = prop_to_url_map.get(idx, "")
        if matched_url:
            matched_count += 1
        found_urls.append({
            "properties_name": item["properties_name"],
            "customer_id": item["customer_id"],
            "url": matched_url
        })

    # Save output JSON
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(found_urls, f, indent=4, ensure_ascii=False)

    print(f"Successfully processed {n_props} properties.")
    print(f"Assigned {matched_count}/{n_urls} URLs to found_url.json.")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manual_search_file = os.path.join(base_dir, "manual_search.json")
    seen_url_file = os.path.join(base_dir, "seen_url.json")
    found_url_file = os.path.join(base_dir, "found_url.json")

    match_urls(manual_search_file, seen_url_file, found_url_file)
