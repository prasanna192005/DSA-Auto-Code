import os
import subprocess
import json
import random
import re
import shutil
import csv
from datetime import datetime
from threading import Lock
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
import backoff
from collections import Counter
from config import BELT_SYLLABUS, REPO_URL  # Defined in config.py

# --- SETUP ---
load_dotenv()
app = Flask(__name__)

# Configure Gemini API
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found in .env file")
    exit(1)
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.0-flash')

SCHEDULED_JOBS_FILE = "scheduled_jobs.json"
REPOS_DIR = "repositories"
HISTORY_FILE = "generation_history.json"
LOG_CSV_FILE = "dsa_dojo_log.csv"
DEBUG_LOG_FILE = "qc_debug_log.txt"  # For debugging QC score issues
csv_lock = Lock()
os.makedirs(REPOS_DIR, exist_ok=True)

belt_map = {
    'White': 'White Belt', 'Yellow': 'Yellow Belt', 'Orange': 'Orange Belt',
    'Red': 'Red Belt', 'Green': 'Green Belt', 'Blue': 'Blue Belt', 'Purple': 'Purple Belt'
}

# --- DEBUG LOGGING ---
def log_debug(message):
    with open(DEBUG_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now()}] {message}\n")
    print(message)

# --- CSV LOGGER ---
def log_to_csv(row_data):
    with csv_lock:
        file_exists = os.path.isfile(LOG_CSV_FILE)
        with open(LOG_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if not file_exists:
                headers = [
                    "ID", "Category", "Concepts", "Question", "Constraints",
                    "Sample Input", "Sample Output", "Test Cases", "Solution_C",
                    "Solution_Python", "Solution_Java", "Solution_Javascript", "Solution_C++", "QC_Score"
                ]
                writer.writerow(headers)
            writer.writerow(row_data)
        log_debug(f"Logged to CSV: {row_data[0]}")

def extract_raw_data(title, readme_md, solution_md, topic, test_cases):
    def parse_section(text, start_heading, end_headings):
        pattern = re.escape(start_heading) + r'(.*?)(?=' + '|'.join(re.escape(h) for h in end_headings) + r'|$)' if end_headings else re.escape(start_heading) + r'(.*)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def parse_code(text, lang_heading):
        pattern = re.escape(lang_heading) + r'\s*```(?:[a-zA-Z\+\#]+)?\s*\n(.*?)\n\s*```'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else "Not provided"

    readme_headings = ['### Description', '### Constraints', '### Example', '### Concepts Covered']
    approach = parse_section(solution_md, '### Approach', ['## C Solution'])
    sol_headings = ['## C Solution', '## C++ Solution', '## Java Solution', '## Python Solution', '## JavaScript Solution']
    sol_c = parse_code(solution_md, sol_headings[0])
    sol_cpp = parse_code(solution_md, sol_headings[1])
    sol_java = parse_code(solution_md, sol_headings[2])
    sol_python = parse_code(solution_md, sol_headings[3])
    sol_js = parse_code(solution_md, sol_headings[4])

    raw_data = {
        "title": title,
        "readme_md": readme_md,
        "approach": approach,
        "solution_c": sol_c,
        "solution_cpp": sol_cpp,
        "solution_java": sol_java,
        "solution_python": sol_python,
        "solution_js": sol_js,
        "test_cases": test_cases,
        "topic": topic
    }
    return raw_data

def parse_and_log(belt, problem_number, topic, title, readme_md, solution_md, test_cases_str, qc_score):
    try:
        def parse_section(text, start_heading, end_headings):
            pattern = re.escape(start_heading) + r'(.*?)(?=' + '|'.join(re.escape(h) for h in end_headings) + r'|$)' if end_headings else re.escape(start_heading) + r'(.*)'
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else ""

        def parse_code(text, lang_heading):
            pattern = re.escape(lang_heading) + r'\s*```(?:[a-zA-Z\+\#]+)?\s*\n(.*?)\n\s*```'
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else "Not provided"

        readme_headings = ['### Description', '### Constraints', '### Example', '### Concepts Covered']
        question = parse_section(readme_md, '### Description', readme_headings[1:])
        constraints = parse_section(readme_md, '### Constraints', readme_headings[2:])
        example_block = parse_section(readme_md, '### Example', readme_headings[3:])
        concepts = parse_section(readme_md, '### Concepts Covered', [])

        sample_input, sample_output = "", ""
        if "Input:" in example_block and "Output:" in example_block:
            parts = example_block.split("Input:")
            if len(parts) > 1:
                input_part = parts[1].split("Output:")[0].strip()
                sample_input = input_part
                output_part = parts[1].split("Output:")[1].strip()
                sample_output = output_part.split("Explanation:")[0].strip() if "Explanation:" in output_part else output_part

        sol_headings = ['## C Solution', '## C++ Solution', '## Java Solution', '## Python Solution', '## JavaScript Solution']
        sol_c = parse_code(solution_md, sol_headings[0])
        sol_cpp = parse_code(solution_md, sol_headings[1])
        sol_java = parse_code(solution_md, sol_headings[2])
        sol_python = parse_code(solution_md, sol_headings[3])
        sol_js = parse_code(solution_md, sol_headings[4])

        row_data = [
            f"{belt.split(' ')[0]}-{problem_number}", topic, concepts, question, constraints,
            sample_input, sample_output, test_cases_str, sol_c, sol_python, sol_java, sol_js, sol_cpp, str(qc_score)
        ]
        log_to_csv(row_data)
    except Exception as e:
        error_msg = f"Error parsing and logging data: {e}"
        log_debug(error_msg)
        return error_msg
    return None

# --- HISTORY & CORE HELPER FUNCTIONS ---
def load_history():
    if not os.path.exists(HISTORY_FILE): return {}
    with open(HISTORY_FILE, 'r') as f:
        try: return json.load(f)
        except json.JSONDecodeError: return {}

def save_history(history):
    with open(HISTORY_FILE, 'w') as f: json.dump(history, f, indent=4)

def update_history(belt, topic, title):
    history = load_history()
    if belt not in history: history[belt] = {"topics": [], "titles": []}
    if "topics" not in history[belt]: history[belt]["topics"] = []
    if "titles" not in history[belt]: history[belt]["titles"] = []
    history[belt]["topics"].append(topic)
    history[belt]["titles"].append(title)
    save_history(history)

def slugify(text):
    return re.sub(r'[^\w\s-]', '', text).strip().lower().replace(' ', '-')

# --- QC SCORE GENERATION ---
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def generate_qc_score(belt, raw_data):
    try:
        history = load_history()
        belt_history = history.get(belt, {"topics": [], "titles": []})
        used_titles = ", ".join(f"'{title}'" for title in belt_history.get("titles", []))
        belt_concepts = [c for cat in BELT_SYLLABUS[belt].values() for c in cat]
        problem_data = json.dumps({
            "title": raw_data["title"],
            "readme_md": raw_data["readme_md"],
            "approach": raw_data["approach"],
            "test_cases": raw_data["test_cases"],
            "solution_c": raw_data["solution_c"],
            "solution_cpp": raw_data["solution_cpp"],
            "solution_java": raw_data["solution_java"],
            "solution_python": raw_data["solution_python"],
            "solution_js": raw_data["solution_js"],
            "topic": raw_data["topic"]
        }, indent=2)

        prompt = f"""
        Evaluate the DSA problem for a {belt} developer. Assign a QC score (1.0 to 5.0) based on:
        1. Quality (20%): Clarity, completeness, correctness (1=poor, 5=excellent).
        2. Creativity (20%): Originality vs. used titles: [{used_titles}] (1=duplicate, 5=unique).
        3. Relevance (20%): Alignment with syllabus: {belt_concepts} (1=irrelevant, 5=aligned).
        4. Use of Concepts (20%): Effective use of concepts (1=not used, 5=deeply applied).
        5. Interrelatedness (20%): Connection to other problems (1=isolated, 5=strong synergy).
        Return JSON: {{"qc_score": <float>, "criteria_scores": {{"quality": <int>, "creativity": <int>, "relevance": <int>, "use_of_concepts": <int>, "interrelatedness": <int>}}}}
        Problem: {problem_data}
        """
        response = model.generate_content(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        log_debug(f"QC score raw response for '{raw_data['title']}': {response_text}")

        try:
            data = json.loads(response_text)
            if not isinstance(data, dict) or "qc_score" not in data or "criteria_scores" not in data:
                raise ValueError("Invalid JSON structure: Missing qc_score or criteria_scores")
            criteria_scores = data["criteria_scores"]
            required_keys = ["quality", "creativity", "relevance", "use_of_concepts", "interrelatedness"]
            if not all(key in criteria_scores for key in required_keys):
                raise ValueError(f"Incomplete criteria_scores: {criteria_scores}")
            scores = [criteria_scores[key] for key in required_keys]
            if not all(isinstance(s, int) and 1 <= s <= 5 for s in scores):
                raise ValueError(f"Invalid criteria scores (must be integers 1-5): {criteria_scores}")
            calculated_qc_score = sum(scores) / len(scores)
            model_qc_score = float(data["qc_score"])
            log_debug(f"Criteria scores: {criteria_scores}")
            log_debug(f"Model QC score: {model_qc_score}, Calculated QC score: {calculated_qc_score}")
            if abs(calculated_qc_score - model_qc_score) > 0.1:
                log_debug(f"Warning: Model QC score ({model_qc_score}) differs from calculated ({calculated_qc_score})")
            return calculated_qc_score, criteria_scores
        except json.JSONDecodeError as e:
            log_debug(f"JSON parsing error: {e}")
            # Fallback scoring
            quality = 3 if raw_data["readme_md"] and raw_data["approach"] else 1
            creativity = 3 if raw_data["title"].lower() not in [t.lower() for t in used_titles] else 1
            relevance = 3 if raw_data["topic"] in belt_concepts else 1
            use_of_concepts = 3 if "Concepts Covered" in raw_data["readme_md"] else 1
            interrelatedness = 2  # Neutral default
            criteria_scores = {
                "quality": quality,
                "creativity": creativity,
                "relevance": relevance,
                "use_of_concepts": use_of_concepts,
                "interrelatedness": interrelatedness
            }
            calculated_qc_score = sum(criteria_scores.values()) / len(criteria_scores)
            log_debug(f"Fallback QC score: {calculated_qc_score}, Criteria: {criteria_scores}")
            return calculated_qc_score, criteria_scores
    except Exception as e:
        log_debug(f"Error generating QC score for '{raw_data['title']}': {e}")
        criteria_scores = {"quality": 1, "creativity": 1, "relevance": 1, "use_of_concepts": 1, "interrelatedness": 1}
        return 1.0, criteria_scores

# --- GENERATION FUNCTIONS ---
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def call_gemini_api(prompt):
    response = model.generate_content(prompt)
    return response

def generate_problem_with_gemini(belt):
    history = load_history()
    belt_history = history.get(belt, {"topics": [], "titles": []})
    all_concepts = [c for cat in BELT_SYLLABUS[belt].values() for c in cat]
    used_concepts = belt_history.get("topics", [])
    used_titles = belt_history.get("titles", [])
    available_concepts = list(set(all_concepts) - set(used_concepts))
    if not available_concepts:
        log_debug(f"All topics for {belt} exhausted. Resetting topic history.")
        history.setdefault(belt, {"topics": [], "titles": []})["topics"] = []
        save_history(history)
        available_concepts = all_concepts

    for attempt in range(3):
        topic = random.choice(available_concepts)
        log_debug(f"Attempt {attempt + 1}: Generating problem for topic '{topic}'...")
        try:
            used_titles_str = ", ".join(f"'{title}'" for title in used_titles)
            prompt = f"""
            Generate a JSON object for a DSA problem on "{topic}" for a {belt} developer.
            Keys: "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".
            Avoid titles: [{used_titles_str}].
            Ensure code is runnable, handles I/O via stdin/stdout, and logic is in a separate function.
            """
            response = call_gemini_api(prompt)
            log_debug(f"Raw API response for '{topic}': {response.text}")
            response_text = response.text.strip().replace("```json", "").replace("```", "")
            data = json.loads(response_text)
            if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
                raise ValueError("Incomplete JSON response from Gemini")
            if data['title'].lower() not in [t.lower() for t in used_titles]:
                data['topic'] = topic
                qc_score, criteria_scores = generate_qc_score(belt, data)
                data['qc_score'] = qc_score
                data['criteria_scores'] = criteria_scores
                log_debug(f"AI-generated problem: {data['title']}, QC Score: {qc_score}, Criteria: {criteria_scores}")
                return data
        except Exception as e:
            log_debug(f"Error during AI generation attempt: {e}")
    log_debug(f"Failed to generate problem for {belt} after 3 attempts")
    return None

def modify_problem(belt, raw_data, mod_prompt):
    history = load_history()
    belt_history = history.get(belt, {"topics": [], "titles": []})
    used_titles_str = ", ".join(f"'{title}'" for title in belt_history.get("titles", []))
    problem_data = json.dumps(raw_data, indent=2)
    try:
        prompt = f"""
        Modify the DSA problem for a {belt} developer per: "{mod_prompt}".
        Avoid titles: [{used_titles_str}].
        Return JSON with: "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".
        Problem: {problem_data}
        Ensure code is runnable, handles I/O via stdin/stdout, and logic is in a separate function.
        """
        response = call_gemini_api(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        log_debug(f"Raw API response for modify: {response_text}")
        data = json.loads(response_text)
        if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
            raise ValueError("Incomplete JSON response from Gemini")
        data['topic'] = data.get('topic', raw_data['topic'])
        qc_score, criteria_scores = generate_qc_score(belt, data)
        data['qc_score'] = qc_score
        data['criteria_scores'] = criteria_scores
        log_debug(f"Modified problem: {data['title']}, QC Score: {qc_score}, Criteria: {criteria_scores}")
        return data
    except Exception as e:
        log_debug(f"Error during problem modification: {e}")
        return None

def generate_problem_from_leetcode(problem_name, belt):
    log_debug(f"Recreating LeetCode problem: {problem_name}")
    try:
        prompt = f"""
        Generate a JSON object for the LeetCode problem "{problem_name}" for a {belt} developer.
        Keys: "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".
        Ensure code is runnable, handles I/O via stdin/stdout, and logic is in a separate function.
        """
        response = call_gemini_api(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        log_debug(f"Raw API response for LeetCode '{problem_name}': {response_text}")
        data = json.loads(response_text)
        if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
            raise ValueError("Incomplete JSON response from Gemini")
        data['topic'] = "LeetCode"
        qc_score, criteria_scores = generate_qc_score(belt, data)
        data['qc_score'] = qc_score
        data['criteria_scores'] = criteria_scores
        log_debug(f"LeetCode problem: {data['title']}, QC Score: {qc_score}, Criteria: {criteria_scores}")
        return data
    except Exception as e:
        log_debug(f"Error generating LeetCode problem: {e}")
        return None

def generate_problem_from_geeksforgeeks(problem_name, belt):
    log_debug(f"Recreating GeeksforGeeks problem: {problem_name}")
    try:
        prompt = f"""
        Generate a JSON object for the GeeksforGeeks problem "{problem_name}" for a {belt} developer.
        Keys: "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".
        Ensure code is runnable, handles I/O via stdin/stdout, and logic is in a separate function.
        """
        response = call_gemini_api(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        log_debug(f"Raw API response for GeeksforGeeks '{problem_name}': {response_text}")
        data = json.loads(response_text)
        if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
            raise ValueError("Incomplete JSON response from Gemini")
        data['topic'] = "GeeksforGeeks"
        qc_score, criteria_scores = generate_qc_score(belt, data)
        data['qc_score'] = qc_score
        data['criteria_scores'] = criteria_scores
        log_debug(f"GeeksforGeeks problem: {data['title']}, QC Score: {qc_score}, Criteria: {criteria_scores}")
        return data
    except Exception as e:
        log_debug(f"Error generating GeeksforGeeks problem: {e}")
        return None

# --- GIT & SCHEDULE FUNCTIONS ---
def commit_problem_to_repo(belt, problem_title, readme_md, solution_md, topic, test_cases, qc_score):
    try:
        repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
        repo_path = os.path.join(REPOS_DIR, repo_name)
        if not os.path.exists(repo_path):
            subprocess.run(["git", "clone", REPO_URL, repo_path], check=True)
        else:
            subprocess.run(["git", "-C", repo_path, "pull"], check=True)
        belt_dir = os.path.join(repo_path, belt.replace(" ", "-"))
        os.makedirs(belt_dir, exist_ok=True)
        problem_number = len([name for name in os.listdir(belt_dir) if os.path.isdir(os.path.join(belt_dir, name))]) + 1
        new_folder_name = f"{problem_number}-{slugify(problem_title)}"
        problem_dir = os.path.join(belt_dir, new_folder_name)
        os.makedirs(problem_dir, exist_ok=True)
        with open(os.path.join(problem_dir, "readme.md"), "w", encoding='utf-8') as f: f.write(readme_md)
        with open(os.path.join(problem_dir, "solution.md"), "w", encoding='utf-8') as f: f.write(solution_md)
        subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", f"feat({belt}): Add problem #{problem_number} - '{problem_title}'"], check=True)
        subprocess.run(["git", "-C", repo_path, "push"], check=True)

        logging_error = parse_and_log(belt, problem_number, topic, problem_title, readme_md, solution_md, test_cases, qc_score)
        if logging_error:
            log_debug(f"Logging failed: {logging_error}")
            return f"Committed '{problem_title}' as problem #{problem_number}, but failed to log to CSV: {logging_error}"
        return f"Successfully committed '{problem_title}' as problem #{problem_number}."
    except Exception as e:
        log_debug(f"Error during commit: {e}")
        return f"An error occurred during commit: {e}"

def schedule_commit(schedule_time, belt, title, readme, solution, topic, test_cases, qc_score):
    job = {
        "id": datetime.now().strftime('%Y%m%d%H%M%S%f'),
        "commit_at": schedule_time,
        "belt": belt,
        "title": title,
        "readme": readme,
        "solution": solution,
        "topic": topic,
        "test_cases": test_cases,
        "qc_score": qc_score
    }
    jobs = []
    if os.path.exists(SCHEDULED_JOBS_FILE):
        with open(SCHEDULED_JOBS_FILE, 'r') as f:
            try: jobs = json.load(f)
            except json.JSONDecodeError: pass
    jobs.append(job)
    with open(SCHEDULED_JOBS_FILE, 'w') as f: json.dump(jobs, f, indent=4)
    update_history(belt, topic, title)
    logging_error = parse_and_log(belt, "N/A", topic, title, readme, solution, test_cases, qc_score)
    if logging_error:
        log_debug(f"Logging failed: {logging_error}")
        return f"Scheduled '{title}' for {schedule_time}, but failed to log to CSV: {logging_error}"
    log_debug(f"Scheduled job for '{title}' at {schedule_time}")
    return f"Successfully scheduled '{title}' for {schedule_time}."

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    log_debug("Received /generate request")
    belt = request.form['belt']
    source = request.form['source']
    num_problems = int(request.form.get('num_problems', 1))
    log_debug(f"Belt: {belt}, Source: {source}, Num Problems: {num_problems}")
    problems_list = []

    for i in range(num_problems):
        log_debug(f"Generating problem {i+1}/{num_problems}")
        raw_data = None
        if source == 'leetcode':
            url = request.form.get('leetcode_url')
            log_debug(f"LeetCode URL: {url}")
            if url and 'leetcode.com/problems/' in url:
                slug = url.strip('/').split('/problems/')[-1].split('/')[0]
                problem_name = ' '.join(word.capitalize() for word in slug.split('-'))
                log_debug(f"Extracted slug: {slug}, problem_name: {problem_name}")
                raw_data = generate_problem_from_leetcode(problem_name, belt)
            else:
                log_debug("Invalid LeetCode URL")
                return jsonify({"message": "Invalid LeetCode URL. Please provide a URL like https://leetcode.com/problems/two-sum/."}), 400
        elif source == 'geeksforgeeks':
            url = request.form.get('leetcode_url')
            log_debug(f"GeeksforGeeks URL: {url}")
            if url and 'geeksforgeeks.org/problems/' in url:
                slug = url.strip('/').split('/problems/')[-1].split('/')[0]
                problem_name = ' '.join(word.capitalize() for word in slug.split('-'))
                log_debug(f"Extracted slug: {slug}, problem_name: {problem_name}")
                raw_data = generate_problem_from_geeksforgeeks(problem_name, belt)
            else:
                log_debug("Invalid GeeksforGeeks URL")
                return jsonify({"message": "Invalid GeeksforGeeks URL. Please provide a URL like https://www.geeksforgeeks.org/problems/two-sum."}), 400
        elif source == 'ai':
            raw_data = generate_problem_with_gemini(belt)
        elif source == 'custom':
            raw_data = {
                "title": "Custom Problem Title",
                "topic": "Custom",
                "test_cases": "Input: \nOutput: ",
                "readme_md": "### Description\n\n### Constraints\n\n### Example\n\n### Concepts Covered\n",
                "approach": "Your approach here...",
                "solution_c": "",
                "solution_cpp": "",
                "solution_java": "",
                "solution_python": "",
                "solution_js": "",
                "qc_score": 1.0,
                "criteria_scores": {
                    "quality": 1, "creativity": 1, "relevance": 1, "use_of_concepts": 1, "interrelatedness": 1
                }
            }

        if raw_data:
            raw_data.setdefault('test_cases', 'Input: \nOutput: ')
            raw_data.setdefault('approach', 'Approach not provided.')
            raw_data.setdefault('solution_c', '// Code not provided.')
            raw_data.setdefault('solution_cpp', '// Code not provided.')
            raw_data.setdefault('solution_java', '// Code not provided.')
            raw_data.setdefault('solution_python', '# Code not provided.')
            raw_data.setdefault('solution_js', '// Code not provided.')
            raw_data.setdefault('qc_score', 1.0)
            raw_data.setdefault('criteria_scores', {
                "quality": 1, "creativity": 1, "relevance": 1, "use_of_concepts": 1, "interrelatedness": 1
            })
            solution_md = (
                f"# Solutions for {raw_data['title']}\n\n"
                f"### Approach\n{raw_data.get('approach', 'Approach not provided.')}\n\n"
                f"## C Solution\n```c\n{raw_data.get('solution_c', '// Code not provided.')}\n```\n\n"
                f"## C++ Solution\n```cpp\n{raw_data.get('solution_cpp', '// Code not provided.')}\n```\n\n"
                f"## Java Solution\n```java\n{raw_data.get('solution_java', '// Code not provided.')}\n```\n\n"
                f"## Python Solution\n```python\n{raw_data.get('solution_python', '# Code not provided.')}\n```\n\n"
                f"## JavaScript Solution\n```javascript\n{raw_data.get('solution_js', '// Code not provided.')}\n```"
            )
            log_debug(f"Generated solution_md for '{raw_data['title']}': {solution_md[:100]}...")
            final_problem_data = {
                "title": raw_data['title'],
                "readme": raw_data['readme_md'],
                "solution": solution_md,
                "test_cases": raw_data.get('test_cases', ''),
                "topic": raw_data['topic'],
                "qc_score": float(raw_data['qc_score']),
                "criteria_scores": raw_data['criteria_scores']
            }
            problems_list.append(final_problem_data)

    if problems_list:
        return jsonify(problems_list)
    else:
        log_debug(f"Failed to generate problem for source '{source}'")
        return jsonify({"message": f"Failed to generate problem for source '{source}'. Please try a different URL or source."}), 500

@app.route('/modify', methods=['POST'])
def modify():
    belt = request.form['belt']
    title = request.form['problem_title']
    readme_md = request.form['readme_content']
    solution_md = request.form['solution_content']
    topic = request.form['topic']
    test_cases = request.form['test_cases']
    mod_prompt = request.form.get('mod_prompt', '').strip()
    if not mod_prompt:
        log_debug("No modification prompt provided")
        return jsonify({"message": "No modification prompt provided."}), 400

    raw_data = extract_raw_data(title, readme_md, solution_md, topic, test_cases)
    updated_raw = modify_problem(belt, raw_data, mod_prompt)
    if updated_raw:
        solution_md = (
            f"# Solutions for {updated_raw['title']}\n\n"
            f"### Approach\n{updated_raw.get('approach', 'Approach not provided.')}\n\n"
            f"## C Solution\n```c\n{updated_raw.get('solution_c', '// Code not provided.')}\n```\n\n"
            f"## C++ Solution\n```cpp\n{updated_raw.get('solution_cpp', '// Code not provided.')}\n```\n\n"
            f"## Java Solution\n```java\n{updated_raw.get('solution_java', '// Code not provided.')}\n```\n\n"
            f"## Python Solution\n```python\n{updated_raw.get('solution_python', '# Code not provided.')}\n```\n\n"
            f"## JavaScript Solution\n```javascript\n{updated_raw.get('solution_js', '// Code not provided.')}\n```"
        )
        final_problem_data = {
            "title": updated_raw['title'],
            "readme": updated_raw['readme_md'],
            "solution": solution_md,
            "test_cases": updated_raw.get('test_cases', ''),
            "topic": updated_raw['topic'],
            "qc_score": float(updated_raw['qc_score']),
            "criteria_scores": updated_raw['criteria_scores']
        }
        return jsonify(final_problem_data)
    else:
        log_debug("Failed to modify the problem")
        return jsonify({"message": "Failed to modify the problem. Please try again."}), 500

@app.route('/commit', methods=['POST'])
def commit():
    data = request.form
    belt, title, readme, solution, action, topic, test_cases, qc_score = (
        data['belt'],
        data['problem_title'],
        data['readme_content'],
        data['solution_content'],
        data['commit_action'],
        data['topic'],
        data['test_cases'],
        data.get('qc_score', '1.0')
    )
    try:
        qc_score = float(qc_score)
        if not (1.0 <= qc_score <= 5.0):
            log_debug("QC score out of range")
            return jsonify({"message": "QC score must be between 1.0 and 5.0."}), 400
    except ValueError:
        log_debug("Invalid QC score format")
        return jsonify({"message": "Invalid QC score format. Please enter a number between 1.0 and 5.0."}), 400

    if action == 'now':
        message = commit_problem_to_repo(belt, title, readme, solution, topic, test_cases, qc_score)
        if "Error" in message or "failed" in message:
            log_debug(message)
            return jsonify({"message": message}), 500
        return jsonify({"message": message})
    elif action == 'schedule':
        schedule_time = data['schedule_time']
        if not schedule_time:
            log_debug("Schedule time not provided")
            return jsonify({"message": "Error: Schedule time not provided."}), 400
        message = schedule_commit(schedule_time, belt, title, readme, solution, topic, test_cases, qc_score)
        if "Error" in message or "failed" in message:
            log_debug(message)
            return jsonify({"message": message}), 500
        return jsonify({"message": message})
    log_debug("Invalid action")
    return jsonify({"message": "Invalid action."}), 400

@app.route('/problems/<belt_name>')
def list_problems(belt_name):
    repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
    repo_path = os.path.join(REPOS_DIR, repo_name)
    belt_dir = os.path.join(repo_path, belt_name.replace(" ", "-"))
    if not os.path.exists(belt_dir):
        log_debug(f"No problems found for belt: {belt_name}")
        return jsonify([])
    problems = [name for name in os.listdir(belt_dir) if os.path.isdir(os.path.join(belt_dir, name))]
    return jsonify(sorted(problems))

@app.route('/delete', methods=['POST'])
def delete_problem():
    data = request.form
    belt, problem_folder = data['belt'], data['problem_folder']
    try:
        repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
        repo_path = os.path.join(REPOS_DIR, repo_name)
        problem_path = os.path.join(repo_path, belt.replace(" ", "-"), problem_folder)
        subprocess.run(["git", "-C", repo_path, "pull"], check=True)
        shutil.rmtree(problem_path)
        subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", f"chore({belt}): Delete problem '{problem_folder}'"], check=True)
        subprocess.run(["git", "-C", repo_path, "push"], check=True)
        delete_row = [f"DELETE-{problem_folder}", "Deletion", "N/A", f"Deleted folder: {problem_folder}", "N/A", "N/A", "N/A", "N/A", "", "", "", "", "", "N/A"]
        log_to_csv(delete_row)
        log_debug(f"Deleted problem: {problem_folder}")
        return jsonify({"message": f"Successfully deleted '{problem_folder}'."})
    except Exception as e:
        log_debug(f"Error during deletion: {e}")
        return jsonify({"message": f"An error occurred during deletion: {e}"}), 500

@app.route('/analytics', methods=['GET'])
def analytics():
    belt_filter = request.args.get('belt', '')
    data = []
    if os.path.exists(LOG_CSV_FILE):
        with open(LOG_CSV_FILE, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row['ID'].startswith('DELETE-'):
                    continue
                id_parts = row['ID'].split('-', 1)
                belt_short = id_parts[0]
                belt = belt_map.get(belt_short, belt_short + ' Belt')
                row['Belt'] = belt
                concepts = [c.strip() for c in row['Concepts'].replace('-', '').split(',') if c.strip()]
                row['ConceptsList'] = concepts
                if not belt_filter or belt == belt_filter:
                    data.append(row)

    belts_count = Counter([d['Belt'] for d in data])
    topics_count = Counter([d['Category'] for d in data])
    all_concepts = [c for d in data for c in d['ConceptsList']]
    concepts_count = Counter(all_concepts)
    top_concepts = dict(concepts_count.most_common(10))

    response = {
        'problems': data,
        'charts': {
            'belts': dict(belts_count),
            'topics': dict(topics_count),
            'top_concepts': top_concepts
        }
    }
    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True, port=5000)