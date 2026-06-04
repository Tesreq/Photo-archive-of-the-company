"""
Модуль database.py — SQLAlchemy-модели и инициализация БД
для информационной системы «Фотоархив компании».
"""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Справочник ролей
# ---------------------------------------------------------------------------
class Role(db.Model):
    __tablename__ = "Role"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False, unique=True)

    # обратная связь
    users = db.relationship("User", backref="role", lazy="dynamic")

    def __repr__(self):
        return f"<Role {self.name}>"


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "User"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    login = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("Role.id"), nullable=False)

    # поля для блокировки при неудачных попытках входа
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    # обратные связи
    event_logs = db.relationship("EventLog", backref="user", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.login}>"

    @property
    def is_locked(self):
        """Вернёт True, если учётная запись временно заблокирована."""
        if self.locked_until is None:
            return False
        now = datetime.utcnow()
        # Приводим locked_until к naive UTC, если он aware
        locked = self.locked_until
        if locked.tzinfo is not None:
            locked = locked.replace(tzinfo=None)
        if now < locked:
            return True
        # срок блокировки истёк — сбрасываем
        self.locked_until = None
        self.failed_attempts = 0
        db.session.commit()
        return False


# ---------------------------------------------------------------------------
# Файлы (метаданные + BLOB)
# ---------------------------------------------------------------------------
class File(db.Model):
    __tablename__ = "File"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    original_date = db.Column(db.DateTime, nullable=False)
    upload_date = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.utcnow()
    )
    file_content = db.Column(db.LargeBinary, nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)

    # обратная связь: ключевые слова (many-to-many)
    keywords = db.relationship(
        "Keyword",
        secondary="File_Keyword",
        backref=db.backref("files", lazy="dynamic"),
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<File {self.file_name}>"

    @property
    def extension(self):
        """Расширение файла без точки (например 'pdf', 'jpg')."""
        if "." not in self.file_name:
            return ""
        return self.file_name.rsplit(".", 1)[-1].lower()

    @property
    def icon_name(self):
        """Имя SVG-иконки в static/icons/ для данного типа файла."""
        ext = self.extension
        # Изображения
        if ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff", "tif"):
            return "image.svg"
        # PDF
        if ext == "pdf":
            return "pdf.svg"
        # Word
        if ext in ("doc", "docx"):
            return "docx.svg"
        # Excel
        if ext in ("xls", "xlsx"):
            return "xlsx.svg"
        # По умолчанию
        return "default.svg"


# ---------------------------------------------------------------------------
# Справочник ключевых слов / тегов
# ---------------------------------------------------------------------------
class Keyword(db.Model):
    __tablename__ = "Keyword"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    def __repr__(self):
        return f"<Keyword {self.name}>"


# ---------------------------------------------------------------------------
# Связующая таблица «Файл ↔ Ключевое слово» (Many-to-Many)
# ---------------------------------------------------------------------------
class FileKeyword(db.Model):
    __tablename__ = "File_Keyword"

    file_id = db.Column(
        db.Integer,
        db.ForeignKey("File.id", ondelete="CASCADE"),
        primary_key=True,
    )
    keyword_id = db.Column(
        db.Integer,
        db.ForeignKey("Keyword.id", ondelete="CASCADE"),
        primary_key=True,
    )


# ---------------------------------------------------------------------------
# Журнал событий (аудит)
# ---------------------------------------------------------------------------
class EventLog(db.Model):
    __tablename__ = "Event_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("User.id", ondelete="SET NULL"),
        nullable=True,
    )
    timestamp = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.utcnow()
    )
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<EventLog {self.action}>"
