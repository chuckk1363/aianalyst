import streamlit as st
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd

# Streamlit Page Config
st.set_page_config(page_title="Stock Analysis", layout="wide")
st.title("📈 Stock Fundamental Dashboard")

# 1. User Input in Sidebar
ticker_symbol = st.sidebar.text_input("Enter Ticker Symbol", value="ET").upper()
years = st.sidebar.slider("Years of History", 1, 20, 10)

if ticker_symbol:
    ticker = yf.Ticker(ticker_symbol)
    
    try:
        company_name = ticker.info.get('longName', ticker_symbol)
        
        # Fetch Data
        price_history = ticker.history(period=f"{years}y")
        price_history.index = price_history.index.tz_localize(None)
        eps_data = ticker.get_earnings_dates(limit=100)

        if eps_data is None or eps_data.empty:
            st.error(f"Could not find earnings data for {ticker_symbol}")
        else:
            # CLEANING & FILTERING
            eps_df = eps_data.dropna(subset=['Reported EPS']).copy()
            eps_df.index = eps_df.index.tz_localize(None)
            eps_df = eps_df.groupby(eps_df.index).mean().sort_index()
            eps_df['TTM EPS'] = eps_df['Reported EPS'].rolling(window=4).sum()

            start_date = price_history.index.min()
            eps_df_filtered = eps_df.loc[start_date:]

            # Prepare P/E Calculation
            pe_df = price_history[['Close']].copy()
            pe_df['TTM_EPS_Mapped'] = eps_df['TTM EPS'].reindex(pe_df.index, method='ffill')
            pe_df['PE_Ratio'] = pe_df['Close'] / pe_df['TTM_EPS_Mapped']

            # Setup Plot
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True, 
                                                gridspec_kw={'height_ratios': [4, 1, 1]})

            # --- TOP CHART: PRICE ---
            ax1.plot(price_history.index, price_history['Close'], color='tab:blue', linewidth=1.5)
            ax1.set_ylabel('Price (USD)', fontweight='bold')
            ax1.set_title(f'{company_name} ({ticker_symbol})', fontsize=16)
            ax1.grid(True, alpha=0.3)

            # --- MIDDLE CHART: EPS ---
            ax2.step(eps_df_filtered.index, eps_df_filtered['TTM EPS'], color='tab:red', where='post', linewidth=2)
            ax2.set_ylabel('TTM EPS', fontweight='bold')
            ax2.grid(True, alpha=0.3)

            # --- BOTTOM CHART: P/E RATIO ---
            ax3.plot(pe_df.index, pe_df['PE_Ratio'], color='tab:green', linewidth=1.5)
            ax3.set_ylabel('P/E Ratio', fontweight='bold')
            ax3.set_ylim(0, pe_df['PE_Ratio'].quantile(0.98)) 
            ax3.grid(True, alpha=0.3)

            plt.tight_layout()
            
            # DISPLAY IN STREAMLIT
            st.pyplot(fig)
            
    except Exception as e:
        st.error(f"Error fetching data: {e}")