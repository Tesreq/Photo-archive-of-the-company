from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET', 'dev-secret-key'),
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(BASE_DIR, 'photo_archive.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=os.path.join(BASE_DIR, 'static', 'uploads')
    )

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        db.create_all()

    @app.route('/')
    def index():
        photos = Photo.query.order_by(Photo.created_at.desc()).limit(8).all()
        return render_template('index.html', photos=photos)

    @app.route('/archive')
    def archive():
        photos = Photo.query.order_by(Photo.created_at.desc()).all()
        return render_template('archive.html', photos=photos)

    @app.route('/photo/<int:photo_id>')
    def photo_detail(photo_id):
        photo = Photo.query.get_or_404(photo_id)
        return render_template('photo.html', photo=photo)

    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            author = request.form.get('author', '').strip()
            description = request.form.get('description', '').strip()
            filename = request.form.get('filename', '').strip()

            if not title or not author or not filename:
                flash('Пожалуйста, заполните все обязательные поля.', 'error')
                return redirect(url_for('upload'))

            photo = Photo(
                title=title,
                author=author,
                description=description,
                filename=filename,
                created_at=datetime.utcnow()
            )
            db.session.add(photo)
            db.session.commit()
            flash('Фотография добавлена в архив.', 'success')
            return redirect(url_for('archive'))

        return render_template('upload.html')

    @app.route('/search')
    def search():
        query = request.args.get('q', '').strip()
        photos = []
        if query:
            photos = Photo.query.filter(
                Photo.title.ilike(f'%{query}%') |
                Photo.author.ilike(f'%{query}%') |
                Photo.description.ilike(f'%{query}%')
            ).order_by(Photo.created_at.desc()).all()
        return render_template('search.html', photos=photos, query=query)

    return app


db = SQLAlchemy()
migrate = Migrate()

class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    author = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Photo {self.title} by {self.author}>'


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
