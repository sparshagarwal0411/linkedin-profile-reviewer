from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import json
import traceback
import re
from datetime import datetime, timezone
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

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

app = Flask(__name__)

# RAG-style benchmarks (local JSON, no vector DB) for comparison context
_RAG_BENCHMARKS_PATH = os.path.join(os.path.dirname(__file__), "data", "rag_benchmarks.json")
_LOCAL_LEADERBOARD_PATH = os.path.join(os.path.dirname(__file__), "data", "leaderboard_local.json")


def _load_rag_benchmarks() -> dict:
    try:
        with open(_RAG_BENCHMARKS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def select_benchmark_context(target_role: str | None) -> str:
    """
    Pick the closest benchmark bundle from local JSON using simple keyword match (RAG-style retrieval).
    """
    data = _load_rag_benchmarks()
    if not data:
        return ""
    role_lower = (target_role or "").lower()
    chosen = None
    chosen_key = "default"
    for key, block in data.items():
        if key == "default" or not isinstance(block, dict):
            continue
        matches = block.get("match") or []
        if any(m.lower() in role_lower for m in matches):
            chosen = block
            chosen_key = key
            break
    if chosen is None:
        chosen = data.get("default") or {}
    lines = [
        f"[Benchmark pack: {chosen_key}]",
        chosen.get("summary", ""),
        "Typical headline patterns: " + "; ".join(chosen.get("typical_headline_patterns") or []),
        "High-signal keywords (examples): " + ", ".join(chosen.get("high_signal_keywords") or []),
        "Common gaps vs strong profiles: " + "; ".join(chosen.get("common_skill_gaps") or []),
    ]
    return "\n".join(lines)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


def json_error(message: str, status: int = 500, **extra):
    """Return a consistent JSON error payload."""
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def wants_json_error() -> bool:
    path = (request.path or "").lower()
    if path.startswith("/api/") or path == "/review":
        return True
    accepted = request.headers.get("Accept", "")
    return "application/json" in accepted.lower()

def get_supabase_client():
    """Lazily load the Supabase client to prevent Vercel Serverless connection freezing."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        return create_client(url, key)
    return None


def _read_local_leaderboard() -> list[dict]:
    try:
        with open(_LOCAL_LEADERBOARD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except OSError:
        return []
    except json.JSONDecodeError:
        return []
    return []


def _write_local_leaderboard(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(_LOCAL_LEADERBOARD_PATH), exist_ok=True)
    with open(_LOCAL_LEADERBOARD_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=True, indent=2)


def save_leaderboard_entry(name: str, score: int | float) -> None:
    rows = _read_local_leaderboard()
    rows.append(
        {
            "name": str(name).strip() or "Anonymous User",
            "score": score,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    rows = sorted(
        rows,
        key=lambda x: x.get("score", 0),
        reverse=True,
    )[:100]
    _write_local_leaderboard(rows)


def get_top_leaderboard(limit: int = 10) -> list[dict]:
    # Prefer Supabase if configured and reachable, otherwise fallback to local store.
    try:
        supabase = get_supabase_client()
        if supabase:
            response = supabase.table("leaderboard").select("*").order("score", desc=True).limit(limit).execute()
            if isinstance(response.data, list):
                return response.data
    except Exception as e:
        print("Supabase leaderboard read failed, using local fallback:", e)

    local_rows = _read_local_leaderboard()
    return sorted(local_rows, key=lambda x: x.get("score", 0), reverse=True)[:limit]

def ensure_api_key():
    """Return an error response if the Gemini API key is missing."""
    if not os.environ.get("GEMINI_API_KEY"):
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
_PROFILE_TEXT_LIMIT = 3000  # keep latency lower to avoid worker timeouts


def build_prompt(
    extracted_text: str,
    target_role: str | None,
    experience_level: str | None,
    dream_companies: str | None,
    stats: dict | None,
) -> str:
    role_part = f"\nTarget job role / title: {target_role}" if target_role else ""
    exp_part = (
        f"\nExperience level (user-selected): {experience_level}"
        if experience_level
        else ""
    )
    companies_part = (
        f"\nDream companies / employers of interest: {dream_companies}"
        if dream_companies
        else ""
    )

    if stats:
        stats_part = (
            "\nParsed network stats from the PDF (may be approximate):\n"
            f"- connections: {stats.get('connections') or 'unknown'}\n"
            f"- followers: {stats.get('followers') or 'unknown'}\n"
        )
    else:
        stats_part = "\nParsed network stats from the PDF were not available.\n"

    benchmark_block = select_benchmark_context(target_role)
    benchmark_section = (
        "\n--- Reference: patterns from strong profiles (use for gap analysis, not as facts about this user) ---\n"
        f"{benchmark_block}\n"
        if benchmark_block
        else ""
    )

    personalization = (
        "Personalization: tailor EVERY section to the target role, experience level, and dream companies when provided. "
        "If a field is empty, infer reasonably from the profile only.\n"
    )

    return (
        "You are a fast, expert LinkedIn coach and recruiter.\n"
        f"{personalization}"
        "Analyse the LinkedIn profile text below. Be concise; each \"reason\" field must be one short sentence.\n\n"
        "SCORING: overall score 0-100 plus four sub-scores 0-100: keywords, recruiter_visibility, impact, completeness. "
        "Sub-scores should reflect the profile text, not wishful thinking. Be conservative; 90+ overall is rare.\n"
        f"PROFILE TEXT:\n{extracted_text[:_PROFILE_TEXT_LIMIT]}\n"
        f"{role_part}{exp_part}{companies_part}\n"
        f"{stats_part}"
        f"{benchmark_section}\n"
        "Return ONLY one valid JSON object. No markdown fences, no commentary.\n"
        "Schema (all keys required; use empty arrays/strings where unknown):\n"
        "{\n"
        '  \"full_name\": string | null,\n'
        '  \"score\": number,\n'
        '  \"score_breakdown\": {\n'
        '    \"keywords\": number,\n'
        '    \"recruiter_visibility\": number,\n'
        '    \"impact\": number,\n'
        '    \"completeness\": number,\n'
        '    \"rationale\": string\n'
        "  },\n"
        '  \"connections\": number | null,\n'
        '  \"followers\": number | null,\n'
        '  \"recruiter_pov\": {\n'
        '    \"strengths\": [ { \"point\": string, \"reason\": string } ],\n'
        '    \"red_flags\": [ { \"point\": string, \"reason\": string } ],\n'
        '    \"hire_probability_percent\": number,\n'
        '    \"hire_probability_reason\": string\n'
        "  },\n"
        '  \"headline\": {\n'
        '    \"rewrite\": string,\n'
        '    \"reason\": string,\n'
        '    \"suggestion\": string,\n'
        '    \"explanation\": string\n'
        "  },\n"
        '  \"about\": {\n'
        '    \"rewrite\": string,\n'
        '    \"reason\": string,\n'
        '    \"suggestion\": string,\n'
        '    \"explanation\": string\n'
        "  },\n"
        '  \"experience\": [\n'
        '    {\n'
        '      \"role\": string,\n'
        '      \"rewrite\": string,\n'
        '      \"reason\": string,\n'
        '      \"tips\": string\n'
        "    }\n"
        "  ],\n"
        '  \"skills\": { \"missing\": string | string[], \"notes\": string },\n'
        '  \"keywords\": string[],\n'
        '  \"benchmark_comparison\": {\n'
        '    \"skill_gaps\": [ { \"gap\": string, \"reason\": string } ],\n'
        '    \"missing_keywords\": [ { \"keyword\": string, \"reason\": string } ],\n'
        '    \"summary\": string\n'
        "  },\n"
        '  \"linkedin_content\": {\n'
        '    \"post_ideas\": [ { \"idea\": string, \"reason\": string } ],\n'
        '    \"weekly_plan\": [ { \"day\": string, \"task\": string, \"reason\": string } ]\n'
        "  },\n"
        '  \"roadmap\": {\n'
        '    \"days_30\": [ { \"action\": string, \"reason\": string } ],\n'
        '    \"days_60\": [ { \"action\": string, \"reason\": string } ],\n'
        '    \"days_90\": [ { \"action\": string, \"reason\": string } ]\n'
        "  },\n"
        '  \"summary\": string\n'
        "}\n"
        "Rules: headline.about.experience rewrites must be copy-ready (clean lines, no placeholders). "
        "Mirror headline.rewrite into suggestion if identical; same for about and experience tips vs rewrite where helpful. "
        "weekly_plan should have 5-7 items covering Mon-Sun style days. "
        "Ensure strict JSON with double quotes."
    )


def normalize_review_json(obj: dict) -> dict:
    """Fill optional fields so the UI always has rewrite + legacy suggestion keys."""
    if not isinstance(obj, dict):
        return obj

    for section in ("headline", "about"):
        block = obj.get(section)
        if isinstance(block, dict):
            rw = block.get("rewrite")
            sug = block.get("suggestion")
            if not rw and sug:
                block["rewrite"] = sug
            if not sug and rw:
                block["suggestion"] = rw
            rs = block.get("reason")
            ex = block.get("explanation")
            if not rs and ex:
                block["reason"] = ex
            if not ex and rs:
                block["explanation"] = rs

    exp = obj.get("experience")
    if isinstance(exp, list):
        for item in exp:
            if not isinstance(item, dict):
                continue
            if not item.get("rewrite") and item.get("tips"):
                item["rewrite"] = item["tips"]
            if not item.get("reason"):
                item["reason"] = ""
            if not item.get("tips") and item.get("rewrite"):
                item["tips"] = item["rewrite"]

    sb = obj.get("score_breakdown")
    defaults_sb = {
        "keywords": None,
        "recruiter_visibility": None,
        "impact": None,
        "completeness": None,
        "rationale": "",
    }
    if not isinstance(sb, dict):
        obj["score_breakdown"] = defaults_sb
    else:
        for k, v in defaults_sb.items():
            if k not in sb:
                sb[k] = v

    rp = obj.get("recruiter_pov")
    rp_def = {
        "strengths": [],
        "red_flags": [],
        "hire_probability_percent": None,
        "hire_probability_reason": "",
    }
    if not isinstance(rp, dict):
        obj["recruiter_pov"] = rp_def
    else:
        for k, v in rp_def.items():
            if k not in rp:
                rp[k] = v

    bc = obj.get("benchmark_comparison")
    bc_def = {"skill_gaps": [], "missing_keywords": [], "summary": ""}
    if not isinstance(bc, dict):
        obj["benchmark_comparison"] = bc_def
    else:
        for k, v in bc_def.items():
            if k not in bc:
                bc[k] = v

    lc = obj.get("linkedin_content")
    lc_def = {"post_ideas": [], "weekly_plan": []}
    if not isinstance(lc, dict):
        obj["linkedin_content"] = lc_def
    else:
        for k, v in lc_def.items():
            if k not in lc:
                lc[k] = v

    rm = obj.get("roadmap")
    rm_def = {"days_30": [], "days_60": [], "days_90": []}
    if not isinstance(rm, dict):
        obj["roadmap"] = rm_def
    else:
        for k, v in rm_def.items():
            if k not in rm:
                rm[k] = v

    return obj


# ------------------ ROUTES ------------------
@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_err):
    if wants_json_error():
        return json_error(
            "Uploaded file is too large.",
            413,
            details="Maximum allowed size is 16 MB.",
        )
    return "Uploaded file is too large. Maximum allowed size is 16 MB.", 413


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    if wants_json_error():
        return json_error(err.description or "HTTP error.", err.code or 500)
    return err


@app.errorhandler(Exception)
def handle_unexpected_exception(err):
    traceback.print_exc()
    if wants_json_error():
        return json_error(
            "Unhandled server error.",
            500,
            details=str(err),
        )
    return "Internal Server Error", 500


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html")

@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    try:
        rows = get_top_leaderboard(limit=10)
        return jsonify({"leaderboard": rows, "source": "supabase_or_local"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/review", methods=["GET", "POST"])
def review():
    if request.method == "GET":
        return redirect(url_for("index"))
    try:
        # Ensure API key exists first
        key_error = ensure_api_key()
        if key_error:
            return key_error

        file = request.files.get("pdf")
        target_role = request.form.get("target_role", "").strip() or None
        experience_level = request.form.get("experience_level", "").strip() or None
        dream_companies = request.form.get("dream_companies", "").strip() or None

        if not file:
            return json_error("No file uploaded.", 400)

        # ----- PDF extraction -----
        try:
            extracted_text = extract_text_from_pdf(file)
        except Exception as e:
            traceback.print_exc()
            return json_error("Failed to parse PDF.", 500, details=str(e))

        if not extracted_text:
            return json_error("No text could be extracted from the PDF.", 400)

        # Basic guard: only proceed if this looks like a LinkedIn profile PDF
        if not is_likely_linkedin_profile(extracted_text):
            return json_error(
                "This PDF does not look like a LinkedIn profile export.",
                400,
                details="Please upload a PDF downloaded from LinkedIn using the 'Save to PDF' option on your profile page.",
            )

        # ----- Parse simple stats and build prompt -----
        stats = parse_profile_stats(extracted_text)
        prompt = build_prompt(
            extracted_text,
            target_role,
            experience_level,
            dream_companies,
            stats,
        )

        # ----- Call Gemini -----
        try:
            gemini_api_key = os.environ.get("GEMINI_API_KEY")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                    "maxOutputTokens": 1800,
                }
            }
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=25,
            )
        except Exception as e:
            traceback.print_exc()
            return json_error("Failed to contact Gemini API.", 500, details=str(e))

        if response.status_code != 200:
            return json_error(
                "Gemini API returned a non-200 status.",
                500,
                status=response.status_code,
                details=response.text,
            )

        try:
            data = response.json()
        except Exception as e:
            return json_error(
                "Gemini API returned non-JSON response.",
                500,
                details=str(e),
                raw=(response.text or "")[:1000],
            )

        try:
            content = (
                data["candidates"][0]["content"]["parts"][0]["text"].strip()
            )
        except Exception as e:
            return json_error(
                "Unexpected Gemini response format.",
                500,
                details=str(e),
                raw=data,
            )

        # ----- Parse JSON from model -----
        try:
            # Strip potential markdown code blocks
            clean_content = content
            if clean_content.startswith("```"):
                lines = clean_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_content = "\n".join(lines).strip()

            review_json = json.loads(clean_content)
            review_json = normalize_review_json(review_json)
        except Exception as e:
            return json_error(
                "Model output was not valid JSON.",
                500,
                details=str(e),
                raw=content,
            )

        # Ensure parsed stats are present even if the model omits them
        if isinstance(review_json, dict):
            if "connections" not in review_json or review_json.get("connections") is None:
                review_json["connections"] = stats.get("connections")
            if "followers" not in review_json or review_json.get("followers") is None:
                review_json["followers"] = stats.get("followers")

            # Save to leaderboard (Supabase first; always fallback local)
            if review_json.get("score") is not None:
                name_to_insert = review_json.get("full_name")
                if not name_to_insert or str(name_to_insert).strip() == "":
                    name_to_insert = "Anonymous User"
                try:
                    supabase = get_supabase_client()
                    if supabase:
                        supabase.table("leaderboard").insert({
                            "name": name_to_insert,
                            "score": review_json["score"]
                        }).execute()
                except Exception as e:
                    print("Failed to save to Supabase leaderboard, using local fallback:", e)
                try:
                    save_leaderboard_entry(name_to_insert, review_json["score"])
                except Exception as e:
                    print("Failed to save local leaderboard entry:", e)

        return jsonify({"review": review_json})
    except Exception as e:
        traceback.print_exc()
        return json_error(
            "Unhandled server error while processing review.",
            500,
            details=str(e),
        )


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