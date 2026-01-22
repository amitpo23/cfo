"""
Machine Learning Models for Financial Predictions
מודלים של למידת מכונה לתחזיות פיננסיות
"""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class MLPrediction:
    """תוצאת תחזית ML"""
    date: datetime
    predicted_value: float
    lower_bound: float
    upper_bound: float
    model_name: str
    confidence: float


@dataclass
class ModelMetrics:
    """מטריקות מודל"""
    model_name: str
    mae: float
    mape: float
    rmse: float
    r2: float
    training_samples: int


class LSTMPredictor:
    """
    מנבא LSTM לתזרים מזומנים
    Long Short-Term Memory neural network predictor
    
    Note: Requires TensorFlow. Will fall back to simpler methods if not available.
    """
    
    def __init__(self, lookback_periods: int = 12, units: int = 50):
        self.lookback = lookback_periods
        self.units = units
        self.model = None
        self.scaler = None
        self._tensorflow_available = False
        
        try:
            import tensorflow as tf
            from sklearn.preprocessing import MinMaxScaler
            self._tensorflow_available = True
            self.scaler = MinMaxScaler(feature_range=(0, 1))
        except ImportError:
            logger.warning("TensorFlow not available. LSTM predictions will use fallback method.")
    
    def prepare_data(self, data: List[float]) -> Tuple[np.ndarray, np.ndarray]:
        """
        הכנת נתונים למודל LSTM
        Prepare sequences for LSTM training
        """
        if not self._tensorflow_available:
            return np.array([]), np.array([])
        
        # נרמול
        data_array = np.array(data).reshape(-1, 1)
        scaled_data = self.scaler.fit_transform(data_array)
        
        X, y = [], []
        for i in range(len(scaled_data) - self.lookback):
            X.append(scaled_data[i:i + self.lookback, 0])
            y.append(scaled_data[i + self.lookback, 0])
        
        return np.array(X), np.array(y)
    
    def build_model(self, input_shape: Tuple[int, int]):
        """
        בניית מודל LSTM
        Build LSTM neural network
        """
        if not self._tensorflow_available:
            return None
        
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import LSTM, Dense, Dropout
        
        model = Sequential([
            LSTM(self.units, return_sequences=True, input_shape=input_shape),
            Dropout(0.2),
            LSTM(self.units, return_sequences=False),
            Dropout(0.2),
            Dense(25, activation='relu'),
            Dense(1)
        ])
        
        model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        return model
    
    def train(
        self,
        historical_data: List[float],
        epochs: int = 100,
        batch_size: int = 32,
        validation_split: float = 0.2
    ) -> Dict[str, Any]:
        """
        אימון המודל
        Train the LSTM model
        """
        if not self._tensorflow_available:
            return {'status': 'failed', 'reason': 'TensorFlow not available'}
        
        if len(historical_data) < self.lookback + 10:
            return {'status': 'failed', 'reason': 'Insufficient data for training'}
        
        X, y = self.prepare_data(historical_data)
        X = X.reshape((X.shape[0], X.shape[1], 1))
        
        self.model = self.build_model((X.shape[1], 1))
        
        history = self.model.fit(
            X, y,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            verbose=0
        )
        
        return {
            'status': 'success',
            'epochs': epochs,
            'final_loss': float(history.history['loss'][-1]),
            'final_val_loss': float(history.history.get('val_loss', [0])[-1])
        }
    
    def predict(
        self,
        last_periods: List[float],
        forecast_horizon: int = 12
    ) -> List[MLPrediction]:
        """
        תחזית עתידית
        Generate future predictions
        """
        if not self._tensorflow_available or self.model is None:
            # Fallback to simple prediction
            return self._fallback_predict(last_periods, forecast_horizon)
        
        # נרמול הנתונים האחרונים
        current = np.array(last_periods[-self.lookback:]).reshape(-1, 1)
        current_scaled = self.scaler.transform(current)
        
        predictions = []
        current_sequence = current_scaled.flatten().tolist()
        
        base_date = datetime.now()
        
        for i in range(forecast_horizon):
            # הכנת הקלט
            x = np.array(current_sequence[-self.lookback:]).reshape(1, self.lookback, 1)
            
            # תחזית
            pred_scaled = self.model.predict(x, verbose=0)[0][0]
            pred_value = self.scaler.inverse_transform([[pred_scaled]])[0][0]
            
            # הוספה לרצף
            current_sequence.append(pred_scaled)
            
            # חישוב טווח ביטחון
            std_dev = np.std(last_periods) * 0.1 * (i + 1)  # אי-ודאות גוברת
            
            predictions.append(MLPrediction(
                date=base_date + timedelta(days=30 * (i + 1)),
                predicted_value=float(max(0, pred_value)),
                lower_bound=float(max(0, pred_value - 1.96 * std_dev)),
                upper_bound=float(pred_value + 1.96 * std_dev),
                model_name='LSTM',
                confidence=max(0.5, 0.95 - i * 0.03)  # ירידה בביטחון לאורך זמן
            ))
        
        return predictions
    
    def _fallback_predict(
        self,
        data: List[float],
        periods: int
    ) -> List[MLPrediction]:
        """תחזית חלופית כשאין TensorFlow"""
        avg = np.mean(data) if data else 0
        std = np.std(data) if data else avg * 0.1
        
        predictions = []
        base_date = datetime.now()
        
        for i in range(periods):
            predictions.append(MLPrediction(
                date=base_date + timedelta(days=30 * (i + 1)),
                predicted_value=float(avg),
                lower_bound=float(max(0, avg - 1.96 * std)),
                upper_bound=float(avg + 1.96 * std),
                model_name='Fallback (Mean)',
                confidence=0.5
            ))
        
        return predictions


class ProphetPredictor:
    """
    מנבא Prophet לתזרים מזומנים
    Facebook Prophet forecaster for business time series
    
    Note: Requires prophet library. Will fall back to simpler methods if not available.
    """
    
    def __init__(self):
        self.model = None
        self._prophet_available = False
        
        try:
            from prophet import Prophet
            self._prophet_available = True
        except ImportError:
            logger.warning("Prophet not available. Will use fallback method.")
    
    def forecast(
        self,
        dates: List[datetime],
        values: List[float],
        periods: int = 12,
        include_seasonality: bool = True
    ) -> List[MLPrediction]:
        """
        תחזית עם Prophet
        Generate forecasts using Prophet
        """
        if not self._prophet_available:
            return self._fallback_forecast(values, periods)
        
        try:
            import pandas as pd
            from prophet import Prophet
            
            # הכנת DataFrame
            df = pd.DataFrame({
                'ds': dates,
                'y': values
            })
            
            # יצירת מודל
            self.model = Prophet(
                yearly_seasonality=include_seasonality,
                weekly_seasonality=False,
                daily_seasonality=False,
                changepoint_prior_scale=0.05,
                interval_width=0.95
            )
            
            self.model.fit(df)
            
            # יצירת תאריכים עתידיים
            future = self.model.make_future_dataframe(periods=periods, freq='M')
            forecast = self.model.predict(future)
            
            # שליפת התחזיות העתידיות
            predictions = []
            future_forecast = forecast.tail(periods)
            
            for _, row in future_forecast.iterrows():
                predictions.append(MLPrediction(
                    date=row['ds'].to_pydatetime(),
                    predicted_value=float(max(0, row['yhat'])),
                    lower_bound=float(max(0, row['yhat_lower'])),
                    upper_bound=float(row['yhat_upper']),
                    model_name='Prophet',
                    confidence=0.95
                ))
            
            return predictions
            
        except Exception as e:
            logger.error(f"Prophet forecast failed: {e}")
            return self._fallback_forecast(values, periods)
    
    def _fallback_forecast(
        self,
        values: List[float],
        periods: int
    ) -> List[MLPrediction]:
        """תחזית חלופית"""
        avg = np.mean(values) if values else 0
        std = np.std(values) if values else avg * 0.1
        
        predictions = []
        base_date = datetime.now()
        
        for i in range(periods):
            predictions.append(MLPrediction(
                date=base_date + timedelta(days=30 * (i + 1)),
                predicted_value=float(avg),
                lower_bound=float(max(0, avg - 1.96 * std)),
                upper_bound=float(avg + 1.96 * std),
                model_name='Fallback (Prophet unavailable)',
                confidence=0.5
            ))
        
        return predictions


class XGBoostPredictor:
    """
    מנבא XGBoost לתזרים מזומנים
    XGBoost predictor with feature engineering
    
    Note: Requires xgboost and sklearn. Will fall back if not available.
    """
    
    def __init__(self):
        self.model = None
        self._xgboost_available = False
        
        try:
            import xgboost as xgb
            from sklearn.model_selection import train_test_split
            self._xgboost_available = True
        except ImportError:
            logger.warning("XGBoost not available. Will use fallback method.")
    
    def prepare_features(
        self,
        dates: List[datetime],
        values: List[float]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        הכנת features
        Feature engineering for time series
        """
        features = []
        targets = []
        
        for i in range(len(values)):
            date = dates[i]
            
            feature = [
                date.month,  # חודש
                date.quarter if hasattr(date, 'quarter') else (date.month - 1) // 3 + 1,  # רבעון
                date.weekday(),  # יום בשבוע
                date.day,  # יום בחודש
                1 if date.month in [1, 7, 8, 12] else 0,  # עונת חגים/חופש
            ]
            
            # Features מבוססי היסטוריה
            if i >= 1:
                feature.append(values[i - 1])  # ערך קודם
            else:
                feature.append(values[i])
            
            if i >= 3:
                feature.append(np.mean(values[i - 3:i]))  # ממוצע 3 תקופות
            else:
                feature.append(np.mean(values[:i + 1]))
            
            if i >= 6:
                feature.append(np.mean(values[i - 6:i]))  # ממוצע 6 תקופות
            else:
                feature.append(np.mean(values[:i + 1]))
            
            if i >= 12:
                feature.append(values[i - 12])  # ערך לפני שנה
            else:
                feature.append(values[0])
            
            features.append(feature)
            targets.append(values[i])
        
        return np.array(features), np.array(targets)
    
    def train(
        self,
        dates: List[datetime],
        values: List[float],
        test_size: float = 0.2
    ) -> ModelMetrics:
        """
        אימון המודל
        Train XGBoost model
        """
        if not self._xgboost_available:
            return ModelMetrics(
                model_name='XGBoost',
                mae=0, mape=0, rmse=0, r2=0,
                training_samples=0
            )
        
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        
        X, y = self.prepare_features(dates, values)
        
        if len(X) < 10:
            return ModelMetrics(
                model_name='XGBoost',
                mae=0, mape=0, rmse=0, r2=0,
                training_samples=len(X)
            )
        
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, shuffle=False
        )
        
        self.model = xgb.XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            random_state=42
        )
        
        self.model.fit(X_train, y_train)
        
        # הערכה
        y_pred = self.model.predict(X_test)
        
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100 if np.all(y_test != 0) else 0
        
        return ModelMetrics(
            model_name='XGBoost',
            mae=float(mae),
            mape=float(mape),
            rmse=float(rmse),
            r2=float(r2),
            training_samples=len(X_train)
        )
    
    def predict(
        self,
        dates: List[datetime],
        values: List[float],
        periods: int = 12
    ) -> List[MLPrediction]:
        """
        תחזית
        Generate predictions
        """
        if not self._xgboost_available or self.model is None:
            return self._fallback_predict(values, periods)
        
        predictions = []
        current_values = values.copy()
        current_dates = dates.copy()
        
        for i in range(periods):
            # יצירת תאריך עתידי
            last_date = current_dates[-1]
            if last_date.month == 12:
                next_date = last_date.replace(year=last_date.year + 1, month=1)
            else:
                next_date = last_date.replace(month=last_date.month + 1)
            
            # הכנת features
            X, _ = self.prepare_features(
                current_dates + [next_date],
                current_values + [current_values[-1]]  # placeholder
            )
            
            # תחזית
            pred_value = float(self.model.predict(X[-1:].reshape(1, -1))[0])
            
            # חישוב טווח ביטחון
            std = np.std(values) * 0.1 * (i + 1)
            
            predictions.append(MLPrediction(
                date=next_date,
                predicted_value=max(0, pred_value),
                lower_bound=max(0, pred_value - 1.96 * std),
                upper_bound=pred_value + 1.96 * std,
                model_name='XGBoost',
                confidence=max(0.5, 0.9 - i * 0.02)
            ))
            
            # עדכון לאיטרציה הבאה
            current_dates.append(next_date)
            current_values.append(pred_value)
        
        return predictions
    
    def _fallback_predict(
        self,
        values: List[float],
        periods: int
    ) -> List[MLPrediction]:
        """תחזית חלופית"""
        avg = np.mean(values) if values else 0
        std = np.std(values) if values else avg * 0.1
        
        predictions = []
        base_date = datetime.now()
        
        for i in range(periods):
            predictions.append(MLPrediction(
                date=base_date + timedelta(days=30 * (i + 1)),
                predicted_value=float(avg),
                lower_bound=float(max(0, avg - 1.96 * std)),
                upper_bound=float(avg + 1.96 * std),
                model_name='Fallback (XGBoost unavailable)',
                confidence=0.5
            ))
        
        return predictions


class EnsembleForecaster:
    """
    תחזית משולבת ממספר מודלים
    Ensemble forecaster combining multiple models
    """
    
    def __init__(self):
        self.lstm = LSTMPredictor()
        self.prophet = ProphetPredictor()
        self.xgboost = XGBoostPredictor()
        
        # משקולות ברירת מחדל
        self.weights = {
            'lstm': 0.35,
            'prophet': 0.35,
            'xgboost': 0.30
        }
    
    def train_all(
        self,
        dates: List[datetime],
        values: List[float]
    ) -> Dict[str, Any]:
        """
        אימון כל המודלים
        Train all ensemble models
        """
        results = {}
        
        # LSTM
        lstm_result = self.lstm.train(values)
        results['lstm'] = lstm_result
        
        # XGBoost
        xgb_metrics = self.xgboost.train(dates, values)
        results['xgboost'] = {
            'mae': xgb_metrics.mae,
            'rmse': xgb_metrics.rmse,
            'r2': xgb_metrics.r2
        }
        
        # Prophet לא צריך אימון מפורש
        results['prophet'] = {'status': 'ready'}
        
        return results
    
    def forecast(
        self,
        dates: List[datetime],
        values: List[float],
        periods: int = 12
    ) -> Dict[str, Any]:
        """
        תחזית משולבת
        Generate ensemble forecast
        """
        # תחזיות מכל מודל
        lstm_preds = self.lstm.predict(values, periods)
        prophet_preds = self.prophet.forecast(dates, values, periods)
        xgb_preds = self.xgboost.predict(dates, values, periods)
        
        # שילוב התחזיות
        ensemble_predictions = []
        
        for i in range(periods):
            lstm_val = lstm_preds[i].predicted_value
            prophet_val = prophet_preds[i].predicted_value
            xgb_val = xgb_preds[i].predicted_value
            
            # ממוצע משוקלל
            weighted_pred = (
                self.weights['lstm'] * lstm_val +
                self.weights['prophet'] * prophet_val +
                self.weights['xgboost'] * xgb_val
            )
            
            # טווח ביטחון מורחב
            all_lowers = [lstm_preds[i].lower_bound, prophet_preds[i].lower_bound, xgb_preds[i].lower_bound]
            all_uppers = [lstm_preds[i].upper_bound, prophet_preds[i].upper_bound, xgb_preds[i].upper_bound]
            
            ensemble_predictions.append(MLPrediction(
                date=lstm_preds[i].date,
                predicted_value=weighted_pred,
                lower_bound=min(all_lowers),
                upper_bound=max(all_uppers),
                model_name='Ensemble',
                confidence=np.mean([lstm_preds[i].confidence, prophet_preds[i].confidence, xgb_preds[i].confidence])
            ))
        
        return {
            'ensemble': [self._prediction_to_dict(p) for p in ensemble_predictions],
            'lstm': [self._prediction_to_dict(p) for p in lstm_preds],
            'prophet': [self._prediction_to_dict(p) for p in prophet_preds],
            'xgboost': [self._prediction_to_dict(p) for p in xgb_preds],
            'weights': self.weights
        }
    
    def update_weights(self, actual_values: List[float], predictions: Dict[str, List[float]]) -> None:
        """
        עדכון משקולות בהתבסס על דיוק
        Update weights based on prediction accuracy
        """
        errors = {}
        
        for model_name, preds in predictions.items():
            if len(preds) == len(actual_values):
                mae = np.mean(np.abs(np.array(actual_values) - np.array(preds)))
                errors[model_name] = mae
        
        if errors:
            # משקולות הפוכות לשגיאה
            total_inv_error = sum(1 / e if e > 0 else 1 for e in errors.values())
            
            for model_name, error in errors.items():
                self.weights[model_name] = (1 / error if error > 0 else 1) / total_inv_error
    
    def _prediction_to_dict(self, pred: MLPrediction) -> Dict[str, Any]:
        """המרה למילון"""
        return {
            'date': pred.date.strftime('%Y-%m-%d'),
            'predicted_value': pred.predicted_value,
            'lower_bound': pred.lower_bound,
            'upper_bound': pred.upper_bound,
            'model_name': pred.model_name,
            'confidence': pred.confidence
        }


def evaluate_forecast_accuracy(
    actual: List[float],
    predicted: List[float]
) -> Dict[str, float]:
    """
    הערכת דיוק תחזית
    Calculate forecast accuracy metrics
    """
    actual_arr = np.array(actual)
    predicted_arr = np.array(predicted)
    
    mae = np.mean(np.abs(actual_arr - predicted_arr))
    rmse = np.sqrt(np.mean((actual_arr - predicted_arr) ** 2))
    
    # MAPE - רק כשאין אפסים
    if np.all(actual_arr != 0):
        mape = np.mean(np.abs((actual_arr - predicted_arr) / actual_arr)) * 100
    else:
        mape = 0
    
    # R-squared
    ss_res = np.sum((actual_arr - predicted_arr) ** 2)
    ss_tot = np.sum((actual_arr - np.mean(actual_arr)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    # Bias - סטייה שיטתית
    bias = np.mean(predicted_arr - actual_arr)
    
    return {
        'mae': float(mae),
        'mape': float(mape),
        'rmse': float(rmse),
        'r2': float(r2),
        'bias': float(bias),
        'samples': len(actual)
    }
