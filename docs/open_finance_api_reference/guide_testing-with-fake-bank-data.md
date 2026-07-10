# Testing with fake bank data

Testing your integration with open finance using our fake bank providers

## What is a fake bank provider?

A fake bank provider is a fake provider that you can use for testing your integration with Open Finance.

<br />

> 🚧 Display sandbox providers toggle must be enabled in Journey settings!
>
> In order to enable payments and connections with sandbox providers, make sure the **“Display sandbox providers”** option is turned on in the Journey settings screen.

> 🚧 Connection must be configured with includeFakeProviders option!
>
> In order for you to see the fake providers in the Connection Journey you must have set the includeFakeProviders: true when creating a connection.

> ❗️ Make sure to remove the includeFakeProviders flag in your production environment

> 🚧 Notice that the Data credentials for Connection testing and the Payment Credentials for Payments testing are different per sandbox.

## Open Finance Sandbox

Open Finance has it's own sandbox provider with fake users for testing.

The **providerId** for Open Finance's sandbox: **open-finance-sandbox**

Available test accounts for open-finance-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID    | Products                                       | Account Numbers                                   | Status                  |
| :-------- | :--------------------------------------------- | :------------------------------------------------ | :---------------------- |
| 043510023 | accounts, balances, cards, loans, transactions | 31-019-29114 31-021-731722 31-050-5703            | ACTIVE                  |
| 321547416 | accounts, balances, cards, loans, transactions | 31-114-435694 31-124-272604 31-064-406821         | ACTIVE                  |
| 1772268   | accounts, balances, cards, loans, transactions | 11-002-11440386 11-002-152384687 11-002-166426662 | ACTIVE                  |
| 8332884   | accounts, balances, cards, loans, transactions | 11-004-78969958 11-005-145532722 11-014-190035856 | ACTIVE                  |
| 058766718 | accounts, balances, cards, loans, transactions | 12-615-32449 12-615-343779 12-627-230522          | ACTIVE                  |
| 038506499 | accounts, balances, cards, loans, transactions | 12-628-667746 12-630-119945 12-630-435510         | ACTIVE                  |
| 520023185 | accounts, balances, cards, loans, transactions | 10-882-43487887 10-940-8924227 10-985-3816794     | ACTIVE                  |
| 321547796 | accounts, balances, cards, loans, transactions | 10-988-3750659 10-922-2084286 10-985-3816794      | ACTIVE                  |
| 321547804 | accounts, balances, cards, loans, transactions | 20-574-308223 20-461-336809 20-723-648357         | ACTIVE                  |
| 321547812 | accounts, balances, cards, loans, transactions | 20-443-113222 20-433-299099 20-477-433289         | ACTIVE                  |
| 321547820 | accounts, balances, cards, loans, transactions | 04-130-158895 04-141-43814 04-118-90291           | ACTIVE                  |
| 321547853 | accounts, balances, cards, loans, transactions | 04-124-317146 04-125-193440 04-124-318436         | ACTIVE                  |
| 050299338 |                                                |                                                   | REJECTED                |
| 064837123 |                                                |                                                   | PARTIALLY\_AUTHORIZED   |
| 316159011 |                                                |                                                   | ERROR                   |
| 316159029 |                                                |                                                   | FETCHING\_ERROR         |
| 316159052 |                                                |                                                   | SUSPENDED\_BY\_PROVIDER |

### Payments credentials:

> 📘 For Single Payment Sandbox testing, for Periodic please see [Periodic Payments Sandbox](https://docs.open-finance.ai/docs/periodic-payments-sandbox)

Each debtor account returns a different status for testing purposes.\
Creditor account details can be any valid bban or iban

You can use any psuId with this sandbox for each account

| PSU ID | debtorAccount IBAN      | debtorAccount BBAN | Result status | Additional info                                                                                 |
| :----- | :---------------------- | :----------------- | :------------ | :---------------------------------------------------------------------------------------------- |
| ANY    | IL060311140000000436003 | 31-114-436003      | ACSC          |                                                                                                 |
| ANY    | IL500311140000000436666 | 31-114-436666      | ACSP          |                                                                                                 |
| ANY    | IL060311140000000436682 | 31-114-436682      | CANC          |                                                                                                 |
| ANY    | IL380311140000000436688 | 31-114-436688      | ACFC          |                                                                                                 |
| ANY    | IL060311140000000436488 | 31-114-436488      | PATC          | After completing the payment it will change to ACTC to simulate multiple authenticators account |
| ANY    | IL410311140000000436440 | 31-114-436440      | PART          |                                                                                                 |
| ANY    | IL120311140000000436283 | 31-114-436283      | PENDING       |                                                                                                 |
| ANY    | IL190311140000000436254 | 31-114-436254      | ACCC          |                                                                                                 |
| ANY    | IL070311140000000435694 | 31-114-435694      | ACTC          |                                                                                                 |
| ANY    | IL630310640000000406821 | 31-064-406821      | ACWC          |                                                                                                 |
| ANY    | IL490311240000000272604 | 31-124-272604      | RJCT          |                                                                                                 |
| ANY    | IL610311140000000435789 | 31-114-435789      | ERROR         |                                                                                                 |

## Mizrahi Tefahot- sandbox

> 🚧 Important: Entering incorrect credentials when attempting to log in to the Mizrahi Tefahot sandbox may result in the browser session being temporarily locked from further login attempts. If this occurs, you may initiate a new session using incognito mode to attempt another login. Please ensure you use the correct credentials.

Mizrahi Tefahot Bank has a sandbox provider with fake users for testing.

The **providerId** for Mizrahi's sandbox: **mizrahi-sandbox**

Available test accounts for mizrahi-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID       | PSU Id Type | User Id   | Password | OTP | Products           |
| :----------- | :---------- | :-------- | :------- | :-- | :----------------- |
| 245938880    | National ID | 102718538 | 1        | 1   | accounts, balances |
| UA0324046596 | Passport    | 773315566 | 1        | 1   | accounts, balances |
| 759158321    | National ID | 6792924   | 1        | 1   | accounts, balances |
| 755733188    | National ID | 741416837 | 1        | 1   | accounts, balances |
| 011462580    | National ID | 153400597 | 1        | 1   | accounts, balances |
| 261690927    | National ID | 288968135 | 1        | 1   | accounts, balances |

<br />

### Payments credentials:

> 📘 For Payment Sandbox testing

| PSU IDs   | User Id    | (creditorAccount) IBAN  | (debtorAccount) IBAN    | OTP | Payment service | Payment product |
| :-------- | :--------- | :---------------------- | :---------------------- | :-- | :-------------- | :-------------- |
| 245938880 | 0102718538 | IL380465020000000923668 | IL730200040000000552717 | 1   | masav           | payments        |

## Leumi- sandbox

Leumi Bank has a sandbox provider with fake users for testing.

The **providerId** for Leumi's sandbox: **leumi-sandbox**

Available test accounts for leumi-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID    | PSU Id Type | Products                        |
| :-------- | :---------- | :------------------------------ |
| 105210748 | National ID | accounts, cards, savings, loans |
| 105210741 | National ID | accounts, cards, savings, loans |
| 339677395 | National ID | accounts, cards, savings, loans |

<br />

### Payments credentials:

> 📘 For Payment Sandbox testing

| PSU IDs   | (creditorAccount) IBAN | (debtorAccount) IBAN    | Payment service | Payment product |
| :-------- | :--------------------- | :---------------------- | :-------------- | :-------------- |
| 105210748 | 10-111-11111           | IL750109490000019519055 | masav           | payments        |

## Beinleumi - sandbox

Beinleumi Bank has a sandbox provider with fake users for testing.

The **providerId** for Beinleumi's sandbox: **beinleumi-sandbox**

Available test accounts for beinleumi-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID    | Customer type    | Password             | Products           |
| :-------- | :--------------- | :------------------- | :----------------- |
| 808089452 | psu1             | No password required | accounts, balances |
| 929913010 | psuBlocked       | No password required | accounts, balances |
| 396854374 | psuMulticurrency | No password required | accounts balances  |

<br />

### Payments credentials:

> 📘 For Payment Sandbox testing

| PSU IDs                                  | Creditor name | (creditorAccount) IBAN  | (debtorAccount) IBAN    | Payment service | Payment product |
| :--------------------------------------- | :------------ | :---------------------- | :---------------------- | :-------------- | :-------------- |
| 928996792                                | Matan Pereg   | IL380465020000000923668 | IL130262880000000557737 | masav           | payments        |
| 939363032 , 288530272,  84712256         | Amit Bracha   | IL220465170000000825082 | IL150310640000000594798 | masav           | payments        |
| 195646716, 773504105,636849226, 32943409 | Matan Pereg   | IL380465020000000923668 | IL440310210000000641772 | masav           | payments        |
| 857646343                                | Orna Elad     | IL150310640000000594798 | IL210262880000000108968 | fp              | payments        |

## Discount - sandbox

Discount Bank has a sandbox provider with fake users for testing.

The **providerId** for Discount's sandbox: **discount-sandbox**

Available test accounts for discount-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID    | Customer type | Password             | Products           |
| :-------- | :------------ | :------------------- | :----------------- |
| 222210007 | Retail        | No password required | accounts, balances |

> ❗️ This account currently returns "PROVIDER\_ERROR", we're currently working on fixing this

### Payments credentials:

> 📘 For Payment Sandbox testing

| PSU ID    | (crediotrAccount) IBAN  | (debtorAccount) IBAN    | Products |
| :-------- | :---------------------- | :---------------------- | :------- |
| 222210023 | IL750121520000091842702 | IL750111520000091842702 | payment  |

## Yahav - sandbox

Yahav Bank has a sandbox provider with fake users for testing.

The **providerId** for Discount's sandbox: **yahav-sandbox**

Available test accounts for yahav-sandbox provider:

### Data credentials:

> 📘 For Connection Sandbox testing

| PSU ID    | Customer type | Password | OTP   | Products                                       |
| :-------- | :------------ | :------- | :---- | :--------------------------------------------- |
| 336480876 | PSU1          | Aa123456 | 12345 | accounts, balances, cards, loans, transactions |

### Payments credentials:

> 📘 For Payment Sandbox testing

| PSU ID    | (crediotrAccount) IBAN | (debtorAccount) IBAN    | Payment service | Products |
| :-------- | :--------------------- | :---------------------- | :-------------- | :------- |
| 336480876 | IL82336629612486362491 | IL402661595875335575586 | masav           | payment  |

> ❗️ This provider currently returns "FORMAT\_ERROR", we're currently working on fixing this.