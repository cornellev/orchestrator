FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV WS_HOST=0.0.0.0 \
    WS_PORT=8080 \
    API_HOST=0.0.0.0 \
    API_PORT=8090 \
    PYTHONUNBUFFERED=1
# Set API_WRITE_TOKEN when exposing the Types API beyond loopback.
# Example: docker run -e API_WRITE_TOKEN=secret ...

EXPOSE 8080 8090

CMD ["python", "-u", "main.py"]
