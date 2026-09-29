import os

from flask import Flask

from database import init_db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY",
        "gedai-clave-desarrollo",
    )

    from .navegacion import bp

    app.register_blueprint(bp)

    with app.app_context():
        init_db()

    return app
