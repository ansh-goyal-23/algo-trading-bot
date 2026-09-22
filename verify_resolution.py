"""
One-off verification script: logs into Kotak Neo and resolves every symbol
in the current PORTFOLIO, printing the matched instrument for each so you
can eyeball that NTPC -> NTPC-EQ (not NTPCGREEN-EQ) and the other 4 symbols
look correct too.

Usage (from repo root, with venv activated):
    source venv/bin/activate
    python /tmp/verify_resolution.py
"""
from dotenv import load_dotenv
load_dotenv()

from execution.portfolio import PORTFOLIO, login

def main():
    client = login()
    print(f"\nVerifying resolution for: {list(PORTFOLIO.keys())}\n")
    for stock in PORTFOLIO:
        results = client.search_scrip(exchange_segment="nse_cm", symbol=stock)
        if not results:
            print(f"{stock:<12} -> NO RESULTS")
            continue
        match = next(
            (r for r in results if r.get("pGroup") == "EQ" and r.get("pSymbolName") == stock),
            None,
        )
        all_eq = [r.get("pSymbolName") for r in results if r.get("pGroup") == "EQ"]
        if match is None:
            print(f"{stock:<12} -> NO EXACT MATCH (EQ candidates were: {all_eq})")
        else:
            flag = "  <-- multiple EQ candidates, check for collision" if len(all_eq) > 1 else ""
            print(f"{stock:<12} -> {match['pTrdSymbol']:<15} token={match['pSymbol']}  (EQ candidates: {all_eq}){flag}")

if __name__ == "__main__":
    main()
