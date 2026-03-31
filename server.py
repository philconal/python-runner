from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route("/run", methods=["POST"])
def run():
    data = request.get_json(silent=True) or {}
    script = data.get("script")
    args = data.get("args", [])

    if not script:
        return jsonify({
            "stdout": "",
            "stderr": "Missing required field: script",
            "code": 1
        }), 400

    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return jsonify({
            "stdout": "",
            "stderr": "Field 'args' must be a list of strings",
            "code": 1
        }), 400

    result = subprocess.run(
        ["python", script, *args],
        capture_output=True,
        text=True
    )
    return jsonify({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "code": result.returncode
    })

app.run(host="0.0.0.0", port=5000)