import os

from opensteuerauszug.webapp.app import app

if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", 10000))
    host = os.environ.get("HOST", "0.0.0.0")
    serve(app, host=host, port=port)
