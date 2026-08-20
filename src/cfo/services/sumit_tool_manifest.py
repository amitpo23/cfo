"""מניפסט כיסוי SUMIT↔מושקו — W3 גל 2 (20/08/2026).

מקור האמת היחיד להכרעה על כל מתודה ציבורית של SumitIntegration:
חשופה ככלי (TOOL_METHOD_MAP), מכוסה ע"י שירות/route קיים
(ALREADY_COVERED), או מוחרגת במפורש עם סיבה (EXCLUDED_SUMIT_METHODS).

השער שנאכף על המניפסט: tests/test_sumit_tool_coverage.py — סורק ב-inspect
את כל המתודות הציבוריות ונכשל על כל מתודה (קיימת או עתידית) שאינה מוכרעת
כאן. שלוש הקבוצות זרות (disjoint) — מתודה מוכרעת פעם אחת בדיוק.
"""
from __future__ import annotations

# ------------------------------------------------------------------ #
# מתודות שהוחלט במודע לא לחשוף למושקו — שם מתודה → סיבה בעברית.
# ------------------------------------------------------------------ #
EXCLUDED_SUMIT_METHODS: dict[str, str] = {
    # --- פרטי אשראי גולמיים (PAN/CVV/תוקף) — איסור קשיח --- #
    "tokenize_card": (
        "אסור למושקו לטפל בפרטי אשראי (מספר כרטיס); שימוש באמצעי "
        "שמור/טוקן בלבד — הטוקניזציה נעשית ב-payments.js בצד הלקוח."
    ),
    "tokenize_single_use": (
        "אסור למושקו לטפל בפרטי אשראי (מספר כרטיס/CVV/תוקף); שימוש "
        "באמצעי שמור/טוקן בלבד."
    ),
    "tokenize_single_use_json": (
        "אסור למושקו לטפל בפרטי אשראי — ה-payload מכיל CardNumber/CVV "
        "גולמיים; שימוש באמצעי שמור/טוקן בלבד."
    ),
    "create_card_transaction": (
        "מקבלת פרטי כרטיס גולמיים (CreditCard_Number) — אסור למושקו "
        "לטפל בפרטי אשראי; לחיוב יש את הכלי charge_customer שעובד "
        "באמצעי שמור/טוקן בלבד."
    ),
    # --- מסומנות NOT SUPPORTED בקוד הקליינט (זורקות תמיד) --- #
    "get_entities_html": (
        "מסומנת NOT SUPPORTED בקוד — ה-endpoint מרנדר view שמור בלבד "
        "(SchemaID+ViewID) ולא רשימת ישויות; יש get_crm_entity_html "
        "פר-ישות."
    ),
    "charge_recurring": (
        "מסומנת NOT SUPPORTED בקוד — אין ב-API חיוב מיידי של הוראה "
        "קיימת; SUMIT מחייבת הוראות פעילות אוטומטית."
    ),
    "send_letter_by_click": (
        "מסומנת NOT SUPPORTED בקוד — SUMIT אינה חושפת שירות דואר; "
        "כלי שתמיד נכשל מפר honest-null (סטייה מודעת מתוכנית הגל, "
        "שביקשה לחשוף: הקוד עצמו זורק תמיד)."
    ),
    "get_letter_tracking_code": (
        "מסומנת NOT SUPPORTED בקוד — SUMIT אינה חושפת שירות דואר או "
        "קודי מעקב."
    ),
    "open_upay_terminal": (
        "מסומנת NOT SUPPORTED בקוד — ה-endpoint האמיתי מקים מסוף סליקה "
        "חדש (נדרשים פרטי חשבון בנק), לא פותח עסקה; לחיוב יש "
        "charge_customer/begin_payment_redirect."
    ),
    # --- סליקה/סודות בסיכון גבוה --- #
    "setup_upay_credentials": (
        "קולטת אימייל+סיסמה של חשבון Upay — סודות אישורי סליקה לעולם "
        "לא עוברים בצ'אט."
    ),
    "multivendor_charge": (
        "סליקה מפוצלת רבת-ספקים שה-payload שלה נושא מפתחות API של "
        "חברות אחרות — סיכון כספי/אבטחתי גבוה ואין לה צורך עסקי ברצף."
    ),
    # --- ניהול משרד/משתמשים בפורטל (החלטת גל 2: EXCLUDED, לא office) --- #
    "create_company": (
        "פתיחת תיק חברה חדש בפורטל המשרד — נעשית דרך הכלי "
        "register_office_client (עם רישום ארגון ברצף) או route ה-admin; "
        "חשיפה ישירה הייתה יוצרת תיק מחויב בלי רישום ברצף."
    ),
    "update_company": (
        "עדכון פרטי תיק חברה בפורטל — פעולה רגישה ברמת משרד; נשארת "
        "ב-route ה-admin הייעודי עם הרשאות מפורשות."
    ),
    "create_user": (
        "יצירת משתמש בפורטל SUMIT — ניהול זהויות; סיכון הרשאות, "
        "בעלים בלבד דרך ה-admin."
    ),
    "set_user_permissions": (
        "שינוי הרשאות משתמש בפורטל — סיכון הסלמת הרשאות; בעלים בלבד "
        "דרך ה-admin."
    ),
    "remove_user_permissions": (
        "הסרת הרשאות משתמש בפורטל — ניהול זהויות; בעלים בלבד דרך "
        "ה-admin."
    ),
    "install_applications": (
        "התקנת אפליקציות בתיק משנה את חיובי/מכסות הלקוח אצל הספק — "
        "בעלים בלבד בפורטל."
    ),
    "user_login_redirect": (
        "מחזירה קישור התחברות-בשם-משתמש (impersonation) — עוקפת אימות; "
        "לעולם לא נחשפת לצ'אט."
    ),
    "update_recurring_settings": (
        "הגדרות חיוב אוטומטי גלובליות של התיק (כל ההוראות בבת אחת) — "
        "שינוי גורף; בעלים בלבד בפורטל."
    ),
}

# ------------------------------------------------------------------ #
# מתודות שכבר בשימוש כלי/שירות/route קיים — לא מכפילים ככלי חדש.
# שם מתודה → הצרכן הקיים.
# ------------------------------------------------------------------ #
ALREADY_COVERED: dict[str, str] = {
    "test_connection": "routes/admin.py + routes/cfo_sync.py + cli.py (בדיקת חיבור)",
    "get_balance": "routes/accounting.py + cli.py",
    "create_customer": "routes/accounting.py (בצ'אט: create_crm_entity)",
    "update_customer": "routes/accounting.py (בצ'אט: update_crm_entity)",
    "get_customer_details_url": "routes/accounting.py",
    "create_customer_remark": "routes/accounting.py",
    "get_document_pdf": "expense_ocr_pipeline + sumit_connector + routes/accounting.py",
    "get_document_details": "routes/accounting.py",
    "create_books_batch": (
        "routes/accounting.py במסלול הפעולות הבלתי-הפיכות (payload מאושר "
        "ושמור); בצ'אט קיים propose_books_batch שמציע בלבד"
    ),
    "get_document_supplier": "sumit_connector",
    "get_document_supplier_details": "ExpenseFilingService + sumit_connector",
    "get_vat_rate": "data_sync_service + routes/sync.py",
    "get_exchange_rate": "data_sync_service + routes/sync.py",
    "update_settings": "routes/accounting.py (הגדרות תיק — לא ערך צ'אט)",
    "create_income_item": "routes/accounting.py",
    "list_income_items": "data_sync_service + routes/accounting.py",
    "load_billing_transactions": "data_sync_service + routes/payments.py",
    "process_billing_transactions": "routes/payments.py",
    "get_billing_status": "routes/payments.py",
    "get_transaction": "routes/payments.py",
    "begin_redirect": "payment_request_service + routes/payments.py",
    "get_payment": "routes/payments.py",
    "list_payments": "data_sync_service + sumit_connector (סנכרון יומי)",
    "get_company_details": "routes/admin.py (מידע ברמת משרד)",
    "list_sms_mailing_lists": "routes/communications.py",
    "add_to_sms_mailing_list": "routes/communications.py",
}

# ------------------------------------------------------------------ #
# כלי מושקו → המתודות הציבוריות שהוא מפעיל (ישירות או דרך service).
# mapping ידני, נבדק מול הקוד — שער הכיסוי צורך את הצד הימני.
# ------------------------------------------------------------------ #
TOOL_METHOD_MAP: dict[str, tuple[str, ...]] = {
    # קיימים לפני גל 2
    "issue_document": ("create_document", "send_document"),
    "create_payment_link": ("create_payment_link",),
    "file_expense": ("add_expense",),
    "office_account_status": ("list_quotas",),
    # W3 גל 1
    "list_recurring": ("list_customer_recurring",),
    "create_recurring": (),  # POST ישיר ל-/billing/recurring/charge/ (אין מתודה ציבורית)
    "cancel_recurring": ("cancel_recurring",),
    "update_recurring": ("update_recurring",),
    "cancel_document": ("cancel_document",),
    "get_customer_debt_report": ("get_debt_report",),
    "send_collection_sms": ("send_sms",),
    # W3 גל 2 — קריאה
    "get_customer_debt": ("get_debt",),
    "get_next_document_number": ("get_next_document_number",),
    "list_sumit_documents": ("list_documents",),
    "list_crm_entities": ("list_entities",),
    "get_crm_entity": ("get_entity",),
    "count_crm_entity_usage": ("count_entity_usage",),
    "get_crm_entity_html": ("get_entity_print_html",),
    "get_crm_folder": ("get_folder",),
    "list_crm_folders": ("list_folders",),
    "list_crm_views": ("list_views",),
    "get_payment_methods": ("get_payment_methods",),
    "get_reference_numbers": ("get_reference_numbers",),
    "list_stock": ("list_stock",),
    "verify_bank_account": ("verify_bank_account",),
    "list_mailing_lists": ("list_mailing_lists",),
    "list_sms_senders": ("list_sms_senders",),
    # W3 גל 2 — כתיבה (כולן עוברות שער אישור מפורש בצ'אט)
    "set_next_document_number": ("set_next_document_number",),
    "move_document_to_books": ("move_document_to_books",),
    "create_document_from_existing": ("create_document_from_existing",),
    "create_crm_entity": ("create_entity",),
    "update_crm_entity": ("update_entity",),
    "archive_crm_entity": ("archive_entity",),
    "delete_crm_entity": ("delete_entity",),
    "set_payment_method": ("set_payment_methods",),
    "remove_payment_method": ("remove_payment_method",),
    "charge_customer": ("charge_customer",),
    "begin_payment_redirect": ("begin_payment_redirect",),
    "send_multiple_sms": ("send_multiple_sms",),
    "send_fax": ("send_fax",),
    "create_ticket": ("create_ticket",),
    "add_to_mailing_list": ("add_to_mailing_list",),
    "subscribe_trigger": ("subscribe_trigger",),
    "unsubscribe_trigger": ("unsubscribe_trigger",),
}
