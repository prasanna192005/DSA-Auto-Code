# app.py
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
from config import BELT_SYLLABUS, REPO_URL

# --- SETUP ---
load_dotenv()
app = Flask(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
SCHEDULED_JOBS_FILE = "scheduled_jobs.json"
REPOS_DIR = "repositories"
HISTORY_FILE = "generation_history.json"
LOG_CSV_FILE = "dsa_dojo_log.csv"
csv_lock = Lock()
os.makedirs(REPOS_DIR, exist_ok=True)

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
                    "Solution_Python", "Solution_Java", "Solution_Javascript", "Solution_C++"
                ]
                writer.writerow(headers)
            writer.writerow(row_data)
        print(f"Successfully logged action to {LOG_CSV_FILE}")

def parse_and_log(belt, problem_number, topic, title, readme_md, solution_md, test_cases_str):
    """Parses problem data and calls the CSV logger."""
    try:
        def parse_section(text, start_heading, end_headings):
            pattern = f"{start_heading}(.*?)(?={'|'.join(end_headings)}|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else ""
        def parse_code(text, lang_start):
            pattern = f"{lang_start}\\s*```[a-zA-Z\\+\\#]*\\n(.*?)\\n```"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return match.group(1).strip() if match else ""
            
        readme_headings = ['### Description', '### Constraints', '### Example', '### Concepts Covered']
        question = parse_section(readme_md, '### Description', readme_headings[1:])
        constraints = parse_section(readme_md, '### Constraints', readme_headings[2:])
        example_block = parse_section(readme_md, '### Example', readme_headings[3:])
        concepts = parse_section(readme_md, '### Concepts Covered', [])
        sample_input, sample_output = "", ""
        if "Input:" in example_block and "Output:" in example_block:
            sample_input = example_block.split("Input:")[1].split("Output:")[0].strip()
            sample_output = example_block.split("Output:")[1].split("Explanation:")[0].strip()

        sol_headings = ['## C Solution', '## C\\+\\+ Solution', '## Java Solution', '## Python Solution', '## JavaScript Solution']
        sol_c, sol_cpp, sol_java, sol_python, sol_js = (parse_code(solution_md, h) for h in sol_headings)

        row_data = [
            f"{belt.split(' ')[0]}-{problem_number}", topic, concepts, question, constraints, 
            sample_input, sample_output, test_cases_str, sol_c, sol_python, sol_java, sol_js, sol_cpp
        ]
        log_to_csv(row_data)
    except Exception as e:
        print(f"❗ Error: Failed to parse and log data. {e}")

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
    history[belt]["topics"].append(topic)
    history[belt]["titles"].append(title)
    save_history(history)
def slugify(text):
    return re.sub(r'[^\w\s-]', '', text).strip().lower().replace(' ', '-')

# --- GENERATION FUNCTION ---
def generate_problem_with_gemini(belt):
    history = load_history()
    belt_history, used_titles = history.get(belt, {}), history.get(belt, {}).get("titles", [])
    all_concepts = [c for cat in BELT_SYLLABUS[belt].values() for c in cat]
    used_concepts = belt_history.get("topics", [])
    available_concepts = list(set(all_concepts) - set(used_concepts))
    if not available_concepts:
        belt_history["topics"] = []
        save_history(history)
        available_concepts = all_concepts
    
    for attempt in range(3):
        topic = random.choice(available_concepts)
        print(f"Attempt {attempt + 1}: Generating problem for topic '{topic}'...")
        try:
            # THIS PROMPT ASKS FOR ALL COMPONENTS SEPARATELY FOR RELIABILITY
            prompt = f"""
            # YOUR ROLE
            You are an expert DSA problem designer. Your task is to generate the components of a DSA problem as a JSON object.

            # YOUR TASK
            Generate a JSON object for a problem on "{topic}" for a {belt} developer. The JSON MUST have the following keys:
            "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".

            # INSTRUCTIONS FOR EACH KEY
            1.  "title": A creative, unique title.
            2.  "readme_md": A markdown string with "### Description", "### Constraints", "### Example", and "### Concepts Covered" sections.
            3.  "approach": A markdown paragraph explaining the algorithm, data structures, and time/space complexity.
            4.  "solution_c": A string containing ONLY the complete, runnable C code.
            5.  "solution_cpp": A string containing ONLY the complete, runnable C++ code.
            6.  "solution_java": A string containing ONLY the complete, runnable Java code.
            7.  "solution_python": A string containing ONLY the complete, runnable Python code.
            8.  "solution_js": A string containing ONLY the complete, runnable JavaScript code.
            9.  "test_cases": A string with 3 to 5 additional test cases. Each test case MUST be on a new line and formatted as 'Input: [data]\\nOutput: [data]'.

            # CRITICAL CODE REQUIREMENTS
            - The code for each language key MUST be a complete program that handles its own I/O from stdin/stdout.
            - The core logic MUST be in a separate function. The `main` function should ONLY call the logic function and handle I/O.
            - DO NOT include the markdown backticks (```) or language identifiers in the code strings.
            """
            response = model.generate_content(prompt)
            data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
            if data['title'].lower() not in [t.lower() for t in used_titles]:
                print(f"Success: Found unique problem titled '{data['title']}'.")
                data['topic'] = topic
                return data
            else:
                print(f"Warning: AI generated a duplicate title despite instructions: '{data['title']}'. Retrying...")
        except Exception as e:
            print(f"Error during generation attempt: {e}")
            continue
    print("Error: Could not generate a unique problem after 3 attempts.")
    return None

# --- GIT & SCHEDULE FUNCTIONS ---
def commit_problem_to_repo(belt, problem_title, readme_md, solution_md, topic, test_cases):
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
        
        update_history(belt, topic, problem_title)
        parse_and_log(belt, problem_number, topic, problem_title, readme_md, solution_md, test_cases)
        return f"Successfully committed '{problem_title}' as problem #{problem_number}."
    except Exception as e:
        return f"An error occurred: {e}"

def schedule_commit(schedule_time, belt, title, readme, solution, topic, test_cases):
    job = { "id": datetime.now().strftime('%Y%m%d%H%M%S%f'), "commit_at": schedule_time, "belt": belt, "title": title, "readme": readme, "solution": solution, "topic": topic, "test_cases": test_cases }
    jobs = []
    if os.path.exists(SCHEDULED_JOBS_FILE):
        with open(SCHEDULED_JOBS_FILE, 'r') as f:
            try: jobs = json.load(f)
            except json.JSONDecodeError: pass
    jobs.append(job)
    with open(SCHEDULED_JOBS_FILE, 'w') as f: json.dump(jobs, f, indent=4)
    update_history(belt, topic, title)
    parse_and_log(belt, "N/A", topic, title, readme, solution, test_cases)
    print(f"Scheduled job for '{title}' at {schedule_time}")

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    belt = request.form['belt']
    num_problems = int(request.form.get('num_problems', 1))
    problems_list = []
    for _ in range(num_problems):
        raw_data = generate_problem_with_gemini(belt)
        if raw_data:
            # THIS IS THE MANUAL ASSEMBLY LOGIC THAT GUARANTEES CORRECT FORMATTING
            solution_md = (
                f"# Solutions for {raw_data['title']}\n\n"
                f"### Approach\n{raw_data['approach']}\n\n"
                f"## C Solution\n```c\n{raw_data['solution_c']}\n```\n\n"
                f"## C++ Solution\n```cpp\n{raw_data['solution_cpp']}\n```\n\n"
                f"## Java Solution\n```java\n{raw_data['solution_java']}\n```\n\n"
                f"## Python Solution\n```python\n{raw_data['solution_python']}\n```\n\n"
                f"## JavaScript Solution\n```javascript\n{raw_data['solution_js']}\n```"
            )
            final_problem_data = {
                "title": raw_data['title'],
                "readme": raw_data['readme_md'],
                "solution": solution_md,
                "test_cases": raw_data['test_cases'],
                "topic": raw_data['topic']
            }
            problems_list.append(final_problem_data)
    
    if problems_list: 
        return jsonify(problems_list)
    else: 
        return jsonify({"message": "Could not generate a unique problem. Please try again."}), 500

@app.route('/commit', methods=['POST'])
def commit():
    data = request.form
    belt, title, readme, solution, action, topic, test_cases = data['belt'], data['problem_title'], data['readme_content'], data['solution_content'], data['commit_action'], data['topic'], data['test_cases']
    if action == 'now':
        message = commit_problem_to_repo(belt, title, readme, solution, topic, test_cases)
        if "Error" in message or "failed" in message: return jsonify({"message": message}), 500
        return jsonify({"message": message})
    elif action == 'schedule':
        schedule_time = data['schedule_time']
        if not schedule_time: return jsonify({"message": "Error: Schedule time not provided."}), 400
        schedule_commit(schedule_time, belt, title, readme, solution, topic, test_cases)
        return jsonify({"message": f"Successfully scheduled '{title}' for {schedule_time}."})
    return jsonify({"message": "Invalid action."}), 400

@app.route('/problems/<belt_name>')
def list_problems(belt_name):
    repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
    repo_path = os.path.join(REPOS_DIR, repo_name)
    belt_dir = os.path.join(repo_path, belt_name.replace(" ", "-"))
    if not os.path.exists(belt_dir): return jsonify([])
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
        delete_row = [f"DELETE-{problem_folder}", "Deletion", "N/A", f"Deleted folder: {problem_folder}", "N/A", "N/A", "N/A", "N/A", "", "", "", "", ""]
        log_to_csv(delete_row)
        return jsonify({"message": f"Successfully deleted '{problem_folder}'."})
    except Exception as e:
        return jsonify({"message": f"An error occurred during deletion: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)