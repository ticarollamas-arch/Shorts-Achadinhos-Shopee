import os, re, json, sqlite3, uuid, subprocess, shutil, hashlib, base64
from pathlib import Path
from functools import wraps
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import requests
from cryptography.fernet import Fernet, InvalidToken

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
STORAGE = BASE / "storage"
UPLOADS = STORAGE / "uploads"
EXPORTS = STORAGE / "exports"
DB_PATH = DATA / "shorts.db"
for p in (DATA, UPLOADS, EXPORTS):
    p.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "change-this-secret-before-deploying")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-now")
ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS settings
          (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS projects
          (id TEXT PRIMARY KEY, title TEXT NOT NULL, product_url TEXT, keywords TEXT,
           source_file TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS clips
          (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, start REAL NOT NULL,
           duration REAL NOT NULL, filename TEXT, status TEXT DEFAULT 'pending',
           checklist TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS app_users
          (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL)""")
        row = c.execute("SELECT username FROM app_users WHERE username=?", (ADMIN_USER,)).fetchone()
        if not row:
            c.execute("INSERT INTO app_users(username,password_hash) VALUES(?,?)",
                      (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD)))

def cipher():
    seed = os.getenv("APP_SECRET", "change-this-secret-before-deploying").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)

def save_setting(key, value):
    token = cipher().encrypt((value or "").encode()).decode()
    with db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, token))

def get_setting(key):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row: return ""
    try: return cipher().decrypt(row["value"].encode()).decode()
    except (InvalidToken, Exception): return ""

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def ffmpeg_path():
    return shutil.which("ffmpeg")

def ffprobe_path():
    return shutil.which("ffprobe")

def video_duration(path):
    probe = ffprobe_path()
    if not probe: return None
    try:
        out = subprocess.check_output([probe, "-v", "error", "-show_entries", "format=duration",
                                       "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                      stderr=subprocess.DEVNULL, timeout=30)
        return float(out.decode().strip())
    except Exception:
        return None

def basic_keywords(title):
    words = re.findall(r"[\wÀ-ÿ]+", title.lower())
    stop = {"com","para","de","da","do","e","em","kit","original"}
    core = [w for w in words if w not in stop and len(w) > 2]
    return list(dict.fromkeys(core))[:12]

def groq_keywords(title):
    key = get_setting("GROQ_API_KEY")
    if not key: return basic_keywords(title)
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
          headers={"Authorization": f"Bearer {key}", "Content-Type":"application/json"},
          json={"model":"llama-3.3-70b-versatile","temperature":0.2,
                "messages":[{"role":"system","content":"Gere palavras-chave curtas para pesquisar vídeos demonstrativos de produto. Retorne somente JSON válido: {\"keywords\":[...]}."},
                            {"role":"user","content":title}]}, timeout=25)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            arr = json.loads(m.group(0)).get("keywords", [])
            if isinstance(arr, list) and arr: return [str(x)[:80] for x in arr[:12]]
    except Exception:
        pass
    return basic_keywords(title)

def youtube_search(query):
    key = get_setting("YOUTUBE_API_KEY")
    if not key: return None, "Configure uma chave YouTube Data API v3 em Configurações para habilitar a busca."
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
            params={"part":"snippet","q":query,"type":"video","maxResults":8,"key":key},
            timeout=20)
        data = r.json()
        if r.status_code != 200:
            return None, data.get("error",{}).get("message","Falha na pesquisa do YouTube.")
        results = []
        for item in data.get("items", []):
            vid = item.get("id",{}).get("videoId")
            sn = item.get("snippet",{})
            if vid:
                results.append({"id":vid,"title":sn.get("title",""),"channel":sn.get("channelTitle",""),
                    "thumb":sn.get("thumbnails",{}).get("medium",{}).get("url",""),
                    "url":f"https://www.youtube.com/watch?v={vid}"})
        return results, None
    except Exception as e:
        return None, str(e)

@app.errorhandler(413)
def too_large(_):
    flash("Arquivo maior que o limite configurado. Reduza o vídeo ou ajuste MAX_UPLOAD_MB.", "error")
    return redirect(url_for("dashboard"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","")
        password = request.form.get("password","")
        with db() as c:
            row = c.execute("SELECT * FROM app_users WHERE username=?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session["user"] = username
            return redirect(url_for("dashboard"))
        flash("Usuário ou senha incorretos.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    with db() as c:
        projects = c.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 30").fetchall()
        counts = {
          "projects": c.execute("SELECT COUNT(*) n FROM projects").fetchone()["n"],
          "clips": c.execute("SELECT COUNT(*) n FROM clips").fetchone()["n"],
          "approved": c.execute("SELECT COUNT(*) n FROM clips WHERE status='approved'").fetchone()["n"]
        }
    return render_template("dashboard.html", projects=projects, counts=counts,
       ffmpeg=bool(ffmpeg_path()), youtube=bool(get_setting("YOUTUBE_API_KEY")), groq=bool(get_setting("GROQ_API_KEY")))

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings():
    if request.method == "POST":
        for k in ("GROQ_API_KEY","YOUTUBE_API_KEY"):
            val = request.form.get(k,"").strip()
            if val: save_setting(k,val)
        if request.form.get("clear_groq"): save_setting("GROQ_API_KEY","")
        if request.form.get("clear_youtube"): save_setting("YOUTUBE_API_KEY","")
        flash("Configurações salvas. As chaves ficam criptografadas no banco local.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", groq=bool(get_setting("GROQ_API_KEY")),
                           youtube=bool(get_setting("YOUTUBE_API_KEY")))

@app.route("/project/new", methods=["POST"])
@login_required
def new_project():
    title = request.form.get("title","").strip()
    product_url = request.form.get("product_url","").strip()
    if not title:
        flash("Informe o título do produto. O link é opcional.", "error")
        return redirect(url_for("dashboard"))
    pid = uuid.uuid4().hex[:12]
    keywords = groq_keywords(title)
    with db() as c:
        c.execute("INSERT INTO projects(id,title,product_url,keywords) VALUES(?,?,?,?)",
                  (pid,title,product_url,json.dumps(keywords,ensure_ascii=False)))
    return redirect(url_for("project", project_id=pid))

@app.route("/project/<project_id>")
@login_required
def project(project_id):
    with db() as c:
        p = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        clips = c.execute("SELECT * FROM clips WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    if not p: return "Projeto não encontrado", 404
    return render_template("project.html", p=p, clips=clips, keywords=json.loads(p["keywords"] or "[]"),
                           duration=video_duration(UPLOADS / p["source_file"]) if p["source_file"] else None)

@app.route("/project/<project_id>/search")
@login_required
def search(project_id):
    with db() as c: p = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p: return "Projeto não encontrado", 404
    q = request.args.get("q") or (p["title"] + " unboxing demonstração review")
    results, error = youtube_search(q)
    return render_template("search.html", p=p, q=q, results=results or [], error=error)

@app.route("/project/<project_id>/upload", methods=["POST"])
@login_required
def upload(project_id):
    with db() as c: p = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p: return "Projeto não encontrado", 404
    f = request.files.get("video")
    if not f or not f.filename:
        flash("Selecione um vídeo autorizado para edição.", "error")
        return redirect(url_for("project", project_id=project_id))
    name = secure_filename(f.filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        flash("Formato não suportado. Use MP4, MOV, M4V, WEBM ou MKV.", "error")
        return redirect(url_for("project", project_id=project_id))
    stored = f"{project_id}_{uuid.uuid4().hex[:8]}{ext}"
    f.save(UPLOADS / stored)
    with db() as c: c.execute("UPDATE projects SET source_file=? WHERE id=?", (stored, project_id))
    flash("Vídeo enviado. Antes de exportar, cada trecho precisa passar pela lista de aprovação.", "success")
    return redirect(url_for("project", project_id=project_id))

@app.route("/project/<project_id>/clip", methods=["POST"])
@login_required
def create_clip(project_id):
    with db() as c: p = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p or not p["source_file"]: flash("Envie primeiro um vídeo autorizado.", "error"); return redirect(url_for("project", project_id=project_id))
    if not ffmpeg_path(): flash("FFmpeg não está instalado no servidor. Peça ao suporte da hospedagem para disponibilizar ffmpeg e ffprobe.", "error"); return redirect(url_for("project", project_id=project_id))
    try:
        start = max(0, float(request.form.get("start", "0")))
        duration = min(90, max(5, float(request.form.get("duration", "30"))))
    except ValueError:
        flash("Tempo inválido.", "error"); return redirect(url_for("project", project_id=project_id))
    src = UPLOADS / p["source_file"]
    total = video_duration(src)
    if total is None or start + duration > total:
        flash("Não foi possível validar a duração ou o trecho ultrapassa o vídeo.", "error")
        return redirect(url_for("project", project_id=project_id))
    # Each clip remains pending until every strict policy checkbox is confirmed.
    cid = uuid.uuid4().hex[:12]
    checklist = {
      "product_match": bool(request.form.get("product_match")),
      "no_watermark": bool(request.form.get("no_watermark")),
      "no_other_brand_logo": bool(request.form.get("no_other_brand_logo")),
      "in_context": bool(request.form.get("in_context")),
      "no_violence": bool(request.form.get("no_violence")),
      "rights_ok": bool(request.form.get("rights_ok"))
    }
    all_ok = all(checklist.values())
    status = "approved" if all_ok else "rejected"
    filename = f"{cid}.mp4" if all_ok else None
    with db() as c:
        c.execute("INSERT INTO clips(id,project_id,start,duration,filename,status,checklist) VALUES(?,?,?,?,?,?,?)",
                  (cid,project_id,start,duration,filename,status,json.dumps(checklist)))
    if not all_ok:
        flash("Trecho rejeitado: todos os critérios obrigatórios precisam ser aprovados. Nenhum arquivo foi exportado.", "error")
        return redirect(url_for("project", project_id=project_id))
    out = EXPORTS / filename
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    cmd = [ffmpeg_path(), "-y", "-ss", str(start), "-i", str(src), "-t", str(duration),
           "-map","0:v:0","-map","0:a?","-vf",vf,"-c:v","libx264","-preset","veryfast",
           "-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
        flash("Corte aprovado e exportado em MP4. O áudio original foi preservado.", "success")
    except Exception:
        with db() as c: c.execute("UPDATE clips SET status='error',filename=NULL WHERE id=?", (cid,))
        flash("Falha ao renderizar. Verifique se o FFmpeg tem suporte a libx264 e AAC.", "error")
    return redirect(url_for("project", project_id=project_id))

@app.route("/download/<filename>")
@login_required
def download(filename):
    if not re.fullmatch(r"[a-f0-9]{12}\.mp4", filename): return "Arquivo inválido", 400
    with db() as c:
        row = c.execute("SELECT id FROM clips WHERE filename=? AND status='approved'", (filename,)).fetchone()
    if not row: return "Arquivo não encontrado", 404
    return send_from_directory(EXPORTS, filename, as_attachment=True)

@app.route("/health")
def health():
    return jsonify({"ok":True,"ffmpeg":bool(ffmpeg_path()),"ffprobe":bool(ffprobe_path())})

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), debug=False)
