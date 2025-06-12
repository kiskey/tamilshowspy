# High-Performance Python Stremio Addon

This project is a complete, production-grade Stremio addon backend built with Python 3.11+ and a modern asynchronous stack. It includes a web crawler, fuzzy title parser, metadata extractor, Redis persistence, and a Stremio-compatible API.

## Features

- **Asynchronous Crawler**: High-concurrency web crawler using `aiohttp` and `asyncio`.
- **Intelligent Parsing**: Extracts video metadata using `guessit` with a robust regex fallback.
- **Fuzzy Search**: Implements `rapidfuzz` for fast and accurate title searching.
- **Robust Persistence**: Uses `redis.asyncio` for high-performance data storage.
- **Stremio API**: Exposes all necessary endpoints (`catalog`, `meta`, `stream`) using `aiohttp`.
- **Background Tasks**: Scheduled jobs for crawling and updating data using an `asyncio` loop.
- **Fault-Tolerant**: Implements exponential backoff (`tenacity`), rate limiting, and graceful error handling.
- **Production-Ready**: Fully configurable via environment variables and containerized with Docker for easy deployment.
- **Structured Logging**: Uses `loguru` for JSON-formatted, insightful logs.

## Setup & Running

### 1. Using Docker (Recommended)

1.  **Create a `.env` file** from `.env.example`:
    ```bash
    cp .env.example .env
    ```
2.  **Edit the `.env` file** with your configuration, especially `REDIS_URL`.

3.  **Build and run with Docker Compose**:
    ```bash
    # (Optional) Create a docker-compose.yml file
    # version: '3.8'
    # services:
    #   redis:
    #     image: redis:7-alpine
    #     command: redis-server --save 60 1 --loglevel warning
    #     volumes:
    #       - redis_data:/data
    #   addon:
    #     build: .
    #     env_file: .env
    #     ports:
    #       - "8080:8080"
    #     depends_on:
    #       - redis
    # volumes:
    #   redis_data:

    docker-compose up --build -d
    ```

### 2. Manual Setup

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Set environment variables**:
    ```bash
    export REDIS_URL="redis://localhost:6379"
    # ... and other variables
    ```
3.  **Run the application**:
    ```bash
    python main.py
    ```

## API Endpoints

- **Manifest**: `/manifest.json`
- **Health Check**: `/health`
- **Catalog**: `/catalog/series/tamil-web.json`
- **Metadata**: `/meta/series/{show_id}.json`
- **Streams**: `/stream/series/{show_id}:{season}:{episode}.json`
- **Search**: `/search?q={query}`
- **Debug**:
  - `/debug/streams/{show_id}`
  - `/debug/redis/{key}`
