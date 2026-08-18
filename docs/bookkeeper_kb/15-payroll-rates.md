# שכר — מדרגות מס, ביטוח לאומי ונקודות זיכוי

**נספג ממרכז הידע `israeli-payroll-calculator` ב-18/08/2026.**

מנהל החשבונות נדרש לשיעורים האלה בכל בדיקת תלוש, בכל פקודת שכר ובכל שאלה על עלות מעביד. עד היום הם היו קיימים בסקיל של Claude Code בלבד — כלומר בלתי-נגישים למושקו ולפרודקשיין.

> **מקור וּוֶתֶק.** התוכן שלהלן מועתק מילולית מקבצי הייחוס של הסקיל — לא הוקלד מחדש, כי שגיאת תעתיק בשיעור מס היא נזק ממשי. כל שיעור נושא את הציטוט החקיקתי ותאריך התוקף שהופיעו במקור. **שיעור בלי תאריך תוקף מפורש — יש לאמת לפני שימוש בדיווח.**

## מתוך `tax-brackets.md`

# Israeli Income Tax Brackets (2026)

Amendment 288 to the Income Tax Ordinance (published 31.3.2026, retroactive to 1.1.2026) widened brackets 3, 4, and 5. Brackets 1, 2, 6, 7 are unchanged from 2025. The earlier "frozen 2025-2027" freeze was lifted by this amendment for 2026.


## Monthly Brackets (2026)
| Bracket | Monthly Income (NIS) | Tax Rate |
|---------|---------------------|----------|
| 1 | 0 - 7,010 | 10% |
| 2 | 7,011 - 10,060 | 14% |
| 3 | 10,061 - 19,000 | 20% |
| 4 | 19,001 - 25,100 | 31% |
| 5 | 25,101 - 46,690 | 35% |
| 6 | 46,691 - 60,130 | 47% |
| 7 | 60,131+ | 50% |

## Annual Brackets (2026)
| Bracket | Annual Income (NIS) | Tax Rate |
|---------|-------------------|----------|
| 1 | 0 - 84,120 | 10% |
| 2 | 84,121 - 120,720 | 14% |
| 3 | 120,721 - 228,000 | 20% |
| 4 | 228,001 - 301,200 | 31% |
| 5 | 301,201 - 560,280 | 35% |
| 6 | 560,281 - 721,560 | 47% |
| 7 | 721,561+ | 50% |

## What Changed vs. 2025 (Amendment 288)
| Bracket | 2025 Monthly | 2026 Monthly |
|---------|-------------|--------------|
| 3 (20%) | 10,061 - 16,150 | 10,061 - 19,000 |
| 4 (31%) | 16,151 - 22,440 | 19,001 - 25,100 |
| 5 (35%) | 22,441 - 46,690 | 25,101 - 46,690 |

Income in the 16,151 - 19,000 band, which was taxed at 31% in 2025, is now taxed at 20%. Income in 22,441 - 25,100, which was taxed at 35% in 2025, is now taxed at 31%. Employees saw a one-time retroactive correction in their March 2026 payslip.

## Surtax (Mas Yesafim)
- Income above 721,560 NIS/year (60,130 NIS/month): additional 3% surtax
- Applies to all income types (salary, capital gains, etc.)
- Effectively creates a 50% + 3% = 53% marginal rate for very high earners

## Tax Credit Points (Nekudot Zikui)
Value per point (2026): **2,904 NIS/year** (~242 NIS/month)

| Circumstance | Points |
|-------------|--------|
| Israeli resident (base) | 2.25 |
| Female (additional) | +0.5 |
| New immigrant (year 1-1.5) | +3.0 |
| New immigrant (year 1.5-2) | +2.0 |
| New immigrant (year 2-3.5) | +1.0 |
| Child under 18 | +1.0 |
| Child under 5 (for women) | +1.5 |
| Single parent | +1.0 |
| Disabled | +2.0 |
| Combat soldier (3 years) | +2.0 |
| Academic degree | +1.0 (year of completion + 1 year) |

## Pension Tax Credit (Zikui Gemel, Section 45a)
Separate from credit points. An employee who pays into a pension fund gets a tax credit of 35% of the eligible contribution:
- Eligible contribution = min(actual employee contribution, 7% x min(insured salary, 9,700 NIS/month))
- Max monthly credit (2026): 35% x 679 = 237.65 NIS/month
- Applied after gross tax, together with credit points. Cannot create negative tax.

See `references/credit-points.md` for the full pension credit calculation.

NOTE: Brackets may update via further amendments; NI ceilings and credit-point value update each January 1.
Always verify current values at https://www.gov.il/he/service/income-tax-calculator.

## מתוך `bituach-leumi-rates.md`

# Bituach Leumi (National Insurance) Rates (2026)

Amendment 252 to the National Insurance Law (effective 1.1.2026) raised the reduced-tier employee rate from 0.4% to 1.04% and the reduced-tier employer rate from 3.55% to 4.51%, and it updated the reduced-tier threshold to 7,703 NIS/month (60% of the 2026 average wage of 13,769 NIS/month). Full-bracket rates also edged up via health-tax re-basing.

## Employee Rates

### Reduced Bracket (up to 7,703 NIS/month)
| Component | Employee | Employer |
|-----------|----------|----------|
| National Insurance | 1.04% | 4.51% |
| Health Tax | 3.23% | 0.00% |
| **Total** | **4.27%** | **4.51%** |

### Full Bracket (7,704 - 51,910 NIS/month)
| Component | Employee | Employer |
|-----------|----------|----------|
| National Insurance | 7.00% | 7.60% |
| Health Tax | 5.17% | 0.00% |
| **Total** | **12.17%** | **7.60%** |

Note: Health tax is an employee-only deduction in Israel. Employers do not contribute to health tax (mas briut).

### Maximum Insurable Salary (2026)
- **51,910 NIS/month** (unchanged from 2025)
- Salary above this amount: no additional NI or health deductions.
- The reduced-tier threshold (7,703) is 60% of the average wage and updates each January 1 by CPI through 2028, then by average-wage growth from 2029.

### What Changed vs. 2025
| Parameter | 2025 | 2026 |
|-----------|------|------|
| Reduced-tier threshold | 7,522 | 7,703 |
| Employee NI (reduced) | 0.40% | 1.04% |
| Employer NI (reduced) | 3.55% | 4.51% |
| Employee health (reduced) | 3.10% | 3.23% |
| Employee health (full) | 5.00% | 5.17% |
| Employee NI (full) | 7.00% | 7.00% (unchanged) |
| Employer NI (full) | 7.60% | 7.60% (unchanged) |
| Max insurable | 50,695 | 51,910 |

### Worked Example (2026)
Employee, monthly gross 12,000 NIS, no shovi rechev:
- Reduced portion: 7,703 x 4.27% = 329 NIS
- Full portion: (12,000 - 7,703) x 12.17% = 4,297 x 12.17% = 523 NIS
- Total employee NI + health: ~852 NIS/month

(2025 equivalent: 7,522 x 3.5% + 4,478 x 12.0% = 263 + 537 = 800 NIS/month. The shift of 52 NIS/month roughly matches the Calcalist "576 NIS/year extra for employees" figure.)

## Self-Employed Rates (2026)
Self-employed got a larger hit under Amendment 252 (reduced-tier rates rose sharply). Consult btl.gov.il for exact current rates before computing atzmai payroll.

### Reduced Bracket (up to 7,703 NIS/month)
- National Insurance: ~5.97% (was 2.87% in 2025)
- Health Tax: ~3.23%

### Full Bracket (7,704 - 51,910 NIS/month)
- National Insurance: ~17.83% (was 12.83% in 2025)
- Health Tax: ~5.17%

## Exemptions
- Under age 18: Reduced rates
- Over retirement age (67M/62-65F): Reduced rates, no health tax
- New immigrants: 12-month exemption from NI (not health)
- Income below minimum: Minimum payment still required

## Shovi Rechev (Company Car Use Value)
- Shovi rechev is subject to NI and health tax on the employee side (employee pays NI and health on the taxable gross = cash + shovi rechev).
- Employer NI also applies to shovi rechev.
- Shovi rechev is NOT part of the pension-insurable salary.

## Payment
- Employee: Deducted from salary by employer
- Self-employed: Quarterly advance payments, annual reconciliation
- Late payment: Interest and linkage differentials apply

## Source
- https://www.btl.gov.il/Insurance/Rates/Pages/%D7%9C%D7%A2%D7%95%D7%91%D7%93%D7%99%D7%9D%20%D7%A9%D7%9B%D7%99%D7%A8%D7%99%D7%9D.aspx (authoritative)

## מתוך `credit-points.md`

# Israeli Tax Credit Points (Nekudot Zikui) — 2026

## Value
Each credit point = **2,904 NIS/year** (approximately 242 NIS/month)

Credit points directly reduce tax liability (not taxable income).
Tax cannot go below zero through credit points (no negative tax/refund).

## Eligibility Table

### Base Credits (Automatic)
| Who | Points | Notes |
|-----|--------|-------|
| Israeli resident | 2.25 | Base for all residents |
| Female resident | 2.75 | Base 2.25 + 0.5 additional |

### Family Status
| Who | Points | Notes |
|-----|--------|-------|
| Child under 18 | 1.0 | Per child, either parent |
| Child under 5 (woman) | 1.5 | Additional for mother, per child |
| Child with disability | 2.0 | Per child, on top of age credit |
| Single parent | 1.0 | Additional |
| Spouse with no income | 1.0 | Below threshold |

### Immigration
| Who | Points | Duration |
|-----|--------|----------|
| New immigrant | 3.0 | Months 1-18 |
| New immigrant | 2.0 | Months 19-24 |
| New immigrant | 1.0 | Months 25-42 |
| Returning resident (10+ years) | Same as new immigrant | Same schedule |

### Military Service
| Who | Points | Duration |
|-----|--------|----------|
| Combat soldier (3 years) | 2.0 | 3 years after discharge |
| Regular soldier (2 years) | 1.0 | 2 years after discharge |
| National service | 1.0 | 2 years after completion |

### Education
| Who | Points | Duration |
|-----|--------|----------|
| Bachelor's degree | 1.0 | Year of completion + 1 year |
| Master's degree | 0.5 | Year of completion + 1 year |
| Vocational diploma | 1.0 | Year of completion + 1 year |

### Special Circumstances
| Who | Points |
|-----|--------|
| Disabled (medical certification) | 2.0 |
| Blind | 2.0 |
| Resident of qualifying community | 0.25-1.0 |

## Claiming Credit Points
- File Form 101 (Hatzharat Oved) with employer at start of employment
- Update when circumstances change (birth, marriage, immigration, etc.)
- Over-claimed credits: Will be corrected in annual tax assessment

## Pension Tax Credit (Zikui Gemel) — Section 45a
Separate from credit points above. An employee who contributes to a pension fund is entitled to a tax credit of **35% of the eligible contribution**. This is distinct from credit points and applies in addition to them.

### Rule (2026)
Eligible contribution = min( actual employee pension contribution , 7% x min(insured_salary, 9,700 NIS/month) )

Tax credit = 35% x eligible contribution

- Insured-salary ceiling for the credit (2026): **9,700 NIS/month**
- Max qualifying contribution: 7% x 9,700 = **679 NIS/month**
- Max monthly credit: 35% x 679 = **237.65 NIS/month** (annual cap 8,148 NIS contribution, ~2,852 NIS credit)
- Credit is applied after gross tax, together with credit points. Tax cannot go below zero.

### Worked Examples (2026)

**Salary 8,000 NIS, 6% pension contribution:**
- Actual employee contribution: 6% x 8,000 = 480 NIS
- Eligible = min(480, 7% x 8,000) = min(480, 560) = 480
- Credit = 35% x 480 = 168 NIS/month

**Salary 15,000 NIS, 6% pension contribution:**
- Actual employee contribution: 6% x 15,000 = 900 NIS
- Eligible = min(900, 7% x 9,700) = min(900, 679) = 679 (capped by 9,700 ceiling)
- Credit = 35% x 679 = 237.65 NIS/month

**Salary 25,000 NIS, 6% pension contribution:** same as above — credit capped at 237.65 NIS/month; additional salary contributes nothing further to this credit.

### Additional Uninsured-Salary Contributions
If the employee has salary components NOT covered by the employer's pension (for example, one-off bonuses), they may make an independent contribution of up to 5% of the uninsured salary, capped at 485 NIS/month, and claim an additional 35% credit on that contribution.

### Where It Shows on the Payslip
- Typically labeled "ניכוי בגין הפקדה לקופת גמל" or "זיכוי 45א" in the deductions column.
- Most payroll systems compute this automatically when the pension contribution line is present. The user may not see a separate "pension credit" line — the credit is baked into the income-tax number.

### Source
- Income Tax Ordinance, Section 45a
- https://www.kolzchut.org.il/he/%D7%96%D7%99%D7%9B%D7%95%D7%99_%D7%9E%D7%9E%D7%A1_%D7%94%D7%9B%D7%A0%D7%A1%D7%94_%D7%91%D7%92%D7%99%D7%9F_%D7%94%D7%A4%D7%A8%D7%A9%D7%95%D7%AA_%D7%9C%D7%91%D7%99%D7%98%D7%95%D7%97_%D7%A4%D7%A0%D7%A1%D7%99%D7%95%D7%A0%D7%99

