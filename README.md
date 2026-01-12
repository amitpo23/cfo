# מערכת CFO - Chief Financial Officer Management System
## מערכת ניהול כספים מתקדמת 💰

מערכת מנהל הכספים הראשי שלך - מערכת מקיפה לניהול כלכלי, התחברות למערכות הנהלת חשבונות, ניתוח פיננסי ותובנות מבוססות AI.

## ✨ תכונות עיקריות

### 📊 ניהול פיננסי מלא
- **ניהול חשבונות** - יצירה ומעקב אחר חשבונות שונים (נכסים, התחייבויות, הכנסות, הוצאות)
- **ניהול עסקאות** - רישום ומעקב אחר כל העסקאות הפיננסיות
- **מאזן אוטומטי** - עדכון אוטומטי של יתרות חשבונות
- **סיכומים פיננסיים** - דוחות רווח והפסד, מצב פיננסי ועוד

### 🔌 התחברות למערכות הנהלת חשבונות
- מבנה מודולרי המאפשר התחברות לכל מערכת הנהלת חשבונות
- תמיכה עתידית ב-QuickBooks, Xero ועוד
- מערכת מדומה (Mock) להדגמה ופיתוח

### 📈 דוחות מתקדמים
- **דוח מאזן** - מצב נכסים והתחייבויות
- **דוח עסקאות** - סיכום מפורט של כל העסקאות
- **דוח רווח והפסד** - הכנסות והוצאות לפי תקופה
- ייצוא ל-Excel עם עיצוב מקצועי

### 🤖 תובנות AI
- **ניתוח פיננסי אוטומטי** - ניתוח מצב פיננסי והמלצות
- **זיהוי דפוסים** - זיהוי דפוסים בעסקאות
- **ייעוץ פיננסי** - שאל כל שאלה פיננסית וקבל תשובה מבוססת AI

### 🖥️ ממשק שורת פקודה (CLI)
ממשק נוח ואינטואיטיבי לביצוע כל הפעולות בקלות

## 🚀 התקנה

### דרישות מקדימות
- Python 3.10 ומעלה
- pip

### שלבי התקנה

1. **שיבוט או הורדת הפרויקט**
```bash
cd /workspaces/cfo
```

2. **יצירת סביבה וירטואלית**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# או
venv\Scripts\activate  # Windows
```

3. **התקנת תלויות**
```bash
pip install -r requirements.txt
pip install -e .
```

4. **הגדרת משתני סביבה**
```bash
cp .env.example .env
# ערוך את קובץ .env והוסף את ה-API keys שלך
```

5. **אתחול מסד הנתונים**
```bash
cfo init
```

## 📖 שימוש

### פקודות בסיסיות

#### אתחול המערכת
```bash
cfo init
```

#### הוספת חשבון חדש
```bash
cfo add-account --name "חשבון בנק" --type asset --balance 10000
```

#### רשימת חשבונות
```bash
cfo list-accounts
```

#### הוספת עסקה
```bash
cfo add-transaction --account-id 1 --type income --amount 5000 --description "תשלום מלקוח"
```

#### רשימת עסקאות אחרונות
```bash
cfo list-transactions --days 30
```

#### סיכום פיננסי
```bash
cfo summary --days 30
```

#### יצירת דוח Excel
```bash
cfo report --days 30 --output "monthly_report.xlsx"
```

### תכונות AI (דורש API key של OpenAI)

#### ניתוח מצב פיננסי
```bash
cfo analyze --days 30
```

#### שאלת שאלה פיננסית
```bash
cfo ask "האם כדאי לי להשקיע בציוד חדש?"
```

### הדגמה עם נתונים מדומים
```bash
cfo demo
```

## 🏗️ מבנה הפרויקט

```
cfo/
├── src/cfo/
│   ├── __init__.py
│   ├── cli.py                 # ממשק שורת פקודה
│   ├── config.py              # הגדרות מערכת
│   ├── database.py            # ניהול מסד נתונים
│   ├── models.py              # מודלים פיננסיים
│   ├── integrations/          # אינטגרציות למערכות חיצוניות
│   │   ├── base.py           # מחלקת בסיס לאינטגרציות
│   │   └── mock_integration.py  # אינטגרציה מדומה
│   └── services/              # שירותי ליבה
│       ├── financial_service.py  # פעולות פיננסיות
│       ├── report_service.py     # יצירת דוחות
│       └── ai_insights.py        # תובנות AI
├── requirements.txt
├── setup.py
├── .env.example
└── README.md
```

## 🔧 הגדרות

ערוך את קובץ `.env` כדי להגדיר:

### מסד נתונים
```
DATABASE_URL=sqlite:///./cfo.db
# או PostgreSQL:
# DATABASE_URL=postgresql://user:password@localhost/cfo_db
```

### API Keys למערכות הנהלת חשבונות
```
QUICKBOOKS_CLIENT_ID=your_id
QUICKBOOKS_CLIENT_SECRET=your_secret
XERO_CLIENT_ID=your_id
XERO_CLIENT_SECRET=your_secret
```

### OpenAI לתובנות AI
```
OPENAI_API_KEY=your_openai_api_key
```

## 🌟 דוגמאות שימוש

### תרחיש 1: התחלת עבודה עם המערכת

```bash
# אתחול
cfo init

# הוספת חשבונות בסיסיים
cfo add-account --name "חשבון בנק ראשי" --type asset --balance 50000
cfo add-account --name "הכנסות" --type revenue --balance 0
cfo add-account --name "הוצאות תפעול" --type expense --balance 0

# רישום עסקאות
cfo add-transaction --account-id 2 --type income --amount 15000 --description "מכירת שירותים"
cfo add-transaction --account-id 3 --type expense --amount 5000 --description "משכורות"

# צפייה במצב נוכחי
cfo summary
```

### תרחיש 2: יצירת דוח חודשי

```bash
# סיכום 30 הימים האחרונים
cfo summary --days 30

# יצירת דוח Excel מפורט
cfo report --days 30 --output "report_december_2025.xlsx"

# ניתוח עם AI
cfo analyze --days 30
```

### תרחיש 3: קבלת ייעוץ פיננסי

```bash
# שאל שאלה כללית
cfo ask "מה המצב הפיננסי שלי?"

# שאל שאלה ספציפית
cfo ask "האם אני יכול להרשות לעצמי לשכור עובד נוסף?"

# בקש המלצות
cfo ask "איך אני יכול לשפר את תזרים המזומנים שלי?"
```

## 🔮 תכונות עתידיות

- [ ] ממשק Web (FastAPI)
- [ ] אפליקציית Mobile
- [ ] אינטגרציה מלאה ל-QuickBooks
- [ ] אינטגרציה מלאה ל-Xero
- [ ] תמיכה במערכות ישראליות (חשבשבת, וכו')
- [ ] ניבוי תזרים מזומנים
- [ ] התראות אוטומטיות
- [ ] דוחות גרפיים
- [ ] ייצוא ל-PDF

## 🤝 תרומה לפרויקט

נשמח לקבל תרומות! אנא:
1. Fork the repository
2. צור branch חדש לתכונה שלך
3. Commit השינויים
4. Push ל-branch
5. פתח Pull Request

## 📄 רישיון

MIT License - ראה קובץ LICENSE לפרטים

## 💬 תמיכה

לשאלות ובעיות, אנא פתח Issue בגיטהאב.

## 🙏 תודות

נבנה עם:
- FastAPI
- SQLAlchemy
- Click & Rich
- OpenAI
- Pandas

---

**נבנה עם ❤️ למען ניהול פיננסי חכם ויעיל**

### Backend (Python + FastAPI)
- **Complete SUMIT API Integration**: All endpoints implemented
  - Accounting (Customers, Documents, Income Items, General Operations)
  - Credit Card Terminal (Billing, Gateway, Vault)
  - CRM (Data, Schema, Views)
  - Payments (Standard & Recurring)
  - Communications (SMS, Email, Fax)
  - Customer Service
  - Company & User Management
  - Stock Management
  - Webhooks

- **Database Models**: SQLAlchemy models for all entities
- **RESTful API**: FastAPI routes with automatic documentation
- **Authentication**: JWT-based authentication system
- **Type Safety**: Pydantic models for all requests/responses

### Frontend (React + TypeScript)
- **Customer Management**: Dashboard for managing customers
- **Document Manager**: Create and manage invoices, receipts, quotes
- **Payment Processing**: Integrated payment interface with card tokenization
- **Analytics Dashboard**: Charts and reports for financial insights
- **Responsive Design**: Modern UI with Tailwind CSS

## 📁 Project Structure

```
cfo/
├── src/cfo/
│   ├── integrations/
│   │   ├── base.py                    # Base integration class
│   │   ├── sumit_integration.py       # Complete SUMIT API integration
│   │   └── sumit_models.py            # Pydantic models for SUMIT
│   ├── api/
│   │   ├── __init__.py                # FastAPI app initialization
│   │   ├── dependencies.py            # Auth and dependencies
│   │   └── routes/
│   │       ├── accounting.py          # Accounting endpoints
│   │       ├── crm.py                 # CRM endpoints
│   │       ├── payments.py            # Payment endpoints
│   │       ├── communications.py      # SMS, Email, Fax endpoints
│   │       └── admin.py               # Admin endpoints
│   ├── models.py                      # Database models
│   ├── config.py                      # Configuration
│   └── database.py                    # Database connection
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CustomerDashboard.tsx
│   │   │   ├── DocumentManager.tsx
│   │   │   ├── PaymentInterface.tsx
│   │   │   └── AnalyticsDashboard.tsx
│   │   ├── services/
│   │   │   └── api.ts                 # API service client
│   │   └── App.tsx                    # Main application
│   └── package.json
└── requirements.txt

```

## 🛠️ Installation

### Backend Setup

1. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**:
Create a `.env` file in the project root:
```env
# SUMIT API Configuration
SUMIT_API_KEY=your_sumit_api_key_here
SUMIT_COMPANY_ID=your_company_id_here

# Database
DATABASE_URL=sqlite:///./cfo.db

# Security
SECRET_KEY=your_secret_key_for_jwt

# Optional
OPENAI_API_KEY=your_openai_key_for_insights
```

4. **Initialize database**:
```bash
python -c "from src.cfo.database import init_db; init_db()"
```

5. **Run the backend server**:
```bash
uvicorn src.cfo.api:app --reload --port 8000
```

The API will be available at `http://localhost:8000`
- API Documentation: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

### Frontend Setup

1. **Navigate to frontend directory**:
```bash
cd frontend
```

2. **Install dependencies**:
```bash
npm install
```

3. **Configure environment**:
Create `frontend/.env`:
```env
VITE_API_BASE_URL=http://localhost:8000/api
```

4. **Run the development server**:
```bash
npm run dev
```

The frontend will be available at `http://localhost:3000`

## 🔧 Configuration

### SUMIT API Setup

1. Get your API credentials from [SUMIT Developer Portal](https://app.sumit.co.il/developers/api/)
2. Add them to your `.env` file
3. Test the connection:
```bash
curl -X GET http://localhost:8000/api/admin/test-connection \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## 📚 API Documentation

### Authentication

All API endpoints (except health checks) require authentication using JWT tokens.

**Get Token** (you'll need to implement this):
```bash
POST /api/auth/login
{
  "username": "user",
  "password": "password"
}
```

**Use Token**:
```bash
Authorization: Bearer YOUR_JWT_TOKEN
```

### Key Endpoints

#### Customers
- `POST /api/accounting/customers` - Create customer
- `PUT /api/accounting/customers/{id}` - Update customer
- `GET /api/accounting/customers/{id}/debt` - Get customer debt

#### Documents
- `POST /api/accounting/documents` - Create document
- `GET /api/accounting/documents` - List documents
- `GET /api/accounting/documents/{id}/pdf` - Download PDF
- `POST /api/accounting/documents/send` - Send by email

#### Payments
- `POST /api/payments/charge` - Process payment
- `GET /api/payments` - List payments
- `GET /api/payments/methods/{customer_id}` - Get payment methods

#### CRM
- `POST /api/crm/entities` - Create entity
- `GET /api/crm/entities` - List entities
- `GET /api/crm/folders` - List folders

#### Communications
- `POST /api/communications/sms/send` - Send SMS
- `POST /api/communications/tickets` - Create ticket

See full API documentation at `http://localhost:8000/api/docs`

## 🎯 Usage Examples

### Create a Customer
```python
from src.cfo.integrations.sumit_integration import SumitIntegration
from src.cfo.integrations.sumit_models import CustomerRequest

async with SumitIntegration(api_key="your_key") as sumit:
    customer = await sumit.create_customer(
        CustomerRequest(
            name="John Doe",
            email="john@example.com",
            phone="+972501234567"
        )
    )
    print(f"Created customer: {customer.customer_id}")
```

### Create an Invoice
```python
from src.cfo.integrations.sumit_models import DocumentRequest, DocumentItem
from decimal import Decimal

async with SumitIntegration(api_key="your_key") as sumit:
    invoice = await sumit.create_document(
        DocumentRequest(
            customer_id="customer_123",
            document_type="invoice",
            items=[
                DocumentItem(
                    description="Consulting Services",
                    quantity=Decimal("10"),
                    price=Decimal("500")
                )
            ]
        )
    )
    print(f"Created invoice: {invoice.document_number}")
```

### Process Payment
```python
from src.cfo.integrations.sumit_models import ChargeRequest
from decimal import Decimal

async with SumitIntegration(api_key="your_key") as sumit:
    payment = await sumit.charge_customer(
        ChargeRequest(
            customer_id="customer_123",
            amount=Decimal("5000"),
            currency="ILS",
            description="Invoice payment"
        )
    )
    print(f"Payment status: {payment.status}")
```

## 🧪 Testing

Run backend tests:
```bash
pytest
```

Run frontend tests:
```bash
cd frontend
npm test
```

## 📦 Deployment

### Backend Deployment

1. **Using Docker**:
```bash
docker build -t cfo-backend .
docker run -p 8000:8000 --env-file .env cfo-backend
```

2. **Using Gunicorn**:
```bash
gunicorn src.cfo.api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Frontend Deployment

```bash
cd frontend
npm run build
# Deploy the dist/ folder to your hosting service
```

## 🔐 Security

- JWT tokens expire after 30 minutes (configurable)
- API keys are stored securely in environment variables
- Card data is tokenized and not stored in the database
- All API communications use HTTPS in production

## 📝 Database Schema

The system includes the following main tables:
- `customers` - Customer information
- `documents` - Invoices, receipts, quotes
- `payments` - Payment transactions
- `recurring_payments` - Subscription/recurring charges
- `income_items` - Products and services
- `crm_entities` - CRM data
- `audit_logs` - Activity tracking

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is proprietary software. All rights reserved.

## 🆘 Support

For issues related to:
- **SUMIT API**: Contact SUMIT support at https://app.sumit.co.il/developers/api/
- **This System**: Open an issue in the repository

## 🔗 Links

- [SUMIT API Documentation](https://app.sumit.co.il/developers/api/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

## 📊 Implemented SUMIT API Endpoints

### ✅ Accounting
- [x] Create/Update Customer
- [x] Customer Details & Debt
- [x] Create/List/Cancel Documents
- [x] Send Documents by Email
- [x] Download Document PDF
- [x] Add Expenses
- [x] Debt Reports
- [x] Income Items Management
- [x] Bank Account Verification
- [x] VAT & Exchange Rates
- [x] Settings Management
- [x] Document Numbering

### ✅ Payments
- [x] Charge Customer
- [x] Payment Methods Management
- [x] Payment History
- [x] Recurring Payments
- [x] Multivendor Charges
- [x] Payment Redirect Flow
- [x] Upay Terminal Integration

### ✅ Credit Card Terminal
- [x] Create Transactions
- [x] Transaction Status
- [x] Redirect Flow
- [x] Billing Transactions
- [x] Card Tokenization (Vault)
- [x] Single-Use Tokens

### ✅ CRM
- [x] Create/Update/Delete Entities
- [x] List Entities
- [x] Entity Usage Count
- [x] Print HTML
- [x] Folder Management
- [x] Views

### ✅ Communications
- [x] Send SMS (Single & Multiple)
- [x] SMS Mailing Lists
- [x] Email Mailing Lists
- [x] Send Fax
- [x] Send Letters (Mail Service)

### ✅ Customer Service
- [x] Create Tickets

### ✅ Admin
- [x] Company Management
- [x] User Management
- [x] Permissions
- [x] Stock Management
- [x] Webhooks
- [x] Quotas
- [x] Application Installation

---

**Built with ❤️ for efficient financial management**