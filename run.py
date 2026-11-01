import os

from leanmgmt import create_app

app = create_app()

if __name__ == "__main__":
    # 5001, not 5000: macOS AirPlay Receiver occupies 5000 and answers 403 there.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5001")), debug=True)
