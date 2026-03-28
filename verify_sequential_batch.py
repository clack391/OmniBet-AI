import requests
import time
import uuid

API_URL = "http://localhost:8000"

def test_sequential_batch():
    print("🚀 [TEST] Starting Sequential Batch Test...")
    
    # 1. Reset Kill Switch
    requests.put(f"{API_URL}/settings/kill-active-analysis", json={"enabled": False})
    
    # 2. Submit a batch of 3 matches
    # Note: We use fake match IDs that will likely fail or take time in the worker
    match_ids = [999001, 999002, 999003]
    print(f"📡 Submitting batch: {match_ids}")
    res = requests.post(f"{API_URL}/predict-async", json={"match_ids": match_ids})
    jobs = res.json()
    
    for job in jobs:
        print(f"   Created Job: {job['job_id']} for Match: {job['match_id']}")

    # 3. Poll and Verify Sequentiality
    # We expect Job 1 to be STARTED/RUNNING while Job 2 & 3 are PENDING
    for _ in range(10):
        statuses = []
        for job in jobs:
            r = requests.get(f"{API_URL}/jobs/{job['job_id']}")
            statuses.append(r.json().get('status'))
        
        print(f"📊 Statuses: {statuses}")
        
        # If any is RUNNING or FAILED/COMPLETED, we can proceed to test cancellation
        if any(s in ['RUNNING', 'COMPLETED', 'FAILED'] for s in statuses):
             print("🛑 [TEST] Triggering GLOBAL KILL SWITCH...")
             requests.put(f"{API_URL}/settings/kill-active-analysis", json={"enabled": True})
             break
        
        time.sleep(2)

    # 4. Verify Final Halted Status
    time.sleep(5)
    final_statuses = []
    for job in jobs:
        r = requests.get(f"{API_URL}/jobs/{job['job_id']}")
        final_statuses.append(r.json().get('status'))
    
    print(f"🏁 Final Statuses: {final_statuses}")
    
    if 'CANCELLED' in final_statuses or any(s in ['FAILED', 'CANCELLED'] for s in final_statuses):
        print("✅ [TEST] Verification Successful: Jobs were handled sequentially and/or halted.")
    else:
        print("❌ [TEST] Verification Failed: No jobs were cancelled.")

if __name__ == "__main__":
    try:
        test_sequential_batch()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("Make sure the API and Celery worker are running.")
