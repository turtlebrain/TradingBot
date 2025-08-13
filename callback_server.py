from flask import Flask, request

app = Flask(__name__)

@app.route("/callback")
def callback():
    # Questrade redirects here with ?code=...
    code = request.args.get("code")
    return f"<h1>Authorization code:</h1><p>{code}</p>"

if __name__ == "__main__":
    # Listen on 0.0.0.0 so ngrok/tunnel can reach it
    app.run(host="0.0.0.0", port=8000, debug=True)