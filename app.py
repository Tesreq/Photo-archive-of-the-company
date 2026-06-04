"""
app.py — Flask-приложение «Фотоархив компании».

Архитектура: монолит, Jinja2-шаблоны + fetch API для действий.
Хранилище: SQLite (BLOB).
Аутентификация: сессии (flask.session).
"""

import mimetypes
import os
from datetime import datetime, timedelta

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import db, Role, User, File, Keyword, FileKeyword, EventLog

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PER_PAGE = 10  # записей на страницу
MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION_MINUTES = 5

# MIME-типы, которые система принимает
ALLOWED_MIME_PREFIXES = ("image/", "application/pdf")


# ---------------------------------------------------------------------------
# Фабрика приложения
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET", "dev-secret-key-change-in-prod"),
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + os.path.join(BASE_DIR, "photo_archive.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    db.init_app(app)

    # =======================================================================
    # Декораторы / помощники
    # =======================================================================

    def login_required(f):
        """Перенаправляет неавторизованных на страницу входа."""
        from functools import wraps

        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login_page"))
            return f(*args, **kwargs)

        return wrapper

    def role_required(*role_names):
        """Проверяет, что текущий пользователь имеет одну из указанных ролей."""
        from functools import wraps

        def decorator(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                if "user_id" not in session:
                    return redirect(url_for("login_page"))
                if session.get("role_name") not in role_names:
                    flash("У вас нет прав для выполнения этого действия.", "error")
                    return redirect(url_for("search"))
                return f(*args, **kwargs)

            return wrapper

        return decorator

    def api_login_required(f):
        """Для API-эндпоинтов: возвращает 401 вместо редиректа."""
        from functools import wraps

        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return jsonify({"error": "Необходима авторизация"}), 401
            return f(*args, **kwargs)

        return wrapper

    def api_role_required(*role_names):
        """Для API-эндпоинтов: возвращает 403 вместо редиректа."""
        from functools import wraps

        def decorator(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                if "user_id" not in session:
                    return jsonify({"error": "Необходима авторизация"}), 401
                if session.get("role_name") not in role_names:
                    return jsonify({"error": "Недостаточно прав"}), 403
                return f(*args, **kwargs)

            return wrapper

        return decorator

    def log_event(action: str, details: str = None):
        """Записывает событие в EventLog."""
        user_id = session.get("user_id")
        entry = EventLog(
            user_id=user_id,
            timestamp=datetime.utcnow(),
            action=action,
            details=details,
        )
        db.session.add(entry)
        db.session.commit()

    # Сделаем текущего пользователя доступным во всех шаблонах
    @app.context_processor
    def inject_user():
        user = None
        if "user_id" in session:
            user = User.query.get(session["user_id"])
        return dict(current_user=user)

    # =======================================================================
    # Страницы (Jinja2)
    # =======================================================================

    @app.route("/")
    def index():
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return redirect(url_for("search"))

    # ----- Вход -----
    @app.route("/login", methods=["GET"])
    def login_page():
        if "user_id" in session:
            return redirect(url_for("search"))
        return render_template("login.html")

    # ----- Поиск -----
    @app.route("/search")
    @login_required
    def search():
        page = request.args.get("page", 1, type=int)
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()
        keywords_str = request.args.get("keywords", "").strip()

        query = File.query

        # Фильтр по интервалу дат (original_date)
        if start_date:
            try:
                sd = datetime.strptime(start_date, "%Y-%m-%d")
                query = query.filter(File.original_date >= sd)
            except ValueError:
                pass
        if end_date:
            try:
                ed = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
                query = query.filter(File.original_date <= ed)
            except ValueError:
                pass

        # Фильтр по ключевым словам (OR)
        matched_file_ids = None
        search_keywords = []
        if keywords_str:
            search_keywords = [
                kw.strip().lower() for kw in keywords_str.split(",") if kw.strip()
            ]
            if search_keywords:
                # Находим keyword_id, которые частично совпадают
                keyword_filters = [
                    Keyword.name.ilike(f"%{kw}%") for kw in search_keywords
                ]
                from sqlalchemy import or_

                matching_keywords = Keyword.query.filter(or_(*keyword_filters)).all()
                if matching_keywords:
                    matching_ids = [k.id for k in matching_keywords]
                    file_ids_sub = (
                        db.session.query(FileKeyword.file_id)
                        .filter(FileKeyword.keyword_id.in_(matching_ids))
                        .distinct()
                        .subquery()
                    )
                    from sqlalchemy import select
                    query = query.filter(
                        File.id.in_(select(file_ids_sub.c.file_id))
                    )
                    matched_file_ids_raw = (
                        db.session.query(FileKeyword.file_id, FileKeyword.keyword_id)
                        .filter(FileKeyword.keyword_id.in_(matching_ids))
                        .all()
                    )
                    # Словарь file_id -> [keyword_name, ...]
                    matched_map: dict[int, list[str]] = {}
                    kw_by_id = {k.id: k.name for k in matching_keywords}
                    for fid, kid in matched_file_ids_raw:
                        matched_map.setdefault(fid, []).append(kw_by_id.get(kid, ""))
                else:
                    # Нет совпадений по тегам — пустой результат
                    query = query.filter(File.id == -1)
                    matched_map = {}
            else:
                matched_map = {}
        else:
            matched_map = {}

        total = query.count()
        files = (
            query.order_by(File.original_date.desc())
            .offset((page - 1) * PER_PAGE)
            .limit(PER_PAGE)
            .all()
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        # Для каждого файла собираем совпавшие ключевые слова
        file_data = []
        for f in files:
            all_kw = [kw.name for kw in f.keywords]
            matched_kw = matched_map.get(f.id, [])
            file_data.append(
                {
                    "file": f,
                    "all_keywords": all_kw,
                    "matched_keywords": matched_kw,
                }
            )

        return render_template(
            "search.html",
            file_data=file_data,
            page=page,
            total_pages=total_pages,
            total=total,
            start_date=start_date,
            end_date=end_date,
            keywords_str=keywords_str,
        )

    # ----- Детальная карточка файла -----
    @app.route("/files/<int:file_id>")
    @login_required
    def file_detail(file_id):
        f = File.query.get_or_404(file_id)
        all_kw = [kw.name for kw in f.keywords]
        return render_template("file_detail.html", file=f, all_keywords=all_kw)

    # ----- Загрузка файла -----
    @app.route("/upload", methods=["GET", "POST"])
    @role_required("Администратор", "Архивариус")
    def upload():
        if request.method == "POST":
            uploaded = request.files.get("file")
            description = request.form.get("description", "").strip()
            original_date_str = request.form.get("original_date", "").strip()
            keywords_str = request.form.get("keywords", "").strip()

            # Валидация
            if not uploaded or not uploaded.filename:
                flash("Необходимо выбрать файл.", "error")
                return redirect(url_for("upload"))

            if not original_date_str:
                flash("Укажите дату оригинала.", "error")
                return redirect(url_for("upload"))

            try:
                original_date = datetime.strptime(original_date_str, "%Y-%m-%d")
            except ValueError:
                flash("Неверный формат даты.", "error")
                return redirect(url_for("upload"))

            # Читаем бинарное содержимое
            file_content = uploaded.read()
            file_size = len(file_content)
            if file_size == 0:
                flash("Файл пуст.", "error")
                return redirect(url_for("upload"))

            filename = secure_filename(uploaded.filename)
            mime_type = uploaded.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"

            # Создаём запись File
            new_file = File(
                file_name=filename,
                description=description or None,
                original_date=original_date,
                upload_date=datetime.utcnow(),
                file_content=file_content,
                file_size=file_size,
                mime_type=mime_type,
            )
            db.session.add(new_file)
            db.session.flush()  # нужен id

            # Ключевые слова
            if keywords_str:
                kw_list = [kw.strip() for kw in keywords_str.split(",") if kw.strip()]
                for kw_name in kw_list:
                    keyword_obj = Keyword.query.filter_by(name=kw_name.lower()).first()
                    if not keyword_obj:
                        keyword_obj = Keyword(name=kw_name.lower())
                        db.session.add(keyword_obj)
                        db.session.flush()
                    # Проверяем, нет ли уже связи
                    exists = FileKeyword.query.filter_by(
                        file_id=new_file.id, keyword_id=keyword_obj.id
                    ).first()
                    if not exists:
                        db.session.add(
                            FileKeyword(file_id=new_file.id, keyword_id=keyword_obj.id)
                        )

            db.session.commit()
            log_event("UPLOAD_FILE", f"file_id={new_file.id}, name={filename}")
            flash("Файл успешно добавлен в архив.", "success")
            return redirect(url_for("search"))

        return render_template("upload.html")

    # ----- Редактирование метаданных -----
    @app.route("/files/<int:file_id>/edit", methods=["GET", "POST"])
    @role_required("Администратор", "Архивариус")
    def file_edit(file_id):
        f = File.query.get_or_404(file_id)
        if request.method == "POST":
            description = request.form.get("description", "").strip()
            original_date_str = request.form.get("original_date", "").strip()
            keywords_str = request.form.get("keywords", "").strip()

            if original_date_str:
                try:
                    f.original_date = datetime.strptime(original_date_str, "%Y-%m-%d")
                except ValueError:
                    flash("Неверный формат даты.", "error")
                    return redirect(url_for("file_edit", file_id=file_id))

            f.description = description or None

            # Обновляем ключевые слова: удаляем старые, добавляем новые
            FileKeyword.query.filter_by(file_id=f.id).delete()
            if keywords_str:
                kw_list = [kw.strip() for kw in keywords_str.split(",") if kw.strip()]
                for kw_name in kw_list:
                    keyword_obj = Keyword.query.filter_by(name=kw_name.lower()).first()
                    if not keyword_obj:
                        keyword_obj = Keyword(name=kw_name.lower())
                        db.session.add(keyword_obj)
                        db.session.flush()
                    db.session.add(
                        FileKeyword(file_id=f.id, keyword_id=keyword_obj.id)
                    )

            db.session.commit()
            log_event("EDIT_FILE", f"file_id={f.id}")
            flash("Метаданные обновлены.", "success")
            return redirect(url_for("file_detail", file_id=f.id))

        all_kw = [kw.name for kw in f.keywords]
        return render_template("file_edit.html", file=f, all_keywords=all_kw)

    # ----- Управление пользователями -----
    @app.route("/users")
    @role_required("Администратор")
    def users():
        page = request.args.get("page", 1, type=int)
        login_filter = request.args.get("login", "").strip()
        role_filter = request.args.get("role", "").strip()
        status_filter = request.args.get("status", "").strip()

        query = User.query.join(Role)

        if login_filter:
            query = query.filter(User.login.ilike(f"%{login_filter}%"))
        if role_filter:
            query = query.filter(Role.name == role_filter)
        if status_filter == "Активен":
            query = query.filter(User.is_active == True)
        elif status_filter == "Заблокирован":
            query = query.filter(User.is_active == False)

        total = query.count()
        users_list = (
            query.order_by(User.id)
            .offset((page - 1) * PER_PAGE)
            .limit(PER_PAGE)
            .all()
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        roles = Role.query.order_by(Role.id).all()

        return render_template(
            "users.html",
            users=users_list,
            roles=roles,
            page=page,
            total_pages=total_pages,
            total=total,
            login_filter=login_filter,
            role_filter=role_filter,
            status_filter=status_filter,
        )

    # ----- Логи событий -----
    @app.route("/logs")
    @role_required("Администратор")
    def logs():
        page = request.args.get("page", 1, type=int)
        total = EventLog.query.count()
        entries = (
            EventLog.query.order_by(EventLog.timestamp.desc())
            .offset((page - 1) * PER_PAGE)
            .limit(PER_PAGE)
            .all()
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        return render_template(
            "logs.html",
            entries=entries,
            page=page,
            total_pages=total_pages,
            total=total,
        )

    # =======================================================================
    # API-эндпоинты (JSON, вызываются через fetch из JavaScript)
    # =======================================================================

    # ----- Аутентификация -----
    @app.route("/api/auth/login", methods=["POST"])
    def api_login():
        login = request.form.get("login", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(login=login).first()

        # Проверка блокировки
        if user and user.is_locked:
            locked = user.locked_until.replace(tzinfo=None) if user.locked_until.tzinfo else user.locked_until
            remaining = (locked - datetime.utcnow()).seconds // 60 + 1
            return jsonify(
                {"error": f"Учётная запись заблокирована. Попробуйте через {remaining} мин."}
            ), 403

        # Проверка пароля
        if not user or not check_password_hash(user.password_hash, password):
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    user.locked_until = datetime.utcnow() + timedelta(
                        minutes=LOCK_DURATION_MINUTES
                    )
                    db.session.commit()
                    return jsonify(
                        {"error": f"Превышен лимит попыток. Блокировка на {LOCK_DURATION_MINUTES} мин."}
                    ), 403
                db.session.commit()
            return jsonify({"error": "Неверный логин или пароль"}), 401

        # Проверка is_active
        if not user.is_active:
            return jsonify({"error": "Учётная запись отключена. Обратитесь к администратору."}), 403

        # Успешный вход
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()

        session["user_id"] = user.id
        session["role_name"] = user.role.name
        session["login"] = user.login

        log_event("LOGIN", f"login={login}")
        return jsonify({"role": user.role.name})

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():
        log_event("LOGOUT", f"login={session.get('login')}")
        session.clear()
        return jsonify({"ok": True})

    # ----- Скачивание файла -----
    @app.route("/api/files/download/<int:file_id>")
    @api_login_required
    def api_download(file_id):
        f = File.query.get_or_404(file_id)
        from io import BytesIO

        return send_file(
            BytesIO(f.file_content),
            mimetype=f.mime_type,
            as_attachment=True,
            download_name=f.file_name,
        )

    # ----- Удаление файла -----
    @app.route("/api/files/delete/<int:file_id>", methods=["DELETE"])
    @api_role_required("Администратор")
    def api_delete_file(file_id):
        f = File.query.get_or_404(file_id)
        # ON DELETE CASCADE в FileKeyword удалит связи автоматически
        # Но сначала логируем
        log_event("DELETE_FILE", f"file_id={f.id}, name={f.file_name}")
        db.session.delete(f)
        db.session.commit()
        return jsonify({"ok": True})

    # ----- Смена роли пользователя -----
    @app.route("/api/admin/users/<int:user_id>/role", methods=["PUT"])
    @api_role_required("Администратор")
    def api_change_role(user_id):
        target = User.query.get_or_404(user_id)
        data = request.get_json(force=True)
        new_role_name = data.get("role", "").strip()

        role_obj = Role.query.filter_by(name=new_role_name).first()
        if not role_obj:
            return jsonify({"error": f"Роль '{new_role_name}' не найдена"}), 400

        # Защита: нельзя менять роль, если это единственный администратор
        if target.role.name == "Администратор" and new_role_name != "Администратор":
            admin_count = User.query.join(Role).filter(Role.name == "Администратор", User.is_active == True).count()
            if admin_count <= 1:
                return jsonify({"error": "Нельзя изменить роль единственного администратора"}), 400

        old_role = target.role.name
        target.role_id = role_obj.id
        db.session.commit()

        # Если меняем самому себе — обновляем сессию
        if target.id == session.get("user_id"):
            session["role_name"] = new_role_name

        log_event("CHANGE_ROLE", f"user_id={target.id}, {old_role} -> {new_role_name}")
        return jsonify({"ok": True, "new_role": new_role_name})

    # ----- Блокировка / разблокировка пользователя -----
    @app.route("/api/admin/users/<int:user_id>/status", methods=["PUT"])
    @api_role_required("Администратор")
    def api_change_status(user_id):
        target = User.query.get_or_404(user_id)
        data = request.get_json(force=True)
        is_active = data.get("is_active")

        if is_active is None:
            return jsonify({"error": "Поле is_active обязательно"}), 400

        # Защита: нельзя заблокировать единственного администратора
        if not is_active and target.role.name == "Администратор":
            admin_count = User.query.join(Role).filter(Role.name == "Администратор", User.is_active == True).count()
            if admin_count <= 1:
                return jsonify({"error": "Нельзя заблокировать единственного администратора"}), 400

        target.is_active = bool(is_active)
        db.session.commit()

        action = "UNBLOCK_USER" if is_active else "BLOCK_USER"
        log_event(action, f"user_id={target.id}, login={target.login}")
        return jsonify({"ok": True, "is_active": target.is_active})

    # ----- Логи (API) -----
    @app.route("/api/admin/logs")
    @api_role_required("Администратор")
    def api_logs():
        page = request.args.get("page", 1, type=int)
        total = EventLog.query.count()
        entries = (
            EventLog.query.order_by(EventLog.timestamp.desc())
            .offset((page - 1) * PER_PAGE)
            .limit(PER_PAGE)
            .all()
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        result = []
        for e in entries:
            result.append(
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "login": e.user.login if e.user else None,
                    "timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "action": e.action,
                    "details": e.details,
                }
            )
        return jsonify({"entries": result, "page": page, "total_pages": total_pages, "total": total})

    # =======================================================================
    # Запуск
    # =======================================================================
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
