# app.py
import os
import subprocess
import json
import random
import re
import shutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai

# import gspread # We will use this later for Google Sheets
from config import BELT_SYLLABUS, REPO_URL

# --- SETUP ---
load_dotenv()
app = Flask(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash-latest')
SCHEDULED_JOBS_FILE = "scheduled_jobs.json"
REPOS_DIR = "repositories"
HISTORY_FILE = "generation_history.json"
os.makedirs(REPOS_DIR, exist_ok=True)

# --- HISTORY HELPER FUNCTIONS ---
def load_history():
    if not os.path.exists(HISTORY_FILE): return {}
    with open(HISTORY_FILE, 'r') as f:
        try: return json.load(f)
        except json.JSONDecodeError: return {}

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def update_history(belt, topic, title):
    history = load_history()
    if belt not in history:
        history[belt] = {"topics": [], "titles": []}
    if "topics" not in history[belt]: history[belt]["topics"] = []
    if "titles" not in history[belt]: history[belt]["titles"] = []
    history[belt]["topics"].append(topic)
    history[belt]["titles"].append(title)
    save_history(history)

# --- GOOGLE SHEETS LOGGER (Placeholder for later) ---
def log_to_google_sheet(action, belt, problem_title, status):
    print(f"--- LOGGING ACTION: Google Sheets logging is currently disabled ---")

# --- CORE HELPER FUNCTIONS ---
def slugify(text):
    return re.sub(r'[^\w\s-]', '', text).strip().lower().replace(' ', '-')

def generate_problem_with_gemini(belt):
    history = load_history()
    belt_history = history.get(belt, {"topics": [], "titles": []})
    
    all_concepts = [concept for category in BELT_SYLLABUS[belt].values() for concept in category]
    used_concepts = belt_history.get("topics", [])
    used_titles = belt_history.get("titles", [])
    
    available_concepts = list(set(all_concepts) - set(used_concepts))
    
    if not available_concepts:
        print(f"All topics for {belt} exhausted. Resetting topic history for this belt.")
        belt_history["topics"] = []
        history[belt] = belt_history
        save_history(history)
        available_concepts = all_concepts

    for attempt in range(3):
        topic = random.choice(available_concepts)
        print(f"Attempt {attempt + 1}: Generating problem for topic '{topic}'...")
        
        try:
            prompt = f"""
            # YOUR ROLE
            You are an expert DSA problem designer and a senior software engineer. Your primary goal is to create high-quality, educational, and perfectly structured problem solutions that are ready for a programming tutorial website.

            # YOUR TASK
            Generate a JSON object for a DSA problem on the topic "{topic}" suitable for a {belt} developer.
            The JSON object must have three keys: "title", "readme", and "solution".

            # INSTRUCTIONS FOR EACH KEY

            ## 1. "title"
            - A concise, accurate, and creative title for a problem about '{topic}'. The title must be unique.

            ## 2. "readme"
            - A markdown string with the following H3 subheadings in this exact order: `### Description`, `### Constraints`, `### Example`, and `### Concepts Covered`.
            - Under the `### Concepts Covered` heading, you MUST list the key concepts from the syllabus used to solve this problem as a bulleted list.

            ## 3. "solution"
            - This MUST be a single markdown string.
            - The string MUST follow this exact sequence and formatting:
                1.  A main heading: `# Solutions for [Generated Problem Title]`
                2.  A subheading: `### Approach`
                3.  A paragraph explaining the core logic, algorithm, and data structures used, including time/space complexity.
                4.  Five subheadings for each language, in this order: `## C Solution`, `## C++ Solution`, `## Java Solution`, `## Python Solution`, `## JavaScript Solution`.
                5.  Under each language heading, a single, fenced code block with the correct language identifier (e.g., ```cpp).

            # --- CRITICAL CODE REQUIREMENTS ---
            - Every code block MUST be a **complete, runnable program**.
            - The core problem-solving logic **MUST be in a separate function** (e.g., `solve()`, `findMax()`, etc.).
            - The `main` function (or equivalent global scope) **MUST ONLY** be used for handling standard input (stdin) and standard output (stdout), and for calling the logic function.
            - **DO NOT** use placeholders like "// your code here". The code must be complete.
            - Refer to the following "Sum of Two Numbers" example as a **strict structural guide**. The code you generate must follow this pattern of separating logic from I/O.

            ### --- STRUCTURAL EXAMPLE TO FOLLOW ---
            # Solutions for Sum of Two Numbers

            ### Approach
            The problem requires us to find the sum of two integers. We can achieve this by reading the two numbers from standard input, passing them to a dedicated function that calculates their sum, and then printing the returned result to standard output. The time complexity is O(1).

            ## C Solution
            ```c
            #include <stdio.h>
            int sum(int a, int b) {{ return a + b; }}
            int main() {{ int num1, num2; scanf("%d %d", &num1, &num2); printf("%d\\n", sum(num1, num2)); return 0; }}
            ```

            ## C++ Solution
            ```cpp
            #include <iostream>
            int sum(int a, int b) {{ return a + b; }}
            int main() {{ int num1, num2; std::cin >> num1 >> num2; std::cout << sum(num1, num2) << std::endl; return 0; }}
            ```

            ## Java Solution
            ```java
            import java.util.Scanner;
            public class Main {{
                public static int sum(int a, int b) {{ return a + b; }}
                public static void main(String[] args) {{ Scanner scanner = new Scanner(System.in); int num1 = scanner.nextInt(); int num2 = scanner.nextInt(); System.out.println(sum(num1, num2)); scanner.close(); }}
            }}
            ```

            ## Python Solution
            ```python
            def sum_two_numbers(a, b): return a + b
            if __name__ == "__main__": num1, num2 = map(int, input().split()); print(sum_two_numbers(num1, num2))
            ```

            ## JavaScript Solution
            ```javascript
            function sum(a, b) {{ return a + b; }}
            const readline = require('readline');
            const rl = readline.createInterface({{ input: process.stdin, output: process.stdout }});
            rl.on('line', (line) => {{ const [num1, num2] = line.split(' ').map(Number); console.log(sum(num1, num2)); rl.close(); }});
            ```
            """
            response = model.generate_content(prompt)
            cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
            data = json.loads(cleaned_text)

            if data['title'] not in used_titles:
                print(f"Success: Found unique problem titled '{data['title']}'.")
                data['topic'] = topic
                return data
            else:
                print(f"Warning: Generated a duplicate title '{data['title']}'. Retrying...")
        except Exception as e:
            print(f"Error during generation attempt: {e}")
            continue
    print("Error: Could not generate a unique problem after 3 attempts.")
    return None

def commit_problem_to_repo(belt, problem_title, readme_md, solution_md, topic):
    try:
        repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
        repo_path = os.path.join(REPOS_DIR, repo_name)
        if not os.path.exists(repo_path):
            subprocess.run(["git", "clone", REPO_URL, repo_path], check=True, capture_output=True, text=True)
        else:
            subprocess.run(["git", "-C", repo_path, "pull"], check=True, capture_output=True, text=True)
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
        log_to_google_sheet('CREATE', belt, new_folder_name, 'Committed')
        return f"Successfully committed '{problem_title}' as problem #{problem_number}."
    except Exception as e:
        log_to_google_sheet('CREATE', belt, problem_title, 'Failed')
        return f"An error occurred: {e}"

def schedule_commit(schedule_time, belt, title, readme, solution, topic):
    job = {
        "id": datetime.now().strftime('%Y%m%d%H%M%S%f'), "commit_at": schedule_time, "belt": belt,
        "title": title, "readme": readme, "solution": solution, "topic": topic
    }
    jobs = []
    if os.path.exists(SCHEDULED_JOBS_FILE):
        with open(SCHEDULED_JOBS_FILE, 'r') as f:
            try: jobs = json.load(f)
            except json.JSONDecodeError: pass
    jobs.append(job)
    with open(SCHEDULED_JOBS_FILE, 'w') as f:
        json.dump(jobs, f, indent=4)
    
    update_history(belt, topic, title)
    log_to_google_sheet('SCHEDULE', belt, title, 'Scheduled')
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
        problem_data = generate_problem_with_gemini(belt)
        if problem_data:
            problems_list.append(problem_data)
    
    if problems_list: return jsonify(problems_list)
    else: return jsonify({"message": "Could not generate a unique problem after several attempts. Please try again."}), 500

@app.route('/commit', methods=['POST'])
def commit():
    data = request.form
    belt, title, readme, solution, action, topic = data['belt'], data['problem_title'], data['readme_content'], data['solution_content'], data['commit_action'], data['topic']
    if action == 'now':
        message = commit_problem_to_repo(belt, title, readme, solution, topic)
        if "Error" in message or "failed" in message: return jsonify({"message": message}), 500
        return jsonify({"message": message})
    elif action == 'schedule':
        schedule_time = data['schedule_time']
        if not schedule_time: return jsonify({"message": "Error: Schedule time not provided."}), 400
        schedule_commit(schedule_time, belt, title, readme, solution, topic)
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
    repo_name = REPO_URL.split(':')[-1].split('/')[-1].replace(".git", "")
    repo_path = os.path.join(REPOS_DIR, repo_name)
    problem_path = os.path.join(repo_path, belt.replace(" ", "-"), problem_folder)
    try:
        subprocess.run(["git", "-C", repo_path, "pull"], check=True)
        shutil.rmtree(problem_path)
        subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", f"chore({belt}): Delete problem '{problem_folder}'"], check=True)
        subprocess.run(["git", "-C", repo_path, "push"], check=True)
        log_to_google_sheet('DELETE', belt, problem_folder, 'Deleted')
        return jsonify({"message": f"Successfully deleted '{problem_folder}'."})
    except Exception as e:
        log_to_google_sheet('DELETE', belt, problem_folder, 'Failed')
        return jsonify({"message": f"An error occurred during deletion: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)