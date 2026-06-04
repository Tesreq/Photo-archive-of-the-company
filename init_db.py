"""
Скрипт первичного наполнения БД.
Создаёт справочник ролей и учётную запись администратора по умолчанию.

Запуск:
    python init_db.py
"""

from app import create_app
from database import db, Role, User
from werkzeug.security import generate_password_hash


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # --- Роли ---
        role_names = ["Администратор", "Архивариус", "Сотрудник"]
        for name in role_names:
            exists = Role.query.filter_by(name=name).first()
            if not exists:
                db.session.add(Role(name=name))
        db.session.commit()

        # --- Дефолтный администратор ---
        admin_login = "admin"
        admin_password = "admin"

        if not User.query.filter_by(login=admin_login).first():
            admin_role = Role.query.filter_by(name="Администратор").first()
            admin = User(
                login=admin_login,
                password_hash=generate_password_hash(admin_password),
                is_active=True,
                role_id=admin_role.id,
            )
            db.session.add(admin)
            db.session.commit()
            print(f"[init_db] Создан администратор: login={admin_login}, password={admin_password}")
        else:
            print(f"[init_db] Администратор '{admin_login}' уже существует — пропуск.")

        print("[init_db] Инициализация завершена.")


if __name__ == "__main__":
    seed()
