import streamlit as st
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import requests

# Set the variable as requested
chart_font_size = 25

# Streamlit Page Config
st.set_page_config(page_title="Stock Analysis", layout="wide")

# CSS to reduce Title size by roughly 1/3
st.markdown("<h2 style='text-align: left;'>📈 Stock Fundamental Dashboard</h2>", unsafe_allow_html=True)

@st.cache_data(ttl=86400)
# Get eps data from the SEC
def get_sec_eps_final(ticker_symbol):
    ticker = ticker_symbol.upper().strip()
    headers = {'User-Agent': "Chuck Krapf (chuckkrapf@yahoo.com)"}
    
    try:
        # 1. Get CIK
        tkr_url = "https://www.sec.gov/files/company_tickers.json"
        ticker_json = requests.get(tkr_url, headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in ticker_json.items() if v['ticker'] == ticker), None)
        if not cik: return pd.DataFrame()

        # 2. Fetch Facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        us_gaap = data.get('facts', {}).get('us-gaap', {})
        
        # 3. Pull Primary Metrics
        eps_raw = us_gaap.get('EarningsPerShareDiluted', {}).get('units', {}).get('USD/shares', [])
        ni_raw = us_gaap.get('NetIncomeLoss', {}).get('units', {}).get('USD', [])
        
        if not eps_raw or not ni_raw: return pd.DataFrame()

        # 4. Get the absolute "Current" Share Count as our baseline
        # We check both DEI and GAAP tags to find the most recent total
        latest_shares = None
        for tag in ['EntityCommonStockSharesOutstanding', 'CommonStockSharesOutstanding']:
            s_data = data.get('facts', {}).get('dei', {}).get(tag, {}).get('units', {}).get('shares', [])
            if not s_data: s_data = us_gaap.get(tag, {}).get('units', {}).get('shares', [])
            if s_data:
                latest_shares = pd.DataFrame(s_data).sort_values('end').iloc[-1]['val']
                break
        if not latest_shares: return pd.DataFrame()

        # 5. Process EPS into Quarters
        df = pd.DataFrame(eps_raw)
        df['end'] = pd.to_datetime(df['end'])
        df['start'] = pd.to_datetime(df.get('start', df['end']))
        df['days'] = (df['end'] - df['start']).dt.days

        qtrs = df[(df['days'] > 60) & (df['days'] < 110)].copy()
        y9m = df[(df['days'] > 240) & (df['days'] < 290)].copy()
        ann = df[(df['days'] > 340) & (df['days'] < 380)].copy()

        q4_list = []
        for _, yr in ann.iterrows():
            match = y9m[(y9m['end'] >= yr['end'] - pd.Timedelta(days=12)) & 
                        (y9m['end'] <= yr['end'] + pd.Timedelta(days=12))]
            val = (yr['val'] - match.iloc[0]['val']) if not match.empty else (yr['val'] / 4)
            q4_list.append({'end': yr['end'], 'val': val, 'days': 90})

        combined = pd.concat([qtrs, pd.DataFrame(q4_list)])
        combined = combined.sort_values(['end', 'filed']).drop_duplicates('end', keep='last')

        # 6. UNIVERSAL SPLIT ADJUSTER
        ni_df = pd.DataFrame(ni_raw)
        ni_df['end'] = pd.to_datetime(ni_df['end'])

        def adjust_for_split(row):
            try:
                # Find Net Income for this specific date
                ni_match = ni_df[ni_df['end'] == row['end']]
                if ni_match.empty:
                    ni_val = ni_df.loc[(ni_df['end'] - row['end']).abs().idxmin(), 'val']
                else:
                    # SEC reports quarterly and annual NI; we need the one matching the EPS duration
                    ni_match = ni_match.copy()
                    ni_match['start'] = pd.to_datetime(ni_match.get('start', ni_match['end']))
                    ni_match['diff'] = (ni_match['end'] - ni_match['start']).dt.days
                    ni_val = ni_match.loc[(ni_match['diff'] - row['days']).abs().idxmin(), 'val']

                # Step 1: How many shares were implied by this EPS report?
                implied_shares_then = ni_val / row['val']
                
                # Step 2: What is the ratio between today's shares and those shares?
                ratio = latest_shares / implied_shares_then
                
                # Step 3: Round to the nearest common split factor (1, 2, 20, etc.)
                # This removes noise from buybacks or share issuance.
                common_splits = [1, 2, 4, 7, 10, 20, 28, 40, 50, 100]
                best_split = min(common_splits, key=lambda x: abs(x - ratio))
                
                return row['val'] / best_split
            except:
                return row['val']

        combined['Reported EPS'] = combined.apply(adjust_for_split, axis=1)
        combined = combined.rename(columns={'end': 'Date'})
        return combined[['Date', 'Reported EPS']].set_index('Date').sort_index()

    except Exception as e:
        print(f"SEC Exception: {e}") # See what's actually happening
        return pd.DataFrame()

ticker_symbol = st.sidebar.text_input("Enter Ticker Symbol", value="ET").upper()
years = st.sidebar.slider("Years of History", 1, 20, 10)

if ticker_symbol:
    with st.spinner(f'Fetching data for {ticker_symbol}...'):
        ticker = yf.Ticker(ticker_symbol)
        
        try:
            info = ticker.info
            company_name = info.get('longName', ticker_symbol)
            
            price_history = ticker.history(period=f"{years}y")

            # 2. VALIDATION: Check if data actually exists
            if price_history.empty:
                st.error(f"❌ Ticker '{ticker_symbol}' not found. Please check the spelling (e.g., AAPL, TSLA, MSFT).")
            else:    
                price_history.index = price_history.index.tz_localize(None)
                eps_data = get_sec_eps_final(ticker_symbol) # Get from SEC

                if eps_data is None or eps_data.empty:
                    eps_data = ticker.get_earnings_dates(limit=100) # Try to get it from yfinance

                if eps_data is None or eps_data.empty:
                    st.error(f"Could not find earnings data for {ticker_symbol}")
                else:
                    eps_df = eps_data.dropna(subset=['Reported EPS']).copy()
                    eps_df.index = eps_df.index.tz_localize(None)
                    eps_df = eps_df.groupby(eps_df.index).mean().sort_index()
                    eps_df['TTM EPS'] = eps_df['Reported EPS'].rolling(window=4).sum()
    
                    start_date = price_history.index.min()
                    eps_df_filtered = eps_df.loc[start_date:]
    
                    pe_df = price_history[['Close']].copy()
                    pe_df['TTM_EPS_Mapped'] = eps_df['TTM EPS'].reindex(pe_df.index, method='ffill')
                    pe_df['PE_Ratio'] = pe_df['Close'] / pe_df['TTM_EPS_Mapped']
                    
                    # Removes Infs and NaNs
                    pe_df.replace([np.inf, -np.inf], np.nan, inplace=True)
                    pe_df = pe_df.dropna(subset=['PE_Ratio'])

                    # 1. Global Font Scaling
                    plt.rcParams.update({'font.size': chart_font_size})
    
                    # 2. Increase height by 50% (Original was 10, now 15)
                    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 15), sharex=True, 
                                                        gridspec_kw={'height_ratios': [4, 1, 1]})
    
                    # --- TOP CHART: PRICE ---
                    ax1.plot(price_history.index, price_history['Close'], color='tab:blue', linewidth=2)
                    ax1.set_ylabel('Price (USD)', fontweight='bold', fontsize=chart_font_size)
                    
                    # 3. Bold Chart Title
                    ax1.set_title(f'{company_name} ({ticker_symbol})', fontsize=chart_font_size + 4, fontweight='bold')
                    ax1.grid(True, alpha=0.3)
    
                    # --- MIDDLE CHART: EPS ---
                    ax2.step(eps_df_filtered.index, eps_df_filtered['TTM EPS'], color='tab:red', where='post', linewidth=2.5)
                    ax2.set_ylabel('TTM EPS', fontweight='bold', fontsize=chart_font_size)
                    ax2.grid(True, alpha=0.3)
    
                    # --- BOTTOM CHART: P/E RATIO ---
                    ax3.plot(pe_df.index, pe_df['PE_Ratio'], color='tab:green', linewidth=2)
                    ax3.set_ylabel('P/E Ratio', fontweight='bold', fontsize=chart_font_size)
                    ax3.set_xlabel('Date', fontsize=chart_font_size)

                    # Filter outliers for the P/E scale. Also handle stocks whose P/E is negative.
                    maxlim = min([pe_df['PE_Ratio'].quantile(0.98), 600.0])
                    minlim = max([pe_df['PE_Ratio'].quantile(0.02), -100.0])
                
                    maxlim = max([maxlim, minlim])
                    minlim = min([maxlim, minlim])

                    #print(f'maxlim: {maxlim}, minlim: {minlim}')
                    
                    if (maxlim > 0 and minlim > 0):
                        ax3.set_ylim(0, maxlim)
                    else:
                        ax3.set_ylim(minlim, maxlim)
           
                    ax3.grid(True, alpha=0.3)
    
                    # Adjusting tick label sizes specifically
                    ax3.tick_params(axis='x', labelsize=chart_font_size - 5)
    
                    plt.tight_layout()
                    st.pyplot(fig)
                
        except Exception as e:
            st.error(f"Error fetching data: {e}")





