from datetime import datetime
import os

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_SUBDIR = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "pdf", "tiff", "tif"}

db = SQLAlchemy()
migrate = Migrate()


class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    author = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def image_url(self):
        return url_for("static", filename=f"uploads/{self.filename}")

    @property
    def file_extension(self):
        if "." not in self.filename:
            return "img"
        return self.filename.rsplit(".", 1)[-1].lower()

    @property
    def file_badge(self):
        extension = self.file_extension.upper()
        return extension if len(extension) <= 4 else "IMG"

    def __repr__(self):
        return f"<Photo {self.title} by {self.author}>"


def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET", "dev-secret-key"),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE_DIR, "photo_archive.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=os.path.join(BASE_DIR, UPLOAD_SUBDIR),
    )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        db.create_all()

    @app.route("/")
    def index():
        return redirect(url_for("search"))

    @app.route("/archive")
    def archive():
        photos = Photo.query.order_by(Photo.created_at.desc()).all()
        return render_template("archive.html", photos=photos, active_page="search")

    @app.route("/photo/<int:photo_id>")
    def photo_detail(photo_id):
        photo = Photo.query.get_or_404(photo_id)
        return render_template("photo.html", photo=photo)

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            description = request.form.get("description", "").strip()
            filename = request.form.get("filename", "").strip()
            image = request.files.get("image")

            if image and image.filename:
                try:
                    filename = save_uploaded_file(image)
                except ValueError:
                    flash("Поддерживаются только изображения: jpg, jpeg, png, webp, gif.", "error")
                    return redirect(url_for("upload"))

            if not title or not author or not filename:
                flash("Заполните название, автора и добавьте файл или имя файла.", "error")
                return redirect(url_for("upload"))

            photo = Photo(
                title=title,
                author=author,
                description=description,
                filename=filename,
                created_at=datetime.utcnow(),
            )
            db.session.add(photo)
            db.session.commit()
            flash("Файл добавлен в архив.", "success")
            return redirect(url_for("search"))

        return render_template("upload.html", active_page="upload")

    @app.route("/search")
    def search():
        query = request.args.get("q", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        photos_query = Photo.query

        if query:
            photos_query = photos_query.filter(
                Photo.title.ilike(f"%{query}%")
                | Photo.author.ilike(f"%{query}%")
                | Photo.description.ilike(f"%{query}%")
            )

        if date_from:
            parsed_from = parse_date(date_from)
            if parsed_from:
                photos_query = photos_query.filter(Photo.created_at >= parsed_from)
        if date_to:
            parsed_to = parse_date(date_to, end_of_day=True)
            if parsed_to:
                photos_query = photos_query.filter(Photo.created_at <= parsed_to)

        photos = photos_query.order_by(Photo.created_at.desc()).all()
        return render_template(
            "search.html",
            photos=photos,
            query=query,
            date_from=date_from,
            date_to=date_to,
            active_page="search",
        )

    @app.route("/users")
    def users():
        demo_users = [
            {
                "name": "Иванов Иван Иванович",
                "department": "Отдел документации",
                "login": "ivanov",
                "role": "Сотрудник",
                "status": "Активен",
            },
            {
                "name": "Петров Петр Петрович",
                "department": "Архивный отдел",
                "login": "petrov",
                "role": "Архивариус",
                "status": "Заблокирован",
            },
        ]
        return render_template("users.html", users=demo_users, active_page="users")

    return app


def parse_date(value, end_of_day=False):
    try:
        date = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        return date.replace(hour=23, minute=59, second=59)
    return date


def save_uploaded_file(file_storage):
    filename = secure_filename(file_storage.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file extension")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = f"{timestamp}-{filename}"
    file_storage.save(os.path.join(BASE_DIR, UPLOAD_SUBDIR, safe_name))
    return safe_name


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
