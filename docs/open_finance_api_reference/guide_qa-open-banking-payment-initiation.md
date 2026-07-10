#  Q&A Open Banking Payment Initiation

This document provides answers to frequently asked questions regarding payment initiation

<br />

In today’s fast-paced digital world, businesses are seeking innovative ways and new payment methods to efficiently and conveniently accept payments from their customers.
Our payment initiation service provides a cutting-edge solution for businesses, enabling digital money transfers easily and directly from the customer’s bank account to the business’s bank account. This eliminates the need for credit cards, physical bank visits, and unnecessary delays or errors, all while significantly saving on clearing costs!

Open Finance provides open banking services under the license and supervision of the Israel Securities Authority.
Our system meets the highest international security standards to ensure the privacy and security of your information.

How It Works:

1. Sending a Payment Request to the Customer: The business generates a digital payment request that includes all transaction details – payment amount, business information, and bank account details.
2. Accessing Bank Information with Customer Authorization: The customer receives the payment initiation request and securely connects to their bank account or banking app via a secure link.
3. Transaction Authorization: The customer grants access to their bank account and approves the transaction. The entire identification and authorization process is handled by their bank under strict security standards.
4. Receiving Payment to the Business Account: Upon customer approval, the payment is transferred directly from the customer's bank account to the business's bank account quickly, without delays, and without high clearing fees (subject to bank operating hours).

First thing first-

The difference between the different types of payments:

|                                                                                                                                                                                                                                                    | Bank Transfer | Credit Card | Payment Initiation |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ----------- | ------------------ |
| Payment is received immediately: • Payment from bank A to bank A - Immediate transfer<br /><br />\* For example: from Leumi Bank to Leumi Bank • Payment from bank A to bank B - Immediate transfer For example: from Leumi Bank to Mizrahi Bank\_ | ✗             | ✗           | ✓                  |
| Advanced debit in PSD2 standard                                                                                                                                                                                                                    | ✗             | ✗           | ✓                  |
| No risk limitation\*\*                                                                                                                                                                                                                             | ✗             | ✗           | ✓                  |
| Digital process without input errors                                                                                                                                                                                                               | ✗             | ✗           | ✓                  |
| Transaction cannot be canceled by the payer                                                                                                                                                                                                        | ✗             | ✗           | ✓                  |
| Balance is updated immediately                                                                                                                                                                                                                     | ✗             | ✗           | ✓                  |
| Exempt from clearing fee                                                                                                                                                                                                                           | ✓             | ✗           | ✓                  |
| Additional fee exempt for gold transfer                                                                                                                                                                                                            | ✗             | ✗           | ✓                  |

Immediate transfer = For supporting banks - Same-day transfer between different banks - thus, even if there is no support, the transfer is executed during the bank's operating hours. The notification in the receiving bank will be booked for the next day according to the banking system.
No risk limitation = No need for bank permission for operations in digital channels

Possible Use- cases:

<Image alt="Image" border={false} src="https://files.readme.io/739abfcfbbc26152bc1ac613a2190033ef3aefb303ed637a6de446676417f243-image.png" />

## Q\&A: Integration and Process Implementation

**Question**: Suppose I clicked/scanned the payment link and my banking app opened. What happens if I close the browser window during the process? Is the transaction canceled? Do I have to wait for bank approval before closing the window?
**Answer**: If the customer opens the link and the bank screen appears, but they abandon the process, the status will be "Pending Execution," and later it will change to "Rejected" within a week. The customer will need to rescan the code and complete the process from the beginning. You don’t need to wait for the bank’s approval before closing the browser, but you do need to press "Approve Payment" in the bank app to complete the transaction. A success status will be received once the action is completed.

**Question**: Is the INIT status set when the payment link is created or only after the customer clicks it?
**Answer**: When the link is created.

**Question**: After approving in the bank's website/app, is there a success screen, or does the window just close?**Answer**: For users of the "Create" method (which uses the Open Finance UI), a success screen is displayed once the customer approves the payment in their bank. However, a custom end screen can always be defined to which the user is redirected after completing the payment.

**Question**: Is the MerchantID provided by you specific to each bank account entered, or is it general? That is, does each receiving bank account get a unique MerchantID?
**Answer**: Yes, the MerchantID is specific to each bank account.

**Question**: Regarding credits – when the merchant receives an SMS, does it include a link to the bank account where the final credit approval is given?
**Answer**: Correct.

**Question**: Credit – Can the merchant details (ID number, company number, phone) be pre-filled?
**Answer**: Yes, during merchant creation.

**Question**: An error message is shown before the user reaches the bank screen
**Answer**:Incorrect ID number – there's a mismatch between the ID on the consent screen and the account holder’s ID. OR Invalid amount – e.g., amount is 0.

**Question**: I received an error message at the end of the transaction and the customer got an "rjct" status
**Answer**:Joint account – login was done using one partner’s credentials, but the ID number belongs to the other. OR-If the bank did not approve the transfer, it might be due to insufficient balance or exceeding the account's transfer limits. It's recommended to try again with a smaller amount or contact the bank for assistance.

## Q\&A: Customer Side

**Question**: How is a deposit made using open banking?
**Answer**: The process includes initial identification using account number and ID number, selecting your bank, logging in, and approving the transfer to the trading account.

**Question**: Who is Open Finance and what is its role in the process?
Answer: Open Finance is a leading fintech company in Israel, providing open banking services and enabling secure fund transfers between bank and trading accounts. It is regulated by the Israel Securities Authority.

**Question**: I don't have my bank login credentials. Can I still use the open banking payment service?
**Answer**: If you're using a mobile device, login is usually done via the app's biometric method (face/fingerprint), so credentials are not needed. If using a desktop, you'll need to recover your bank login details before using the open banking service.

**Question**: Can I use the new deposit service with any bank in Israel?
**Answer**: The service supports most Israeli banks. During the process, you can select your bank from the available list.

**Question**: Why doesn’t my bank appear in the list?
**Answer**: The list only includes banks that have completed the open banking integration. If your bank isn’t listed, it may not yet support open banking.

**Question**: I was redirected to the bank app/site, but only the app/site opened – not the payment process:
**Answer**:This could be a login issue or due to a previous session running in the background. Close the banking app completely and try again.

**Question**: I see an error after identifying at the bank or during the payment process – possible reasons:
**Answer**:Incorrect ID number – mismatch between consent screen and bank account holder. OR Unreasonable amount – e.g., 0 or no decimal format (must be x.xx). OR Joint account – login was done with one partner’s details, but the ID belongs to the other.

**Question**: During the identification process, the system doesn’t recognize me. Why?
**Answer**: Check that the identification details are correct. For older accounts, verify the account is still active; for new accounts, ensure it has been fully activated.

**Question**: Is using open banking safe?
**Answer**: Yes, open banking is conducted according to the highest security standards.