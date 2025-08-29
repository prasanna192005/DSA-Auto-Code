# scheduler.py
import json
import os
import time
from datetime import datetime
from app import commit_problem_to_repo # Reuse the commit function

SCHEDULED_JOBS_FILE = "scheduled_jobs.json"

def run_scheduler():
    print("Scheduler started. Checking for jobs every 60 seconds...")
    while True:
        if not os.path.exists(SCHEDULED_JOBS_FILE):
            time.sleep(60)
            continue
            
        with open(SCHEDULED_JOBS_FILE, 'r+') as f:
            try:
                jobs = json.load(f)
            except json.JSONDecodeError:
                jobs = []

            now = datetime.now()
            pending_jobs = []
            jobs_to_run = []

            for job in jobs:
                commit_time = datetime.fromisoformat(job['commit_at'])
                if commit_time <= now:
                    jobs_to_run.append(job)
                else:
                    pending_jobs.append(job)

            f.seek(0)
            f.truncate()
            json.dump(pending_jobs, f, indent=4)
        
        if jobs_to_run:
            print(f"Found {len(jobs_to_run)} job(s) to run.")
            for job in jobs_to_run:
                print(f"Running job ID {job['id']}: {job['title']}")
                commit_problem_to_repo(
                    job['belt'], 
                    job['title'], 
                    job['readme'], 
                    job['solution'],
                    job['test_cases'],
                    job['topic'],
                )
        
        time.sleep(60)

if __name__ == "__main__":
    run_scheduler()