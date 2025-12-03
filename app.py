from flask import Flask, render_template, request, jsonify
import os
import json
import traceback
import re

import fitz  # PyMuPDF
import requests
from dotenv import load_dotenv


"""
Simple LinkedIn profile reviewer:
 - Upload a LinkedIn PDF export
 - Extract text with PyMuPDF
 - Send to Groq LLM for structured JSON feedback
"""

# ------------------ CONFIG / ENV ------------------
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


def ensure_api_key():
    """Return an error response if the Groq API key is missing."""
    if not GROQ_API_KEY:
        return jsonify(
            {
                "error": "Missing GROQ_API_KEY environment variable.",
                "details": "Set GROQ_API_KEY in a .env file or your shell before running the app.",
            }
        ), 500
    return None


# ------------------ PDF EXTRACTION / PARSING ------------------
def extract_text_from_pdf(file_storage):
    """
    Extract plain text from an uploaded PDF using PyMuPDF.
    file_storage is a Werkzeug FileStorage object from request.files["pdf"].
    """
    # Read file bytes once, then pass to PyMuPDF
    pdf_bytes = file_storage.read()
    if not pdf_bytes:
        raise ValueError("Uploaded file is empty or unreadable.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_chunks = [page.get_text() for page in doc]
    return "\n".join(text_chunks).strip()


def parse_profile_stats(extracted_text: str) -> dict:
    """
    Very small heuristic parser to try to spot number of connections / followers
    from the exported LinkedIn PDF text.
    """
    connections = None
    followers = None

    try:
        conn_match = re.search(
            r"(\d[\d,]*\+?).{0,8}connections?",
            extracted_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if conn_match:
            raw = conn_match.group(1).replace(",", "")
            if raw.endswith("+"):
                raw = raw[:-1]
            connections = int(raw)
    except Exception:
        connections = None

    try:
        foll_match = re.search(
            r"(\d[\d,]*\+?).{0,8}followers?",
            extracted_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if foll_match:
            raw = foll_match.group(1).replace(",", "")
            if raw.endswith("+"):
                raw = raw[:-1]
            followers = int(raw)
    except Exception:
        followers = None

    return {"connections": connections, "followers": followers}


# ------------------ PROMPT BUILDER ------------------
def build_prompt(
    extracted_text: str,
    target_role: str | None,
    stats: dict | None,
) -> str:
    role_part = f"\nTarget job role / title: {target_role}" if target_role else ""

    if stats:
        stats_part = (
            "\nParsed network stats from the PDF (may be approximate):\n"
            f"- connections: {stats.get('connections') or 'unknown'}\n"
            f"- followers: {stats.get('followers') or 'unknown'}\n"
        )
    else:
        stats_part = "\nParsed network stats from the PDF were not available.\n"

    return (
        "You are an expert LinkedIn profile and career coach.\n\n"
        "You will receive the raw text of a LinkedIn profile exported as PDF.\n"
        "Analyse it for clarity, impact, and alignment with the target role.\n\n"
        "PROFILE TEXT (from PDF):\n"
        "------------------------\n"
        f"{extracted_text}\n"
        "------------------------\n"
        f"{role_part}\n"
        f"{stats_part}\n"
        "Return ONLY a single valid JSON object, no backticks, no extra text.\n"
        "JSON schema:\n"
        "{\n"
        '  \"score\": number,            // 0-100 overall strength\n'
        '  \"connections\": number | null, // parsed / estimated from profile\n'
        '  \"followers\": number | null,   // parsed / estimated from profile\n'
        '  \"headline\": {\n'
        '    \"suggestion\": string,   // a single, ready-to-use LinkedIn headline\n'
        '    \"explanation\": string   // why this headline works\n'
        "  },\n"
        '  \"about\": {\n'
        '    \"suggestion\": string,   // a full About section the user can copy-paste\n'
        '    \"explanation\": string   // how it improves clarity and positioning\n'
        "  },\n"
        '  \"experience\": [\n'
        "    { \"role\": string, \"tips\": string } // concrete phrasing suggestions per role\n"
        "  ],\n"
        '  \"skills\": {\n'
        "    \"missing\": string | string[],\n"
        "    \"notes\": string\n"
        "  },\n"
        '  \"keywords\": string[],\n'
        '  \"summary\": string           // 2-3 line summary of key advice in natural language\n'
        "}\n"
        "Make sure the JSON is strictly valid and parsable."
    )


# ------------------ ROUTES ------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/review", methods=["POST"])
def review():
    # Ensure API key exists first
    key_error = ensure_api_key()
    if key_error:
        return key_error

    file = request.files.get("pdf")
    target_role = request.form.get("target_role", "").strip() or None

    if not file:
        return jsonify({"error": "No file uploaded."}), 400

    # ----- PDF extraction -----
    try:
        extracted_text = extract_text_from_pdf(file)
    except Exception as e:
        traceback.print_exc()
        return (
            jsonify(
                {
                    "error": "Failed to parse PDF.",
                    "details": str(e),
                }
            ),
            500,
        )

    if not extracted_text:
        return jsonify({"error": "No text could be extracted from the PDF."}), 400

    # ----- Parse simple stats and build prompt -----
    stats = parse_profile_stats(extracted_text)
    prompt = build_prompt(extracted_text, target_role, stats)

    # ----- Call Groq -----
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                # Updated model: llama3-8b-8192 is decommissioned
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1800,
            },
            timeout=60,
        )
    except Exception as e:
        traceback.print_exc()
        return (
            jsonify(
                {
                    "error": "Failed to contact Groq API.",
                    "details": str(e),
                }
            ),
            500,
        )

    if response.status_code != 200:
        return (
            jsonify(
                {
                    "error": "Groq API returned a non-200 status.",
                    "status": response.status_code,
                    "details": response.text,
                }
            ),
            500,
        )

    data = response.json()

    try:
        content = (
            data["choices"][0]["message"]["content"].strip()
        )  # type: ignore[index]
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Unexpected Groq response format.",
                    "details": str(e),
                    "raw": data,
                }
            ),
            500,
        )

    # ----- Parse JSON from model -----
    try:
        review_json = json.loads(content)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Model output was not valid JSON.",
                    "details": str(e),
                    "raw": content,
                }
            ),
            500,
        )

    # Ensure parsed stats are present even if the model omits them
    if isinstance(review_json, dict):
        if "connections" not in review_json or review_json.get("connections") is None:
            review_json["connections"] = stats.get("connections")
        if "followers" not in review_json or review_json.get("followers") is None:
            review_json["followers"] = stats.get("followers")

    return jsonify({"review": review_json})


if __name__ == "__main__":
    # debug=True is fine for local development
    app.run(debug=True, port=5000, use_reloader=False)