"""
MAIN FILE - RomanEng Compiler website
Run:  python app.py      ->  http://localhost:5000

app.py          : Flask app + compiler API  (run this file)
auth.py         : login / logout / security
database.py    : SQL Server 2022 connection + tables
config.py       : DB settings
compiler_core.py: compiler (Lexical, Syntax, Semantic, Intermediate Code)
"""
import secrets

from flask import Flask, request, jsonify, render_template

import config
import database as db
import compiler_core as cc
from auth import auth_bp, login_required, current_user

app = Flask(__name__)
app.secret_key = config.SECRET_KEY or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.register_blueprint(auth_bp)


@app.route("/")
@login_required
def home():
    return render_template("index.html", user=current_user()["name"])


@app.route("/api/meta")
@login_required
def meta():
    return jsonify(
        keywords=[{"purpose": p, "word": w} for p, w, _ in cc.KW],
        types=[{"purpose": p, "word": w} for p, w, _ in cc.TY],
        operators=[{"purpose": p, "normal": n, "word": w} for p, n, w in cc.OP],
        bnf=cc.BNF, sample=cc.SAMPLE, phases=cc.PHASE_INFO)


def _body():
    d = request.get_json(silent=True) or {}
    return str(d.get("source", ""))[:20000], d


@app.route("/api/compile", methods=["POST"])
@login_required
def api_compile():
    """Dependent mode: runs all 4 phases as a pipeline plus the program output. Saved to history."""
    src, d = _body()
    result = cc.compile_all(src, str(d.get("inputs", ""))[:2000])
    if src.strip():
        try:
            db.save_history(current_user()["id"], src, "success" if result["run"] else "failed")
        except Exception as e:
            print("Could not save history:", e)
    return jsonify(result)


@app.route("/api/phase", methods=["POST"])
@login_required
def api_phase():
    """Independent mode: runs a single phase."""
    src, d = _body()
    key = d.get("phase")
    if key not in ("lexical", "syntax", "semantic", "icg"):
        return jsonify(error="Invalid phase"), 400
    return jsonify(cc.run_one(key, src))


@app.route("/api/history", methods=["GET", "DELETE"])
@login_required
def api_history():
    uid = current_user()["id"]
    try:
        if request.method == "DELETE":
            db.clear_history(uid)
            return jsonify(ok=True)
        return jsonify(items=db.get_history(uid))
    except Exception as e:
        return jsonify(error=str(e)), 500


if __name__ == "__main__":
    try:
        db.init_db()
        print(f"✔ SQL Server connected ->  {config.DB_SERVER} / {config.DB_NAME}")
    except Exception as e:
        print("\n✘ Could not connect to SQL Server:\n ", e)
        print("\nCheck: (1) the SQL Server service is running  (2) DB_SERVER in config.py is correct"
              "\n       (3) ODBC Driver 17/18 for SQL Server is installed  (4) pip install pyodbc")
        raise SystemExit(1)
    app.run(host="127.0.0.1", port=5000, debug=False)
