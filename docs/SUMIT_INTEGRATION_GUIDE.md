# SUMIT Integration Guide - Complete Documentation

**Date:** June 25, 2026  
**Version:** 1.0  
**Status:** Complete Reference

---

## Part 1: Bank Account Integration (חיבור תיק הנהלת חשבונות לצד)

### Overview
SUMIT enables accounting firms to connect client accounting files with independent business accounts within the system. This creates a seamless connection between firm-managed files and client business accounts.

### Key Capabilities After Connection
- Import income documents created by the client
- File and organize expense documents uploaded by the client
- Process expense receipts (for advanced clients)
- Manage client business operations from firm account

### Setup Methods

#### Method 1: During New File Creation
When creating a new client file in SUMIT:
1. Select "Business establishment for client" option
2. System grants client owner permissions to:
   - Upload expenses
   - Import income history
   - Create revenue documents
   - Process credit card settlements
   - Manage business operations

#### Method 2: Single File Import
When importing a single file:
1. Select "Business establishment for client" option
2. System automatically connects file to client's business account
3. Connection completes upon import finish

#### Method 3: Bulk Import
Using "Import files in table" screen:
1. Mark multiple files for business account creation
2. System automatically connects each file to corresponding business
3. All connections happen in batch during import

### Connection Process Flow

#### Step 1: Click "Connect Client Business" Button
- Location: Top toolbar in SUMIT
- Available after creating client file in firm's account

#### Step 2: System Evaluates Authorization Status
The system checks one of three scenarios:

**Scenario A: Existing Authorization**
- Client already has business account
- Client previously granted permission
- Action: Connection executes immediately upon confirmation
- Time: Instant
- User action: Click confirm

**Scenario B: Pending Authorization**
- Client has business account
- Authorization not yet granted
- Action: System sends email request to client
- Client approval trigger: Client approves in email
- Result: Connection completes automatically
- Time: Automatic upon client approval

**Scenario C: No Existing Account**
- Client doesn't have SUMIT business account
- Action: System creates new business account
- Action: Sends invitation email to client
- Result: Immediate connection established
- Time: Instant (client account created automatically)

#### Step 3: Verify Connection
- Check firm-client file link established
- Confirm client can upload documents
- Verify income/expense sync

### Post-Connection Features

#### Document Management
1. **Income Documents**
   - Client creates income documents
   - Firm imports and files them
   - Automatic categorization available

2. **Expense Documents**
   - Client uploads expense receipts
   - Firm organizes and files them
   - OCR processing for receipt data
   - Automatic supplier matching

3. **Credit Card Settlements**
   - Client uploads credit card statements
   - Automatic transaction matching
   - Period reconciliation

#### Client Permissions
- Upload expenses
- Create revenue documents
- Import income history
- Process settlements
- Access shared firm tools

### Disconnection Procedure

#### How to Disconnect
Navigation path:
```
More Menu → Additional Links → Advanced Actions → Disconnect Client Business from Your Firm
```

#### What Disconnection Does
- Removes file-to-business link only
- **Does NOT affect:**
  - User permissions
  - Team access
  - Document history
  - Accounting records

#### After Disconnection
- Client cannot upload new documents
- Firm retains all previously imported documents
- Can reconnect later if needed

### Technical Integration Points

#### Authentication
- Firm initiates connection in SUMIT UI
- Client receives email notification
- Client approves (if needed)
- System verifies permissions

#### Data Sync
- Firm imports client documents
- SUMIT handles categorization
- System matches expenses to suppliers
- Income documents tagged by source

#### Error Handling
- Failed connection attempts return error message
- Client approval timeout: 30 days
- Reconnection possible after disconnection

### Validation Rules

#### Before Connection
- [ ] Client file exists in firm account
- [ ] Client business account accessible
- [ ] Email contact valid for client
- [ ] Permissions properly configured

#### After Connection
- [ ] Client can upload documents
- [ ] Income/expense sync working
- [ ] File status shows "Connected"
- [ ] No permission errors

### Common Integration Scenarios

#### Scenario 1: New Client Onboarding
1. Create new file in SUMIT
2. Select "Business establishment for client"
3. File automatically connects to new client account
4. Client receives invitation email
5. Client approves (if needed)
6. Ready for document upload

**Timeline:** 5-10 minutes

#### Scenario 2: Existing Client Migration
1. Import existing client file
2. Select "Business establishment for client"
3. System creates new business account
4. Sends connection invitation to client
5. Client approves
6. Historical documents can be imported

**Timeline:** 10-15 minutes

#### Scenario 3: Reconnecting Disconnected Client
1. Select "Connect Client Business" in toolbar
2. Select existing client business account
3. System sends re-authorization email
4. Client approves
5. Connection re-established

**Timeline:** 5-10 minutes (+ client approval time)

---

## Part 2: Accounting Management System (מחירון הנהלת חשבונות)

### System Overview
SUMIT provides a complete accounting management system ("מערכת הנהלת חשבונות מלאה") including comprehensive financial management, tax compliance, and reporting features.

### Core Features Included in All Tiers

#### Bookkeeping
- Single-entry bookkeeping
- Double-entry bookkeeping
- Automatic transaction matching
- Receipt/invoice matching

#### Tax & Compliance
- VAT reporting (monthly/quarterly)
- Annual reports (forms 1301 and 6111)
- Tax planning tools
- Compliance validation

#### Document Management
- Digital expense filing with OCR
- OCR learning (improves accuracy over time)
- Supplier database matching
- Expense categorization
- Receipt image storage

#### Bank Integration
- Automatic bank synchronization
- Multi-account support
- Transaction import
- Bank statement matching
- Reconciliation tools

#### Client Portal
- Client business account access
- Document upload capability
- Income/expense management
- Report viewing
- Status tracking

#### Reporting
- Financial statements
- P&L reports
- Balance sheets
- VAT reports
- Annual tax forms

### Pricing Structure

#### Tier-Based Model
SUMIT operates on a tiered pricing system with three service levels: Silver, Gold, and Diamond.

#### Pricing Components

**Fixed Monthly Charge (Tier Cost)**
- Determined by selected tier (Silver, Gold, or Diamond)
- "בסכום קבוע" (fixed monthly amount)
- Charged per subscription
- Includes base support and features

**Variable Per-Account Costs**
- Additional charge for each account file
- Varies by account type (double-entry, exempt owner, single-entry)
- Charges exceeding tier price billed separately
- Credit system: Monthly credits up to tier cost included

#### Tier Details

**Gold Tier (Standard)**
- **Cost:** ₪1,990 + VAT/month
- **Annual Reports:** Included at no extra cost
- **Accounts:** Unlimited (variable charges apply per account)
- **Support:** Standard email & phone
- **Best for:** Most accounting firms

**Silver Tier (Startup)**
- **Cost:** Lower than Gold (exact pricing varies)
- **Features:** Core bookkeeping and tax compliance
- **Accounts:** Limited per tier
- **Support:** Email support
- **Best for:** New offices, small firms

**Diamond Tier (Premium)**
- **Cost:** Higher than Gold (exact pricing varies)
- **Features:** All features + advanced support
- **Accounts:** Unlimited with priority processing
- **Support:** Priority phone, dedicated manager
- **Best for:** Large firms, high transaction volume

#### Special Account Types

**Frozen Accounts**
- Cost: ₪2 + VAT/month
- Use: Previously active, now inactive
- Status: Historical records preserved
- Purpose: Archive with minimal cost

**Demo Accounts**
- Cost: No charge
- Use: Testing and training
- Limitation: Cannot process real transactions
- Duration: Unlimited

### Billing Model

#### Monthly Billing Cycle
- **Billing Date:** 1st of each month
- **Coverage Period:** Upcoming month
- **Payment Method:** Automatic charge to registered account

#### Initial Payment
- **Timing:** 30 days after creating first account
- **Amount:** Tier cost + pro-rata account charges
- **What triggers:** First account creation

#### Monthly Charges Calculation
```
Total Monthly Cost = Tier Cost + Variable Account Charges

Where:
- Tier Cost = Selected tier (Silver/Gold/Diamond)
- Variable Account Charges = (# of accounts × per-account rate) - Tier credit
```

#### Credit System
- Monthly credit = Tier cost (included in price)
- Additional account charges billed separately
- Excess usage monthly (no annual contracts)
- Flexible upgrade/downgrade between tiers

### Trial & Startup Options

#### Trial Mode
- **Cost:** Free
- **Account Limit:** Up to 2 limited account files
- **Duration:** Indefinite (can stay on trial)
- **Features:** Full system access (with limitations)
- **Use Case:** Testing before commitment
- **Upgrade:** Anytime to paid tier

#### Startup Mode
- **Cost:** Unlimited accounts, no minimum payment
- **Account Limit:** Unlimited
- **Duration:** Ideal for migration periods
- **Features:** Full system access
- **Payment:** Only pay for actual usage
- **Use Case:** New offices, migrations, startups

#### Transition Path
1. Start in Trial Mode
2. Test with 2 accounts
3. Decide to scale
4. Switch to Startup Mode (no minimum commitment)
5. Upgrade to paid tier when ready

### Feature Comparison by Tier

| Feature | Silver | Gold | Diamond |
|---------|--------|------|---------|
| Double-entry bookkeeping | ✓ | ✓ | ✓ |
| VAT reporting | ✓ | ✓ | ✓ |
| Annual reports (1301/6111) | ✓ | ✓ | ✓ |
| Digital expense filing | ✓ | ✓ | ✓ |
| OCR processing | ✓ | ✓ | ✓ |
| Bank synchronization | ✓ | ✓ | ✓ |
| Client portal | ✓ | ✓ | ✓ |
| Unlimited accounts | ✗ | ✓ | ✓ |
| Annual reports included | ✗ | ✓ | ✓ |
| Priority support | ✗ | ✗ | ✓ |
| Dedicated manager | ✗ | ✗ | ✓ |

### Integration with Our CFO System

#### Data Flow
```
Our Backend ↔ SUMIT API ↔ SUMIT Client Business Account ↔ Client

Key Integration Points:
1. Document upload (expenses, invoices)
2. Income import
3. Bank transaction sync
4. Expense categorization
5. Report generation
```

#### Capabilities We Can Leverage
1. **Automatic Bank Sync** - Use SUMIT's bank connection
2. **Document Processing** - Use SUMIT's OCR and categorization
3. **Client Portal** - Redirect clients to SUMIT for uploads
4. **Reporting** - Pull SUMIT reports via API
5. **Compliance** - Validate against SUMIT tax forms

---

## Implementation Checklist

### Before Integration
- [ ] Verify firm SUMIT account access
- [ ] Confirm client business account exists
- [ ] Test connection workflow manually
- [ ] Validate email delivery
- [ ] Check permissions configuration

### During Integration
- [ ] Implement "Connect Client Business" API call
- [ ] Handle authorization scenarios (A/B/C)
- [ ] Implement document import workflow
- [ ] Set up expense matching
- [ ] Configure client portal link

### After Integration
- [ ] Verify client can upload documents
- [ ] Test income/expense sync
- [ ] Validate expense categorization
- [ ] Check report generation
- [ ] Monitor for errors

### Testing Scenarios
- [ ] New client connection (Scenario C)
- [ ] Existing authorized client (Scenario A)
- [ ] Client authorization flow (Scenario B)
- [ ] Bulk import multiple clients
- [ ] Disconnect and reconnect
- [ ] Error handling (invalid email, etc.)

---

## Error Handling & Troubleshooting

### Common Errors

**Error: "Client account not found"**
- Cause: Scenario C - no existing account
- Solution: System creates account automatically
- Verify: Check client's email for invitation

**Error: "Authorization pending"**
- Cause: Scenario B - client hasn't approved
- Solution: Wait for client approval or resend email
- Timeline: Max 30 days

**Error: "Connection already exists"**
- Cause: File already connected to client account
- Solution: Use disconnect/reconnect workflow
- Verify: Check firm's "Connected Accounts" list

**Error: "Invalid email address"**
- Cause: Client email format incorrect
- Solution: Verify and correct email before connecting
- Verify: Send test email first

### Support Resources
- SUMIT Help Center: https://help.sumit.co.il
- Email Support: support@sumit.co.il
- Phone: Available for Gold/Diamond tiers

---

**Document Version:** 1.0  
**Last Updated:** June 25, 2026  
**Next Review:** September 25, 2026

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
