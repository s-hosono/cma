from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, send_from_directory, session
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, send_from_directory, session
from werkzeug.utils import secure_filename
from pathlib import Path
import io
import os
import functools
from .services.diagram_analysis import analyze_file
from .services.process_breakdown import breakdown_process, ProcessStep
from .services.company_matching import match_companies
from .services.task_mapping import (
    normalize_category_key,
    keywords_for_category,
    categories_for_steps,
    steps_by_category,
)
from .services.report_generation import render_report_html, render_report_pdf, render_report_docx, render_assignments_docx
from .db.company_db import fetch_all, save_assignment, fetch_assignments, create_company, update_company, delete_company, fetch_by_id, fetch_assignment_files, fetch_assignments_for_file

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "dxf", "dwg"}


def create_app():
    app = Flask(__name__)
    # session secret (dev default)
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')

    # expose admin flag in templates
    @app.context_processor
    def inject_user():
        return {
            'is_admin': bool(session.get('is_admin')),
            'current_user': session.get('user')
        }

    def admin_required(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('is_admin'):
                # For API: JSON error. For normal pages, redirect to login with next
                if request.path.startswith('/api/'):
                    return jsonify({"ok": False, "error": "admin required"}), 403
                return redirect(url_for('login', next=request.url))
            return fn(*args, **kwargs)
        return wrapper

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        return send_from_directory(UPLOAD_DIR, filename)

    @app.post("/analyze")
    def analyze():
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "ファイルがありません"}), 400
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXT:
            return jsonify({"error": f"未対応の拡張子: {ext}"}), 400
        filename = secure_filename(f.filename)
        p = UPLOAD_DIR / filename
        f.save(p)
        features = analyze_file(p)
        app.config['last_upload_filename'] = filename
        preview_url = url_for('uploaded_file', filename=filename) if ext in {"png", "jpg", "jpeg"} else None
        return jsonify({
            "filename": features.filename,
            "ext": features.ext,
            "material": features.material,
            "part_type": features.part_type,
            "surface_finish": features.surface_finish,
            "tolerances": features.tolerances,
            "dims_text": features.dims_text,
            "notes": features.notes,
            "recommended_process": features.recommended_process,
            "recommended_machine": features.recommended_machine,
            "preview_url": preview_url,
        })

    @app.post("/process")
    def process():
        data = request.get_json(silent=True) or {}
        filename = data.get("filename") or app.config.get('last_upload_filename')
        if not filename:
            return redirect(url_for("index"))
        p = UPLOAD_DIR / secure_filename(filename)
        if not p.exists():
            return render_template("index.html", error="アップロードファイルが見つかりません。最初からやり直してください。")
        features = analyze_file(p)
        for key, dst in [("material","material"),("part_type","part_type"),("dimensions","dims_text"),("annotations","notes")]:
            val = data.get(key)
            if val:
                setattr(features, dst, val)
        process_steps = breakdown_process(features)
        matches = match_companies(process_steps)
        html = render_report_html(features, process_steps, matches)
        app.config['last_result'] = {
            'features': features,
            'process': process_steps,
            'matches': matches,
            'html': html,
        }
        return render_template("result.html", report_html=html)

    @app.post("/process/ui")
    def process_ui():
        data = request.get_json(silent=True) or {}
        filename = data.get("filename") or app.config.get('last_upload_filename')
        if not filename:
            return redirect(url_for("index"))
        p = UPLOAD_DIR / secure_filename(filename)
        if not p.exists():
            return render_template("index.html", error="アップロードファイルが見つかりません。最初からやり直してください。")
        features = analyze_file(p)
        for key, dst in [("material","material"),("part_type","part_type"),("dimensions","dims_text"),("annotations","notes")]:
            val = data.get(key)
            if val:
                setattr(features, dst, val)
        steps = breakdown_process(features)
        app.config['last_features'] = features
        app.config['last_steps'] = steps
        app.config['last_upload_filename'] = filename
        return render_template("process.html", features=features, steps=steps)

    # GETでも②の画面を再表示できるようにする
    @app.get("/process/ui")
    def process_ui_get():
        features = app.config.get('last_features')
        steps = app.config.get('last_steps') or []
        if not features:
            filename = app.config.get('last_upload_filename')
            if not filename:
                return redirect(url_for('index'))
            p = UPLOAD_DIR / secure_filename(filename)
            if not p.exists():
                return redirect(url_for('index'))
            features = analyze_file(p)
        if not steps:
            steps = breakdown_process(features)
            app.config['last_steps'] = steps
        return render_template("process.html", features=features, steps=steps)

    @app.post("/match")
    def match():
        data = request.get_json(silent=True) or {}
        features = app.config.get('last_features')
        if not features:
            filename = app.config.get('last_upload_filename')
            if not filename:
                return redirect(url_for('index'))
            p = UPLOAD_DIR / secure_filename(filename)
            features = analyze_file(p)
        steps_in = data.get('steps')
        if steps_in and isinstance(steps_in, list):
            steps = []
            for s in steps_in:
                try:
                    steps.append(
                        ProcessStep(
                            name=str(s.get('name') or s.get('operation') or ''),
                            machine=str(s.get('machine') or ''),
                            minutes=int(s.get('minutes') or 10),
                            tolerance=s.get('tolerance'),
                            precision=s.get('precision')
                        )
                    )
                except Exception:
                    continue
        else:
            steps = app.config.get('last_steps') or []

        matches = match_companies(steps)
        html = render_report_html(features, steps, matches)
        app.config['last_result'] = {
            'features': features,
            'process': steps,
            'matches': matches,
            'html': html,
        }
        # ④を最後の画面とするため、レポートUIへ遷移
        return redirect(url_for('reports_list'))

    @app.route("/match/ui", methods=["GET", "POST"])
    def match_ui():
        features = app.config.get('last_features')
        if not features:
            filename = app.config.get('last_upload_filename')
            if filename:
                p = UPLOAD_DIR / secure_filename(filename)
                if p.exists():
                    features = analyze_file(p)
        steps = app.config.get('last_steps') or []
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            steps_in = data.get('steps')
            if steps_in and isinstance(steps_in, list):
                new_steps = []
                for s in steps_in:
                    try:
                        new_steps.append(
                            ProcessStep(
                                name=str(s.get('name') or s.get('operation') or ''),
                                machine=str(s.get('machine') or ''),
                                minutes=int(s.get('minutes') or 10),
                                tolerance=s.get('tolerance'),
                                precision=s.get('precision')
                            )
                        )
                    except Exception:
                        continue
                if new_steps:
                    steps = new_steps
                    app.config['last_steps'] = steps
        if not steps and features:
            steps = breakdown_process(features)
            app.config['last_steps'] = steps

        raw_key = request.args.get('task')
        sel_key = normalize_category_key(raw_key) or 'drilling'

        companies = fetch_all()
        cat_map = steps_by_category(steps)
        steps_in_cat = [s for _, s in cat_map.get(sel_key, [])]
        steps_scope = steps_in_cat if steps_in_cat else steps

        matches_full = match_companies(steps) if steps else []
        matches = match_companies(steps_scope) if steps_scope else []

        keys = [k.lower() for k in keywords_for_category(sel_key)]
        def prio_count(m):
            text = f"{m.company.machines} {m.company.skills} {m.company.notes}".lower()
            return sum(1 for kw in keys if kw and kw in text)
        matches = sorted(matches, key=lambda m: (prio_count(m), m.score), reverse=True)

        tabs = categories_for_steps(steps)

        companies_json = [
            {
                'id': c.id,
                'name': c.name,
                'machines': c.machines,
                'skills': c.skills,
                'notes': c.notes,
                'capacity': getattr(c, 'capacity', '') or '',
                'location': getattr(c, 'location', '') or '',
            } for c in companies
        ]
        matches_json = [
            {
                'company': {'id': m.company.id, 'name': m.company.name},
                'score': m.score
            } for m in matches
        ]

        if features and steps:
            html = render_report_html(features, steps, matches_full)
            app.config['last_result'] = {
                'features': features,
                'process': steps,
                'matches': matches_full,
                'html': html,
            }

        return render_template(
            "match.html",
            features=features,
            steps=steps,
            companies=companies,
            matches=matches,
            selected_key=sel_key,
            tabs=tabs,
            keywords=keys,
            steps_in_category=steps_in_cat,
            companies_json=companies_json,
            matches_json=matches_json,
        )

    @app.post("/assignments/save")
    def assignments_save():
        data = request.get_json(silent=True) or {}
        task = (data.get('task') or '').strip()
        company_id = data.get('company_id')
        drawing_file = (data.get('drawing_file') or app.config.get('last_upload_filename') or '').strip()
        if not task or not company_id:
            return jsonify({"ok": False, "error": "task と company_id が必要です"}), 400
        try:
            aid = save_assignment(task, int(company_id), drawing_file)
            return jsonify({"ok": True, "id": aid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/upload")
    def upload():
        f = request.files.get("file")
        if not f:
            return redirect(url_for("index"))
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXT:
            return render_template("index.html", error=f"未対応の拡張子: {ext}")
        filename = secure_filename(f.filename)
        p = UPLOAD_DIR / filename
        f.save(p)
        features = analyze_file(p)
        process = breakdown_process(features)
        matches = match_companies(process)
        html = render_report_html(features, process, matches)
        app.config['last_result'] = {
            'features': features,
            'process': process,
            'matches': matches,
            'html': html,
        }
        return render_template("result.html", report_html=html)

    @app.get("/companies")
    def companies_list():
        companies = fetch_all()
        return render_template("companies.html", companies=companies)

    # Admin APIs for Companies
    @app.post("/api/companies")
    @admin_required
    def api_companies_create():
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        machines = (data.get('machines') or '').strip()
        skills = (data.get('skills') or '').strip()
        notes = (data.get('notes') or '').strip()
        capacity = (data.get('capacity') or '').strip()
        location = (data.get('location') or '').strip()
        if not name or not machines:
            return jsonify({"ok": False, "error": "name と machines は必須です"}), 400
        cid = create_company(name, machines, skills, notes, capacity, location)
        row = fetch_by_id(cid)
        return jsonify({"ok": True, "id": cid, "company": row.__dict__ if row else None})

    @app.put("/api/companies/<int:company_id>")
    @admin_required
    def api_companies_update(company_id: int):
        data = request.get_json(silent=True) or {}
        ok = update_company(company_id, data)
        row = fetch_by_id(company_id)
        return jsonify({"ok": ok, "company": row.__dict__ if row else None})

    @app.delete("/api/companies/<int:company_id>")
    @admin_required
    def api_companies_delete(company_id: int):
        ok = delete_company(company_id)
        return jsonify({"ok": ok})

    # Auth routes
    @app.get('/login')
    def login():
        return render_template('login.html', error=None, next=request.args.get('next') or '')

    @app.post('/login')
    def login_post():
        username = (request.form.get('username') or (request.json or {}).get('username') or '').strip()
        password = (request.form.get('password') or (request.json or {}).get('password') or '').strip()
        admin_user = os.environ.get('ADMIN_USER', 'admin')
        admin_pass = os.environ.get('ADMIN_PASS', 'admin')
        nxt = request.form.get('next') or (request.json or {}).get('next') or url_for('companies_list')
        if username == admin_user and password == admin_pass:
            session['is_admin'] = True
            session['user'] = username
            return redirect(nxt)
        return render_template('login.html', error='Invalid username or password', next=nxt)

    @app.get('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.get("/assignments")
    def assignments_list():
        rows = fetch_assignments()
        companies = {c.id: c for c in fetch_all()}
        items = []
        for rid, task_name, company_id, created_at, drawing_file in rows:
            c = companies.get(company_id)
            items.append({
                'id': rid,
                'task_name': task_name,
                'company_id': company_id,
                'company_name': c.name if c else f"ID:{company_id}",
                'created_at': created_at,
                'drawing_file': drawing_file,
            })
        files = fetch_assignment_files()
        return render_template("assignments.html", items=items, files=files)

    @app.get("/reports")
    def reports_list():
        # 図面の選択UIを出し、選択された図面の割当一覧を表示
        selected = request.args.get('file') or (app.config.get('last_upload_filename') or '')
        files = [name for (name, _cnt) in fetch_assignment_files()]
        items = []
        companies = {c.id: c for c in fetch_all()}
        if selected:
            rows = fetch_assignments_for_file(selected)
            for rid, task_name, company_id, created_at, drawing_file in rows:
                c = companies.get(company_id)
                items.append({
                    'id': rid,
                    'task_name': task_name,
                    'company_id': company_id,
                    'company_name': c.name if c else f"ID:{company_id}",
                    'created_at': created_at,
                    'drawing_file': drawing_file,
                })
        # last_result からメタを補助的に表示（選択ファイル一致時）
        meta = None
        data = app.config.get('last_result')
        if data:
            features = data.get('features')
            if getattr(features, 'filename', '') == selected:
                steps = data.get('process') or []
                matches = data.get('matches') or []
                top = [{'name': m.company.name, 'score': m.score} for m in (matches[:3] if isinstance(matches, list) else [])]
                meta = {
                    'filename': getattr(features, 'filename', ''),
                    'material': getattr(features, 'material', ''),
                    'part_type': getattr(features, 'part_type', ''),
                    'steps_count': len(steps),
                    'top_matches': top,
                }
        return render_template("reports.html", report=meta, selected_file=selected, files=files, items=items)

    @app.get("/download/docx")
    def download_docx():
        # 選択された図面の割当レポート or 通常レポート
        selected = request.args.get('file') or (app.config.get('last_upload_filename') or '')
        if selected:
            # 割当のみのエクスポート
            companies = {c.id: c for c in fetch_all()}
            rows = fetch_assignments_for_file(selected)
            items = []
            for rid, task_name, company_id, created_at, drawing_file in rows:
                c = companies.get(company_id)
                items.append({
                    'id': rid,
                    'task_name': task_name,
                    'company_id': company_id,
                    'company_name': c.name if c else f"ID:{company_id}",
                    'created_at': created_at,
                    'drawing_file': drawing_file,
                })
            if items:
                docx_bytes = render_assignments_docx(selected, items)
                return send_file(io.BytesIO(docx_bytes), mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document', as_attachment=True, download_name=f'assignments_{selected}.docx')
        # フォールバック：最新解析の通常レポート
        data = app.config.get('last_result')
        if not data:
            return redirect(url_for("index"))
        docx_bytes = render_report_docx(data['features'], data['process'], data['matches'])
        return send_file(io.BytesIO(docx_bytes), mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document', as_attachment=True, download_name=f'cma_report_{getattr(data["features"], "filename", "report")}.docx')

    return app
