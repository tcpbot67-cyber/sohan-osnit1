from datetime import datetime, timezone
import os
import re
import sqlite3
from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import httpx
import uvicorn

app = FastAPI(
    title="SOHAN_OSNIT API & Admin Panel",
    description="Telegram Ultra Channel OSINT Engine & Key Management System",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# 🔐 CONFIGURATION & DATABASE SETUP
# =====================================================================
# অ্যাডমিন প্যানেলে লগইন করার মাস্টার পাসওয়ার্ড (চাইলে পরিবর্তন করতে পারেন)
MASTER_ADMIN_SECRET = os.environ.get("MASTER_SECRET", "SOHAN_ADMIN_999")
DB_FILE = "sohan_osnit.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            api_key TEXT PRIMARY KEY,
            owner TEXT,
            plan TEXT,
            requests_used INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    # ডিফল্ট অ্যাডমিন কী (প্রথমবার অটোমেটিক তৈরি হবে)
    c.execute(
        "INSERT OR IGNORE INTO api_keys (api_key, owner, plan, requests_used,"
        " created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "SOHAN_VIP_KEY",
            "Sohan (Main Admin)",
            "Unlimited",
            0,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        ),
    )
    conn.commit()
    conn.close()


init_db()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# =====================================================================
# 🛡️ API KEY VERIFICATION
# =====================================================================
async def verify_api_key(
    key: str = Query(None, description="আপনার API Key দিন"),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    provided_key = (key or x_api_key or "").strip()

    if not provided_key:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "unauthorized",
                "system": "sohan_osnit",
                "error": "API Key Missing!",
                "message": "Use /api/channel?key=YOUR_KEY&username=@channel",
                "contact_owner": "DM TO BUY KEY: @SOHAN_YT",
            },
        )

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT owner, plan, requests_used FROM api_keys WHERE api_key = ?",
        (provided_key,),
    )
    row = c.fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=403,
            detail={
                "status": "forbidden",
                "system": "sohan_osnit",
                "error": "Invalid or Removed API Key!",
                "contact_owner": "DM TO BUY KEY: @SOHAN_YT",
            },
        )

    c.execute(
        "UPDATE api_keys SET requests_used = requests_used + 1 WHERE api_key"
        " = ?",
        (provided_key,),
    )
    conn.commit()
    conn.close()

    return {
        "key": provided_key,
        "owner": row[0],
        "plan": row[1],
        "requests_used": row[2] + 1,
    }


# =====================================================================
# 🧠 OSINT SCRAPER HELPER FUNCTIONS
# =====================================================================
def parse_compact_number(text):
    if not text:
        return 0
    clean = (
        text.upper()
        .replace("SUBSCRIBERS", "")
        .replace("SUBSCRIBER", "")
        .replace("MEMBERS", "")
        .replace(" ", "")
        .replace(",", "")
        .strip()
    )
    try:
        if "K" in clean:
            return int(float(clean.replace("K", "")) * 1000)
        elif "M" in clean:
            return int(float(clean.replace("M", "")) * 1000000)
        digits = re.sub(r"[^\d]", "", clean)
        return int(digits) if digits else 0
    except Exception:
        return 0


def calculate_detailed_age(created_dt):
    if not created_dt:
        return {
            "formatted": "Unknown",
            "total_days": 0,
            "years": 0,
            "months": 0,
            "days": 0,
        }
    now = datetime.now(timezone.utc)
    diff = now - created_dt
    years = diff.days // 365
    months = (diff.days % 365) // 30
    days = (diff.days % 365) % 30
    return {
        "formatted": (
            f"{years} Years, {months} Months, {days} Days ({diff.days} Days"
            " Total)"
        ),
        "total_days": diff.days,
        "years": years,
        "months": months,
        "days": days,
    }


def detect_datacenter(photo_url, page_html):
    locations = {
        1: "DC1 - Miami, USA",
        2: "DC2 - Amsterdam, Netherlands",
        3: "DC3 - Miami, USA",
        4: "DC4 - Amsterdam, Netherlands",
        5: "DC5 - Singapore",
    }
    search_str = (photo_url or "") + " " + (page_html[:5000] or "")
    match = re.search(r"cdn([1-5])\.telesco\.pe", search_str)
    if match:
        dc_id = int(match.group(1))
        return {
            "dc_id": dc_id,
            "server_location": locations.get(dc_id, "Unknown"),
        }
    return {"dc_id": "Hidden / Default", "server_location": "Unknown"}


def deep_osint_extractor(bio_text, posts_text, channel_username):
    newline = "\n"
    combined_text = bio_text + newline + posts_text

    bio_mentions = list(
        set(
            [
                f"@{u}"
                for u in re.findall(r"@([a-zA-Z0-9_]{4,32})", bio_text)
                if u.lower() != channel_username.lower()
            ]
        )
    )

    post_mentions = list(
        set(
            [
                f"@{u}"
                for u in re.findall(r"@([a-zA-Z0-9_]{4,32})", posts_text)
                if u.lower() != channel_username.lower()
            ]
        )
    )

    all_detected_users = list(set(bio_mentions + post_mentions))
    linked_bots = [
        u for u in all_detected_users if u.lower().endswith("bot")
    ]

    owner = "Not Explicitly Mentioned"
    admins = []
    promo_contacts = []

    all_lines = bio_text.split(newline) + posts_text.split(newline)
    for line in all_lines:
        l_low = line.lower()
        users = [
            f"@{u}"
            for u in re.findall(r"@([a-zA-Z0-9_]{4,32})", line)
            if u.lower() != channel_username.lower()
        ]
        if not users:
            continue

        if any(
            k in l_low
            for k in [
                "owner",
                "creator",
                "founder",
                "ceo",
                "dev",
                "developer",
                "ওনার",
                "মালিক",
            ]
        ):
            if owner == "Not Explicitly Mentioned":
                owner = users[0]
        if any(
            k in l_low
            for k in [
                "admin",
                "support",
                "mod",
                "manager",
                "help",
                "অ্যাডমিন",
                "সাপোর্ট",
            ]
        ):
            for u in users:
                if u not in admins:
                    admins.append(u)
        if any(
            k in l_low
            for k in ["ad", "promo", "buy", "paid", "contact", "dm", "business"]
        ):
            for u in users:
                if u not in promo_contacts:
                    promo_contacts.append(u)

    if owner == "Not Explicitly Mentioned" and len(bio_mentions) == 1:
        owner = f"{bio_mentions[0]} (Detected from Bio)"

    emails = list(
        set(
            re.findall(
                r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", combined_text
            )
        )
    )
    external_urls = list(
        set(
            [
                url
                for url in re.findall(r"https?://[^\s<>\"']+", combined_text)
                if "t.me" not in url and "telesco.pe" not in url
            ]
        )
    )

    return {
        "owner_account": owner,
        "admin_and_support_accounts": (
            admins
            if admins
            else (bio_mentions if bio_mentions else ["None Found"])
        ),
        "promotion_or_contact_accounts": promo_contacts,
        "associated_bots": linked_bots,
        "bio_mentioned_usernames": bio_mentions,
        "posts_mentioned_usernames": post_mentions[:15],
        "extracted_emails": emails,
        "external_websites": external_urls[:10],
    }


# =====================================================================
# 👑 ADMIN PANEL API ENDPOINTS (CREATE, LIST & REMOVE KEYS)
# =====================================================================
@app.get("/admin/keys")
async def manage_keys(
    secret: str = Query(..., description="Master Admin Secret"),
    action: str = Query("list", description="list / add / remove"),
    target_key: str = Query(None, description="API Key to Create or Delete"),
    owner_name: str = Query("Client", description="Owner Name"),
    plan: str = Query("VIP", description="Plan Name"),
):
    if secret != MASTER_ADMIN_SECRET:
        raise HTTPException(
            status_code=403, detail="Invalid Master Admin Password!"
        )

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if action == "add" and target_key:
        clean_key = target_key.strip()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        c.execute(
            "INSERT OR REPLACE INTO api_keys (api_key, owner, plan,"
            " requests_used, created_at) VALUES (?, ?, ?, 0, ?)",
            (clean_key, owner_name.strip(), plan.strip(), now_str),
        )
        conn.commit()

    elif action == "remove" and target_key:
        c.execute(
            "DELETE FROM api_keys WHERE api_key = ?", (target_key.strip(),)
        )
        conn.commit()

    c.execute(
        "SELECT api_key, owner, plan, requests_used, created_at FROM api_keys"
        " ORDER BY rowid DESC"
    )
    rows = c.fetchall()
    conn.close()

    keys_list = [
        {
            "key": r[0],
            "owner": r[1],
            "plan": r[2],
            "requests_used": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]
    return {"status": "success", "total_keys": len(keys_list), "keys": keys_list}


# =====================================================================
# 🔍 MAIN CHANNEL OSINT ENDPOINT
# =====================================================================
@app.get("/api/channel")
async def get_ultra_channel_info(
    username: str = Query(..., description="Channel Username বা Link দিন"),
    auth_data: dict = Depends(verify_api_key),
):
    clean_user = (
        username.replace("https://t.me/s/", "")
        .replace("https://t.me/", "")
        .replace("t.me/", "")
        .replace("@", "")
        .split("/")[0]
        .split("?")[0]
        .strip()
    )

    if not clean_user:
        return {"status": "error", "message": "Invalid Username"}

    base_url = f"https://t.me/{clean_user}"
    preview_url = f"https://t.me/s/{clean_user}"

    async with httpx.AsyncClient(
        headers=HEADERS, follow_redirects=True, timeout=20.0
    ) as client:
        try:
            res_base = await client.get(base_url)
            res_prev = await client.get(preview_url)

            soup_base = BeautifulSoup(res_base.text, "html.parser")
            soup_prev = BeautifulSoup(res_prev.text, "html.parser")

            title_tag = soup_base.find(
                "div", class_="tgme_page_title"
            ) or soup_prev.find("div", class_="tgme_channel_info_header_title")
            if not title_tag:
                return {
                    "status": "error",
                    "message": "Channel not found or username is invalid!",
                }

            channel_name = title_tag.get_text(strip=True)

            sub_tag = soup_base.find("div", class_="tgme_page_extra")
            sub_raw = sub_tag.get_text(strip=True) if sub_tag else "0"
            sub_count = parse_compact_number(sub_raw)

            media_counters = {
                "photos": 0,
                "videos": 0,
                "files": 0,
                "links": 0,
                "voice": 0,
            }
            for counter_div in soup_prev.find_all(
                "div", class_="tgme_channel_info_counter"
            ):
                val_span = counter_div.find("span", class_="counter_value")
                type_span = counter_div.find("span", class_="counter_type")
                if val_span and type_span:
                    c_val = parse_compact_number(val_span.get_text(strip=True))
                    c_type = type_span.get_text(strip=True).lower()
                    if "subscriber" in c_type and sub_count == 0:
                        sub_count = c_val
                        sub_raw = f"{val_span.get_text(strip=True)} subscribers"
                    elif "photo" in c_type:
                        media_counters["photos"] = c_val
                    elif "video" in c_type:
                        media_counters["videos"] = c_val
                    elif "file" in c_type:
                        media_counters["files"] = c_val
                    elif "link" in c_type:
                        media_counters["links"] = c_val
                    elif "voice" in c_type:
                        media_counters["voice"] = c_val

            desc_tag = soup_prev.find(
                "div", class_="tgme_channel_info_description"
            ) or soup_base.find("div", class_="tgme_page_description")
            bio_text = (
                desc_tag.get_text(separator="\n", strip=True)
                if desc_tag
                else ""
            )

            img_tag = soup_base.find(
                "img", class_="tgme_page_photo_image"
            ) or soup_prev.find("img", class_="tgme_page_photo_image")
            photo_url = (
                img_tag["src"] if img_tag and img_tag.get("src") else None
            )

            is_verified = bool(soup_prev.find("i", class_="verified-icon"))
            dc_info = detect_datacenter(photo_url, res_prev.text)

            creation_dt = None
            first_post_id_found = None

            for test_id in [1, 2, 5, 10, 20, 50]:
                res_first = await client.get(
                    f"https://t.me/s/{clean_user}/{test_id}"
                )
                soup_f = BeautifulSoup(res_first.text, "html.parser")
                t_tags = soup_f.find_all("time", datetime=True)
                if t_tags:
                    creation_dt = datetime.fromisoformat(t_tags[0]["datetime"])
                    first_msgs = soup_f.find_all(
                        "div",
                        class_="tgme_widget_message",
                        attrs={"data-post": True},
                    )
                    if first_msgs:
                        first_post_id_found = int(
                            first_msgs[0]["data-post"].split("/")[1]
                        )
                    break

            if not creation_dt:
                fallback_times = soup_prev.find_all("time", datetime=True)
                if fallback_times:
                    creation_dt = datetime.fromisoformat(
                        fallback_times[0]["datetime"]
                    )

            age_details = calculate_detailed_age(creation_dt)

            msg_divs = soup_prev.find_all(
                "div", class_="tgme_widget_message", attrs={"data-post": True}
            )

            views_list = []
            author_signatures = []
            forwarded_from_channels = []
            recent_posts_text = []
            post_ids = []
            last_post_info = None

            for m in msg_divs:
                p_id = int(m["data-post"].split("/")[1])
                post_ids.append(p_id)

                v_span = m.find("span", class_="tgme_widget_message_views")
                v_count = (
                    parse_compact_number(v_span.get_text(strip=True))
                    if v_span
                    else 0
                )
                if v_count > 0:
                    views_list.append(v_count)

                auth_span = m.find(
                    "span", class_="tgme_widget_message_from_author"
                )
                if auth_span:
                    a_name = auth_span.get_text(strip=True)
                    if a_name and a_name not in author_signatures:
                        author_signatures.append(a_name)

                fwd_a = m.find("a", class_="tgme_widget_message_forwarded_from_name")
                if fwd_a:
                    fwd_name = fwd_a.get_text(strip=True)
                    fwd_link = fwd_a.get("href", "")
                    fwd_entry = f"{fwd_name} ({fwd_link})"
                    if fwd_entry not in forwarded_from_channels:
                        forwarded_from_channels.append(fwd_entry)

                txt_div = m.find("div", class_="tgme_widget_message_text")
                p_text = (
                    txt_div.get_text(separator="\n", strip=True)
                    if txt_div
                    else ""
                )
                if p_text:
                    recent_posts_text.append(p_text)

                t_tag = m.find("time", datetime=True)
                p_time = t_tag["datetime"] if t_tag else None
                last_post_info = {
                    "post_id": p_id,
                    "post_link": f"https://t.me/{clean_user}/{p_id}",
                    "posted_at": p_time,
                    "views": v_count,
                    "preview_text": (
                        p_text[:200] + "..." if len(p_text) > 200 else p_text
                    ),
                }

            total_created_posts = max(post_ids) if post_ids else 0
            avg_views = (
                int(sum(views_list) / len(views_list)) if views_list else 0
            )
            max_views = max(views_list) if views_list else 0
            min_views = min(views_list) if views_list else 0
            engagement_rate = (
                round((avg_views / sub_count) * 100, 2)
                if sub_count > 0
                else 0.0
            )

            activity_status = "Unknown / No Posts"
            if last_post_info and last_post_info["posted_at"]:
                last_dt = datetime.fromisoformat(last_post_info["posted_at"])
                days_since_last = (datetime.now(timezone.utc) - last_dt).days
                if days_since_last <= 3:
                    activity_status = "Highly Active (Posted within 3 days)"
                elif days_since_last <= 15:
                    activity_status = (
                        f"Moderately Active (Last post {days_since_last} days"
                        " ago)"
                    )
                else:
                    activity_status = (
                        f"Inactive / Dead (Last post {days_since_last} days"
                        " ago)"
                    )

            posts_per_day = (
                round(total_created_posts / age_details["total_days"], 2)
                if age_details["total_days"] > 0
                else 0
            )

            joined_posts = "\n".join(recent_posts_text)
            osint_data = deep_osint_extractor(bio_text, joined_posts, clean_user)

            return {
                "status": "success",
                "system_name": "sohan_osnit",
                "auth_info": {
                    "key_owner": auth_data["owner"],
                    "plan": auth_data["plan"],
                    "total_requests_used": auth_data["requests_used"],
                },
                "channel_profile": {
                    "name": channel_name,
                    "username": f"@{clean_user}",
                    "channel_url": base_url,
                    "preview_url": preview_url,
                    "subscribers_raw": sub_raw,
                    "subscribers_exact_approx": sub_count,
                    "is_verified": is_verified,
                    "has_public_preview": bool(msg_divs),
                    "activity_status": activity_status,
                    "datacenter_info": dc_info,
                    "profile_photo_hd": photo_url,
                    "description_bio": bio_text,
                },
                "age_and_history": {
                    "created_date_utc": (
                        creation_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                        if creation_dt
                        else "Unknown"
                    ),
                    "channel_age": age_details["formatted"],
                    "age_breakdown": {
                        "years": age_details["years"],
                        "months": age_details["months"],
                        "days": age_details["days"],
                        "total_days_old": age_details["total_days"],
                    },
                    "oldest_surviving_post_id": first_post_id_found,
                    "first_post_link": (
                        f"https://t.me/{clean_user}/{first_post_id_found}"
                        if first_post_id_found
                        else None
                    ),
                },
                "owner_and_admin_osint": {
                    "detected_owner": osint_data["owner_account"],
                    "detected_admins_and_support": osint_data[
                        "admin_and_support_accounts"
                    ],
                    "promotion_and_business_contacts": osint_data[
                        "promotion_or_contact_accounts"
                    ],
                    "admin_post_signatures": (
                        author_signatures
                        if author_signatures
                        else ["Anonymous (No Admin Signature Enabled)"]
                    ),
                    "linked_bots_in_channel": osint_data["associated_bots"],
                    "all_bio_mentions": osint_data["bio_mentioned_usernames"],
                    "recent_post_mentions": osint_data[
                        "posts_mentioned_usernames"
                    ],
                    "extracted_emails": osint_data["extracted_emails"],
                    "external_websites": osint_data["external_websites"],
                },
                "analytics_and_engagement": {
                    "total_posts_published_ever": total_created_posts,
                    "average_posts_per_day": posts_per_day,
                    "recent_average_views": avg_views,
                    "recent_highest_views": max_views,
                    "recent_lowest_views": min_views,
                    "engagement_rate_percent": f"{engagement_rate}%",
                    "media_statistics": media_counters,
                    "frequently_forwarded_from": (
                        forwarded_from_channels
                        if forwarded_from_channels
                        else ["Original Content (No Recent Forwards)"]
                    ),
                },
                "latest_post_details": last_post_info,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}


# =====================================================================
# 🌐 BUILT-IN ADMIN PANEL & LIVE TESTER WEBSITE (SOHAN_OSNIT)
# =====================================================================
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SOHAN_OSNIT | Admin & API Portal</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: #07090e; color: #e2e8f0; padding: 20px; }
        .container { max-width: 1050px; margin: 0 auto; }
        .header {
            text-align: center; padding: 25px; background: linear-gradient(135deg, #0f172a, #1e1b4b);
            border: 1px solid #3b82f6; border-radius: 14px; box-shadow: 0 0 25px rgba(59, 130, 246, 0.25);
            margin-bottom: 25px;
        }
        .header h1 { font-size: 28px; color: #38bdf8; letter-spacing: 2px; text-transform: uppercase; }
        .header p { color: #94a3b8; margin-top: 6px; font-size: 14px; }
        .url-box {
            margin-top: 12px; background: #020617; padding: 10px 15px; border-radius: 8px;
            border: 1px dashed #38bdf8; display: inline-block; color: #22d3ee; font-family: monospace; font-size: 13px;
            word-break: break-all;
        }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
        .card {
            background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 20px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.4);
        }
        .card h2 { font-size: 18px; color: #f8fafc; margin-bottom: 15px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; }
        label { display: block; font-size: 12px; color: #94a3b8; margin-bottom: 5px; margin-top: 12px; }
        input {
            width: 100%; padding: 10px 12px; background: #020617; border: 1px solid #334155;
            border-radius: 8px; color: #fff; font-size: 14px; outline: none;
        }
        input:focus { border-color: #38bdf8; }
        .btn-row { display: flex; gap: 10px; margin-top: 15px; }
        button {
            cursor: pointer; padding: 10px 16px; border: none; border-radius: 8px;
            font-weight: 600; font-size: 14px; transition: 0.2s; width: 100%;
        }
        .btn-primary { background: #0284c7; color: #fff; }
        .btn-primary:hover { background: #0369a1; }
        .btn-success { background: #059669; color: #fff; }
        .btn-success:hover { background: #047857; }
        .btn-danger { background: #e11d48; color: #fff; padding: 6px 12px; font-size: 12px; width: auto; }
        .btn-copy { background: #334155; color: #38bdf8; padding: 6px 10px; font-size: 12px; width: auto; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #1e293b; }
        th { color: #38bdf8; font-weight: 600; }
        pre {
            background: #020617; color: #4ade80; padding: 15px; border-radius: 8px;
            border: 1px solid #1e293b; overflow-x: auto; max-height: 380px; font-size: 12px; margin-top: 15px;
        }
        .badge { background: #1e293b; color: #38bdf8; padding: 3px 8px; border-radius: 6px; font-family: monospace; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>⚡ SOHAN_OSNIT PORTAL ⚡</h1>
        <p>Telegram Ultra Channel OSINT API & Key Control Panel | Owner: <b>@SOHAN_YT</b></p>
        <div class="url-box" id="apiEndpointDisplay">Loading API Endpoint...</div>
    </div>

    <div class="grid">
        <!-- ADMIN KEY PANEL -->
        <div class="card">
            <h2>🔑 Admin Key Generator & Manager</h2>
            <label>Master Admin Secret Password</label>
            <input type="password" id="adminSecret" placeholder="Enter Master Secret (e.g. SOHAN_ADMIN_999)">

            <label>New API Key Name</label>
            <div style="display:flex; gap:8px;">
                <input type="text" id="newKey" placeholder="e.g. SOHAN_KEY_777">
                <button class="btn-copy" onclick="generateRandomKey()">Random</button>
            </div>

            <label>Client / Owner Name</label>
            <input type="text" id="ownerName" placeholder="e.g. Rahim / Buyer 1">

            <div class="btn-row">
                <button class="btn-success" onclick="createKey()">➕ Create Key</button>
                <button class="btn-primary" onclick="loadKeys()">🔄 View Active Keys</button>
            </div>

            <div id="keysTableContainer" style="margin-top: 15px; overflow-x:auto;"></div>
        </div>

        <!-- LIVE CHANNEL OSINT TESTER -->
        <div class="card">
            <h2>🔍 Live Channel OSINT Scanner</h2>
            <label>Your Active API Key</label>
            <input type="text" id="testApiKey" value="SOHAN_VIP_KEY" placeholder="Enter API Key">

            <label>Telegram Channel Username or Link</label>
            <input type="text" id="testUsername" value="@durov" placeholder="e.g. @durov or https://t.me/durov">

            <div class="btn-row">
                <button class="btn-primary" onclick="testChannelApi()">🚀 Scan Channel Full Info</button>
                <button class="btn-copy" onclick="copyDirectApiLink()">📋 Copy API Link</button>
            </div>

            <pre id="apiOutput">Click "Scan Channel Full Info" to test your API response here...</pre>
        </div>
    </div>
</div>

<script>
    const baseUrl = window.location.origin;
    document.getElementById("apiEndpointDisplay").innerText = baseUrl + "/api/channel?key=YOUR_KEY&username=@channel";

    function generateRandomKey() {
        const rand = Math.random().toString(36).substring(2, 8).toUpperCase();
        document.getElementById("newKey").value = "SOHAN_OSNIT_" + rand;
    }

    async function loadKeys() {
        const secret = document.getElementById("adminSecret").value.trim();
        if (!secret) return alert("Please enter Master Admin Secret first!");

        const res = await fetch(`${baseUrl}/admin/keys?secret=${encodeURIComponent(secret)}&action=list`);
        const data = await res.json();
        if (!res.ok) return alert(data.detail || "Invalid Master Secret!");

        renderKeysTable(data.keys);
    }

    async function createKey() {
        const secret = document.getElementById("adminSecret").value.trim();
        const key = document.getElementById("newKey").value.trim();
        const owner = document.getElementById("ownerName").value.trim() || "Client";

        if (!secret || !key) return alert("Enter both Master Secret and New API Key!");

        const res = await fetch(`${baseUrl}/admin/keys?secret=${encodeURIComponent(secret)}&action=add&target_key=${encodeURIComponent(key)}&owner_name=${encodeURIComponent(owner)}`);
        const data = await res.json();
        if (!res.ok) return alert(data.detail || "Error creating key!");

        document.getElementById("newKey").value = "";
        renderKeysTable(data.keys);
    }

    async function deleteKey(targetKey) {
        const secret = document.getElementById("adminSecret").value.trim();
        if (!confirm(`Remove API Key: ${targetKey}?`)) return;

        const res = await fetch(`${baseUrl}/admin/keys?secret=${encodeURIComponent(secret)}&action=remove&target_key=${encodeURIComponent(targetKey)}`);
        const data = await res.json();
        if (res.ok) renderKeysTable(data.keys);
    }

    function renderKeysTable(keys) {
        let html = `<table><thead><tr><th>API Key</th><th>Owner</th><th>Used</th><th>Action</th></tr></thead><tbody>`;
        keys.forEach(k => {
            html += `<tr>
                <td><span class="badge">${k.key}</span></td>
                <td>${k.owner}</td>
                <td>${k.requests_used}</td>
                <td>
                    <button class="btn-copy" onclick="navigator.clipboard.writeText('${baseUrl}/api/channel?key=${k.key}&username=@durov'); alert('Full API URL Copied!');">Copy URL</button>
                    <button class="btn-danger" onclick="deleteKey('${k.key}')">Remove</button>
                </td>
            </tr>`;
        });
        html += `</tbody></table>`;
        document.getElementById("keysTableContainer").innerHTML = html;
    }

    async function testChannelApi() {
        const key = document.getElementById("testApiKey").value.trim();
        const user = document.getElementById("testUsername").value.trim();
        const out = document.getElementById("apiOutput");
        out.innerText = "⏳ Scanning Telegram Channel OSINT Data...";

        try {
            const res = await fetch(`${baseUrl}/api/channel?key=${encodeURIComponent(key)}&username=${encodeURIComponent(user)}`);
            const data = await res.json();
            out.innerText = JSON.stringify(data, null, 2);
        } catch (err) {
            out.innerText = "Error: " + err.message;
        }
    }

    function copyDirectApiLink() {
        const key = document.getElementById("testApiKey").value.trim();
        const user = document.getElementById("testUsername").value.trim();
        const url = `${baseUrl}/api/channel?key=${encodeURIComponent(key)}&username=${encodeURIComponent(user)}`;
        navigator.clipboard.writeText(url);
        alert("Direct API URL Copied:\n" + url);
    }
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_admin_portal():
    return HTML_PAGE


if __name__ == "__main__":
    raw_port = (
        os.environ.get("PORT")
        or os.environ.get("SERVER_PORT")
        or "8000"
    )
    port = int(raw_port)
    print("==========================================================")
    print(f"⚡ SOHAN_OSNIT WEB PORTAL & API STARTED ON PORT: {port}")
    print(f"🌐 Admin & Web UI: http://0.0.0.0:{port}/")
    print(
        f"🔗 API Endpoint: http://0.0.0.0:{port}/api/channel?key=SOHAN_VIP_KEY&username=@durov"
    )
    print("==========================================================")
    uvicorn.run(app, host="0.0.0.0", port=port)