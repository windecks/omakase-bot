#!/usr/bin/env python3
"""
Fleet Manager - Run multiple sniper/monitor tasks simultaneously.
Usage: python fleet.py tasks.yaml
"""
import sys
import yaml
import time
import logging
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from src.config import BotConfig
from src.browser import BrowserManager
from src.sniper import run_sniper
from src.monitor import run_monitor
from src.notifications import setup_logging

def run_task(task_dict: dict, startup_delay: int = 0) -> bool:
    """Worker function to execute a single bot task."""
    setup_logging()
    
    if startup_delay > 0:
        logging.info("Staggering task start: waiting %ds for %s...", startup_delay, task_dict.get("restaurant_id", "unknown"))
        time.sleep(startup_delay)
    
    # Initialize config
    cfg = BotConfig()
    for k, v in task_dict.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    
    try:
        cfg.validate()
    except SystemExit as e:
        logging.error("Task validation failed: %s", e)
        return False
        
    logging.info("Starting task: %s for %s", cfg.mode, cfg.restaurant_id)
    
    success = False
    try:
        with BrowserManager(cfg) as bm:
            if cfg.mode == "sniper":
                success = run_sniper(bm, cfg)
            elif cfg.mode == "monitor":
                success = run_monitor(bm, cfg)
            else:
                logging.error("Unknown mode: %s", cfg.mode)
    except Exception as e:
        logging.error("Task crashed: %s", e)
        traceback.print_exc()
        
    return success

def check_cloakbrowser_update() -> bool:
    try:
        import subprocess, json
        out = subprocess.check_output([sys.executable, "-m", "pip", "list", "--outdated", "--format=json"])
        packages = json.loads(out)
        return any(pkg.get("name") == "cloakbrowser" for pkg in packages)
    except Exception as e:
        logging.error("Failed to check for updates: %s", e)
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python fleet.py <tasks.yaml>")
        sys.exit(1)
        
    setup_logging()
    
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    tasks = data.get("tasks", [])
    if not tasks:
        logging.error("No tasks found in %s", sys.argv[1])
        sys.exit(1)
        
    logging.info("Starting Fleet Manager with %d tasks...", len(tasks))
    
    # Run processes
    with ProcessPoolExecutor(max_workers=len(tasks)) as executor:
        futures = {}
        for i, t in enumerate(tasks):
            futures[executor.submit(run_task, t, i * 60)] = t
        
        import concurrent.futures
        import subprocess
        import os
        import multiprocessing
        
        last_update_check = time.time()
        
        while futures:
            # Check for updates every 24 hours (24 * 3600 seconds)
            if time.time() - last_update_check > 24 * 3600:
                last_update_check = time.time()
                logging.info("Checking for cloakbrowser updates...")
                if check_cloakbrowser_update():
                    logging.info("Update found! Upgrading cloakbrowser and restarting fleet...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "cloakbrowser"])
                    # Terminate all running tasks immediately
                    for p in multiprocessing.active_children():
                        p.terminate()
                    # Restart the fleet manager process entirely
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                    
            try:
                # Wait up to 60 seconds so we can break out and evaluate the update timer
                for future in concurrent.futures.as_completed(futures, timeout=60):
                    task_dict = futures.pop(future)
                    try:
                        result = future.result()
                        if result:
                            logging.info("Task completed successfully: %s", task_dict.get("restaurant_id"))
                        else:
                            logging.warning("Task failed or ended: %s", task_dict.get("restaurant_id"))
                    except Exception as e:
                        logging.error("Task threw exception: %s", e)
                    
                    # Self-healing: Restart monitor tasks automatically if they crash or exit
                    mode = task_dict.get("mode", "sniper")
                    if mode == "monitor":
                        if result:
                            logging.info("Monitor task succeeded! NOT restarting: %s", task_dict.get("restaurant_id"))
                        else:
                            logging.info("Restarting monitor task in 10s: %s", task_dict.get("restaurant_id"))
                            time.sleep(10)
                            futures[executor.submit(run_task, task_dict, 0)] = task_dict
            except concurrent.futures.TimeoutError:
                # Expected timeout every 60s if no tasks complete, allows loop to re-evaluate the update timer
                pass
    
        logging.info("All tasks completed successfully. Idling to prevent Docker from restarting the container...")
        while True:
            time.sleep(3600)

if __name__ == "__main__":
    main()
