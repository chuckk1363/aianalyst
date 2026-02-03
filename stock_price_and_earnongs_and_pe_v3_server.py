import streamlit as st
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Set the variable as requested
chart_font_size = 25

# Streamlit Page Config
st.set_page_config(page_title="Stock Analysis", layout="wide")

# CSS to reduce Title size by roughly 1/3
st.markdown("<h2 style='text-align: left;'>📈 Stock Fundamental Dashboard</h2>", unsafe_allow_html=True)

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
                eps_data = ticker.get_earnings_dates(limit=100)
    
                if eps_data is None or eps_data.empty:
                    st.error(f"Could not find earnings data for {ticker_symbol}")
                else:
                    # 1. CLEANING
                    eps_df = eps_data.reset_index()
                    eps_df.columns.values[0] = 'Date'
                    eps_df.set_index('Date', inplace=True)
                    eps_df = eps_df.dropna(subset=['Reported EPS']).copy()
                    eps_df.index = eps_df.index.tz_localize(None)
                    
                    # Resolve duplicates (Yahoo sometimes lists the same date twice with different times)
                    eps_df = eps_df.groupby(eps_df.index).mean().sort_index()
                
                    # 2. SMARTER TTM CALCULATION
                    # Instead of assuming 4 rows = 1 year, we use a time-based rolling window.
                    # '365D' sums all reported EPS in the last 365 days.
                    eps_df['TTM EPS'] = eps_df['Reported EPS'].rolling(window='365D', min_periods=1).sum()
                
                    # 3. GAP DETECTION (Validation)
                    # Check if the most recent earnings date is too old (e.g., more than 8 months ago)
                    last_report = eps_df.index.max()
                    days_since_report = (pd.Timestamp.now() - last_report).days
                    
                    if days_since_report > 240: # 8 months
                        st.error(f"⚠️ Warning: Earnings data for {ticker_symbol} appears outdated or incomplete (Last report: {last_report.date()}). P/E calculations may be inaccurate.")
                        
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
                    maxlim = pe_df['PE_Ratio'].quantile(0.98)
                    minlim = pe_df['PE_Ratio'].quantile(0.02)
                
                    print(f'maxlim: {maxlim}, minlim: {minlim}')
                    
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






