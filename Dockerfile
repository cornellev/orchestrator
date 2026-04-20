FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV WS_HOST=0.0.0.0 \
    WS_PORT=8080 \
    API_HOST=0.0.0.0 \
    API_PORT=8090

EXPOSE 8080 8090

CMD ["python", "main.py"]
