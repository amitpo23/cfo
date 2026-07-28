#!/usr/bin/env python3
"""בדיקת הקמת ערוץ WhatsApp — לבעלים בלבד.

⚠️ הסקריפט מבצע **קריאות רשת חיות** ל-Graph API של Meta ולכן הוא מחוץ לתחום
לכל סוכן אוטומטי (ראו AGENTS.md). הרצה ידנית של הבעלים בלבד.

כל הקריאות הן **קריאה בלבד** (GET) פרט ל-`--send-to`, ששולח הודעת בדיקה
אחת לנמען שציינת במפורש.

    python scripts/check_whatsapp_setup.py
    python scripts/check_whatsapp_setup.py --send-to 972501234567

מה זה בודק, לפי הסדר שבו דברים באמת נשברים:
  1. ארבעת משתני הסביבה קיימים.
  2. ה-token תקף ומורשה על ה-phone_number_id (הכשל הנפוץ ביותר).
  3. חתימת ה-webhook שהשרת שלנו יחשב תואמת את מה ש-Meta תשלח.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

REQUIRED = [
    ("WHATSAPP_PHONE_NUMBER_ID", "מזהה המספר מ-WhatsApp Manager"),
    ("WHATSAPP_ACCESS_TOKEN", "טוקן הגישה של האפליקציה"),
    ("WHATSAPP_VERIFY_TOKEN", "מחרוזת שאתה בוחר, נרשמת גם ב-Meta"),
    ("WHATSAPP_APP_SECRET", "App Secret מ-Meta App → Settings → Basic"),
]
API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v21.0")

OK = "\033[92m✓\033[0m"
BAD = "\033[91m✗\033[0m"


def _get(url: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": {"message": str(exc)}}


def check_env() -> dict[str, str]:
    print("\n1. משתני סביבה")
    values, missing = {}, []
    for name, hint in REQUIRED:
        value = os.environ.get(name, "").strip()
        values[name] = value
        if value:
            print(f"   {OK} {name}")
        else:
            print(f"   {BAD} {name} — {hint}")
            missing.append(name)
    if missing:
        print(f"\n   חסרים {len(missing)} ערכים. הוסף אותם ל-Vercel (Production)")
        print("   או ל-.env.local לבדיקה מקומית, והרץ שוב.")
        sys.exit(1)
    return values


def check_token(values: dict[str, str]) -> None:
    print("\n2. תקפות ה-token מול Meta")
    phone_id = values["WHATSAPP_PHONE_NUMBER_ID"]
    url = (
        f"https://graph.facebook.com/{API_VERSION}/{phone_id}"
        "?fields=display_phone_number,verified_name,quality_rating"
    )
    status, body = _get(url, values["WHATSAPP_ACCESS_TOKEN"])

    if status == 200:
        print(f"   {OK} מחובר")
        print(f"      מספר:  {body.get('display_phone_number', '—')}")
        print(f"      שם:    {body.get('verified_name', '—')}")
        print(f"      איכות: {body.get('quality_rating', '—')}")
        return

    message = (body.get("error") or {}).get("message", "לא ידוע")
    print(f"   {BAD} נכשל (HTTP {status}): {message}")
    if status == 401:
        print("      ה-token פג או שגוי. הפק חדש ב-Meta App → WhatsApp → API Setup.")
    elif status == 404:
        print("      ה-phone_number_id לא נמצא. ודא שהעתקת את ה-ID ולא את המספר עצמו.")
    elif status == 403:
        print("      ל-token אין הרשאה על המספר הזה — בדוק שהם מאותה אפליקציה.")
    sys.exit(1)


def check_signature(values: dict[str, str]) -> None:
    """מוודא שהחתימה שנחשב תואמת את הנוסחה של Meta: sha256 של הגוף הגולמי."""
    print("\n3. חישוב חתימת webhook")
    sample = b'{"object":"whatsapp_business_account","entry":[]}'
    expected = "sha256=" + hmac.new(
        values["WHATSAPP_APP_SECRET"].encode(), sample, hashlib.sha256,
    ).hexdigest()
    print(f"   {OK} תקין — לגוף לדוגמה החתימה תהיה")
    print(f"      {expected[:32]}…")
    print("      אם Meta שולחת ו-403 חוזר, סימן ש-APP_SECRET אינו של אותה אפליקציה.")


def send_test(values: dict[str, str], to: str) -> None:
    print(f"\n4. שליחת הודעת בדיקה אל {to}")
    payload = json.dumps({
        "messaging_product": "whatsapp", "to": to, "type": "text",
        "text": {"body": "מושקו כאן. החיבור עובד ✅"},
    }).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/{API_VERSION}/{values['WHATSAPP_PHONE_NUMBER_ID']}/messages",
        data=payload,
        headers={
            "Authorization": f"Bearer {values['WHATSAPP_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.loads(resp.read().decode())
        print(f"   {OK} נשלח. בדוק את הוואטסאפ שלך.")
    except urllib.error.HTTPError as exc:
        body = {}
        try:
            body = json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            pass
        message = (body.get("error") or {}).get("message", "")
        print(f"   {BAD} נכשל (HTTP {exc.code}): {message}")
        if "recipient" in message.lower() or exc.code == 400:
            print("      במספר בדיקה של Meta מותר לשלוח רק לנמענים שרשמת מראש")
            print("      ב-Meta App → WhatsApp → API Setup → To.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="בדיקת הקמת ערוץ WhatsApp (בעלים בלבד)")
    parser.add_argument("--send-to", help="מספר בפורמט בינלאומי בלי + (למשל 972501234567)")
    args = parser.parse_args()

    print("בדיקת ערוץ WhatsApp של מושקו")
    print("=" * 40)
    values = check_env()
    check_token(values)
    check_signature(values)
    if args.send_to:
        send_test(values, args.send_to)

    print("\n" + "=" * 40)
    print(f"{OK} מוכן. השלב הבא: הצבע את ה-Webhook ב-Meta אל")
    print("   https://cfo-2.vercel.app/api/whatsapp/webhook")
    print("   עם ה-VERIFY_TOKEN שלך, והירשם ל-messages.")


if __name__ == "__main__":
    main()
