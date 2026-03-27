from flask import Flask, render_template, request, jsonify, send_file
import os
import json
import traceback
import re

import fitz  # PyMuPDF
import requests
from dotenv import load_dotenv
from certificate import generate_certificate_pdf
import io
from supabase import create_client, Client


"""
Simple LinkedIn profile reviewer:
 - Upload a LinkedIn PDF export
 - Extract text with PyMuPDF
 - Send to Groq LLM for structured JSON feedback
"""

# ------------------ CONFIG / ENV ------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print("Failed to initialize Supabase:", e)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


def ensure_api_key():
    """Return an error response if the Gemini API key is missing."""
    if not GEMINI_API_KEY:
        return jsonify(
            {
                "error": "Missing GEMINI_API_KEY environment variable.",
                "details": "Set GEMINI_API_KEY in a .env file or your shell before running the app.",
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


def is_likely_linkedin_profile(text: str) -> bool:
    """
    Heuristic check to see if the extracted PDF text looks like a LinkedIn profile export.
    We look for a combination of LinkedIn-specific markers and typical section labels.
    """
    lower = text.lower()

    must_have_any = [
        "linkedin profile",
        "www.linkedin.com/in/",
        "linkedin.com/in/",
        "experience",
        "about",
        "recommendations",
        "skills",
        "accomplishments",
    ]

    # Require at least 2 distinct LinkedIn-ish markers
    hits = 0
    for marker in must_have_any:
        if marker in lower:
            hits += 1
    if hits < 2:
        return False

    # Also reject obviously tiny or non-profile documents
    if len(text.split()) < 80:
        return False

    return True


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
        "You are a fast, expert LinkedIn coach.\n"
        "Analyse this LinkedIn profile text. Be concise and write brief, punchy explanations.\n\n"
        "SCORING RULES: 0-100 scale. Be conservative. 90+ is rare.\n"
        f"PROFILE TEXT:\n{extracted_text[:2500]}\n"  # Truncate text to 2500 chars to speed up processing
        f"{role_part}\n"
        f"{stats_part}\n"
        "Return ONLY a single valid JSON object, no backticks, no extra text.\n"
        "JSON schema:\n"
        "{\n"
        '  \"full_name\": string | null,   // inferred profile owner name, or null if unclear\n'
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

@app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html")

@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    if not supabase:
        return jsonify({"error": "Supabase not configured."}), 500
    try:
        response = supabase.table("leaderboard").select("*").order("score", desc=True).limit(10).execute()
        return jsonify({"leaderboard": response.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    # Basic guard: only proceed if this looks like a LinkedIn profile PDF
    if not is_likely_linkedin_profile(extracted_text):
        return (
            jsonify(
                {
                    "error": "This PDF does not look like a LinkedIn profile export.",
                    "details": "Please upload a PDF downloaded from LinkedIn using the 'Save to PDF' option on your profile page.",
                }
            ),
            400,
        )

    # ----- Parse simple stats and build prompt -----
    stats = parse_profile_stats(extracted_text)
    prompt = build_prompt(extracted_text, target_role, stats)

    # ----- Call Gemini -----
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-8b:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
    except Exception as e:
        traceback.print_exc()
        return (
            jsonify(
                {
                    "error": "Failed to contact Gemini API.",
                    "details": str(e),
                }
            ),
            500,
        )

    if response.status_code != 200:
        return (
            jsonify(
                {
                    "error": "Gemini API returned a non-200 status.",
                    "status": response.status_code,
                    "details": response.text,
                }
            ),
            500,
        )

    data = response.json()

    try:
        content = (
            data["candidates"][0]["content"]["parts"][0]["text"].strip()
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Unexpected Gemini response format.",
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

        # Save to leaderboard
        if supabase and review_json.get("full_name") and review_json.get("score"):
            try:
                supabase.table("leaderboard").insert({
                    "name": review_json["full_name"],
                    "score": review_json["score"]
                }).execute()
            except Exception as e:
                print("Failed to save to leaderboard:", e)

    return jsonify({"review": review_json})


@app.route("/certificate")
def certificate():
    """
    Generate a PDF certificate for the given score and return it as a download.
    Frontend will call this with a query param, e.g. /certificate?score=82
    """
    score = request.args.get("score", type=int)
    if score is None:
        return jsonify({"error": "Missing or invalid 'score' query parameter."}), 400

    name = request.args.get("name", default="Your LinkedIn Profile").strip() or "Your LinkedIn Profile"

    # Create an in-memory buffer and get PDF bytes (safe for readonly / ephemeral filesystems)
    buffer = io.BytesIO()
    pdf_bytes = generate_certificate_pdf(
        name=name,
        score=score,
        issuer="LinkedIn AI Reviewer",
        credits_text="LinkedIn AI Reviewer - Sparsh Agarwal",
        output_stream=buffer,
    )

    if pdf_bytes is None:
        # Fallback: previous behavior when function saved to disk (shouldn't normally happen now)
        output_path = os.path.join("static", "linkedin_certificate.pdf")
        return send_file(
            output_path,
            as_attachment=True,
            download_name="linkedin_profile_certificate.pdf",
            mimetype="application/pdf",
        )

    # Stream the in-memory PDF back
    buffer = io.BytesIO(pdf_bytes)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="linkedin_profile_certificate.pdf",
        mimetype="application/pdf",
    )

if __name__ == "__main__":
    # debug=True is fine for local development
    app.run(debug=True, port=5000, use_reloader=False)