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
                    "Solution_Python", "Solution_Java", "Solution_Javascript", "Solution_C++", "QC_Score"
                ]
                writer.writerow(headers)
            writer.writerow(row_data)
        print(f"Successfully logged action to {LOG_CSV_FILE}")

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

        # print(f"Parsing solution_md:\n{solution_md}")

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

        # print(f"Parsed solutions: C={sol_c}, C++={sol_cpp}, Java={sol_java}, Python={sol_python}, JS={sol_js}")

        row_data = [
            f"{belt.split(' ')[0]}-{problem_number}", topic, concepts, question, constraints, 
            sample_input, sample_output, test_cases_str, sol_c, sol_python, sol_java, sol_js, sol_cpp, str(qc_score)
        ]
        log_to_csv(row_data)
    except Exception as e:
        error_msg = f"Error parsing and logging data: {e}"
        print(error_msg)
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
        # YOUR ROLE
        You are an expert DSA problem evaluator tasked with assigning a Quality-Creativity (QC) score to a problem.

        # YOUR TASK
        Evaluate the following DSA problem for a {belt} developer and assign a QC score from 1 to 5 based on the criteria below. Return only a JSON object with a single key "qc_score" containing an integer from 1 to 5.

        # PROBLEM DATA
        {problem_data}

        # EVALUATION CRITERIA (each weighted at 20%)
        1. **Quality (20%)**: Assess clarity, completeness, and correctness. Check if `readme_md` has clear sections ("### Description", "### Constraints", "### Example", "### Concepts Covered"), solutions are complete and correct, and test cases cover edge cases. Score 1 (poorly written, incomplete) to 5 (clear, complete, correct).
        2. **Creativity (20%)**: Assess originality. For AI-generated problems, check if the title and description are unique compared to these used titles: [{used_titles}]. For LeetCode problems, evaluate if the adaptation adds unique context. Score 1 (highly similar) to 5 (highly original).
        3. **Relevance to Belt (20%)**: Check if the problem aligns with the belt’s syllabus: {belt_concepts}. Ensure complexity (from `approach`) suits the belt (e.g., O(n) for White Belt). Score 1 (irrelevant or too easy/hard) to 5 (perfectly aligned).
        4. **Use of Concepts (20%)**: Verify if the problem effectively uses concepts listed in `Concepts Covered` and demonstrated in solutions. Score 1 (concepts mentioned but not used) to 5 (concepts deeply integrated).
        5. **Interrelatedness (20%)**: Assess if the problem builds on or complements existing problems in the belt’s history: [{used_titles}]. Score 1 (isolated) to 5 (strong connection).

        # SCORING
        - Assign a score (1–5) for each criterion.
        - Compute the final QC score as the rounded average of the five scores.
        - Return: ```json\n{{"qc_score": <integer>}}\n```

        # EXAMPLE
        For a problem with scores Quality=4, Creativity=3, Relevance=5, Use of Concepts=4, Interrelatedness=3:
        Final QC score = round((4+3+5+4+3)/5) = 4
        Return: ```json\n{{"qc_score": 4}}\n```
        """
        response = model.generate_content(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        print(f"QC score response: {response_text}")
        data = json.loads(response_text)
        return data.get("qc_score", 1)
    except Exception as e:
        print(f"Error generating QC score: {e}")
        return 1  # Default to 1 if evaluation fails

# --- GENERATION FUNCTIONS ---
def generate_problem_with_gemini(belt):
    history = load_history()
    belt_history = history.get(belt, {"topics": [], "titles": []})
    all_concepts = [c for cat in BELT_SYLLABUS[belt].values() for c in cat]
    used_concepts = belt_history.get("topics", [])
    used_titles = belt_history.get("titles", [])
    available_concepts = list(set(all_concepts) - set(used_concepts))
    if not available_concepts:
        print(f"All topics for {belt} exhausted. Resetting topic history.")
        history.setdefault(belt, {"topics": [], "titles": []})["topics"] = []
        save_history(history)
        available_concepts = all_concepts
    
    for attempt in range(3):
        topic = random.choice(available_concepts)
        print(f"Attempt {attempt + 1}: Generating problem for topic '{topic}'...")
        try:
            used_titles_str = ", ".join(f"'{title}'" for title in used_titles)
            prompt = f"""
            # YOUR ROLE
            You are an expert DSA problem designer. Your task is to generate the components of a DSA problem as a JSON object.

            # YOUR TASK
            Generate a JSON object for a problem on "{topic}" for a {belt} developer. The JSON MUST have the following keys:
            "title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases".

            # CRITICAL CONTEXT
            The following titles have already been used for this belt and you MUST NOT create a problem with the same or a very similar title: [{used_titles_str}]

            # INSTRUCTIONS FOR EACH KEY
            1. "title": A creative, unique title, different from the context list.
            2. "readme_md": A markdown string with "### Description", "### Constraints", "### Example", and "### Concepts Covered" sections.
            3. "approach": A markdown paragraph explaining the algorithm, data structures, and time/space complexity.
            4. "solution_c": A string containing ONLY the complete, runnable C code.
            5. "solution_cpp": A string containing ONLY the complete, runnable C++ code.
            6. "solution_java": A string containing ONLY the complete, runnable Java code.
            7. "solution_python": A string containing ONLY the complete, runnable Python code.
            8. "solution_js": A string containing ONLY the complete, runnable JavaScript code.
            9. "test_cases": A string with 3-5 additional test cases, each on a new line, formatted as 'Input: [data]\\nOutput: [data]'.

            # CRITICAL CODE REQUIREMENTS
            - The code for each language key MUST be a complete program that handles its own I/O from stdin/stdout.
            - The core logic MUST be in a separate function. The `main` function should ONLY call the logic function and handle I/O.
            - DO NOT include the markdown backticks (```) or language identifiers in the code strings.
            """
            response = model.generate_content(prompt)
            response_text = response.text.strip().replace("```json", "").replace("```", "")
            # print(f"Gemini response for AI generation: {response_text}")
            data = json.loads(response_text)
            if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
                raise ValueError("Incomplete JSON response from Gemini")
            if data['title'].lower() not in [t.lower() for t in used_titles]:
                data['topic'] = topic
                data['qc_score'] = generate_qc_score(belt, data)
                return data
        except Exception as e:
            print(f"Error during AI generation attempt: {e}")
    return None

def generate_problem_from_leetcode(problem_name, belt):
    print(f"Recreating LeetCode problem: {problem_name}")
    try:
        prompt = f"""
        # YOUR ROLE
        You are an expert DSA problem designer tasked with recreating a LeetCode problem.

        # YOUR TASK
        Generate a JSON object for the LeetCode problem titled "{problem_name}" for a {belt} developer. The JSON MUST include these keys:
        - "title": The exact LeetCode title (e.g., "Two Sum").
        - "readme_md": Markdown with sections: "### Description", "### Constraints", "### Example", "### Concepts Covered" (tailored for {belt} level).
        - "approach": A markdown paragraph explaining the optimal algorithm and time/space complexity.
        - "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js": Complete, runnable code for each language, with logic in a separate function and I/O handled in main.
        - "test_cases": 3-5 test cases formatted as 'Input: [data]\\nOutput: [data]' (one per line).

        # CRITICAL CODE REQUIREMENTS
        - Code must be raw, runnable, and exclude markdown backticks (```).
        - Code must handle I/O via stdin/stdout.
        - Ensure the title matches "{problem_name}" exactly.
        """
        response = model.generate_content(prompt)
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        # print(f"Gemini response for LeetCode: {response_text}")
        data = json.loads(response_text)
        if not all(key in data for key in ["title", "readme_md", "approach", "solution_c", "solution_cpp", "solution_java", "solution_python", "solution_js", "test_cases"]):
            raise ValueError("Incomplete JSON response from Gemini")
        data['topic'] = "LeetCode"
        data['qc_score'] = generate_qc_score(belt, data)
        return data
    except Exception as e:
        print(f"Error generating LeetCode problem: {e}")
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
            print(f"Logging failed: {logging_error}")
            return f"Committed '{problem_title}' as problem #{problem_number}, but failed to log to CSV: {logging_error}"
        return f"Successfully committed '{problem_title}' as problem #{problem_number}."
    except Exception as e:
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
        print(f"Logging failed: {logging_error}")
        return f"Scheduled '{title}' for {schedule_time}, but failed to log to CSV: {logging_error}"
    print(f"Scheduled job for '{title}' at {schedule_time}")
    return f"Successfully scheduled '{title}' for {schedule_time}."

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    print("Received /generate request")
    belt = request.form['belt']
    source = request.form['source']
    num_problems = int(request.form.get('num_problems', 1))
    print(f"Belt: {belt}, Source: {source}, Num Problems: {num_problems}")
    problems_list = []
    
    for i in range(num_problems):
        print(f"Generating problem {i+1}/{num_problems}")
        raw_data = None
        if source == 'leetcode':
            url = request.form.get('leetcode_url')
            print(f"LeetCode URL: {url}")
            if url and 'leetcode.com/problems/' in url:
                slug = url.strip('/').split('/problems/')[-1].split('/')[0]
                problem_name = ' '.join(word.capitalize() for word in slug.split('-'))
                print(f"Extracted slug: {slug}, problem_name: {problem_name}")
                raw_data = generate_problem_from_leetcode(problem_name, belt)
            else:
                print("Invalid LeetCode URL")
                return jsonify({"message": "Invalid LeetCode URL. Please provide a URL like https://leetcode.com/problems/two-sum/."}), 400
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
                "qc_score": 1
            }

        if raw_data:
            raw_data.setdefault('test_cases', 'Input: \nOutput: ')
            raw_data.setdefault('approach', 'Approach not provided.')
            raw_data.setdefault('solution_c', '// Code not provided.')
            raw_data.setdefault('solution_cpp', '// Code not provided.')
            raw_data.setdefault('solution_java', '// Code not provided.')
            raw_data.setdefault('solution_python', '# Code not provided.')
            raw_data.setdefault('solution_js', '// Code not provided.')
            raw_data.setdefault('qc_score', 1)
            solution_md = (
                f"# Solutions for {raw_data['title']}\n\n"
                f"### Approach\n{raw_data.get('approach', 'Approach not provided.')}\n\n"
                f"## C Solution\n```c\n{raw_data.get('solution_c', '// Code not provided.')}\n```\n\n"
                f"## C++ Solution\n```cpp\n{raw_data.get('solution_cpp', '// Code not provided.')}\n```\n\n"
                f"## Java Solution\n```java\n{raw_data.get('solution_java', '// Code not provided.')}\n```\n\n"
                f"## Python Solution\n```python\n{raw_data.get('solution_python', '# Code not provided.')}\n```\n\n"
                f"## JavaScript Solution\n```javascript\n{raw_data.get('solution_js', '// Code not provided.')}\n```"
            )
            print(f"Generated solution_md:\n{solution_md}")
            final_problem_data = {
                "title": raw_data['title'],
                "readme": raw_data['readme_md'],
                "solution": solution_md,
                "test_cases": raw_data.get('test_cases', ''),
                "topic": raw_data['topic'],
                "qc_score": raw_data['qc_score']
            }
            problems_list.append(final_problem_data)
    
    if problems_list:
        return jsonify(problems_list)
    else:
        return jsonify({"message": f"Failed to generate problem for source '{source}'. Please try a different URL or source."}), 500

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
        data.get('qc_score', '1')
    )
    if action == 'now':
        message = commit_problem_to_repo(belt, title, readme, solution, topic, test_cases, int(qc_score))
        if "Error" in message or "failed" in message: return jsonify({"message": message}), 500
        return jsonify({"message": message})
    elif action == 'schedule':
        schedule_time = data['schedule_time']
        if not schedule_time: return jsonify({"message": "Error: Schedule time not provided."}), 400
        message = schedule_commit(schedule_time, belt, title, readme, solution, topic, test_cases, int(qc_score))
        if "Error" in message or "failed" in message: return jsonify({"message": message}), 500
        return jsonify({"message": message})
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
        delete_row = [f"DELETE-{problem_folder}", "Deletion", "N/A", f"Deleted folder: {problem_folder}", "N/A", "N/A", "N/A", "N/A", "", "", "", "", "", "N/A"]
        log_to_csv(delete_row)
        return jsonify({"message": f"Successfully deleted '{problem_folder}'."})
    except Exception as e:
        return jsonify({"message": f"An error occurred during deletion: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)