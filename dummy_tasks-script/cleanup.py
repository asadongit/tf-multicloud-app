import httpx

TASKS_URL = "http://127.0.0.1:8001/api/tasks"
DELETE_URL = "http://127.0.0.1:8001/api/admin/tasks"
HEADERS = {"X-Admin-Token": "admin-token"}

prefixes = ("aws-", "azure-", "gcp-", "kubernetes-", "local-")

def cleanup_realistic_tasks():
    print("Fetching tasks to identify realistic tasks...")
    
    with httpx.Client() as client:
        try:
            response = client.get(TASKS_URL)
            response.raise_for_status()
            tasks = response.json()
        except Exception as e:
            print(f"Failed to fetch tasks: {e}")
            return
            
        target_tasks = [t for t in tasks if t["task_name"].startswith(prefixes)]
        print(f"Found {len(target_tasks)} realistic tasks to delete.")
        
        for t in target_tasks:
            name = t["task_name"]
            try:
                del_res = client.delete(f"{DELETE_URL}/{name}", headers=HEADERS)
                if del_res.status_code == 204:
                    print(f"Deleted successfully: {name}")
                else:
                    print(f"Failed to delete {name}: {del_res.status_code} - {del_res.text}")
            except Exception as e:
                print(f"Error deleting {name}: {e}")
                
    print("Cleanup finished.")

if __name__ == "__main__":
    cleanup_realistic_tasks()

