# Overview

Webhooks are used us to notify you when a new event that is regarding you has occurred in our systems.

## Configuration

In order to enable and use our webhooks you will need to enable it from the Dashboard:

1. Enter to your client settings in our [Dashboard](https://dashboard.open-finance.ai/settings/alerts).
2. Enable the Webhook in the update mode section

![](https://files.readme.io/ea1f373-Screen_Shot_2022-04-11_at_15.12.28.png "Screen Shot 2022-04-11 at 15.12.28.png")

3. Insert a webhook url for success and for failure update. In order to test locali, we strongly recommend using [Ngrok](https://ngrok.com)
4. Create a connection and finish the flow to see the if your server is configured correctly to handle the request

> 📘 Webhook request details
>
> Our webhooks always sent as an HTTPS request with the method POST. All of the event data is sent in the request body.