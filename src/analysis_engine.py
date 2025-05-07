import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

class AnalysisEngine:
    def __init__(self, config_manager, logger_object):
        self.config_manager = config_manager
        self.logger = logger_object.bind(name="AnalysisEngine")
        self.strategy_params = self.config_manager.get_strategy_params()
        self.logger.info("AnalysisEngine initialized.")

    def detect_swing_points(self, df: pd.DataFrame, candle_body_ratio_threshold: float = 0.3) -> pd.DataFrame:
        """
        Detects swing highs and lows based on the strategy parameters.
        A swing high is a candle high that is higher than the highs of a certain number of candles 
        to its left and right (defined by lookback_left and lookback_right in config).
        A swing low is a candle low that is lower than the lows of a certain number of candles
        to its left and right.

        Adds 'swing_high' and 'swing_low' columns to the DataFrame.
        - swing_high will have the price of the high if it's a swing high, else NaN.
        - swing_low will have the price of the low if it's a swing low, else NaN.
        
        Args:
            df: Pandas DataFrame with 'high' and 'low' columns.
            candle_body_ratio_threshold: Minimum ratio of candle body to total range for a candle to be considered strong enough
                                         to potentially form a swing point. Helps filter out dojis or very small body candles
                                         from being marked as primary swing points if desired.

        Returns:
            Pandas DataFrame with added 'swing_high' and 'swing_low' columns.
        """
        if 'high' not in df.columns or 'low' not in df.columns:
            self.logger.error("DataFrame must contain 'high' and 'low' columns for swing point detection.")
            return df

        lookback_left = self.strategy_params.get('swing_points', {}).get('lookback_left', 5)
        lookback_right = self.strategy_params.get('swing_points', {}).get('lookback_right', 5)

        df_copy = df.copy()
        df_copy['swing_high'] = np.nan
        df_copy['swing_low'] = np.nan
        
        # Calculate candle body and range for filtering weak candles (optional)
        # df_copy['candle_body'] = abs(df_copy['open'] - df_copy['close'])
        # df_copy['candle_range'] = df_copy['high'] - df_copy['low']
        # df_copy['body_to_range_ratio'] = df_copy['candle_body'] / df_copy['candle_range']
        # df_copy['body_to_range_ratio'].fillna(0, inplace=True) # Handle division by zero if range is 0

        for i in range(lookback_left, len(df_copy) - lookback_right):
            is_sh = True
            for j in range(1, lookback_left + 1):
                if df_copy['high'].iloc[i] <= df_copy['high'].iloc[i-j]:
                    is_sh = False
                    break
            if is_sh:
                for j in range(1, lookback_right + 1):
                    if df_copy['high'].iloc[i] < df_copy['high'].iloc[i+j]: 
                        is_sh = False
                        break
            if is_sh:
                df_copy.loc[df_copy.index[i], 'swing_high'] = df_copy['high'].iloc[i]

            is_sl = True
            for j in range(1, lookback_left + 1):
                if df_copy['low'].iloc[i] >= df_copy['low'].iloc[i-j]:
                    is_sl = False
                    break
            if is_sl:
                for j in range(1, lookback_right + 1):
                    if df_copy['low'].iloc[i] > df_copy['low'].iloc[i+j]: 
                        is_sl = False
                        break
            if is_sl:
                df_copy.loc[df_copy.index[i], 'swing_low'] = df_copy['low'].iloc[i]
        
        return df_copy

    def detect_bos(self, df_with_swings: pd.DataFrame) -> pd.DataFrame:
        """
        Detects Break of Structure (BOS) based on swing points and closing prices.

        Args:
            df_with_swings: DataFrame with 'close', 'swing_high', 'swing_low' columns.

        Returns:
            DataFrame with added 'bullish_bos_level', 'bearish_bos_level',
            'bullish_bos_src_time', 'bearish_bos_src_time' columns.
        """
        df = df_with_swings.copy()
        df['bullish_bos_level'] = np.nan
        df['bearish_bos_level'] = np.nan
        df['bullish_bos_src_time'] = pd.NaT 
        df['bearish_bos_src_time'] = pd.NaT

        confirmation_candles = self.strategy_params.get('bos', {}).get('confirmation_candles', 1)
        if confirmation_candles < 1:
            confirmation_candles = 1 # Ensure at least 1

        active_sh_price = np.nan
        active_sh_time = pd.NaT
        active_sl_price = np.nan
        active_sl_time = pd.NaT

        for i in range(len(df)):
            current_time = df.index[i]
            current_close = df['close'].iloc[i]

            # Update active swing points if a new one is encountered at current_time
            # These become the levels to beat for a BOS
            if pd.notna(df['swing_high'].iloc[i]):
                # A new SH is formed, this is now our active SH to watch for a break
                active_sh_price = df['swing_high'].iloc[i]
                active_sh_time = current_time
            
            if pd.notna(df['swing_low'].iloc[i]):
                # A new SL is formed, this is now our active SL to watch for a break
                active_sl_price = df['swing_low'].iloc[i]
                active_sl_time = current_time

            # Check for Bullish BOS
            # active_sh_time < current_time ensures the swing high was formed *before* the current candle tries to break it.
            if pd.notna(active_sh_price) and active_sh_time < current_time:
                if current_close > active_sh_price:
                    # Potential BOS, check confirmation candles from current candle onwards
                    if i + confirmation_candles - 1 < len(df):
                        confirmed = True
                        # The first candle (current_close) already broke. Check next confirmation_candles - 1
                        for k_confirm in range(1, confirmation_candles): 
                            if df['close'].iloc[i + k_confirm] <= active_sh_price:
                                confirmed = False
                                break
                        
                        if confirmed:
                            bos_confirm_time = df.index[i + confirmation_candles - 1]
                            df.loc[bos_confirm_time, 'bullish_bos_level'] = active_sh_price
                            df.loc[bos_confirm_time, 'bullish_bos_src_time'] = active_sh_time
                            self.logger.debug(f"Bullish BOS confirmed at {bos_confirm_time}: Broke SH {active_sh_price} (from {active_sh_time}) with close {df['close'].iloc[i + confirmation_candles - 1]}.")
                            active_sh_price = np.nan # Invalidate this SH for subsequent bullish BOS
                            active_sh_time = pd.NaT
            
            # Check for Bearish BOS
            if pd.notna(active_sl_price) and active_sl_time < current_time:
                if current_close < active_sl_price:
                    if i + confirmation_candles - 1 < len(df):
                        confirmed = True
                        for k_confirm in range(1, confirmation_candles):
                            if df['close'].iloc[i + k_confirm] >= active_sl_price:
                                confirmed = False
                                break
                        
                        if confirmed:
                            bos_confirm_time = df.index[i + confirmation_candles - 1]
                            df.loc[bos_confirm_time, 'bearish_bos_level'] = active_sl_price
                            df.loc[bos_confirm_time, 'bearish_bos_src_time'] = active_sl_time
                            self.logger.debug(f"Bearish BOS confirmed at {bos_confirm_time}: Broke SL {active_sl_price} (from {active_sl_time}) with close {df['close'].iloc[i + confirmation_candles - 1]}.")
                            active_sl_price = np.nan # Invalidate this SL for subsequent bearish BOS
                            active_sl_time = pd.NaT
        return df

# Example usage (for testing)
if __name__ == '__main__':
    import asyncio
    # Assuming config_manager and logger_instance are set up as in other modules
    # This requires src to be in PYTHONPATH or running with python -m src.analysis_engine
    from .config_manager import config_manager
    from .logging_service import logger_instance
    from .data_ingestion import DataIngestionModule # For fetching test data

    async def test_analysis_engine():
        logger_instance.info("Starting AnalysisEngine test...")
        
        # Initialize DataIngestionModule to get some data
        data_module = DataIngestionModule(config_manager, logger_instance)
        initialized = await data_module.initialize()
        if not initialized or not data_module.exchange:
            logger_instance.error("Failed to initialize DataIngestionModule. Aborting test.")
            return

        # Fetch some test data
        symbol_to_test = config_manager.get("portfolio.coins_to_scan", ["BTCUSDT"])[0]
        timeframe_to_test = config_manager.get("strategy_params.timeframes.contextual", "15m")
        logger_instance.info(f"Fetching data for {symbol_to_test} ({timeframe_to_test}) for swing point test...")
        ohlcv_df = await data_module.fetch_ohlcv(symbol=symbol_to_test, timeframe=timeframe_to_test, limit=50)
        await data_module.close()

        if ohlcv_df is None or ohlcv_df.empty:
            logger_instance.error(f"Could not fetch OHLCV data for {symbol_to_test}. Aborting test.")
            return
        
        logger_instance.info(f"Fetched {len(ohlcv_df)} candles for {symbol_to_test}.")
        # Add 'open' and 'close' if missing and needed for future candle body ratio logic
        # For now, swing point detection only needs 'high' and 'low'
        # If 'open'/'close' are not in the DataFrame from fetch_ohlcv (they should be),
        # this part would need adjustment or dummy data for the commented-out body_ratio logic.
        # Current fetch_ohlcv from ccxt provides them implicitly in the list order.

        # Initialize AnalysisEngine
        analysis_engine = AnalysisEngine(config_manager, logger_instance)
        
        # Test swing point detection
        df_with_swings = analysis_engine.detect_swing_points(ohlcv_df.copy()) # Pass a copy
        
        swing_highs = df_with_swings[df_with_swings['swing_high'].notna()]
        swing_lows = df_with_swings[df_with_swings['swing_low'].notna()]
        
        logger_instance.info(f"Detected {len(swing_highs)} swing highs:")
        if not swing_highs.empty:
            logger_instance.info(f"\n{swing_highs[['high', 'swing_high']]}")
        
        logger_instance.info(f"Detected {len(swing_lows)} swing lows:")
        if not swing_lows.empty:
            logger_instance.info(f"\n{swing_lows[['low', 'swing_low']]}")

        # Test BOS detection
        logger_instance.info("Testing BOS detection...")
        df_with_bos = analysis_engine.detect_bos(df_with_swings.copy())

        bullish_bos_events = df_with_bos[df_with_bos['bullish_bos_level'].notna()]
        bearish_bos_events = df_with_bos[df_with_bos['bearish_bos_level'].notna()]

        logger_instance.info(f"Detected {len(bullish_bos_events)} bullish BOS events:")
        if not bullish_bos_events.empty:
            logger_instance.info(f"\n{bullish_bos_events[['close', 'bullish_bos_level', 'bullish_bos_src_time']]}")

        logger_instance.info(f"Detected {len(bearish_bos_events)} bearish BOS events:")
        if not bearish_bos_events.empty:
            logger_instance.info(f"\n{bearish_bos_events[['close', 'bearish_bos_level', 'bearish_bos_src_time']]}")

        conf_candles = analysis_engine.strategy_params.get('bos', {}).get('confirmation_candles', 1)
        logger_instance.info(f"BOS detection used confirmation_candles: {conf_candles}")

        lookback_left = analysis_engine.strategy_params.get('swing_points', {}).get('lookback_left', 5)
        lookback_right = analysis_engine.strategy_params.get('swing_points', {}).get('lookback_right', 5)
        logger_instance.info(f"Swing point detection used lookbacks: Left={lookback_left}, Right={lookback_right}")
        logger_instance.info("AnalysisEngine test finished.")

    asyncio.run(test_analysis_engine()) 