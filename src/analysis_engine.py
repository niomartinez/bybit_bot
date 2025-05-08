import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

class AnalysisEngine:
    def __init__(self, config_manager, logger_object, data_ingestion_module=None):
        self.config_manager = config_manager
        self.logger = logger_object.bind(name="AnalysisEngine")
        self.strategy_params = self.config_manager.get_strategy_params()
        self.data_ingestion_module = data_ingestion_module
        if self.data_ingestion_module is None and self.strategy_params.get('entry_logic_5m',{}).get('enabled', True):
             self.logger.warning("DataIngestionModule not provided to AnalysisEngine, 5m entry logic will be skipped if attempted.")
        self.logger.info("AnalysisEngine initialized.")

    def _get_timeframe_specific_params(self, base_key: str, timeframe_key: Optional[str] = None) -> Dict:
        """Helper to get parameters for a specific timeframe (e.g., 15m or 5m)."""
        if timeframe_key:
            specific_params = self.strategy_params.get(f"{base_key}_{timeframe_key}", None)
            if specific_params is not None:
                return specific_params
        return self.strategy_params.get(base_key, {})

    def detect_swing_points(self, df: pd.DataFrame, timeframe_key: Optional[str] = None) -> pd.DataFrame:
        """
        Detects swing highs and lows based on the strategy parameters.
        Can use timeframe-specific parameters if timeframe_key is provided (e.g., '5m').
        """
        if 'high' not in df.columns or 'low' not in df.columns:
            self.logger.error("DataFrame must contain 'high' and 'low' columns for swing point detection.")
            return df

        swing_point_params = self._get_timeframe_specific_params('swing_points', timeframe_key)
        lookback_left = swing_point_params.get('lookback_left', 5)
        lookback_right = swing_point_params.get('lookback_right', 5)
        
        df_copy = df.copy()
        df_copy['swing_high'] = np.nan
        df_copy['swing_low'] = np.nan
        
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

    def detect_bos(self, df_with_swings: pd.DataFrame, timeframe_key: Optional[str] = None) -> pd.DataFrame:
        """
        Detects Break of Structure (BOS) based on swing points and closing prices.
        Can use timeframe-specific parameters if timeframe_key is provided (e.g., '5m').
        """
        df = df_with_swings.copy()
        df['bullish_bos_level'] = np.nan
        df['bearish_bos_level'] = np.nan
        df['bullish_bos_src_time'] = pd.Series(index=df.index, dtype='datetime64[ns]')
        df['bearish_bos_src_time'] = pd.Series(index=df.index, dtype='datetime64[ns]')

        bos_params = self._get_timeframe_specific_params('bos', timeframe_key)
        confirmation_candles = bos_params.get('confirmation_candles', 1)

        if confirmation_candles < 1:
            confirmation_candles = 1 
        
        active_sh_price = np.nan
        active_sh_time = pd.NaT
        active_sl_price = np.nan
        active_sl_time = pd.NaT

        for i in range(len(df)):
            current_time = df.index[i]
            current_close = df['close'].iloc[i]

            if pd.notna(df['swing_high'].iloc[i]):
                active_sh_price = df['swing_high'].iloc[i]
                active_sh_time = current_time
            
            if pd.notna(df['swing_low'].iloc[i]):
                active_sl_price = df['swing_low'].iloc[i]
                active_sl_time = current_time

            if pd.notna(active_sh_price) and active_sh_time < current_time:
                if current_close > active_sh_price:
                    if i + confirmation_candles - 1 < len(df):
                        confirmed = True
                        for k_confirm in range(1, confirmation_candles): 
                            if df['close'].iloc[i + k_confirm] <= active_sh_price:
                                confirmed = False
                                break
                        
                        if confirmed:
                            bos_confirm_time = df.index[i + confirmation_candles - 1]
                            df.loc[bos_confirm_time, 'bullish_bos_level'] = active_sh_price
                            df.loc[bos_confirm_time, 'bullish_bos_src_time'] = active_sh_time
                            active_sh_price = np.nan 
                            active_sh_time = pd.NaT
            
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
                            active_sl_price = np.nan 
                            active_sl_time = pd.NaT
        return df

    def identify_impulse_leg(self, df_with_bos: pd.DataFrame, timeframe_key: Optional[str] = None) -> pd.DataFrame:
        """
        Identifies the impulse leg associated with each Break of Structure (BOS).
        The impulse leg starts from the swing point that initiated the move leading to the BOS,
        and ends at the new swing point formed after the BOS.
        Assumes df_with_bos contains swing_high/low columns detected for the relevant timeframe.
        """
        df = df_with_bos.copy()
        df['impulse_leg_start_time'] = pd.Series(index=df.index, dtype='datetime64[ns]')
        df['impulse_leg_start_price'] = np.nan
        df['impulse_leg_end_time'] = pd.Series(index=df.index, dtype='datetime64[ns]')
        df['impulse_leg_end_price'] = np.nan
        df['impulse_direction'] = None
        df['fib_levels'] = pd.Series(index=df.index, dtype=object) 

        for i in range(len(df)):
            current_event_time = df.index[i] 

            if pd.notna(df['bullish_bos_level'].iloc[i]):
                bos_src_time = df['bullish_bos_src_time'].iloc[i]
                
                relevant_swing_lows = df.loc[:bos_src_time, 'swing_low'].dropna()
                if not relevant_swing_lows.empty:
                    impulse_start_time = relevant_swing_lows.index[-1]
                    impulse_start_price = relevant_swing_lows.iloc[-1]

                    subsequent_swing_highs = df.loc[current_event_time:, 'swing_high'].dropna()
                    
                    if impulse_start_time is not pd.NaT:
                         subsequent_swing_highs = subsequent_swing_highs[subsequent_swing_highs.index > impulse_start_time]

                    if not subsequent_swing_highs.empty:
                        impulse_end_time = subsequent_swing_highs.index[0]
                        impulse_end_price = subsequent_swing_highs.iloc[0]
                        
                        if impulse_end_price > impulse_start_price:
                            df.at[current_event_time, 'impulse_leg_start_time'] = impulse_start_time
                            df.at[current_event_time, 'impulse_leg_start_price'] = impulse_start_price
                            df.at[current_event_time, 'impulse_leg_end_time'] = impulse_end_time
                            df.at[current_event_time, 'impulse_leg_end_price'] = impulse_end_price
                            df.at[current_event_time, 'impulse_direction'] = 'bullish'
                            
                            fib_data = self.calculate_fibonacci_levels(impulse_end_price, impulse_start_price, 'bullish')
                            df.at[current_event_time, 'fib_levels'] = fib_data

                        # else:
                            # self.logger.warning(f"Bullish BOS at {current_event_time}: Identified impulse end {impulse_end_price}@{impulse_end_time} is not higher than start {impulse_start_price}@{impulse_start_time}. Leg ignored.")
                    # else:
                        # self.logger.debug(f"Bullish BOS at {current_event_time}: No subsequent swing high found after BOS to define impulse end.")
                # else:
                    # self.logger.debug(f"Bullish BOS at {current_event_time}: No prior swing low found to define impulse start.")

            elif pd.notna(df['bearish_bos_level'].iloc[i]):
                bos_src_time = df['bearish_bos_src_time'].iloc[i]

                relevant_swing_highs = df.loc[:bos_src_time, 'swing_high'].dropna()
                if not relevant_swing_highs.empty:
                    impulse_start_time = relevant_swing_highs.index[-1]
                    impulse_start_price = relevant_swing_highs.iloc[-1]

                    subsequent_swing_lows = df.loc[current_event_time:, 'swing_low'].dropna()
                    
                    if impulse_start_time is not pd.NaT:
                        subsequent_swing_lows = subsequent_swing_lows[subsequent_swing_lows.index > impulse_start_time]

                    if not subsequent_swing_lows.empty:
                        impulse_end_time = subsequent_swing_lows.index[0]
                        impulse_end_price = subsequent_swing_lows.iloc[0]

                        if impulse_end_price < impulse_start_price:
                            df.at[current_event_time, 'impulse_leg_start_time'] = impulse_start_time
                            df.at[current_event_time, 'impulse_leg_start_price'] = impulse_start_price
                            df.at[current_event_time, 'impulse_leg_end_time'] = impulse_end_time
                            df.at[current_event_time, 'impulse_leg_end_price'] = impulse_end_price
                            df.at[current_event_time, 'impulse_direction'] = 'bearish'

                            fib_data = self.calculate_fibonacci_levels(impulse_start_price, impulse_end_price, 'bearish')
                            df.at[current_event_time, 'fib_levels'] = fib_data
                            # self.logger.debug(f"Bearish Impulse Leg for BOS at {current_event_time}: Starts {impulse_start_price}@{impulse_start_time}, Ends {impulse_end_price}@{impulse_end_time}")
                        # else:
                            # self.logger.warning(f"Bearish BOS at {current_event_time}: Identified impulse end {impulse_end_price}@{impulse_end_time} is not lower than start {impulse_start_price}@{impulse_start_time}. Leg ignored.")
                    # else:
                        # self.logger.debug(f"Bearish BOS at {current_event_time}: No subsequent swing low found after BOS to define impulse end.")
                # else:
                    # self.logger.debug(f"Bearish BOS at {current_event_time}: No prior swing high found to define impulse start.")
        return df

    def calculate_fibonacci_levels(self, impulse_leg_high: float, impulse_leg_low: float, direction: str) -> Dict[str, float]:
        """
        Calculates Fibonacci retracement levels for a given impulse leg.
        """
        fib_params = self.strategy_params.get('fibonacci', {})
        fib_levels_config = fib_params.get('levels_to_watch', [0.5, 0.618, 0.786])

        if not isinstance(fib_levels_config, list):
            self.logger.warning(f"strategy_params.fibonacci.levels_to_watch in config is not a list. Using default: {[0.5, 0.618, 0.786]}")
            fib_levels_config = [0.5, 0.618, 0.786]
            
        calculated_levels = {}
        leg_range = impulse_leg_high - impulse_leg_low
        if leg_range == 0:
            # self.logger.warning("Impulse leg range is zero, cannot calculate Fibonacci levels.")
            return calculated_levels

        for level in fib_levels_config:
            if not (0 < level < 1):
                # self.logger.warning(f"Invalid Fibonacci level {level} in config. Skipping.")
                continue
            
            level_key = f"{level:.3f}".rstrip('0').rstrip('.') 

            if direction == 'bullish':
                calculated_levels[level_key] = impulse_leg_high - (leg_range * level)
            elif direction == 'bearish':
                calculated_levels[level_key] = impulse_leg_low + (leg_range * level)
            # else:
                # self.logger.warning(f"Unknown impulse direction '{direction}' for Fibonacci calculation.")
                # return {} 
        return calculated_levels

    def detect_fvg(self, df_ohlcv: pd.DataFrame, 
                     timeframe_key: Optional[str] = None,
                     impulse_start_time: Optional[pd.Timestamp] = None, 
                     impulse_end_time: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """
        Detects Fair Value Gaps (FVGs) in the provided OHLCV data.
        FVGs are marked at the index of the second candle (candle i) in the 3-candle pattern.
        """
        df = df_ohlcv.copy()
        df['bullish_fvg_top'] = np.nan
        df['bullish_fvg_bottom'] = np.nan
        df['bearish_fvg_top'] = np.nan
        df['bearish_fvg_bottom'] = np.nan

        scan_df = df
        if impulse_start_time and impulse_end_time:
            scan_df = df.loc[impulse_start_time:impulse_end_time]
        elif impulse_start_time:
            scan_df = df.loc[impulse_start_time:]
        elif impulse_end_time:
            scan_df = df.loc[:impulse_end_time]

        if len(scan_df) < 3:
            return df 

        for i in range(1, len(scan_df) - 1):
            idx_i = scan_df.index[i] 
            
            high_i_minus_1 = scan_df['high'].iloc[i-1]
            low_i_plus_1 = scan_df['low'].iloc[i+1]
            
            if high_i_minus_1 < low_i_plus_1:
                df.loc[idx_i, 'bullish_fvg_top'] = low_i_plus_1
                df.loc[idx_i, 'bullish_fvg_bottom'] = high_i_minus_1
                # self.logger.debug(f"Bullish FVG detected at {idx_i} for {timeframe_key if timeframe_key else 'general'}: Top={low_i_plus_1}, Bottom={high_i_minus_1}")

            low_i_minus_1 = scan_df['low'].iloc[i-1]
            high_i_plus_1 = scan_df['high'].iloc[i+1]

            if low_i_minus_1 > high_i_plus_1:
                df.loc[idx_i, 'bearish_fvg_top'] = low_i_minus_1
                df.loc[idx_i, 'bearish_fvg_bottom'] = high_i_plus_1
                # self.logger.debug(f"Bearish FVG detected at {idx_i} for {timeframe_key if timeframe_key else 'general'}: Top={low_i_minus_1}, Bottom={high_i_plus_1}")
        return df

    def find_poi_confluence(self, df_processed: pd.DataFrame, timeframe_key: Optional[str] = None) -> pd.DataFrame:
        """
        Identifies Points of Interest (POIs) based on confluence of FVG, Fibonacci levels, and BOS retest.
        POIs are marked at the timestamp of the FVG that forms the core of the confluence.
        This method assumes it's working on the 15m (contextual) DataFrame which has 15m impulse legs and FVGs.
        """
        df = df_processed.copy()
        df['poi_type'] = None
        df['poi_high_price'] = np.nan
        df['poi_low_price'] = np.nan
        df['poi_confidence_score'] = 0
        df['poi_contributing_factors'] = [[] for _ in range(len(df))]

        poi_params = self.strategy_params.get('poi_confluence', {})
        min_confidence_score_cfg = poi_params.get('min_confidence_score', 3)
        bos_retest_tolerance_percent = poi_params.get('bos_retest_tolerance_percent', 0.1) / 100.0
        fib_fvg_overlap_tolerance_percent = poi_params.get('fib_fvg_overlap_tolerance_percent', 0.05) / 100.0

        impulse_leg_rows = df[df['impulse_direction'].notna()]

        for bos_event_time, leg_row in impulse_leg_rows.iterrows():
            direction = leg_row['impulse_direction']
            impulse_start_time = leg_row['impulse_leg_start_time']
            impulse_end_time = leg_row['impulse_leg_end_time']
            fib_levels_dict = leg_row['fib_levels']
            
            bos_level_price = leg_row['bullish_bos_level'] if direction == 'bullish' else leg_row['bearish_bos_level']

            if pd.isna(impulse_start_time) or pd.isna(impulse_end_time) or not fib_levels_dict or pd.isna(bos_level_price):
                continue

            fvgs_within_leg = df.loc[impulse_start_time:impulse_end_time]

            for fvg_time, fvg_row_data in fvgs_within_leg.iterrows():
                current_confidence = 0
                contributing_factors = []
                
                fvg_high, fvg_low, fvg_col_type = np.nan, np.nan, None
                
                if direction == 'bullish' and pd.notna(fvg_row_data['bullish_fvg_top']):
                    fvg_high = fvg_row_data['bullish_fvg_top']
                    fvg_low = fvg_row_data['bullish_fvg_bottom']
                    fvg_col_type = 'bullish_fvg'
                elif direction == 'bearish' and pd.notna(fvg_row_data['bearish_fvg_top']):
                    fvg_high = fvg_row_data['bearish_fvg_top'] 
                    fvg_low = fvg_row_data['bearish_fvg_bottom']
                    fvg_col_type = 'bearish_fvg'
                
                if not fvg_col_type or pd.isna(fvg_high) or pd.isna(fvg_low) or fvg_high == fvg_low :
                    continue

                current_confidence += 1 
                contributing_factors.append("FVG_IN_IMPULSE")

                fvg_mid_price = (fvg_high + fvg_low) / 2
                for fib_key, fib_price in fib_levels_dict.items():
                    tolerance = fib_price * fib_fvg_overlap_tolerance_percent
                    if max(fvg_low, fib_price - tolerance) <= min(fvg_high, fib_price + tolerance):
                        current_confidence += 1
                        contributing_factors.append(f"FIB_{fib_key}_OVERLAP")
                        break 
                
                bos_tolerance_abs = bos_level_price * bos_retest_tolerance_percent
                if max(fvg_low, bos_level_price - bos_tolerance_abs) <= min(fvg_high, bos_level_price + bos_tolerance_abs) :
                    current_confidence += 1
                    contributing_factors.append("BOS_RETEST_NEAR_FVG")

                if current_confidence >= min_confidence_score_cfg:
                    if current_confidence >= df.at[fvg_time, 'poi_confidence_score']:
                        df.at[fvg_time, 'poi_type'] = direction 
                        df.at[fvg_time, 'poi_high_price'] = fvg_high
                        df.at[fvg_time, 'poi_low_price'] = fvg_low
                        df.at[fvg_time, 'poi_confidence_score'] = current_confidence
                        df.at[fvg_time, 'poi_contributing_factors'] = list(contributing_factors) 
                        # self.logger.info(f"POI Confirmed at {fvg_time} ({direction}): Score={current_confidence}, Factors={contributing_factors}, POI Range=({fvg_low}-{fvg_high})")
        return df

    async def find_5m_entry_signals(self, df_15m_processed: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Identifies 5m entry signals based on 15m POIs.
        Fetches 5m data, runs 5m analysis (swings, BOS, FVGs), and checks entry conditions.
        """
        if self.data_ingestion_module is None:
            self.logger.error("DataIngestionModule not available. Cannot fetch 5m data or find 5m entry signals.")
            return df_15m_processed

        df_15m_with_entries = df_15m_processed.copy()
        df_15m_with_entries['entry_5m_time'] = pd.Series(index=df_15m_with_entries.index, dtype='datetime64[ns]')
        df_15m_with_entries['entry_5m_price'] = np.nan
        df_15m_with_entries['entry_5m_type'] = None # 'FVG_MITIGATION', 'MSS_RETEST'
        df_15m_with_entries['entry_5m_sl_price'] = np.nan
        df_15m_with_entries['entry_5m_raw_data_range_start'] = pd.Series(index=df_15m_with_entries.index, dtype='datetime64[ns]')
        df_15m_with_entries['entry_5m_raw_data_range_end'] = pd.Series(index=df_15m_with_entries.index, dtype='datetime64[ns]')

        # Config for 5m entries
        entry_logic_5m_params = self.strategy_params.get('entry_logic_5m', {})
        use_fvg_entry = entry_logic_5m_params.get('use_fvg_entry', True)
        use_mss_bos_entry = entry_logic_5m_params.get('use_mss_bos_entry', True)
        # Simple SL buffer (e.g., percentage or fixed amount - needs refinement)
        sl_buffer_percent = 0.0005 # Example: 0.05% buffer beyond structure
        
        # How many 15m candles back from POI candle time to fetch 5m data for context, and how many forward for entry hunting
        # Example: if POI is at 15:00 on 15m chart, we might want 5m data from 14:00 to 16:00
        context_timeframe_duration_minutes = pd.Timedelta(self.strategy_params.get('timeframes',{}).get('contextual','15m')).total_seconds() / 60
        num_15m_candles_back_for_5m = 4
        num_15m_candles_forward_for_5m = 8

        pois_15m = df_15m_with_entries[df_15m_with_entries['poi_confidence_score'] > 0].sort_index()

        for poi_15m_time, poi_15m_row in pois_15m.iterrows():
            poi_15m_type = poi_15m_row['poi_type']
            poi_15m_high = poi_15m_row['poi_high_price']
            poi_15m_low = poi_15m_row['poi_low_price']
            self.logger.info(f"Processing 15m POI at {poi_15m_time} ({poi_15m_type}) for 5m entry signals. POI Range: {poi_15m_low}-{poi_15m_high}")

            fetch_5m_start_time = poi_15m_time - pd.Timedelta(minutes=num_15m_candles_back_for_5m * context_timeframe_duration_minutes)
            fetch_5m_end_time = poi_15m_time + pd.Timedelta(minutes=num_15m_candles_forward_for_5m * context_timeframe_duration_minutes)
            
            df_15m_with_entries.at[poi_15m_time, 'entry_5m_raw_data_range_start'] = fetch_5m_start_time
            df_15m_with_entries.at[poi_15m_time, 'entry_5m_raw_data_range_end'] = fetch_5m_end_time

            df_5m = await self.data_ingestion_module.fetch_ohlcv(
                symbol=symbol, 
                timeframe=self.strategy_params.get('timeframes',{}).get('execution','5m'), 
                since=int(fetch_5m_start_time.timestamp() * 1000),
                limit=1000
            )

            if df_5m is None or df_5m.empty:
                self.logger.warning(f"Could not fetch 5m data for {symbol} from {fetch_5m_start_time} to {fetch_5m_end_time} for POI at {poi_15m_time}.")
                continue
            
            df_5m = df_5m[(df_5m.index >= fetch_5m_start_time) & (df_5m.index <= fetch_5m_end_time)]
            if df_5m.empty:
                self.logger.info(f"No 5m data available in the precise range {fetch_5m_start_time} to {fetch_5m_end_time} for POI at {poi_15m_time}.")
                continue
                
            self.logger.info(f"Fetched {len(df_5m)} 5m candles for {symbol} from {df_5m.index.min()} to {df_5m.index.max()} for POI at {poi_15m_time}")

            df_5m = self.detect_swing_points(df_5m, timeframe_key='5m')
            df_5m = self.detect_fvg(df_5m, timeframe_key='5m')
            
            # Iterate through 5m candles *after* price has entered the 15m POI zone
            # The POI time (fvg_time on 15m) is our reference. We look for entries *after* this time.
            # candles_after_poi_touch_or_entry_into_poi = df_5m[df_5m.index >= poi_15m_time] # Start looking from the 15m POI candle forward
            
            # State variables for tracking 5m interaction within the POI
            has_entered_poi = False
            entry_found_for_poi = False
            # Track swings formed *after* POI entry to define the pullback for MSS
            last_5m_swing_low_ts = pd.NaT
            last_5m_swing_low_price = np.nan
            last_5m_swing_high_ts = pd.NaT
            last_5m_swing_high_price = np.nan

            # Iterate through 5m candles starting around the POI time
            for idx_5m in df_5m.index:
                if idx_5m < poi_15m_time:
                     continue # Skip candles before the 15m POI event time
                 
                if entry_found_for_poi:
                    break # Stop processing 5m candles once an entry is found for this POI

                row_5m = df_5m.loc[idx_5m]

                # Check if price on 5m chart has entered the 15m POI range
                current_candle_entered_poi = max(row_5m['low'], poi_15m_low) <= min(row_5m['high'], poi_15m_high)
                if current_candle_entered_poi:
                    has_entered_poi = True
                
                if not has_entered_poi:
                    continue # Keep iterating 5m candles until price first enters the 15m POI

                # --- Price is now interacting or has interacted with the 15m POI --- 
                
                # Update last known 5m swing points formed *after* POI entry started
                if pd.notna(row_5m['swing_low']):
                    last_5m_swing_low_ts = idx_5m
                    last_5m_swing_low_price = row_5m['swing_low']
                if pd.notna(row_5m['swing_high']):
                    last_5m_swing_high_ts = idx_5m
                    last_5m_swing_high_price = row_5m['swing_high']

                # --- Check Entry Triggers --- 
                entry_price = np.nan
                sl_price = np.nan
                entry_type = None

                # Option A: 5m FVG Mitigation Entry (Check first)
                if use_fvg_entry:
                    if poi_15m_type == 'bullish' and pd.notna(row_5m['bullish_fvg_top']):
                        # Check if current candle low dipped into the FVG marked at this candle's time
                        if row_5m['low'] <= row_5m['bullish_fvg_top']:
                            entry_price = row_5m['close'] # Simple entry trigger
                            # SL below the most recent 5m swing low formed *before* or *at* this FVG candle
                            relevant_lows = df_5m.loc[:idx_5m, 'swing_low'].dropna()
                            if not relevant_lows.empty:
                                sl_price = relevant_lows.iloc[-1] * (1 - sl_buffer_percent)
                            else: # Fallback SL
                                sl_price = row_5m['low'] * (1 - sl_buffer_percent * 2) 
                            entry_type = 'FVG_MITIGATION'
                            self.logger.info(f"ENTRY_5M (FVG): {poi_15m_type} for {symbol} at {idx_5m}, Price: {entry_price:.4f}, SL: {sl_price:.4f}. 15m POI: {poi_15m_low}-{poi_15m_high}")
                    
                    elif poi_15m_type == 'bearish' and pd.notna(row_5m['bearish_fvg_top']):
                         # Check if current candle high reached into the FVG
                        if row_5m['high'] >= row_5m['bearish_fvg_bottom']:
                            entry_price = row_5m['close']
                            # SL above the most recent 5m swing high formed *before* or *at* this FVG candle
                            relevant_highs = df_5m.loc[:idx_5m, 'swing_high'].dropna()
                            if not relevant_highs.empty:
                                sl_price = relevant_highs.iloc[-1] * (1 + sl_buffer_percent)
                            else: # Fallback SL
                                sl_price = row_5m['high'] * (1 + sl_buffer_percent * 2)
                            entry_type = 'FVG_MITIGATION'
                            self.logger.info(f"ENTRY_5M (FVG): {poi_15m_type} for {symbol} at {idx_5m}, Price: {entry_price:.4f}, SL: {sl_price:.4f}. 15m POI: {poi_15m_low}-{poi_15m_high}")

                # Option B: 5m Market Structure Shift (MSS/BOS) Entry (Check if FVG entry didn't trigger)
                if use_mss_bos_entry and pd.isna(entry_price):
                    if poi_15m_type == 'bullish' and pd.notna(last_5m_swing_high_price) and last_5m_swing_high_ts >= last_5m_swing_low_ts:
                        # Condition: Close breaks the last 5m swing HIGH that formed after the last 5m swing LOW (during POI interaction)
                        if row_5m['close'] > last_5m_swing_high_price:
                            entry_price = row_5m['close'] # Simple entry on break
                            # SL below the swing low that formed *before* this MSS break
                            if pd.notna(last_5m_swing_low_price):
                                sl_price = last_5m_swing_low_price * (1 - sl_buffer_percent)
                            else: # Fallback if no swing low recorded during interaction yet
                                sl_price = row_5m['low'] * (1 - sl_buffer_percent * 2)
                            entry_type = 'MSS_BOS'
                            self.logger.info(f"ENTRY_5M (MSS): {poi_15m_type} for {symbol} at {idx_5m}, Price: {entry_price:.4f}, SL: {sl_price:.4f}. Broke 5m SH: {last_5m_swing_high_price}")

                    elif poi_15m_type == 'bearish' and pd.notna(last_5m_swing_low_price) and last_5m_swing_low_ts >= last_5m_swing_high_ts:
                        # Condition: Close breaks the last 5m swing LOW that formed after the last 5m swing HIGH
                        if row_5m['close'] < last_5m_swing_low_price:
                            entry_price = row_5m['close']
                            # SL above the swing high that formed *before* this MSS break
                            if pd.notna(last_5m_swing_high_price):
                                sl_price = last_5m_swing_high_price * (1 + sl_buffer_percent)
                            else: # Fallback
                                sl_price = row_5m['high'] * (1 + sl_buffer_percent * 2)
                            entry_type = 'MSS_BOS'
                            self.logger.info(f"ENTRY_5M (MSS): {poi_15m_type} for {symbol} at {idx_5m}, Price: {entry_price:.4f}, SL: {sl_price:.4f}. Broke 5m SL: {last_5m_swing_low_price}")

                # If an entry was triggered by either logic:
                if pd.notna(entry_price) and pd.notna(sl_price):
                    # Check if an entry wasn't already recorded for this 15m POI
                    if pd.isna(df_15m_with_entries.at[poi_15m_time, 'entry_5m_time']):
                         df_15m_with_entries.at[poi_15m_time, 'entry_5m_time'] = idx_5m
                         df_15m_with_entries.at[poi_15m_time, 'entry_5m_price'] = entry_price
                         df_15m_with_entries.at[poi_15m_time, 'entry_5m_type'] = entry_type
                         df_15m_with_entries.at[poi_15m_time, 'entry_5m_sl_price'] = sl_price
                         entry_found_for_poi = True # Mark entry found for this POI
                         # Don't break here immediately, allow loop to finish current candle analysis (in case multiple conditions met, though unlikely with current logic)
                    # else: Log that an entry was already found? Maybe not necessary.

            
            if not entry_found_for_poi:
                 self.logger.info(f"No 5m entry signal found for 15m POI at {poi_15m_time} for {symbol} within the scanned 5m window.")

        return df_15m_with_entries

    async def run_analysis(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Runs the full analysis pipeline for a single symbol.
        1. Fetch 15m data.
        2. Run 15m analysis (Swings, BOS, Impulse, Fibs, FVGs, POIs).
        3. If POIs found, run 5m analysis for entry signals.
        4. Format and return found entry signals as a list of dictionaries.
        """
        self.logger.debug(f"Running full analysis for {symbol}...")
        signals_found = []

        try:
            # --- 1. Fetch 15m Data --- 
            timeframe_15m = self.strategy_params.get("strategy_params.timeframes.contextual", "15m")
            # Fetch enough data for lookbacks and context
            ohlcv_df_15m = await self.data_ingestion_module.fetch_ohlcv(symbol=symbol, timeframe=timeframe_15m, limit=500) 

            if ohlcv_df_15m is None or ohlcv_df_15m.empty:
                self.logger.warning(f"Could not fetch 15m OHLCV data for {symbol}. Skipping analysis.")
                return []
            
            # --- 2. Run 15m Analysis --- 
            df_15m_swings = self.detect_swing_points(ohlcv_df_15m.copy(), timeframe_key=None)
            df_15m_bos = self.detect_bos(df_15m_swings, timeframe_key=None)
            df_15m_impulse = self.identify_impulse_leg(df_15m_bos)
            df_15m_fvg = self.detect_fvg(df_15m_impulse.copy(), timeframe_key=None) 
            df_15m_poi = self.find_poi_confluence(df_15m_fvg)

            # --- 3. Find 5m Entry Signals based on 15m POIs --- 
            df_with_5m_entries = await self.find_5m_entry_signals(df_15m_poi.copy(), symbol)

            # --- 4. Format Output --- 
            entry_signals_df = df_with_5m_entries[df_with_5m_entries['entry_5m_time'].notna()].copy()
            
            if not entry_signals_df.empty:
                self.logger.info(f"Formatting {len(entry_signals_df)} entry signals found for {symbol}.")
                # Select and rename columns for the final signal dictionary
                entry_signals_df.rename(columns={
                    'entry_5m_time': 'timestamp', # Use 5m entry time as signal time
                    'poi_type': 'direction', 
                    'entry_5m_price': 'entry_price',
                    'entry_5m_sl_price': 'stop_loss_price',
                    'poi_confidence_score': 'confidence_score',
                    'bullish_bos_level': 'bos_level_15m_bullish', # Keep separate potentially?
                    'bearish_bos_level': 'bos_level_15m_bearish',
                    'poi_low_price': 'fvg_low_15m', # POI range represents FVG generally
                    'poi_high_price': 'fvg_high_15m',
                    'fib_levels': 'fib_levels_15m_data', # Keep the dict
                    'entry_5m_type': 'entry_trigger_5m'
                }, inplace=True)

                # Add symbol column
                entry_signals_df['symbol'] = symbol
                
                # Convert fib_levels dict to string representation for easier logging/alerting
                # Also maybe extract which specific fib levels were touched
                entry_signals_df['fib_levels_15m_touched'] = entry_signals_df.apply(self._format_fib_levels, axis=1)
                
                # Select columns needed for alerting/journaling
                output_columns = [
                    'timestamp', 'symbol', 'direction', 'confidence_score',
                    'entry_price', 'stop_loss_price', 
                    'bos_level_15m_bullish', 'bos_level_15m_bearish',
                    'fvg_low_15m', 'fvg_high_15m', 'fib_levels_15m_touched',
                    'entry_trigger_5m'
                    # Position size, risk, TPs will be added in main loop
                ]
                # Filter for columns that actually exist in the dataframe
                existing_output_columns = [col for col in output_columns if col in entry_signals_df.columns]
                signals_df_final = entry_signals_df[existing_output_columns]
                
                # Convert DataFrame rows to list of dictionaries
                signals_found = signals_df_final.to_dict(orient='records')
                
                # Convert Timestamps to ISO strings
                for signal in signals_found:
                    if pd.notna(signal.get('timestamp')):
                        signal['timestamp'] = signal['timestamp'].isoformat()
                    # Combine bullish/bearish BOS levels into one field for simplicity?
                    signal['bos_level_15m'] = signal.pop('bos_level_15m_bullish', None) or signal.pop('bos_level_15m_bearish', None)
                    if signal['bos_level_15m'] is None: signal['bos_level_15m'] = 'N/A'

            else:
                 self.logger.debug(f"No 5m entry signals met criteria for {symbol}.")

        except Exception as e:
            self.logger.error(f"Error during analysis pipeline for {symbol}: {e}", exc_info=True)
            return [] # Return empty list on error

        self.logger.debug(f"Finished analysis for {symbol}, found {len(signals_found)} signals.")
        return signals_found

    def _format_fib_levels(self, row) -> str:
        """Helper function to format Fibonacci levels data for output."""
        fib_dict = row.get('fib_levels_15m_data')
        fvg_low = row.get('fvg_low_15m')
        fvg_high = row.get('fvg_high_15m')
        touched = []
        if isinstance(fib_dict, dict) and pd.notna(fvg_low) and pd.notna(fvg_high):
            for level_key, level_price in fib_dict.items():
                # Check if the fib level is within the FVG/POI range
                if fvg_low <= level_price <= fvg_high:
                    touched.append(level_key)
        return str(touched) if touched else "N/A"

# Example usage remains the same, but now calls run_analysis
if __name__ == '__main__':
    import asyncio
    from .config_manager import config_manager
    from .logging_service import logger_instance
    from .data_ingestion import DataIngestionModule 

    async def test_analysis_engine():
        logger_instance.info("Starting AnalysisEngine test...")
        
        data_module = DataIngestionModule(config_manager, logger_instance)
        initialized = await data_module.initialize()
        if not initialized or not data_module.exchange:
            logger_instance.error("Failed to initialize DataIngestionModule. Aborting test.")
            return

        analysis_engine = AnalysisEngine(config_manager, logger_instance, data_module) 
        
        symbols_to_test = config_manager.get("portfolio.coins_to_scan", ["BTCUSDT", "ETHUSDT"])
        
        all_test_signals = []
        for symbol in symbols_to_test:
            logger_instance.info(f"--- Running analysis for {symbol} ---")
            signals = await analysis_engine.run_analysis(symbol)
            logger_instance.info(f"Analysis for {symbol} completed. Found {len(signals)} signals.")
            if signals:
                logger_instance.info(f"Signal(s) for {symbol}: {signals}")
                all_test_signals.extend(signals)
            await asyncio.sleep(1) # Avoid rate limits

        logger_instance.info(f"--- Total Signals Found Across Symbols: {len(all_test_signals)} ---")

        await data_module.close()
        logger_instance.info("AnalysisEngine test finished.")

    # Ensure logs directory exists
    log_config = config_manager.get_logging_config()
    log_file_path = Path(log_config.get("log_file", "logs/bot.log"))
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(test_analysis_engine()) 