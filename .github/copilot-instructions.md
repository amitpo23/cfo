# CFO Financial Management System - AI Agent Guide

## System Overview

This is a bilingual (Hebrew/English) financial management system integrating with SUMIT API for Israeli accounting. The codebase consists of:
- **Backend**: FastAPI REST API with SQLAlchemy ORM
- **Frontend**: React + TypeScript SPA with Vite
- **Integration Layer**: Complete async SUMIT API client (80+ methods)
- **Services**: AI insights (OpenAI), financial analytics, reporting

## Architecture & Data Flow

### Core Patterns
The system follows a layered architecture with clear separation:
1. **Integration Layer** (`src/cfo/integrations/`) - External API clients inherit from `BaseIntegration` base class
2. **API Layer** (`src/cfo/api/routes/`) - FastAPI routers organized by domain (accounting, crm, payments, communications, admin)
3. **Service Layer** (`src/cfo/services/`) - Business logic for AI insights, financial analysis, and reporting
4. **Data Layer** (`src/cfo/models.py`, `database.py`) - SQLAlchemy models with dual support (Pydantic for API, SQLAlchemy for DB)

### SUMIT Integration Pattern
All SUMIT API interactions use the async context manager pattern:
```python
async with SumitIntegration(api_key=settings.sumit_api_key) as sumit:
    result = await sumit.method_name(params)
```

The `SumitIntegration` class (1700+ lines) implements every SUMIT endpoint with:
- Type-safe request/response models from `sumit_models.py`
- Automatic error handling and logging
- Resource cleanup via context manager

## Configuration & Environment

### Required Setup
1. **Environment variables**: Copy `.env.example` to `.env` and configure:
   - `SUMIT_API_KEY` + `SUMIT_COMPANY_ID` (primary integration)
   - `OPENAI_API_KEY` (for AI insights service)
   - `DATABASE_URL` (defaults to `sqlite:///./cfo.db`)
2. **Database initialization**: Run `cfo init` before first use
3. **Python environment**: Requires Python 3.10+, install with `pip install -e .`

### Key Settings Pattern
All configuration is centralized in `src/cfo/config.py` using Pydantic Settings:
```python
from cfo.config import settings
# settings.sumit_api_key, settings.database_url, etc.
```

## Development Workflows

### Running the Application
- **Backend API**: `cfo run` (starts uvicorn on port 8000, hot reload in debug mode)
- **Frontend Dev**: `cd frontend && npm run dev` (Vite dev server on port 5173)
- **CLI Commands**: `cfo --help` to see all available commands
- **Test SUMIT Connection**: `cfo test-sumit` before making API calls

### API Documentation
FastAPI auto-generates docs at `/api/docs` (Swagger UI) and `/api/redoc` when server is running

### Database Migrations
The system uses SQLAlchemy declarative models in `models.py`. For schema changes:
- Models are defined in `Base` declarative class
- Use `init_db()` to create tables (development)
- For production, set up Alembic migrations (configured but not actively used)

## Code Conventions

### Bilingual Documentation
- **Python docstrings**: Hebrew for business logic, English for technical patterns
- **Comments**: Hebrew comments for domain concepts, English for code structure
- **API responses**: Hebrew-friendly field names but English JSON keys

### Model Patterns
Dual model strategy is critical:
- **Pydantic models** (e.g., `CustomerRequest`, `CustomerResponse`) for API validation and serialization
- **SQLAlchemy models** (e.g., `Account`, `Transaction`) for database persistence
- Use `model_config = {"from_attributes": True}` for Pydantic to read from ORM models

### Dependency Injection
FastAPI routes use DI extensively:
```python
async def endpoint(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
```
Dependencies defined in `api/dependencies.py`

### Error Handling
- SUMIT integration logs all API errors via `_log_error()`
- FastAPI routes raise `HTTPException` with appropriate status codes
- Use Rich console for CLI error formatting

## Critical Integration Points

### SUMIT API Client
When adding new SUMIT endpoints to `sumit_integration.py`:
1. Define Pydantic request/response models in `sumit_models.py` first
2. Add async method to `SumitIntegration` class with proper type hints
3. Use `self._make_request()` helper for consistent error handling
4. Update corresponding FastAPI route in `api/routes/` directory

### Frontend-Backend Communication
- Frontend API client in `frontend/src/services/api.ts`
- Uses Axios with base URL configured in Vite
- React Query for state management and caching
- API expects JWT bearer token (auth system partially implemented)

### Service Layer Usage
Services depend on other components:
- `AIInsightsService` requires `FinancialService` and OpenAI API key
- `ReportService` uses SQLAlchemy session from `database.py`
- CLI commands call services directly, not via API routes

## Project-Specific Decisions

### Why Async Throughout?
SUMIT API is async-first, so the entire integration layer uses `async/await`. This cascades to FastAPI routes but NOT to CLI commands (which use `asyncio.run()`).

### Why Dual Frontend/Backend?
System supports both programmatic API access (for integrations) and interactive web UI (for end users). CLI provides admin/testing interface.

### Security Note
JWT auth in `dependencies.py` uses hardcoded secret key - **this is a placeholder**. For production, set proper `SECRET_KEY` in settings and implement user management.

## Testing Patterns

While test files aren't in the workspace structure, the pattern is:
- Use `pytest` with `pytest-asyncio` for async tests
- Mock SUMIT API responses using `httpx` responders
- Test CLI commands by calling functions directly, not via shell

## Common Tasks

### Adding a New SUMIT Feature
1. Check SUMIT API docs, define models in `sumit_models.py`
2. Implement method in `SumitIntegration` class
3. Add FastAPI route in appropriate router file
4. Update frontend service and create/update React component
5. Test with `cfo test-sumit` and via API docs

### Adding AI Insights
Extend `AIInsightsService` in `services/ai_insights.py`. Pattern:
- Fetch financial data via `FinancialService`
- Format as Hebrew text for GPT-4
- Return Hebrew analysis/recommendations

### Generating Reports
Use `ReportService` in `services/report_service.py` for Excel exports with `openpyxl`. Follow existing patterns for styled reports with Hebrew RTL support.

## Financial Forecasting & Cash Flow Management

### Cash Flow Analysis
The system should support comprehensive cash flow management patterns found in leading financial systems:

**Cash Flow Statement Components**:
- **Operations**: Net income/loss, depreciation, working capital changes (AR, AP, inventory)
- **Investing**: Fixed asset changes, investment activities
- **Financing**: Equity changes, debt activities, dividend payments

**Implementation Pattern** (inspired by ERPNext):
```python
def get_cash_flow_data(company, period_list, filters):
    # Net profit/loss from P&L
    net_income = get_net_income(company, period_list)
    
    # Operating activities
    operating_cash = {
        'depreciation': get_account_type_data('Depreciation'),
        'ar_changes': get_account_type_data('Receivable'),
        'ap_changes': get_account_type_data('Payable'),
        'inventory_changes': get_account_type_data('Stock')
    }
    
    # Investing + Financing activities
    investing_cash = get_account_type_data('Fixed Asset')
    financing_cash = get_account_type_data('Equity')
    
    return calculate_net_cash_flow(net_income, operating_cash, investing_cash, financing_cash)
```

### Financial Forecasting Skills

**Time Series Forecasting Methods**:
1. **Exponential Smoothing** (for revenue/expense forecasting)
   - Single exponential smoothing for trends
   - Holt-Winters for seasonality
   - Configurable smoothing constants (α, β, γ)

2. **ARIMA Models** (for complex patterns)
   - Auto-regressive integrated moving average
   - Suitable for non-stationary financial data

3. **Machine Learning Approaches**:
   - LSTM (Long Short-Term Memory) for multi-step forecasts
   - XGBoost/Random Forest for feature-based predictions
   - Prophet for business-friendly time series

**Forecasting Implementation Pattern**:
```python
class FinancialForecastService:
    def __init__(self, historical_data, method='exponential_smoothing'):
        self.data = historical_data
        self.method = method
    
    def forecast_cash_flow(self, periods=12):
        """תחזית תזרים מזומנים"""
        if self.method == 'exponential_smoothing':
            return self._exponential_smoothing_forecast(periods)
        elif self.method == 'lstm':
            return self._lstm_forecast(periods)
        elif self.method == 'arima':
            return self._arima_forecast(periods)
    
    def _exponential_smoothing_forecast(self, periods):
        # Single exponential smoothing
        alpha = 0.3  # Smoothing constant
        forecast = []
        last_value = self.data[-1]
        
        for _ in range(periods):
            next_value = alpha * last_value + (1 - alpha) * forecast[-1] if forecast else last_value
            forecast.append(next_value)
        
        return forecast
    
    def calculate_forecast_accuracy(self, actual, predicted):
        """חישוב דיוק תחזית (MAPE, RMSE)"""
        mape = mean_absolute_percentage_error(actual, predicted)
        rmse = root_mean_squared_error(actual, predicted)
        return {'mape': mape, 'rmse': rmse}
```

**Budget vs Actual Variance Analysis**:
```python
def analyze_budget_variance(budget_data, actual_data):
    """ניתוח סטיות תקציב"""
    variance = {
        'absolute': actual_data - budget_data,
        'percentage': ((actual_data - budget_data) / budget_data) * 100,
        'favorable': actual_data > budget_data if revenue else actual_data < budget_data
    }
    return variance
```

### Deferred Revenue/Expense Recognition
For subscription businesses and long-term contracts:
- Track deferred revenue/expense accounts
- Automate periodic recognition based on contract terms
- Generate deferred revenue schedules
- Simulate future postings for forecasting

### Key Financial Ratios for Forecasting
When building forecasting features, calculate and track:
- **Liquidity**: Current ratio, quick ratio, cash ratio
- **Profitability**: Gross margin, net margin, ROE, ROA
- **Efficiency**: Asset turnover, inventory turnover, DSO
- **Leverage**: Debt-to-equity, interest coverage
- **Growth**: Revenue growth rate, profit growth rate

### Integration with AI Insights
Extend `AIInsightsService` to include forecasting:
```python
async def predict_cash_flow(self, horizon_months=12):
    """תחזית תזרים מזומנים מבוססת AI"""
    historical_cf = self.financial_service.get_cash_flow_history()
    
    prompt = f"""
    בהתבסס על נתוני תזרים מזומנים היסטוריים:
    {historical_cf}
    
    חזה את תזרים המזומנים ל-{horizon_months} חודשים הבאים.
    כלול:
    1. תחזית חודשית מפורטת
    2. טווח ביטחון (best/worst case)
    3. גורמי סיכון ואזהרות
    4. המלצות לניהול תזרים
    """
    
    return self.client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
```

### Data Sources for Forecasting
- Historical transaction data from `Transaction` model
- SUMIT API data (invoices, payments, recurring charges)
- External economic indicators (optional integration)
- Seasonal patterns from past years

### Visualization Requirements
- Interactive cash flow charts (using Recharts in frontend)
- Forecast confidence intervals
- Historical vs predicted comparison
- Waterfall charts for cash flow components

## Machine Learning for Financial Predictions

### Recommended ML Libraries
Add to `requirements.txt` for advanced forecasting:
```python
# Time Series & Forecasting
statsmodels==0.14.0       # ARIMA, exponential smoothing
prophet==1.1.5            # Facebook's forecasting tool
scikit-learn==1.3.0       # ML algorithms
tensorflow==2.13.0        # Deep learning (LSTM)
xgboost==2.0.0            # Gradient boosting
```

### LSTM Implementation for Cash Flow Forecasting
```python
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
import numpy as np

class LSTMCashFlowPredictor:
    def __init__(self, lookback_periods=12):
        self.lookback = lookback_periods
        self.model = None
    
    def prepare_data(self, cash_flow_series):
        """הכנת נתונים למודל LSTM"""
        X, y = [], []
        for i in range(len(cash_flow_series) - self.lookback):
            X.append(cash_flow_series[i:i+self.lookback])
            y.append(cash_flow_series[i+self.lookback])
        return np.array(X), np.array(y)
    
    def build_model(self, input_shape):
        """בניית מודל LSTM"""
        model = Sequential([
            LSTM(50, return_sequences=True, input_shape=input_shape),
            Dropout(0.2),
            LSTM(50, return_sequences=False),
            Dropout(0.2),
            Dense(25),
            Dense(1)
        ])
        model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        return model
    
    def train(self, historical_data, epochs=100):
        """אימון המודל"""
        X, y = self.prepare_data(historical_data)
        X = X.reshape((X.shape[0], X.shape[1], 1))
        
        self.model = self.build_model((X.shape[1], 1))
        self.model.fit(X, y, epochs=epochs, batch_size=32, validation_split=0.2)
    
    def predict(self, last_periods, forecast_horizon=12):
        """תחזית עתידית"""
        predictions = []
        current = last_periods[-self.lookback:].copy()
        
        for _ in range(forecast_horizon):
            x = current[-self.lookback:].reshape(1, self.lookback, 1)
            pred = self.model.predict(x, verbose=0)[0][0]
            predictions.append(pred)
            current = np.append(current, pred)
        
        return predictions
```

### Prophet Integration for Business Forecasting
```python
from prophet import Prophet
import pandas as pd

class ProphetForecaster:
    """מנבא תזרים מזומנים עם Prophet"""
    
    def forecast_revenue(self, historical_data, periods=12):
        """תחזית הכנסות עם seasonality"""
        df = pd.DataFrame({
            'ds': historical_data['dates'],  # תאריכים
            'y': historical_data['revenue']   # הכנסות
        })
        
        model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=False,
            daily_seasonality=False,
            changepoint_prior_scale=0.05
        )
        model.fit(df)
        
        future = model.make_future_dataframe(periods=periods, freq='M')
        forecast = model.predict(future)
        
        return {
            'predicted': forecast['yhat'].tail(periods).tolist(),
            'lower_bound': forecast['yhat_lower'].tail(periods).tolist(),
            'upper_bound': forecast['yhat_upper'].tail(periods).tolist(),
            'trend': forecast['trend'].tail(periods).tolist()
        }
```

### XGBoost for Feature-Based Predictions
```python
import xgboost as xgb
from sklearn.model_selection import train_test_split

class XGBoostFinancialPredictor:
    """חיזוי פיננסי מבוסס features"""
    
    def prepare_features(self, transactions):
        """הכנת features מעסקאות"""
        features = pd.DataFrame({
            'month': transactions['date'].dt.month,
            'quarter': transactions['date'].dt.quarter,
            'day_of_week': transactions['date'].dt.dayofweek,
            'avg_transaction_size': transactions.groupby('customer_id')['amount'].transform('mean'),
            'transaction_count': transactions.groupby('customer_id').size(),
            'days_since_last': transactions.groupby('customer_id')['date'].diff().dt.days,
            'cumulative_revenue': transactions.groupby('customer_id')['amount'].cumsum()
        })
        return features
    
    def train_model(self, X, y):
        """אימון מודל XGBoost"""
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
        
        model = xgb.XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            random_state=42
        )
        model.fit(X_train, y_train)
        
        # הערכת ביצועים
        train_score = model.score(X_train, y_train)
        test_score = model.score(X_test, y_test)
        
        return model, {'train_r2': train_score, 'test_r2': test_score}
```

### Ensemble Forecasting Approach
```python
class EnsembleForecaster:
    """שילוב מספר מודלים לתחזית מדויקת יותר"""
    
    def __init__(self):
        self.lstm = LSTMCashFlowPredictor()
        self.prophet = ProphetForecaster()
        self.xgb = XGBoostFinancialPredictor()
    
    def forecast(self, historical_data, periods=12):
        """תחזית משולבת"""
        lstm_pred = self.lstm.predict(historical_data, periods)
        prophet_pred = self.prophet.forecast_revenue(historical_data, periods)
        xgb_pred = self.xgb.predict(self.xgb.prepare_features(historical_data))
        
        # Weighted average של התחזיות
        weights = {'lstm': 0.4, 'prophet': 0.4, 'xgb': 0.2}
        
        ensemble = []
        for i in range(periods):
            weighted_pred = (
                weights['lstm'] * lstm_pred[i] +
                weights['prophet'] * prophet_pred['predicted'][i] +
                weights['xgb'] * xgb_pred[i]
            )
            ensemble.append(weighted_pred)
        
        return {
            'ensemble': ensemble,
            'lstm': lstm_pred,
            'prophet': prophet_pred,
            'xgb': xgb_pred.tolist()
        }
```

### Model Evaluation Metrics
```python
def evaluate_forecast(actual, predicted):
    """הערכת דיוק תחזית"""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    
    return {
        'mae': mean_absolute_error(actual, predicted),
        'rmse': np.sqrt(mean_squared_error(actual, predicted)),
        'mape': np.mean(np.abs((actual - predicted) / actual)) * 100,
        'r2': r2_score(actual, predicted),
        'bias': np.mean(predicted - actual)  # סטייה שיטתית
    }
```
