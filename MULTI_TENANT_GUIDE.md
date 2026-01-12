# CFO System - Multi-Tenant Admin Guide

## 🎯 מערכת ניהול רב-ארגונית

המערכת תומכת בניהול מרובה ארגונים (multi-tenant) כאשר כל לקוח מקבל:
- חשבון ארגוני נפרד עם API credentials משלו
- ניהול משתמשים עם הרשאות מדורגות
- אינטגרציה עם SUMIT או מערכות הנהח"ש אחרות
- מעקב מלא אחר פעילות (audit logs)

## 📋 תפקידים במערכת

1. **Super Admin** - מנהל על:
   - יכול לנהל את כל הארגונים
   - יוצר ארגונים חדשים
   - רואה את כל הנתונים
   - לא משוייך לארגון ספציפי

2. **Admin** - מנהל ארגון:
   - מנהל משתמשים בארגון שלו
   - מעדכן הגדרות ארגון
   - מגדיר אינטגרציות API
   - רואה רק את נתוני הארגון שלו

3. **Accountant** - רואה חשבון:
   - ניהול חשבונות ועסקאות
   - גישה לדוחות פיננסיים
   - אישור תשלומים

4. **Manager** - מנהל:
   - צפייה בדוחות
   - ניהול לקוחות ופרויקטים

5. **User** - משתמש רגיל:
   - גישה בסיסית למערכת
   - הזנת נתונים

6. **Viewer** - צופה בלבד:
   - צפייה בלבד ללא אפשרות עריכה

## 🚀 התקנה ראשונית

### 1. התקנת תלויות

```bash
cd /workspaces/cfo
pip install -r requirements.txt
pip install -e .
```

### 2. הגדרת משתני סביבה

עדכן את `.env`:

```env
# Database
DATABASE_URL=sqlite:///./cfo.db

# Security (שנה בסביבת ייצור!)
JWT_SECRET_KEY=your-super-secret-key-change-in-production-min-32-chars
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# SUMIT API (אופציונלי)
SUMIT_API_KEY=your_sumit_api_key
SUMIT_COMPANY_ID=your_company_id

# OpenAI (אופציונלי)
OPENAI_API_KEY=your_openai_api_key
```

### 3. יצירת מנהל על ראשון

```bash
python create_admin.py
```

התסריט ישאל:
- Email
- Full Name
- Password (ואימות)
- Phone (אופציונלי)

### 4. הפעלת השרת

```bash
cfo run
```

השרת יעלה על `http://localhost:8000`

## 📚 API Documentation

גש ל-Swagger UI לתיעוד API אינטראקטיבי:
```
http://localhost:8000/api/docs
```

## 🔐 זרימת התחברות

### 1. הרשמה (Register)
```http
POST /api/admin/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "full_name": "שם מלא",
  "phone": "050-1234567",
  "role": "user",
  "organization_id": 1
}
```

### 2. התחברות (Login)
```http
POST /api/admin/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

תגובה:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "full_name": "שם מלא",
    "role": "user",
    "organization_id": 1
  }
}
```

### 3. שימוש ב-Token

הוסף header לכל בקשה:
```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

## 🏢 ניהול ארגונים

### יצירת ארגון חדש (Super Admin בלבד)

```http
POST /api/admin/organizations
Authorization: Bearer {super_admin_token}
Content-Type: application/json

{
  "name": "מסעדת השף",
  "business_type": "restaurant",
  "tax_id": "123456789",
  "phone": "03-1234567",
  "email": "info@restaurant.com",
  "address": "רחוב הראשי 1, תל אביב",
  "integration_type": "sumit",
  "api_credentials": {
    "api_key": "sumit_api_key_here",
    "company_id": "company_123"
  }
}
```

### עדכון הגדרות ארגון

```http
PATCH /api/admin/organizations/1
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "integration_type": "quickbooks",
  "api_credentials": {
    "client_id": "qb_client_id",
    "client_secret": "qb_secret"
  },
  "settings": {
    "default_currency": "ILS",
    "fiscal_year_start": "01-01"
  }
}
```

## 👥 ניהול משתמשים

### הוספת משתמש לארגון

```http
POST /api/admin/auth/register
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "email": "employee@restaurant.com",
  "password": "SecurePass123!",
  "full_name": "עובד מסעדה",
  "role": "accountant",
  "organization_id": 1
}
```

### רשימת משתמשים בארגון

```http
GET /api/admin/users?organization_id=1
Authorization: Bearer {admin_token}
```

### עדכון הרשאות משתמש

```http
PATCH /api/admin/users/5
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "role": "manager",
  "is_active": true
}
```

## 🔍 מעקב ופעילות (Audit Logs)

### צפייה בלוגים

```http
GET /api/admin/audit-logs?organization_id=1&action=LOGIN
Authorization: Bearer {admin_token}
```

תגובה:
```json
[
  {
    "id": 1,
    "user_id": 5,
    "organization_id": 1,
    "action": "LOGIN",
    "entity_type": "User",
    "entity_id": 5,
    "details": {},
    "created_at": "2026-01-12T10:30:00"
  }
]
```

## 🔗 סוגי אינטגרציות

### 1. SUMIT
```json
{
  "integration_type": "sumit",
  "api_credentials": {
    "api_key": "your_sumit_api_key",
    "company_id": "your_company_id"
  }
}
```

### 2. QuickBooks
```json
{
  "integration_type": "quickbooks",
  "api_credentials": {
    "client_id": "qb_client_id",
    "client_secret": "qb_client_secret",
    "realm_id": "qb_realm_id"
  }
}
```

### 3. Xero
```json
{
  "integration_type": "xero",
  "api_credentials": {
    "client_id": "xero_client_id",
    "client_secret": "xero_client_secret"
  }
}
```

### 4. Manual (ללא אינטגרציה)
```json
{
  "integration_type": "manual",
  "api_credentials": {}
}
```

## 📊 דוגמאות שימוש

### תרחיש 1: חברת ייעוץ עם מספר לקוחות

```python
# Super admin creates organizations for each client
POST /api/admin/organizations
{
  "name": "לקוח א - חברת הייטק",
  "business_type": "technology",
  "integration_type": "quickbooks"
}

POST /api/admin/organizations
{
  "name": "לקוח ב - מסעדה",
  "business_type": "restaurant",
  "integration_type": "sumit"
}

# Create admin for each organization
POST /api/admin/auth/register
{
  "email": "admin@client-a.com",
  "role": "admin",
  "organization_id": 1
}
```

### תרחיש 2: מסעדה עם צוות

```python
# Admin creates employees
POST /api/admin/auth/register
{
  "email": "accountant@restaurant.com",
  "role": "accountant",
  "organization_id": 1
}

POST /api/admin/auth/register
{
  "email": "manager@restaurant.com",
  "role": "manager",
  "organization_id": 1
}
```

## 🔒 אבטחה

### Best Practices

1. **Passwords**: השתמש בסיסמאות חזקות (מינימום 8 תווים, אותיות גדולות/קטנות, מספרים, סימנים)
2. **JWT Secret**: החלף את `JWT_SECRET_KEY` בסביבת ייצור
3. **HTTPS**: בייצור השתמש רק ב-HTTPS
4. **Rate Limiting**: הוסף rate limiting לנתיבי authentication
5. **Audit Logs**: עקוב אחר לוגים באופן קבוע

## 🐛 פתרון בעיות

### בעיה: "Email already registered"
- הדוא"ל כבר קיים במערכת
- השתמש בדוא"ל אחר או אפס סיסמה

### בעיה: "Access denied"
- המשתמש אין לו הרשאות מספיקות
- בדוק את תפקיד המשתמש

### בעיה: "Organization not found"
- ה-organization_id לא קיים
- וודא שהארגון נוצר תחילה

## 📞 תמיכה

לעזרה נוספת:
- Swagger Docs: http://localhost:8000/api/docs
- Audit Logs: בדוק את `audit_logs` table
- Logs: `cfo --log-level DEBUG run`
