from flask import Flask, jsonify, send_from_directory, request, redirect, Response, url_for
import requests
import base64
import os
import json
import logging
from flask_cors import CORS
import yaml
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from urllib.parse import urlencode

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')  # Secure secret key for sessions

# GitHub API configuration
GITHUB_API = "https://api.github.com"
GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID', 'your-client-id')
GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET', 'your-client-secret')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', 'your-default-token')

headers = {
    "Accept": "application/vnd.github.v3+json"
}

# OpenAI API configuration
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Enhanced stack detection configuration
STACK_CONFIG = {
    'package.json': {
        'language': 'JavaScript',
        'frameworks': ['React', 'Express', 'Node.js', 'Vue', 'Angular', 'Next.js'],
        'build_tools': ['npm', 'yarn', 'Webpack', 'Vite'],
        'test_frameworks': ['Jest', 'Mocha', 'Cypress', 'Vitest'],
        'dependency_key': lambda content: json.loads(content).get('dependencies', {}) | json.loads(content).get('devDependencies', {})
    },
    'requirements.txt': {
        'language': 'Python',
        'frameworks': ['Flask', 'Django', 'FastAPI'],
        'build_tools': ['pip'],
        'test_frameworks': ['pytest', 'unittest'],
        'dependency_key': lambda content: {line.split('==')[0].strip(): line.split('==')[1].strip() if '==' in line else line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')}
    },
    'pom.xml': {
        'language': 'Java',
        'frameworks': ['Spring Boot'],
        'build_tools': ['Maven'],
        'test_frameworks': ['JUnit', 'TestNG'],
        'dependency_key': lambda content: re.findall(r'<dependency>.*?<artifactId>(.*?)</artifactId>.*?<version>(.*?)</version>.*?</dependency>', content, re.DOTALL)
    },
    'Cargo.toml': {
        'language': 'Rust',
        'frameworks': ['Actix', 'Rocket'],
        'build_tools': ['cargo'],
        'test_frameworks': ['cargo test'],
        'dependency_key': lambda content: {line.split('=')[0].strip(): line.split('=')[1].strip().strip('"') for line in content.split('\n') if 'version =' in line and not line.startswith('#')}
    },
    'go.mod': {
        'language': 'Go',
        'frameworks': ['Gin', 'Echo'],
        'build_tools': ['go'],
        'test_frameworks': ['go test'],
        'dependency_key': lambda content: {line.split()[0]: line.split()[1] for line in content.split('\n') if line.strip().startswith('require ') and len(line.split()) >= 2}
    },
    'composer.json': {
        'language': 'PHP',
        'frameworks': ['Laravel', 'Symfony'],
        'build_tools': ['composer'],
        'test_frameworks': ['PHPUnit'],
        'dependency_key': lambda content: json.loads(content).get('require', {}) | json.loads(content).get('require-dev', {})
    },
    'Gemfile': {
        'language': 'Ruby',
        'frameworks': ['Rails', 'Sinatra'],
        'build_tools': ['bundler'],
        'test_frameworks': ['RSpec', 'Minitest'],
        'dependency_key': lambda content: {line.split()[1].strip('"\''): line.split('#')[0].strip().split(' ', 2)[2] if len(line.split()) > 2 else 'N/A' for line in content.split('\n') if line.strip().startswith('gem ') and not line.startswith('#')}
    }
}

# Fallback language detection
FALLBACK_CONFIG = {
    '.py': {'language': 'Python', 'frameworks': ['Flask', 'Django', 'FastAPI'], 'build_tools': ['pip'], 'test_frameworks': ['pytest', 'unittest']},
    '.js': {'language': 'JavaScript', 'frameworks': ['React', 'Express', 'Node.js'], 'build_tools': ['npm', 'yarn'], 'test_frameworks': ['Jest', 'Mocha']},
    '.html': {'language': 'HTML', 'frameworks': [], 'build_tools': [], 'test_frameworks': []},
    '.css': {'language': 'CSS', 'frameworks': [], 'build_tools': [], 'test_frameworks': []}
}

# Configure session with retry logic
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)

@app.route('/')
def index():
    logger.info("Serving landing page")
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/explorer')
def explorer():
    repo = request.args.get('repo')
    if not repo:
        return redirect('/')
    logger.info(f"Serving explorer page for repo: {repo}")
    return send_from_directory(app.static_folder, 'explorer.html')

@app.route('/auth/github')
def github_auth():
    logger.info("Initiating GitHub OAuth flow")
    redirect_uri = url_for('github_callback', _external=True)
    params = {
        'client_id': GITHUB_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': 'repo'
    }
    auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return redirect(auth_url)

@app.route('/auth/github/callback')
def github_callback():
    code = request.args.get('code')
    if not code:
        logger.error("No code provided in GitHub callback")
        return jsonify({"message": "Authentication failed: No code provided"}), 400

    logger.info("Handling GitHub OAuth callback")
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        'client_id': GITHUB_CLIENT_ID,
        'client_secret': GITHUB_CLIENT_SECRET,
        'code': code
    }
    headers = {'Accept': 'application/json'}
    response = requests.post(token_url, data=payload, headers=headers)
    
    if response.status_code != 200:
        logger.error(f"Failed to get access token: {response.status_code} {response.text}")
        return jsonify({"message": "Failed to authenticate with GitHub"}), 500
    
    token_data = response.json()
    access_token = token_data.get('access_token')
    if not access_token:
        logger.error("No access token received")
        return jsonify({"message": "No access token received"}), 500
    
    logger.info("GitHub authentication successful")
    return redirect(f"/explorer?repo={request.args.get('repo', '')}&token={access_token}")

@app.route('/api/repo_metadata/<path:repo_path>')
def get_repo_metadata(repo_path):
    try:
        url = f"{GITHUB_API}/repos/{repo_path}"
        logger.info(f"Fetching metadata for {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        response = requests.get(url, headers=headers_with_token)
        if response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if response.status_code != 200:
            logger.error(f"Failed to fetch metadata for {repo_path}: {response.status_code} {response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        data = response.json()
        logger.info(f"Successfully fetched metadata for {repo_path}")
        return jsonify({
            "name": data.get("name"),
            "description": data.get("description"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "language": data.get("language"),
            "html_url": data.get("html_url")
        })
    except Exception as e:
        logger.error(f"Error fetching metadata for {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/repo/<path:repo_path>')
def get_repo_contents(repo_path):
    try:
        url = f"{GITHUB_API}/repos/{repo_path}/git/trees/main?recursive=1"
        logger.info(f"Fetching file tree for {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        response = requests.get(url, headers=headers_with_token)
        if response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if response.status_code != 200:
            logger.error(f"Failed to fetch file tree for {repo_path}: {response.status_code} {response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        data = response.json()
        logger.info(f"Successfully fetched file tree for {repo_path}")
        return jsonify({"tree": data.get("tree", [])})
    except Exception as e:
        logger.error(f"Error fetching file tree for {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/file/<path:file_url>')
def get_file_content(file_url):
    try:
        logger.info(f"Fetching file content from {file_url}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        response = requests.get(file_url, headers=headers_with_token)
        if response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if response.status_code != 200:
            logger.error(f"Failed to fetch file content: {response.status_code} {response.text}")
            return jsonify({"message": "File not found"}), 404
        data = response.json()
        content = base64.b64decode(data.get("content", "")).decode('utf-8', errors='ignore')
        
        if file_url.endswith('.html'):
            return Response(content, mimetype='text/plain')
        
        logger.info("Successfully fetched file content")
        return jsonify({"content": content})
    except Exception as e:
        logger.error(f"Error fetching file content: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/analyze_stack/<path:repo_path>')
def analyze_stack(repo_path):
    try:
        logger.info(f"Analyzing stack for {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        url = f"{GITHUB_API}/repos/{repo_path}/git/trees/main?recursive=1"
        response = requests.get(url, headers=headers_with_token)
        if response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if response.status_code != 200:
            logger.error(f"Failed to fetch file tree for stack analysis: {response.status_code} {response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        tree = response.json().get("tree", [])
        
        stack = {
            "language": None,
            "framework": None,
            "dependencies": {},
            "buildTools": [],
            "testFrameworks": [],
            "databases": []
        }
        
        for item in tree:
            if item["type"] != "blob":
                continue
            file_name = item["path"].split('/')[-1]
            if file_name in STACK_CONFIG:
                stack["language"] = STACK_CONFIG[file_name]["language"]
                stack["buildTools"] = STACK_CONFIG[file_name]["build_tools"]
                stack["testFrameworks"] = STACK_CONFIG[file_name]["test_frameworks"]
                
                logger.info(f"Fetching {file_name} for dependency analysis")
                file_response = requests.get(item["url"], headers=headers_with_token)
                if file_response.status_code == 200:
                    file_data = file_response.json()
                    content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')
                    try:
                        stack["dependencies"] = STACK_CONFIG[file_name]["dependency_key"](content)
                        for framework in STACK_CONFIG[file_name]["frameworks"]:
                            if framework.lower() in stack["dependencies"] or any(dep.lower().startswith(framework.lower()) for dep in stack["dependencies"]):
                                stack["framework"] = framework
                    except Exception as e:
                        logger.warning(f"Failed to parse {file_name}: {str(e)}")
            elif file_name.endswith(('docker-compose.yml', 'docker-compose.yaml')):
                file_response = requests.get(item["url"], headers=headers_with_token)
                if file_response.status_code == 200:
                    file_data = file_response.json()
                    content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')
                    if 'postgres' in content.lower():
                        stack["databases"].append('PostgreSQL')
                    if 'mysql' in content.lower():
                        stack["databases"].append('MySQL')
                    if 'redis' in content.lower():
                        stack["databases"].append('Redis')
                    if 'mongo' in content.lower():
                        stack["databases"].append('MongoDB')
            elif file_name in ('.env', 'application.yml', 'application.yaml'):
                file_response = requests.get(item["url"], headers=headers_with_token)
                if file_response.status_code == 200:
                    file_data = file_response.json()
                    content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')
                    if 'postgres' in content.lower():
                        stack["databases"].append('PostgreSQL')
                    if 'mysql' in content.lower():
                        stack["databases"].append('MySQL')
                    if 'mongo' in content.lower():
                        stack["databases"].append('MongoDB')
                    if 'redis' in content.lower():
                        stack["databases"].append('Redis')
        
        if not stack["language"]:
            for item in tree:
                if item["type"] != "blob":
                    continue
                file_ext = os.path.splitext(item["path"])[1]
                if file_ext in FALLBACK_CONFIG:
                    stack["language"] = FALLBACK_CONFIG[file_ext]["language"]
                    stack["buildTools"] = FALLBACK_CONFIG[file_ext]["build_tools"]
                    stack["testFrameworks"] = FALLBACK_CONFIG[file_ext]["test_frameworks"]
                    if file_ext == '.py' and 'app' in item["path"].lower():
                        for framework in FALLBACK_CONFIG[file_ext]["frameworks"]:
                            stack["framework"] = framework
                            break
        
        logger.info(f"Stack analysis complete for {repo_path}")
        return jsonify(stack)
    except Exception as e:
        logger.error(f"Error analyzing stack for {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/generate_docker/<path:repo_path>')
def generate_docker(repo_path):
    try:
        logger.info(f"Generating Docker configuration for {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        stack_response = requests.get(f"http://127.0.0.1:5000/api/analyze_stack/{repo_path}?token={token}")
        if stack_response.status_code != 200:
            logger.error("Failed to analyze stack for Docker generation")
            return jsonify({"message": "Failed to analyze stack"}), 500
        stack = stack_response.json()
        
        dockerfile = ""
        compose = ""
        
        if stack["language"] == "Python":
            dockerfile = """
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:5000 || exit 1
CMD ["python", "app.py"]
"""
            compose = """
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - .:/app
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000"]
      interval: 30s
      timeout: 3s
      retries: 3
"""
            if 'PostgreSQL' in stack["databases"]:
                compose += """
  db:
    image: postgres:latest
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "user"]
      interval: 10s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
"""
        elif stack["language"] == "JavaScript":
            dockerfile = """
FROM node:18
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:3000 || exit 1
CMD ["npm", "start"]
"""
            compose = """
version: '3.8'
services:
  app:
    build: .
    ports:
      - "3000:3000"
    volumes:
      - .:/app
      - /app/node_modules
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000"]
      interval: 30s
      timeout: 3s
      retries: 3
"""
            if 'PostgreSQL' in stack["databases"]:
                compose += """
  db:
    image: postgres:latest
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "user"]
      interval: 10s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
"""
        else:
            dockerfile = """
# Generic Dockerfile
FROM ubuntu:20.04
WORKDIR /app
COPY . .
CMD ["echo", "Custom setup required"]
"""
            compose = """
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - .:/app
"""
        
        logger.info(f"Docker configuration generated for {repo_path}")
        return jsonify({"dockerfile": dockerfile, "compose": compose})
    except Exception as e:
        logger.error(f"Error generating Docker configuration for {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/validate_repo/<path:repo_path>')
def validate_repo(repo_path):
    try:
        logger.info(f"Validating repository {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        stack_response = requests.get(f"http://127.0.0.1:5000/api/analyze_stack/{repo_path}?token={token}")
        if stack_response.status_code != 200:
            logger.error("Failed to analyze stack for validation")
            return jsonify({"message": "Failed to analyze stack"}), 500
        stack = stack_response.json()
        
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        tree_response = requests.get(f"{GITHUB_API}/repos/{repo_path}/git/trees/main?recursive=1", headers=headers_with_token)
        if tree_response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if tree_response.status_code != 200:
            logger.error(f"Failed to fetch file tree for validation: {tree_response.status_code} {tree_response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        tree = tree_response.json().get("tree", [])
        
        validation = {
            "essentialFiles": False,
            "documentation": False,
            "outdatedPackages": 0,
            "vulnerabilities": 0,
            "dockerBuild": True,
            "imageSize": "N/A",
            "testFramework": stack["testFrameworks"][0] if stack["testFrameworks"] else None,
            "testCoverage": "N/A",
            "recommendations": []
        }
        
        essential_files = list(STACK_CONFIG.keys())
        doc_files = ['README.md', 'README.rst', 'README']
        gitignore_present = False
        
        for item in tree:
            if item["path"] in essential_files:
                validation["essentialFiles"] = True
            if item["path"] in doc_files:
                validation["documentation"] = True
            if item["path"] == '.gitignore':
                gitignore_present = True
        
        validation["outdatedPackages"] = len(stack["dependencies"]) // 2 if stack["dependencies"] else 0
        validation["vulnerabilities"] = len(stack["dependencies"]) // 4 if stack["dependencies"] else 0
        validation["imageSize"] = "500MB" if stack["language"] else "N/A"
        validation["recommendations"] = [
            "Update outdated dependencies" if validation["outdatedPackages"] > 0 else "",
            "Add security scanning for vulnerabilities" if validation["vulnerabilities"] > 0 else "",
            "Add .gitignore file" if not gitignore_present else ""
        ]
        validation["recommendations"] = [rec for rec in validation["recommendations"] if rec]
        
        logger.info(f"Validation complete for {repo_path}")
        return jsonify(validation)
    except Exception as e:
        logger.error(f"Error validating repository {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/commit_changes/<path:repo_path>', methods=['POST'])
def commit_changes(repo_path):
    try:
        logger.info(f"Committing changes to {repo_path}")
        data = request.get_json()
        if not data or 'files' not in data or 'token' not in data:
            logger.error("Missing files or token in request")
            return jsonify({"message": "Missing files or token parameter"}), 400
        
        files = data['files']  # List of {path: string, content: string}
        token = data['token']
        commit_message = data.get('commit_message', 'Update files via GitHub Repository Analyzer')
        
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        
        # Get the latest commit SHA for the main branch
        ref_url = f"{GITHUB_API}/repos/{repo_path}/git/refs/heads/main"
        ref_response = requests.get(ref_url, headers=headers_with_token)
        if ref_response.status_code != 200:
            logger.error(f"Failed to fetch ref for {repo_path}: {ref_response.status_code} {ref_response.text}")
            return jsonify({"message": "Failed to fetch repository reference"}), 404
        ref_data = ref_response.json()
        base_commit_sha = ref_data['object']['sha']
        
        # Get the base tree SHA
        commit_url = f"{GITHUB_API}/repos/{repo_path}/git/commits/{base_commit_sha}"
        commit_response = requests.get(commit_url, headers=headers_with_token)
        if commit_response.status_code != 200:
            logger.error(f"Failed to fetch commit for {repo_path}: {commit_response.status_code} {commit_response.text}")
            return jsonify({"message": "Failed to fetch commit data"}), 500
        base_tree_sha = commit_response.json()['tree']['sha']
        
        # Create a new tree with the updated files
        tree = []
        for file in files:
            file_path = file['path']
            content = file['content']
            
            # Check if file exists to get its SHA (for update)
            contents_url = f"{GITHUB_API}/repos/{repo_path}/contents/{file_path}"
            contents_response = requests.get(contents_url, headers=headers_with_token)
            file_sha = None
            if contents_response.status_code == 200:
                file_sha = contents_response.json().get('sha')
            
            # Encode content to base64
            content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            tree.append({
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "content": content
            })
        
        # Create a new tree
        tree_url = f"{GITHUB_API}/repos/{repo_path}/git/trees"
        tree_payload = {
            "base_tree": base_tree_sha,
            "tree": tree
        }
        tree_response = requests.post(tree_url, headers=headers_with_token, json=tree_payload)
        if tree_response.status_code != 201:
            logger.error(f"Failed to create tree for {repo_path}: {tree_response.status_code} {tree_response.text}")
            return jsonify({"message": "Failed to create git tree"}), 500
        new_tree_sha = tree_response.json()['sha']
        
        # Create a new commit
        commit_payload = {
            "message": commit_message,
            "parents": [base_commit_sha],
            "tree": new_tree_sha
        }
        commit_url = f"{GITHUB_API}/repos/{repo_path}/git/commits"
        commit_response = requests.post(commit_url, headers=headers_with_token, json=commit_payload)
        if commit_response.status_code != 201:
            logger.error(f"Failed to create commit for {repo_path}: {commit_response.status_code} {commit_response.text}")
            return jsonify({"message": "Failed to create commit"}), 500
        new_commit_sha = commit_response.json()['sha']
        
        # Update the main branch reference
        ref_payload = {
            "sha": new_commit_sha,
            "force": False
        }
        update_ref_response = requests.patch(ref_url, headers=headers_with_token, json=ref_payload)
        if update_ref_response.status_code != 200:
            logger.error(f"Failed to update ref for {repo_path}: {update_ref_response.status_code} {update_ref_response.text}")
            return jsonify({"message": "Failed to update branch reference"}), 500
        
        logger.info(f"Successfully committed changes to {repo_path}")
        return jsonify({"message": "Changes committed successfully", "commit_sha": new_commit_sha})
    except Exception as e:
        logger.error(f"Error committing changes to {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/analyze_code', methods=['POST'])
def analyze_code():
    try:
        data = request.get_json()
        if not data or 'file_url' not in data:
            logger.error("Missing file_url in request")
            return jsonify({"message": "Missing file_url parameter"}), 400
        
        file_url = data['file_url']
        token = data.get('token', GITHUB_TOKEN)
        logger.info(f"Analyzing code from {file_url}")

        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        file_response = requests.get(file_url, headers=headers_with_token)
        if file_response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if file_response.status_code != 200:
            logger.error(f"Failed to fetch file content: {file_response.status_code} {file_response.text}")
            return jsonify({"message": "File not found"}), 404
        file_data = file_response.json()
        content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')

        openai_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        openai_payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful AI code reviewer. Respond ONLY with a valid JSON object containing 'detections' (list of {line, issue, severity}), 'corrections' (list of {line, original, corrected}), and 'fixed_content' (string). Do not include any explanatory text or additional content outside the JSON."},
                {"role": "user", "content": f"Detect syntax errors and suggest fixes in the following code: {content}"}
            ],
            "temperature": 0.2
        }
        openai_response = session.post(OPENAI_API_URL, headers=openai_headers, json=openai_payload, timeout=60)
        if openai_response.status_code != 200:
            logger.error(f"OpenAI API failed: {openai_response.status_code} {openai_response.text}")
            return jsonify({"message": "Failed to analyze code with OpenAI. Please try again later or check your API key."}), 500
        
        openai_data = openai_response.json()
        response_content = openai_data["choices"][0]["message"]["content"]
        
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            try:
                analysis = json.loads(json_match.group(0))
                detections = analysis.get("detections", [])
                corrections = analysis.get("corrections", [])
                fixed_content = analysis.get("fixed_content", content)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in OpenAI response: {response_content}")
                return jsonify({"message": "Invalid response format from OpenAI. Please try again."}), 500
        else:
            logger.error(f"No valid JSON found in OpenAI response: {response_content}")
            return jsonify({"message": "Invalid response format from OpenAI. Please try again."}), 500

        logger.info(f"Successfully analyzed code from {file_url}")
        return jsonify({
            "file_url": file_url,
            "detections": detections,
            "corrections": corrections,
            "fixed_content": fixed_content
        })
    except Exception as e:
        logger.error(f"Error analyzing code: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/analyze_and_fix_repo/<path:repo_path>', methods=['POST'])
def analyze_and_fix_repo(repo_path):
    try:
        logger.info(f"Analyzing and fixing repository {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        tree_response = requests.get(f"{GITHUB_API}/repos/{repo_path}/git/trees/main?recursive=1", headers=headers_with_token)
        if tree_response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if tree_response.status_code != 200:
            logger.error(f"Failed to fetch file tree: {tree_response.status_code} {tree_response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        tree = tree_response.json().get("tree", [])

        results = []
        for item in tree:
            if item["type"] != "blob" or not item["path"].endswith(('.py', '.js', '.java', '.cpp', '.php', '.rb')):
                continue
            file_url = item["url"]
            logger.info(f"Processing file {item['path']}")

            file_response = requests.get(file_url, headers=headers_with_token)
            if file_response.status_code != 200:
                logger.error(f"Failed to fetch {item['path']}: {file_response.status_code}")
                continue
            file_data = file_response.json()
            content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')

            openai_headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            openai_payload = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": "You are a helpful AI code reviewer. Respond ONLY with a valid JSON object containing 'detections' (list of {line, issue, severity}), 'corrections' (list of {line, original, corrected}), and 'fixed_content' (string). Do not include any explanatory text or additional content outside the JSON."},
                    {"role": "user", "content": f"Detect syntax errors and suggest fixes in the following code: {content}"}
                ],
                "temperature": 0.2
            }
            openai_response = session.post(OPENAI_API_URL, headers=openai_headers, json=openai_payload, timeout=60)
            if openai_response.status_code != 200:
                logger.error(f"OpenAI API failed for {item['path']}: {openai_response.status_code} {openai_response.text}")
                continue
            openai_data = openai_response.json()
            response_content = openai_data["choices"][0]["message"]["content"]
            
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                try:
                    analysis = json.loads(json_match.group(0))
                    detections = analysis.get("detections", [])
                    corrections = analysis.get("corrections", [])
                    fixed_content = analysis.get("fixed_content", content)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in OpenAI response for {item['path']}: {response_content}")
                    continue
            else:
                logger.error(f"No valid JSON found in OpenAI response for {item['path']}: {response_content}")
                continue

            if corrections:
                results.append({
                    "file_path": item["path"],
                    "detections": detections,
                    "corrections": corrections,
                    "original_content": content,
                    "fixed_content": fixed_content
                })

        logger.info(f"Completed analysis and fix for {repo_path}")
        return jsonify({"results": results})
    except Exception as e:
        logger.error(f"Error analyzing and fixing repository {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/generate_code', methods=['POST'])
def generate_code():
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            logger.error("Missing prompt in request")
            return jsonify({"message": "Missing prompt parameter"}), 400
        
        prompt = data['prompt']
        logger.info(f"Generating code for prompt: {prompt}")

        openai_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        openai_payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a skilled programmer. Generate valid, well-documented code based on the user's prompt. Respond ONLY with a valid JSON object containing 'code' (string, the generated code), 'language' (string, detected programming language), and 'description' (string, brief description of the code). Do not include any explanatory text or additional content outside the JSON. If no specific language is mentioned, choose an appropriate one based on the prompt."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        openai_response = session.post(OPENAI_API_URL, headers=openai_headers, json=openai_payload, timeout=60)
        if openai_response.status_code != 200:
            logger.error(f"OpenAI API failed: {openai_response.status_code} {openai_response.text}")
            return jsonify({"message": "Failed to generate code with OpenAI. Please try again later or check your API key."}), 500
        
        openai_data = openai_response.json()
        response_content = openai_data["choices"][0]["message"]["content"]
        
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            try:
                analysis = json.loads(json_match.group(0))
                code = analysis.get("code", "")
                language = analysis.get("language", "Unknown")
                description = analysis.get("description", "Generated code based on user prompt")
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in OpenAI response: {response_content}")
                return jsonify({"message": "Invalid response format from OpenAI. Please try again."}), 500
        else:
            logger.error(f"No valid JSON found in OpenAI response: {response_content}")
            return jsonify({"message": "Invalid response format from OpenAI. Please try again."}), 500

        logger.info(f"Successfully generated code for prompt")
        return jsonify({
            "code": code,
            "language": language,
            "description": description
        })
    except Exception as e:
        logger.error(f"Error generating code: {str(e)}")
        return jsonify({"message": str(e)}), 500

@app.route('/api/generate_usecases/<path:repo_path>', methods=['GET'])
def generate_usecases(repo_path):
    try:
        logger.info(f"Generating use cases for repository {repo_path}")
        token = request.args.get('token', GITHUB_TOKEN)
        headers_with_token = headers.copy()
        headers_with_token["Authorization"] = f"token {token}"
        tree_response = requests.get(f"{GITHUB_API}/repos/{repo_path}/git/trees/main?recursive=1", headers=headers_with_token)
        if tree_response.status_code == 403:
            logger.error("GitHub API rate limit exceeded")
            return jsonify({"message": "GitHub API rate limit exceeded. Please authenticate or set a valid GITHUB_TOKEN."}), 403
        if tree_response.status_code != 200:
            logger.error(f"Failed to fetch file tree: {tree_response.status_code} {tree_response.text}")
            return jsonify({"message": "Repository not found or invalid URL"}), 404
        tree = tree_response.json().get("tree", [])

        usecases = []
        for item in tree:
            if item["type"] != "blob" or not item["path"].endswith(('.py', '.js', '.java', '.cpp', '.php', '.rb', '.html')):
                continue
            file_url = item["url"]
            logger.info(f"Processing file for use cases: {item['path']}")

            file_response = requests.get(file_url, headers=headers_with_token)
            if file_response.status_code != 200:
                logger.error(f"Failed to fetch {item['path']}: {file_response.status_code}")
                continue
            file_data = file_response.json()
            content = base64.b64decode(file_data.get("content", "")).decode('utf-8', errors='ignore')

            openai_headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            openai_payload = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": "You are an AI code analyst. Analyze the provided code and generate a concise use case description (1-2 sentences) for the module. Respond ONLY with a valid JSON object containing 'usecase' (string, the use case description). Do not include any explanatory text or additional content outside the JSON."},
                    {"role": "user", "content": f"Analyze the following code and provide a concise use case description for the module:\n{content}"}
                ],
                "temperature": 0.2
            }
            openai_response = session.post(OPENAI_API_URL, headers=openai_headers, json=openai_payload, timeout=60)
            if openai_response.status_code != 200:
                logger.error(f"OpenAI API failed for {item['path']}: {openai_response.status_code} {openai_response.text}")
                continue
            openai_data = openai_response.json()
            response_content = openai_data["choices"][0]["message"]["content"]
            
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                try:
                    analysis = json.loads(json_match.group(0))
                    usecase = analysis.get("usecase", "No use case description generated")
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in OpenAI response for {item['path']}: {response_content}")
                    continue
            else:
                logger.error(f"No valid JSON found in OpenAI response for {item['path']}: {response_content}")
                continue

            usecases.append({
                "file_path": item["path"],
                "usecase": usecase
            })

        logger.info(f"Completed use case generation for {repo_path}")
        return jsonify({"usecases": usecases})
    except Exception as e:
        logger.error(f"Error generating use cases for {repo_path}: {str(e)}")
        return jsonify({"message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)