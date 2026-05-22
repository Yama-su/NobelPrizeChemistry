from flask import Flask, render_template
import json
import os

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "nobel_chemistry_list.json")

try:
    with open(DATA_FILE, encoding="utf-8") as f:
        nobel_list = json.load(f)
except FileNotFoundError:
    raise SystemExit(f"データファイルが見つかりません: {DATA_FILE}")
except json.JSONDecodeError as e:
    raise SystemExit(f"データファイルの JSON が不正です: {e}")

# 年代降順にソートして表示
nobel_list_sorted = sorted(nobel_list, key=lambda x: x["year"], reverse=True)


@app.route("/")
def index():
    return render_template("index.html", nobel_list=nobel_list_sorted)


@app.route("/detail/<int:year>")
def detail(year):
    for entry in nobel_list:
        if entry["year"] == year:
            return render_template("detail.html", entry=entry)
    return "Not Found", 404


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug)
