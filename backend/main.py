import os
import json
import datetime
import requests
from flask import Flask, request, jsonify
from google.cloud import storage

app = Flask(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "")
RAG_BUCKET = os.environ.get("RAG_BUCKET", "")
RAG_PREFIX = os.environ.get("RAG_PREFIX", "")

LOG_FILE = "logs.json"
_logs = []

BLOCKED_TERMS = ["hack", "weapon", "bomb"]

ALASKA_CITIES = {
    "anchorage": (61.2181, -149.9003),
    "fairbanks": (64.8378, -147.7164),
    "juneau": (58.3019, -134.4197),
}

docs = []
all_chunks = []


def is_prompt_safe(text: str) -> bool:
    t = (text or "").lower()
    return not any(term in t for term in BLOCKED_TERMS)


def validate_response(text: str) -> str:
    if not text:
        return "No response generated."
    return text.strip()


def log_event(prompt: str, response: str, tools: list):
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "prompt": prompt,
        "response": response,
        "tools_used": tools,
    }
    _logs.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(_logs, f, indent=2)


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150):
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + chunk_size])
        i += (chunk_size - overlap)
    return chunks


def retrieve_context(query: str, top_k: int = 5):
    q = query.lower()
    scored = []
    for c in all_chunks:
        score = 0
        cl = c.lower()
        for token in q.split():
            if token in cl:
                score += 1
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def nws_get_forecast_by_latlon(lat: float, lon: float) -> str:
    headers = {"User-Agent": "ads-agent", "Accept": "application/geo+json"}

    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    r = requests.get(points_url, headers=headers, timeout=20)
    if r.status_code != 200:
        return f"Weather API error (points): {r.status_code}"

    forecast_url = r.json()["properties"]["forecast"]
    fr = requests.get(forecast_url, headers=headers, timeout=20)
    if fr.status_code != 200:
        return f"Weather API error (forecast): {fr.status_code}"

    periods = fr.json()["properties"]["periods"]
    p0 = periods[0]
    return f"{p0.get('name','Forecast')}: {p0.get('detailedForecast','')}"


def load_rag_docs():
    global docs, all_chunks

    if not RAG_BUCKET:
        print("RAG_BUCKET is not set. No docs loaded.")
        return

    storage_client = storage.Client()
    bucket = storage_client.bucket(RAG_BUCKET)

    loaded = []
    for blob in bucket.list_blobs(prefix=RAG_PREFIX):
        if blob.name.endswith("/"):
            continue
        try:
            text = blob.download_as_text()
            if text and text.strip():
                loaded.append(text)
        except Exception as e:
            print("Error reading blob:", blob.name, str(e))

    docs = loaded

    chunks = []
    for d in docs:
        chunks.extend(chunk_text(d))
    all_chunks = chunks

    print("Docs loaded:", len(docs))
    print("Chunks created:", len(all_chunks))


def ads_agent_answer(user_question: str) -> str:
    tools_used = []

    if not is_prompt_safe(user_question):
        answer = "Unsafe request. Please ask about Alaska snow services or weather."
        log_event(user_question, answer, ["blocked"])
        return answer

    ctx = retrieve_context(user_question, top_k=5)
    tools_used.append("rag")

    ql = (user_question or "").lower()
    weather_text = ""

    if any(k in ql for k in ["weather", "forecast", "alert", "temperature", "snow"]):
        for city in ALASKA_CITIES:
            if city in ql:
                lat, lon = ALASKA_CITIES[city]
                weather_text = nws_get_forecast_by_latlon(lat, lon)
                tools_used.append("weather_api")
                break

    response_parts = []
    if ctx:
        response_parts.append("Relevant FAQ Information:")
        for c in ctx:
            response_parts.append(c.strip())

    if weather_text:
        response_parts.append("")
        response_parts.append("Weather Info (NWS):")
        response_parts.append(weather_text)

    answer = validate_response("\n\n".join(response_parts))
    log_event(user_question, answer, tools_used)
    return answer


@app.get("/health")
def health():
    return jsonify({"status": "ok", "docs_loaded": len(docs), "chunks": len(all_chunks)})


@app.post("/ask")
def ask():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "")
    answer = ads_agent_answer(question)
    return jsonify({"answer": answer})


# Load docs when the container starts
load_rag_docs()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
