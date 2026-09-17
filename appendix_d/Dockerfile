FROM python:3.12-slim
ARG KIBAN_INSTALL_TIMESFM_TORCH=0
WORKDIR /app
COPY pyproject.toml README.md requirements*.txt ./
COPY forecast_provider ./forecast_provider
RUN pip install --no-cache-dir \
        -r requirements-statsforecast.txt \
        -r requirements-mlforecast.txt \
        -r requirements-timesfm.txt \
        -r requirements-auth.txt \
        ".[api,postgres,statsforecast,mlforecast,timesfm,auth]" \
    && if [ "$KIBAN_INSTALL_TIMESFM_TORCH" = "1" ]; then \
         pip install --no-cache-dir -r requirements-timesfm-torch.txt; \
       fi
RUN mkdir -p /var/lib/kiban/artifacts /var/lib/kiban/work \
    && chown -R 65532:65532 /var/lib/kiban
USER 65532:65532
CMD ["uvicorn", "forecast_provider.api.factory:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000"]
