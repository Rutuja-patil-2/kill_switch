FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi==0.165.0 "uvicorn[standard]==0.54.0"
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
