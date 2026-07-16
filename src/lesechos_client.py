"""Les Echos client — réutilisable, compatible avec le token d'authentification."""
import os
import re
import subprocess
import json
from datetime import datetime, timedelta
from typing import Optional

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TOKEN = os.environ.get("LESECHOS_TOKEN", "")
if not TOKEN:
    token_file = os.path.expanduser("~/.hermes/.lesechos_token")
    if os.path.exists(token_file):
        TOKEN = open(token_file).read().strip()


def _curl(url, cookie_jar, referer=None):
    cmd = [
        "curl", "-sL", url,
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: fr-FR,fr;q=0.9",
        "-H", "Accept-Encoding: gzip, deflate, br",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: same-origin",
        "-b", cookie_jar,
        "--compressed",
    ]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return ""


def _login(cookie_jar):
    """Authenticate with the Les Echos token."""
    cmd = [
        "curl", "-sL", f"https://www.lesechos.fr/autologin?token={TOKEN}",
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: fr-FR,fr;q=0.9",
        "-H", "Accept-Encoding: gzip, deflate, br",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none",
        "-H", "Sec-Fetch-User: ?1",
        "-H", "Upgrade-Insecure-Requests: 1",
        "-c", cookie_jar,
        "-o", "/dev/null",
        "--compressed",
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.returncode == 0


def _escape_unicode(text):
    """Clean unicode escape sequences from JSON."""
    text = text.replace("\\xa0", " ")
    replacements = {
        "\\u002F": "/", "\\u2019": "'", "\\u2013": "-", "\\u2014": "-",
        "\\u0026": "&", "\\u00e9": "é", "\\u00e0": "à", "\\u00e8": "è",
        "\\u00ea": "ê", "\\u00f4": "ô", "\\u00ee": "î", "\\u00fb": "û",
        "\\u00ef": "ï", "\\u00eb": "ë", "\\u00e7": "ç", "\\u00c9": "É",
        "\\u00ab": "«", "\\u00bb": "»", "\\u20ac": "€",
        "\\u2018": "'", "\\u201c": '"', "\\u201d": '"',
    }
    for esc, char in replacements.items():
        text = text.replace(esc, char)
    text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
    return text


def is_available():
    return bool(TOKEN)


def fetch_articles(section=None, limit=30):
    """Fetch recent articles from Les Echos.
    
    Args:
        section: URL path like /finance-marches/banque-assurances or None for front page
        limit: max articles to return
        
    Returns:
        list of dicts with title, summary, link, date
    """
    if not TOKEN:
        print("[lesechos] No token available")
        return []
    
    cookie_jar = f"/tmp/lesechos_cookies_{os.getpid()}.txt"
    
    try:
        if not _login(cookie_jar):
            print("[lesechos] Login failed")
            return []
        
        # Fetch the section page
        if section:
            url = f"https://www.lesechos.fr{section}"
        else:
            url = "https://www.lesechos.fr"
        
        html = _curl(url, cookie_jar)
        
        if not html:
            return []
        
        articles = []
        
        # Try to find article data in JSON-LD or inline JSON
        json_pattern = re.compile(
            r'"(?:title|headline|shortDescription|description|url|dateModified|datePublished|articleBody)"\s*:\s*"((?:\\.|[^"\\])*)"',
            re.DOTALL,
        )
        matches = json_pattern.findall(html)
        
        # Build article objects from JSON matches
        current = {}
        for m in matches:
            val = _escape_unicode(m)
            if not val.strip() or len(val) > 500:
                continue
            # Heuristic: group values into article objects
            if val.startswith("http") and "lesechos.fr" in val:
                if current.get("title") and current.get("link") != val:
                    if current.get("title") not in [a.get("title") for a in articles]:
                        articles.append(current)
                    current = {"link": val}
                else:
                    current["link"] = val
            elif len(val) > 20 and val.count(" ") > 3:
                if "title" not in current:
                    current["title"] = val
                elif current.get("title") and len(current.get("title", "")) > 0:
                    if "summary" not in current:
                        current["summary"] = val[:200]
                    elif current.get("summary") and val not in current.values():
                        if current.get("title") not in [a.get("title") for a in articles]:
                            articles.append(current)
                        current = {}
            
            # Also catch article cards in structured HTML
            title_match = re.search(r'<h3[^>]*>([^<]+)</h3>', html)
        
        # Fallback: extract from HTML
        if len(articles) < 3:
            articles = []
            # Find article cards
            cards = re.findall(
                r'<article[^>]*>.*?<h[23][^>]*>(.*?)</h[23]>.*?</article>',
                html[:200000],
                re.DOTALL,
            )
            for card_html in cards[:limit]:
                title_m = re.search(r'href="([^"]+)"[^>]*>([^<]+)', card_html)
                if title_m:
                    title = _escape_unicode(title_m.group(2)).strip()
                    if title and len(title) > 10:
                        articles.append({
                            "title": title,
                            "link": "https://www.lesechos.fr" + title_m.group(1) if title_m.group(1).startswith("/") else title_m.group(1),
                            "summary": "",
                            "source": "lesechos",
                        })
        
        # Deduplicate and limit
        seen = set()
        unique = []
        for a in articles:
            t = a.get("title", "")[:50]
            if t and t not in seen:
                seen.add(t)
                a["date"] = datetime.now().isoformat()
                unique.append(a)
        
        # Extract full article content for top articles
        for a in unique[:10]:
            try:
                article_html = _curl(a["link"], cookie_jar, referer=url)
                # Extract lead paragraph
                lead_m = re.search(
                    r'<p class="[^"]*lead[^"]*"[^>]*>(.*?)</p>',
                    article_html,
                    re.DOTALL | re.IGNORECASE,
                )
                if lead_m:
                    a["summary"] = re.sub(r'<[^>]+>', "", lead_m.group(1)).strip()[:300]
                
                # Also try meta description
                if not a.get("summary"):
                    meta_m = re.search(
                        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
                        article_html,
                    )
                    if meta_m:
                        a["summary"] = _escape_unicode(meta_m.group(1))[:300]
            except Exception:
                pass
        
        return unique[:limit]
    
    finally:
        # Cleanup cookie jar
        try:
            os.remove(cookie_jar)
        except OSError:
            pass


def search_company_articles(company_name, section=None, days=3, limit=20):
    """Search Les Echos for articles mentioning a specific company.
    
    Args:
        company_name: Company name or ticker to search for
        section: Les Echos section to search
        days: lookback period
        limit: max articles
    
    Returns:
        list of articles mentioning the company
    """
    articles = fetch_articles(section=section, limit=limit)
    
    # Keywords to detect this company
    keywords = [company_name.lower()]
    
    # Add common variations
    if company_name == "LVMH":
        keywords.extend(["lvmh", "moët", "hennessy", "arnault", "louis vuitton"])
    elif company_name == "TotalEnergies":
        keywords.extend(["total", "totalenergies", "pouyanné"])
    elif company_name == "BNP Paribas":
        keywords.extend(["bnp", "bnp paribas", "bonnafé"])
    
    results = []
    for a in articles:
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            results.append(a)
    
    return results


if __name__ == "__main__":
    # Test
    articles = fetch_articles(limit=10)
    print(f"✅ {len(articles)} articles récupérés")
    for a in articles[:5]:
        print(f"  • {a.get('title','?')[:80]}")
        if a.get("summary"):
            print(f"    {a['summary'][:100]}")
