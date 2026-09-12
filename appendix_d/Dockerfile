FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md requirements.txt requirements-statsforecast.txt requirements-mlforecast.txt requirements-auth.txt ./
COPY forecast_provider ./forecast_provider
RUN pip install --no-cache-dir -r requirements-statsforecast.txt -r requirements-mlforecast.txt -r requirements-auth.txt ".[api,postgres,statsforecast,mlforecast,auth]"
USER 65532:65532
CMD ["uvicorn", "forecast_provider.api.factory:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000"]
