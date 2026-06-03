import pandas as pd
import requests
import gzip
import shutil
import os
import time

def download_instruments(url, filename):
    print(f"Downloading instruments from {url}...")
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            shutil.copyfileobj(response.raw, f)
        print("Download complete.")
    else:
        print(f"Failed to download instruments. Status: {response.status_code}")
        return False
    return True

def get_stocks_and_underlyings(instruments_file):
    print("Processing instruments...")
    df = pd.read_csv(instruments_file)

    # Filter for NSE options stocks
    optstk_df = df[(df['instrument_type'] == 'OPTSTK') & (df['exchange'] == 'NSE_FO')]

    # Get unique stocks and their nearest expiry
    # We'll use 'name' as the common identifier
    stock_names = optstk_df['name'].unique()

    # Map to underlying instrument_key in NSE_EQ
    underlyings = df[(df['name'].isin(stock_names)) & (df['instrument_type'] == 'EQUITY') & (df['exchange'] == 'NSE_EQ')]

    # Create a mapping of stock name to its underlying instrument key
    underlying_map = underlyings.groupby('name')['instrument_key'].first().to_dict()

    # Get nearest expiry for each stock
    nearest_expiries = optstk_df.groupby('name')['expiry'].min().to_dict()

    stocks_to_fetch = []
    for name in stock_names:
        if name in underlying_map and name in nearest_expiries:
            stocks_to_fetch.append({
                'name': name,
                'underlying_key': underlying_map[name],
                'expiry': nearest_expiries[name]
            })

    print(f"Found {len(stocks_to_fetch)} stocks with options and underlying keys.")
    return stocks_to_fetch

def fetch_option_chain(underlying_key, expiry, token):
    url = "https://api.upstox.com/v2/option/chain"
    params = {
        'instrument_key': underlying_key,
        'expiry_date': expiry
    }
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                wait_time = (2 ** attempt) + 1
                print(f"Rate limited for {underlying_key}. Waiting {wait_time}s...")
                time.sleep(wait_time)
            elif response.status_code == 401:
                print("Unauthorized. Please check your access token.")
                return None
            else:
                print(f"Error fetching {underlying_key}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Exception fetching {underlying_key}: {e}")
            time.sleep(1)
    return None

def process_option_chain_data(json_data):
    if not json_data or 'data' not in json_data:
        return []

    flattened_data = []
    for item in json_data['data']:
        base_info = {
            'expiry': item.get('expiry'),
            'pcr': item.get('pcr'),
            'strike_price': item.get('strike_price'),
            'underlying_key': item.get('underlying_key'),
            'underlying_spot_price': item.get('underlying_spot_price')
        }

        for opt_type in ['call_options', 'put_options']:
            opt_data = item.get(opt_type)
            if opt_data:
                row = base_info.copy()
                row['option_type'] = 'CE' if opt_type == 'call_options' else 'PE'

                market_data = opt_data.get('market_data', {})
                for k, v in market_data.items():
                    row[f'market_{k}'] = v

                # Calculate change in OI
                row['market_change_oi'] = row.get('market_oi', 0) - row.get('market_prev_oi', 0)

                greeks = opt_data.get('option_greeks', {})
                for k, v in greeks.items():
                    row[f'greek_{k}'] = v

                flattened_data.append(row)

    return flattened_data

if __name__ == "__main__":
    INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    INSTRUMENTS_FILE = "complete.csv.gz"

    if not os.path.exists(INSTRUMENTS_FILE):
        download_instruments(INSTRUMENTS_URL, INSTRUMENTS_FILE)

    ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0ODM0MzYiLCJqdGkiOiI2YTFmZTU3N2EwZWM3ODJmODExZDg5M2QiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4MDQ3NTI1NSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzgwNTI0MDAwfQ.vLqGgA8z2gBhXgJerwygb3GS8GzzMma1dbwQTjQLjgA"

    stocks = get_stocks_and_underlyings(INSTRUMENTS_FILE)

    all_option_data = []
    # To avoid long execution in this environment, I'll limit to a few stocks for initial run
    # but the logic is ready for all stocks.
    # The user asked for ALL stocks.

    print(f"Starting to fetch option chains for {len(stocks)} stocks...")
    for i, stock in enumerate(stocks):
        print(f"[{i+1}/{len(stocks)}] Fetching {stock['name']}...")
        json_resp = fetch_option_chain(stock['underlying_key'], stock['expiry'], ACCESS_TOKEN)
        if json_resp:
            flat_rows = process_option_chain_data(json_resp)
            for row in flat_rows:
                row['stock_name'] = stock['name']
            all_option_data.extend(flat_rows)

        # Small delay to respect rate limits
        time.sleep(0.2)

        # Safety break for the sandbox if it takes too long
        # if i >= 10: break

    if all_option_data:
        final_df = pd.DataFrame(all_option_data)
        output_file = "option_chain_all_stocks.csv"
        final_df.to_csv(output_file, index=False)
        print(f"Data saved to {output_file}. Total rows: {len(final_df)}")
    else:
        print("No data collected.")
