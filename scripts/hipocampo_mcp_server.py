from flask import Flask, request, jsonify
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Missing 'query' parameter"}), 400
    try:
        result = subprocess.run(
            [
                "/home/alex/.gemini/mcp_venv/bin/python3",
                "/home/alex/.gemini/scripts/hipocampo_search.py",
                query
            ],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Search successful for query: {query}")
        return jsonify({"output": result.stdout})
    except subprocess.CalledProcessError as e:
        logger.error(f"Error: {e.stderr}")
        return jsonify({"error": e.stderr}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001, debug=False)
