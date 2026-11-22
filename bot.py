#!/usr/bin/env python3
"""
ربات انتشار خودکار پروژه‌های گیت‌هاب در کانال تلگرام.

- پروژه (ریپازیتوری) جدید  -> پست معرفی: توضیحات + بخشی از README + لینک
- ریلیز جدید               -> پست آپدیت: نسخه + تغییرات + لینک
- (اختیاری) کامیت جدید      -> پست آپدیت، اگر UPDATE_MODE=commits باشد

فقط از کتابخانه‌های استاندارد پایتون استفاده می‌کند؛ نیازی به نصب چیزی نیست.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import time

GITHUB_USER = os.environ.get("GITHUB_USER", "keyvan-alavi")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@technokey1")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
UPDATE_MODE = os.environ.get("UPDATE_MODE", "releases")  # releases | commits
POST_EXISTING = os.environ.get("POST_EXISTING", "true").lower() == "true"
DELAY_BETWEEN_POSTS = 4  # ثانیه؛ تلگرام ارسال سریع پشت‌سرهم به کانال را محدود می‌کند
FORCE_REPO = os.environ.get("FORCE_REPO", "").strip()
SELF_REPO = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

README_LIMIT = 900
NOTES_LIMIT = 700


# ---------------------------------------------------------------- HTTP helpers
def gh(path, accept="application/vnd.github+json", allow_404=False):
    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "technokey-telegram-bot")
    if GH_TOKEN:
        req.add_header("Authorization", "Bearer " + GH_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode("utf-8", "replace")
            return data if accept.endswith("raw") else json.loads(data)
    except urllib.error.HTTPError as e:
        if e.code == 404 and allow_404:
            return None
        raise


def tg_send(text, button_url=None, button_text="مشاهده در گیت‌هاب"):
    payload = {
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if button_url:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
            time.sleep(DELAY_BETWEEN_POSTS)
            return result
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < 3:       # محدودیت سرعت تلگرام: صبر و تلاش دوباره
                try:
                    wait = json.loads(body)["parameters"]["retry_after"]
                except Exception:
                    wait = 30
                print(f"Telegram rate limit, waiting {wait}s")
                time.sleep(wait + 1)
                continue
            raise RuntimeError(f"Telegram error {e.code}: {body}")


# ------------------------------------------------------------ text formatting
def md_to_telegram(md, limit):
    """تبدیل ساده Markdown به HTML تلگرام + کوتاه کردن متن."""
    md = re.sub(r"```.*?```", "", md, flags=re.S)           # بلوک‌های کد
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)             # تصاویر و بج‌ها
    md = re.sub(r"\[\s*\]\([^)]*\)", "", md)                 # لینک‌های خالی باقی‌مانده
    md = re.sub(r"<[^>]+>", "", md)                          # تگ‌های HTML
    out, size, skipped_title = [], 0, False
    for raw in md.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"[-*_=]{3,}", line):
            if out and out[-1] != "":
                out.append("")
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h and not skipped_title and len(h.group(1)) == 1:
            skipped_title = True                              # عنوان اصلی README تکراری است
            continue
        line = html.escape(line, quote=False)
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        if h:
            line = "<b>" + re.sub(r"</?[a-z][^>]*>", "", line[len(h.group(1)) + 1:].strip()) + "</b>"
        line = re.sub(r"^[-*+]\s+", "• ", line)
        if size + len(line) > limit:
            out.append("…")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out).strip()


def hashtags(repo):
    tags = ["#" + re.sub(r"[^\w]", "_", t) for t in repo.get("topics", [])[:5]]
    if repo.get("language"):
        tags.append("#" + re.sub(r"[^\w]", "_", repo["language"]))
    return " ".join(tags)


# ------------------------------------------------------------------ messages
def post_new_repo(repo):
    name, url = repo["name"], repo["html_url"]
    readme = gh(f"/repos/{GITHUB_USER}/{name}/readme", accept="application/vnd.github.raw", allow_404=True)
    parts = [f"🚀 <b>پروژه جدید: {html.escape(name)}</b>"]
    if repo.get("description"):
        parts.append(html.escape(repo["description"]))
    if repo.get("language"):
        parts.append(f"🛠 زبان اصلی: {html.escape(repo['language'])}")
    if readme:
        excerpt = md_to_telegram(readme, README_LIMIT)
        if excerpt:
            parts.append(excerpt)
    parts.append("📥 برای دریافت پروژه، دانلود یا همراهی در توسعه آن، به لینک زیر مراجعه فرمایید:\n" + url)
    tags = hashtags(repo)
    if tags:
        parts.append(tags)
    tg_send("\n\n".join(parts), url)


def post_release(repo, rel):
    name, url = repo["name"], rel.get("html_url") or repo["html_url"]
    tag = rel.get("tag_name", "")
    parts = [f"🔄 <b>آپدیت جدید برای {html.escape(name)}</b>",
             f"نسخه <b>{html.escape(tag)}</b> اعمال شد."]
    notes = md_to_telegram(rel.get("body") or "", NOTES_LIMIT)
    if notes:
        parts.append("📝 تغییرات:\n" + notes)
    parts.append("برای دسترسی و دریافت نسخه جدید، به لینک زیر مراجعه کنید:\n" + url)
    tg_send("\n\n".join(parts), url, "دریافت آپدیت")


def post_commit(repo, commit):
    msg = (commit["commit"]["message"] or "").splitlines()[0]
    url = commit["html_url"]
    parts = [f"🔄 <b>آپدیت جدید برای {html.escape(repo['name'])}</b>",
             f"📝 {html.escape(msg)}",
             "برای مشاهده تغییرات و دریافت آخرین نسخه، به لینک زیر مراجعه کنید:\n" + repo["html_url"]]
    tg_send("\n\n".join(parts), repo["html_url"], "مشاهده پروژه")


# --------------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def list_repos():
    repos, page = [], 1
    while True:
        batch = gh(f"/users/{GITHUB_USER}/repos?per_page=100&type=owner&sort=created&page={page}")
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


def latest_release(name):
    return gh(f"/repos/{GITHUB_USER}/{name}/releases/latest", allow_404=True)


def latest_commit(name, branch):
    data = gh(f"/repos/{GITHUB_USER}/{name}/commits?sha={urllib.parse.quote(branch)}&per_page=1", allow_404=True)
    return data[0] if data else None


# ---------------------------------------------------------------------- main
def main():
    state = load_state()
    first_run = not state.get("initialized")
    known = state.setdefault("repos", {})
    errors = 0

    repos = [r for r in list_repos()
             if not r["fork"] and not r["archived"]
             and r["name"] not in (SELF_REPO, GITHUB_USER)]
    repos.sort(key=lambda r: r["created_at"])   # قدیمی‌ترین اول، تا ترتیب کانال زمانی باشد

    for repo in repos:
        name = repo["name"]
        try:
            rel = latest_release(name)
            rel_tag = rel["tag_name"] if rel else None
            commit = latest_commit(name, repo["default_branch"]) if UPDATE_MODE == "commits" else None
            sha = commit["sha"] if commit else None

            if FORCE_REPO and name.lower() == FORCE_REPO.lower():
                post_new_repo(repo)
                known[name] = {"release": rel_tag, "sha": sha}
                print(f"[forced] {name}")
                continue

            entry = known.get(name)
            if entry is None:
                if first_run and not POST_EXISTING:
                    known[name] = {"release": rel_tag, "sha": sha}   # ثبت بی‌صدا
                    continue
                post_new_repo(repo)
                known[name] = {"release": rel_tag, "sha": sha}
                print(f"[new repo] {name}")
            elif rel and rel_tag != entry.get("release"):
                post_release(repo, rel)
                entry["release"] = rel_tag
                entry["sha"] = sha
                print(f"[release] {name} {rel_tag}")
            elif UPDATE_MODE == "commits" and commit and sha != entry.get("sha"):
                if entry.get("sha"):
                    post_commit(repo, commit)
                    print(f"[commit] {name} {sha[:7]}")
                entry["sha"] = sha
        except Exception as e:  # یک پروژه خراب نباید بقیه را متوقف کند
            errors += 1
            print(f"ERROR on {name}: {e}", file=sys.stderr)

    state["initialized"] = True
    save_state(state)
    if first_run and not POST_EXISTING:
        print(f"First run: {len(known)} existing repos recorded silently, nothing posted.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
