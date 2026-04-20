# app.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

from flask import Flask, render_template, jsonify, request
import json
import threading
import os
from detector import FlickrDetector
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
detector = FlickrDetector()

scan_thread = None
scan_results = []

def run_scan_in_background(threshold, global_search):
    global scan_results
    try:
        scan_results = detector.find_duplicates(threshold=threshold, global_search=global_search)
    except Exception as e:
        print(f"Scan error: {e}")
        detector.status["message"] = f"Error: {str(e)}"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/duplicates")
def get_duplicates():
    try:
        with open("duplicates.json") as f:
            return jsonify(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify([])

@app.route("/api/scan", methods=["POST"])
def scan_duplicates():
    global scan_thread
    data = request.json
    threshold = data.get("threshold", 5)
    global_search = data.get("global_search", False)
    
    if scan_thread and scan_thread.is_alive():
        return jsonify({"error": "Scan already in progress"}), 400
        
    scan_thread = threading.Thread(target=run_scan_in_background, args=(threshold, global_search))
    scan_thread.start()
    return jsonify({"status": "started"})

@app.route("/api/status")
def get_status():
    status = detector.status.copy()
    status["is_running"] = scan_thread is not None and scan_thread.is_alive()
    return jsonify(status)

@app.route("/api/cancel", methods=["POST"])
def cancel_scan():
    detector.cancel()
    return jsonify({"status": "cancelling"})

@app.route("/api/delete", methods=["POST"])
def delete_photo():
    photo_id = request.json["photo_id"]
    try:
        detector.flickr.photos.delete(photo_id=photo_id)
        return {"status": "ok"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
