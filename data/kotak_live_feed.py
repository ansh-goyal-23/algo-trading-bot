"""
Live market data feed via Kotak Neo Trade API.
Requires NEO_* variables in .env (never hardcode credentials here).
"""
import os
import time
import pyotp
from dotenv import load_dotenv
from neo_api_client import NeoAPI

load_dotenv(dotenv_path=os.path.expanduser("~/Documents/algo-trading-bot/.env"))

CONSUMER_KEY = os.getenv("NEO_CONSUMER_KEY")
MOBILE = os.getenv("NEO_MOBILE")
UCC = os.getenv("NEO_UCC")
MPIN = os.getenv("NEO_MPIN")
TOTP_SECRET = os.getenv("NEO_TOTP_SECRET")

STOCKS = ["ITBEES", "RELIANCE", "TCS"]


def login():
    client = NeoAPI(
        environment="prod",
        consumer_key=CONSUMER_KEY,
        access_token=None,
        neo_fin_key=None,
    )
    totp = pyotp.TOTP(TOTP_SECRET).now()
    client.totp_login(mobile_number=MOBILE, ucc=UCC, totp=totp)
    client.totp_validate(mpin=MPIN)
    print("Logged in successfully")
    return client


def resolve_tokens(client, stocks):
    instrument_tokens = []
    token_to_name = {}
    for stock in stocks:
        results = client.search_scrip(exchange_segment="nse_cm", symbol=stock)
        if not results:
            raise Exception(f"Token not found for {stock}")

        # Prefer the regular equity series (pGroup == "EQ" / symbol ends "-EQ")
        match = next((r for r in results if r.get("pGroup") == "EQ"), None)
        if match is None:
            match = results[0]  # fallback if no EQ match found

        token = str(match["pSymbol"])
        name = match["pTrdSymbol"]
        instrument_tokens.append({"instrument_token": token, "exchange_segment": "nse_cm"})
        token_to_name[str(token)] = name
        print(f"Resolved {stock} -> {name} (token {token})")
    return instrument_tokens, token_to_name


def start_feed(stocks=STOCKS, on_tick=None):
    client = login()
    instrument_tokens, token_to_name = resolve_tokens(client, stocks)
    print("Subscribed tokens:", instrument_tokens)

    def on_message(message):
        if not isinstance(message, dict) or message.get("type") != "stock_feed":
            return
        for tick in message.get("data", []):
            if "ltp" not in tick:
                continue  # partial update (depth/qty only) - skip
            token = str(tick.get("tk"))
            name = token_to_name.get(token, tick.get("ts", token))
            ltp = tick.get("ltp")
            if on_tick:
                on_tick(name, ltp, tick)
            else:
                print(f"{name} LTP = {ltp}")

    def on_error(error):
        print("Feed error:", error)

    def on_open(message):
        print("WebSocket connected", message)

    def on_close(message):
        print("WebSocket closed", message)

    client.on_message = on_message
    client.on_error = on_error
    client.on_open = on_open
    client.on_close = on_close

    client.subscribe(instrument_tokens=instrument_tokens, isIndex=False, isDepth=False)
    print("Live feed started")
    return client


if __name__ == "__main__":
    start_feed()
    while True:
        time.sleep(1)
