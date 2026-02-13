use_streamlit = True

if use_streamlit:
    import streamlit as st
#else:
#    class Streamlit:


import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import requests
from matplotlib.offsetbox import TextArea, VPacker, AnnotationBbox



def get_fcf_yield(ticker):
    """
    Calculates TTM Free Cash Flow Yield using the 'Stub Period' method.
    Formula: (TTM Operating Cash Flow - TTM CapEx) / Market Cap
    """
    ticker = ticker.upper().strip()
    headers = {"User-Agent": "FinanceAnalyst/1.0 (chuckkrapf@yahoo.com)"}

    try:
        # 1. Get CIK
        cik_map = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in cik_map.items() if v['ticker'] == ticker), None)
        if not cik: return 0.0
    
        # 2. Get SEC Facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        gaap = data.get('facts', {}).get('us-gaap', {})
    
        def get_ttm_cashflow_metric(tag_list):
            """Helper to convert cumulative YTD SEC data into a TTM value."""
            df = pd.DataFrame()
            for tag in tag_list:
                if tag in gaap and 'USD' in gaap[tag].get('units', {}):
                    df = pd.DataFrame(gaap[tag]['units']['USD'])
                    break
            
            if df.empty: return 0.0
    
            # Clean and sort
            df['end'] = pd.to_datetime(df['end'])
            df['start'] = pd.to_datetime(df['start'])
            df['days'] = (df['end'] - df['start']).dt.days
            df = df.sort_values(['end', 'filed'], ascending=[True, True]).drop_duplicates('end', keep='last')
    
            # Get components for: Current YTD + (Prior Full Year - Prior YTD)
            latest_report = df.iloc[-1]
            
            # If the latest report is already a full year (10-K), just return it
            if 350 <= latest_report['days'] <= 375:
                return float(latest_report['val'])
            
            # Otherwise, find the same YTD period from last year and the last full year
            current_ytd_val = latest_report['val']
            current_ytd_days = latest_report['days']
            
            # Find Prior Full Year (approx 365 days)
            prior_full_year = df[df['days'].between(350, 375)].iloc[-1]['val']
            
            # Find Prior YTD (same number of days as current YTD, but from a year ago)
            # We look for a report ending roughly 365 days before the current one
            target_prior_end = latest_report['end'] - pd.Timedelta(days=365)
            try:
                prior_ytd = df[df['end'].between(target_prior_end - pd.Timedelta(days=15), 
                                               target_prior_end + pd.Timedelta(days=15)) 
                               & (df['days'] == current_ytd_days)].iloc[-1]['val']
            except:
                # Fallback: if we can't find the exact prior YTD, just use the current YTD * (365/days)
                # This is less accurate but prevents a crash
                return float(current_ytd_val * (365 / current_ytd_days))
    
            return float(current_ytd_val + (prior_full_year - prior_ytd))
    
        # --- Calculations ---
        # Operating Cash Flow Tags
        ocf_ttm = get_ttm_cashflow_metric(['NetCashProvidedByUsedInOperatingActivities'])
        
        # CapEx Tags (AEE uses PaymentsToAcquirePropertyPlantAndEquipment)
        capex_ttm = get_ttm_cashflow_metric([
            'PaymentsToAcquirePropertyPlantAndEquipment', 
            'PaymentsToAcquireProductiveAssets',
            'CapitalExpenditures'
        ])
    
        fcf_ttm = ocf_ttm - capex_ttm
    
        # Get Market Cap from yfinance
        ytick = yf.Ticker(ticker)
        mkt_cap = ytick.info.get('marketCap')
    
        if not mkt_cap or mkt_cap == 0: return 0.0
    
        fcf_yield = (fcf_ttm / mkt_cap) * 100
        return round(float(fcf_yield), 2)

    except Exception as e:

        print(f"Error getting free cash flow yield: {e}")
        return 0.0
        
# Usage:
# print(f"AEE FCF Yield: {get_fcf_yield('AEE')}%")

def is_dividend_data_ok(div_df):

    return 'start' in div_df.columns and 'end' in div_df.columns


def get_dividend_yield_percent_final(ticker):
    """
    Calculates the actual TTM Dividend Yield % by summing the last 4 
    discrete quarterly payments from SEC filings. Returns 0.0 on error.
    """
    ticker = ticker.upper().strip()
    headers = {"User-Agent": "AnalysisBot (yourname@example.com)"}

    # Priority list of SEC tags for dividends per share
    dividend_tags = [
        'CommonStockDividendsPerShareDeclared',
        'CommonStockDividendsPerShareCashPaid',
        'DividendsCommonStockCash', # Sometimes used for per-share if units are USD/shares
    ]
    
    try:
        # Get CIK and SEC Facts
        tkr_url = "https://www.sec.gov/files/company_tickers.json"
        ticker_json = requests.get(tkr_url, headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in ticker_json.items() if v['ticker'] == ticker), None)
        
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        us_gaap = data['facts']['us-gaap']

        # Find first available tag
        df = pd.DataFrame()
        for tag in dividend_tags:
            if tag in us_gaap and 'USD/shares' in us_gaap[tag].get('units', {}):
                df_test = pd.DataFrame(us_gaap[tag]['units']['USD/shares'])

                if is_dividend_data_ok(df_test):
                    df = df_test
                    break
        
        if df.empty:
            print(f"Error getting dividend yield: Can't find dividend tag in facts | us-gaap database")
            return 0.0
            
        # Extract and Filter Dividend Data
        # We look for the 'CommonStockDividendsPerShareDeclared' tag
        #print(f"data tags: {data['facts']['us-gaap'].keys()}")
        #div_raw = data['facts']['us-gaap']['CommonStockDividendsPerShareDeclared']['units']['USD/shares']
        #df = pd.DataFrame(div_raw)
        df['start'] = pd.to_datetime(df['start'])
        df['end'] = pd.to_datetime(df['end'])
        
        # Calculate duration: This is the key to avoiding cumulative YTD values
        df['duration'] = (df['end'] - df['start']).dt.days
        
        # Filter for discrete quarters (approx 90 days)
        # This removes the YTD sums like 2.04, 3.10, and 4.00
        df_discrete = df[(df['duration'] >= 80) & (df['duration'] <= 100)].copy()
        
        # 3. Deduplicate and Get TTM Sum
        # Keep the most recently filed entry for any given period end
        df_discrete = df_discrete.sort_values(['end', 'filed']).drop_duplicates('end', keep='last')
        
        # Sort by date and take the last 4 quarters
        last_4_payments = df_discrete.sort_values('end', ascending=False)['val'].head(4)
        
        if last_4_payments.empty:
            print("get_dividend_yield_percent_final error: last_4_payments.empty")
            return 0.0
            
        ttm_dividend_sum = last_4_payments.sum()

        # 4. Get Current Price
        # Using yfinance to ensure the yield is based on the current market value
        ytick = yf.Ticker(ticker)
        current_price = ytick.fast_info['lastPrice']
        
        # Calculate Yield: (Total Dividends / Price) * 100
        dividend_yield = (ttm_dividend_sum / current_price) * 100
        
        return round(float(dividend_yield), 2)

    except Exception as e:
        # Return 0.0 if ticker has no dividends, CIK isn't found, or API fails
        print(f"Error getting dividend yield: {e}")
        return 0.0


# Find the payout ratio.  pe_df is a dataframe containing columns 'TTM_EPS_Mapped' and 'Close'
def get_payout_ratio(pe_df, div_yield):

    if 'TTM_EPS_Mapped' in pe_df.columns and 'Close' in pe_df.columns:

        try:
            #print(f"Div Yld {div_yield}")
            #print(f"Close {pe_df['Close'].iloc[-1]}")
            #print(f"EPS {pe_df['TTM_EPS_Mapped'].iloc[-1]}")
            return round(div_yield * pe_df['Close'].iloc[-1] / pe_df['TTM_EPS_Mapped'].iloc[-1], 0)

        except Exception as e:
            print(f"Payout Ratio Calculation Error: {e}")
            return 0.0

    else:
        print("Payout Ratio Calculation Error: Missing columns in data")
        return 0.0



def get_profitability_metrics(ticker):
    """
    Returns (ROE, ROIC) as a tuple of floats. Returns (0.0, 0.0) on error.
    """
    ticker = ticker.upper().strip()
    headers = {"User-Agent": "FinanceAnalyst/1.0 (chuckkrapf@yahoo.com)"}
    
    try:
        # 1. Get CIK
        tkr_url = "https://www.sec.gov/files/company_tickers.json"
        ticker_json = requests.get(tkr_url, headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in ticker_json.items() if v['ticker'] == ticker), None)

        # 2. Get SEC Facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        gaap = data['facts']['us-gaap']

        def get_latest_val(tag_list, is_duration=False):
            """Helper to grab the latest value from a list of possible SEC tags."""
            for tag in tag_list:
                if tag in gaap:
                    df = pd.DataFrame(gaap[tag]['units']['USD'])
                    # For Income items (Net Income, EBIT), we sum the last 4 discrete quarters
                    if is_duration:
                        df['start'] = pd.to_datetime(df['start'])
                        df['end'] = pd.to_datetime(df['end'])
                        df['dur'] = (df['end'] - df['start']).dt.days
                        # Filter for ~90 day discrete quarters
                        df = df[(df['dur'] >= 80) & (df['dur'] <= 100)]
                        return df.sort_values('end').tail(4)['val'].sum()
                    # For Balance Sheet (Equity, Debt), we just take the single latest point-in-time
                    else:
                        return df.sort_values('end').iloc[-1]['val']
            return 0

        # --- Data Extraction ---
        # Net Income (TTM)
        net_income = get_latest_val(['NetIncomeLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'], is_duration=True)
        
        # Operating Income / EBIT (TTM)
        ebit = get_latest_val(['OperatingIncomeLoss', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'], is_duration=True)
        
        # Tax Rate Calculation
        tax_exp = get_latest_val(['IncomeTaxExpenseBenefit'], is_duration=True)
        pretax = get_latest_val(['IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments'], is_duration=True)
        tax_rate = max(0, min(tax_exp / pretax, 0.40)) if pretax > 0 else 0.21 # Default to 21% if math fails
        
        # Equity (Point-in-time)
        equity = get_latest_val(['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'])

        # Debt (Point-in-time)
        short_debt = get_latest_val(['ShortTermBorrowings', 'DebtCurrent'])
        long_debt = get_latest_val(['LongTermDebtNoncurrent', 'LongTermDebt'])
        total_debt = short_debt + long_debt
        
        # Cash (Point-in-time)
        cash = get_latest_val(['CashAndCashEquivalentsAtCarryingValue'])

        # --- Calculations ---
        # ROE = Net Income / Equity
        roe = (net_income / equity) * 100 if equity > 0 else 0
        
        # ROIC = NOPAT / (Equity + Debt - Cash)
        # NOPAT = EBIT * (1 - Tax Rate)
        nopat = ebit * (1 - tax_rate)
        invested_capital = equity + total_debt - cash
        roic = (nopat / invested_capital) * 100 if invested_capital > 0 else 0

        return round(roe, 2), round(roic, 2)

    except Exception as e:
        print(f"Error getting ROE and ROIC: {e}")
        return 0.0, 0.0

# --- Execution ---
# roe, roic = get_profitability_metrics("MO")
# print(f"ROE: {roe}% | ROIC: {roic}%")


def get_debt_to_ebitda(ticker):
    """
    Calculates the TTM Debt-to-EBITDA ratio.
    Formula: (Short-term Debt + Long-term Debt) / (TTM Operating Income + TTM D&A)
    Returns 0.0 on error.
    """
    ticker = ticker.upper().strip()
    headers = {"User-Agent": "InstitutionalAnalysis/1.1 (chuckkrapf@yahoo.com.com)"}
    
    try:
        # 1. Get CIK
        cik_map = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in cik_map.items() if v['ticker'] == ticker), None)
        if not cik: return 0.0

        # 2. Get SEC Facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        gaap = data.get('facts', {}).get('us-gaap', {})

        def get_latest_point(tag_list):
            """Returns the most recent balance sheet value."""
            for tag in tag_list:
                if tag in gaap:
                    df = pd.DataFrame(gaap[tag]['units']['USD'])
                    return float(df.sort_values('end').iloc[-1]['val'])
            return 0.0

        def get_ttm_duration(tag_list):
            """Sums the last 4 discrete quarters to get a TTM flow value."""
            for tag in tag_list:
                if tag in gaap:
                    df = pd.DataFrame(gaap[tag]['units']['USD'])
                    df['start'] = pd.to_datetime(df['start'])
                    df['end'] = pd.to_datetime(df['end'])
                    df['days'] = (df['end'] - df['start']).dt.days
                    # Filter for discrete quarterly reports (~90 days)
                    # This prevents mixing YTD cumulative numbers with quarterly numbers
                    discrete = df[df['days'].between(80, 105)].copy()
                    if not discrete.empty:
                        return float(discrete.sort_values('end').tail(4)['val'].sum())
            return 0.0

        # --- Component Extraction ---
        
        # Debt (Balance Sheet - Point in Time)
        st_debt = get_latest_point(['ShortTermBorrowings', 'DebtCurrent', 'LinesOfCreditCurrent'])
        lt_debt = get_latest_point(['LongTermDebtNoncurrent', 'LongTermDebt', 'NetLongTermDebt'])
        total_debt = st_debt + lt_debt

        # EBITDA Components (Income/Cash Flow Statement - TTM)
        ebit = get_ttm_duration(['OperatingIncomeLoss', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'])
        
        # D&A is often found in the Cash Flow section
        da = get_ttm_duration(['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'Depreciation'])

        ebitda_ttm = ebit + da

        # 3. Final Calculation
        if ebitda_ttm <= 0:
            return 0.0
            
        ratio = total_debt / ebitda_ttm
        return round(float(ratio), 2)

    except Exception as e:
        # Catch-all for missing tags or API issues
        print(f"Error getting debt/EBITDA: {e}")
        return 0.0

# Example Usage:
# print(f"MO Debt/EBITDA: {get_debt_to_ebitda('MO')}")

# Get a grade based on where the number is in a list. Example:
# get_grade(x, [2.0, 3.0, 4.0, 5.0], ["A", "B", "C", "D", "E"]) returns:
# "A" if x <= 2.0, "B" if x <= 3.0, ..., "E" if x > 5.0.
def get_grade(x, num_list, grade_list):

    if len(num_list) >= len(grade_list):
        return ""

    for num, grade in zip(num_list, grade_list):

        if x <= num:
            return grade

    return grade_list[len(grade_list)-1]


def get_current_ratio(ticker):
    """
    Calculates the Current Ratio (Current Assets / Current Liabilities).
    Uses a fallback system for SEC GAAP tags and returns 0.0 on error.
    """
    ticker = ticker.upper().strip()
    headers = {"User-Agent": "LiquidityAnalysis/1.1 (chuckkrapf@yahoo.com)"}
    
    try:
        # 1. Get CIK
        cik_map = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers).json()
        cik = next((str(v['cik_str']).zfill(10) for k, v in cik_map.items() if v['ticker'] == ticker), None)
        if not cik: return 0.0

        # 2. Get SEC Facts
        facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = requests.get(facts_url, headers=headers).json()
        gaap = data.get('facts', {}).get('us-gaap', {})

        def get_latest_balance_sheet_val(tag_list):
            """Iterates through tags and returns the most recent point-in-time value."""
            for tag in tag_list:
                if tag in gaap and 'USD' in gaap[tag].get('units', {}):
                    df = pd.DataFrame(gaap[tag]['units']['USD'])
                    # Filter for entries without a 'start' date (point-in-time snapshots)
                    # or just take the most recent 'end' date.
                    df = df.sort_values(by=['end', 'filed'], ascending=[True, True])
                    return float(df.iloc[-1]['val'])
            return None

        # --- Component Extraction ---
        
        # Current Assets Tags
        assets_tags = [
            'AssetsCurrent', 
            'AssetsCurrentExcludingAssetsHeldForSale'
        ]
        current_assets = get_latest_balance_sheet_val(assets_tags)

        # Current Liabilities Tags
        liabilities_tags = [
            'LiabilitiesCurrent', 
            'LiabilitiesCurrentExcludingLiabilitiesHeldForSale'
        ]
        current_liabilities = get_latest_balance_sheet_val(liabilities_tags)

        # 3. Calculation
        if current_assets is None or current_liabilities is None or current_liabilities == 0:
            return 0.0
            
        ratio = current_assets / current_liabilities
        return round(float(ratio), 2)

    except Exception as e:
        # Silently catch errors (network, missing JSON keys, etc.) and return 0.0
        print(f"Error getting current ratio: {e}")
        return 0.0

# Example Usage:
# print(f"Current Ratio for {ticker}: {get_current_ratio(ticker)}")


# Set the variable as requested
chart_font_size = 25

# Streamlit Page Config
st.set_page_config(page_title="Stock Analysis", layout="wide")

# CSS to reduce Title size by roughly 1/3
st.markdown("<h2 style='text-align: left;'>📈 Stock Fundamental Dashboard</h2>", unsafe_allow_html=True)

#@st.cache_data(ttl=86400)
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
                    fig, (ax1, ax2, ax3, ax_text) = plt.subplots(4, 1, figsize=(16, 20), sharex=True, 
                                                        gridspec_kw={'height_ratios': [6, 2, 2, 2]})
    
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
                    
                    # Create individual text elements with different styles
                    headersize=40
                    infosize=30
                    header2size=infosize
                    
                    headerprops = dict(size=headersize, weight='bold')
                    header2props = dict(size=header2size, weight='bold')
                    
                    infoprops = dict(size=infosize)
                    greeninfoprops = dict(size=infosize, color='green')
                    redinfoprops = dict(size=infosize, color='red')
                    orangeinfoprops = dict(size=infosize, color='orange')
                    
                    lines = []
                    lines.append(TextArea(f"Stock Report: {ticker_symbol}", textprops=headerprops))
                    div_yield = get_dividend_yield_percent_final(ticker_symbol)
                    lines.append(TextArea(f"Dividend Yield {div_yield}%", textprops=infoprops))
                    lines.append(TextArea(f"Dividend Payout Ratio {get_payout_ratio(pe_df, div_yield)}%", textprops=infoprops))

                    lines.append(TextArea("", textprops=infoprops))
                    lines.append(TextArea("Profitability and Efficiency", textprops=header2props))
                    roe, roic = get_profitability_metrics(ticker_symbol)
                    lines.append(TextArea(f"ROE: {roe}% | ROIC: {roic}%", textprops=infoprops))
                    lines.append(TextArea(f"Free Cash Flow Yield: {get_fcf_yield(ticker_symbol)}%", textprops=infoprops))

                    lines.append(TextArea("", textprops=infoprops))
                    lines.append(TextArea("Safety", textprops=header2props))
                    debt2ebitda = get_debt_to_ebitda(ticker_symbol)
                    lines.append(TextArea(f"Debt/EBITDA: {debt2ebitda} ({get_grade(debt2ebitda, [2.0, 3.0, 4.0, 5.0], ['A','B','C','D','E'])})", textprops=infoprops))
                    lines.append(TextArea(f"Current Ratio: {get_current_ratio(ticker_symbol)}", textprops=infoprops))
                    
                    # Pack the text lines vertically (pad=0 is internal padding, sep=5 is space between lines)
                    report_box = VPacker(children=lines, align="left", pad=0, sep=5)
                    
                    # Place the "Container" on the plot
                    # xybox attaches it to a coordinate; box_alignment=(0, 1) anchors it to the top-left
                    anchored_box = AnnotationBbox(report_box, xy=(0.0, 0.9), 
                                                  xycoords='axes fraction',
                                                  box_alignment=(0, 1),
                                                  bboxprops=dict(alpha=0)) # alpha=0 hides the box border

                    ax_text.add_artist(anchored_box)

                    # Clean up: Hide the axis lines/ticks for the text area
                    ax_text.axis('off')

                    # Force ax3 to show x-axis labels despite sharex=True
                    #plt.setp(ax3.get_xticklabels(), visible=True)

                    # 1. Tell the tick parameters to stop hiding labels
                    ax3.tick_params(labelbottom=True)
                    
                    # 2. If you are using a recent version of Matplotlib, you might also need:
                    for label in ax3.get_xticklabels():
                        label.set_visible(True)
    
                    plt.tight_layout()
                    st.pyplot(fig)
                
        except Exception as e:
            st.error(f"Error fetching data: {e}")








