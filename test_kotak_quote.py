import os, pyotp
from dotenv import load_dotenv
from neo_api_client import NeoAPI

load_dotenv(dotenv_path=os.path.expanduser("~/Documents/algo-trading-bot/.env"))

client = NeoAPI(environment="prod", consumer_key=os.getenv("NEO_CONSUMER_KEY"),
                access_token=None, neo_fin_key=None)
totp = pyotp.TOTP(os.getenv("NEO_TOTP_SECRET")).now()
client.totp_login(mobile_number=os.getenv("NEO_MOBILE"), ucc=os.getenv("NEO_UCC"), totp=totp)
client.totp_validate(mpin=os.getenv("NEO_MPIN"))

result = client.quotes(
    instrument_tokens=[{"instrument_token": "21808", "exchange_segment": "nse_cm"}],
    quote_type="ohlc"
)
print("RAW QUOTE RESPONSE:", result)
