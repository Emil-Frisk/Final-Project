import subprocess
import os
import sys
from pathlib import Path
import time
import psutil
from typing import Union

class ProcessManager:
    def __init__(self, logger, target_dir):
        self.processes = {}
        self.logger = logger
        self.entry_point = self.get_entry_point()
        self.target_dir = target_dir

    def launch_process(self, file_name, args=None) -> Union[int, None]:
        """Launch a Python file_name and return PID or none if error"""
        try:
            ### Support filenames with .py and w/o it
            res = file_name.split(".py")
            if len(res) == 2:
                file_name = res[0]
            
            file_path = os.path.join(self.target_dir, f"{file_name}.py")
            venv_python = "C:\liikealusta\.venv\Scripts\pythonw.exe"
            
            ### adding file_name to the launch options to find and check for its existance later
            cmd =  [venv_python, file_path, f"entrypoint={file_name}"]
                
            ### Prevent process recursion
            if self.entry_point == file_name:
                self.logger.error("Recursion spotted not spawning a new process")
                return 
            
            if args:
                cmd.extend(args)
                
            process = subprocess.Popen(
                cmd
            )

            pid = process.pid
            self.processes[pid] = {
                'process': process,
                'file_name': file_name,
                'launch-time': time.time()
            }
            self.logger.info(f"Launched {file_name} with PID: {process.pid}")
            return pid
        except Exception as e:
            self.logger.error(f"Failed to launch process {file_name}: {e}")
            return None

    def cleanup_process(self, pid) -> bool:
        """Cleanup a specific file_name by PID"""
        if pid not in self.processes:
            self.logger.error(f"No process found with PID: {pid}")
            return False
            
        process_info = self.processes[pid]
        process = process_info['process']
        
        try:
            # Check if the process is still running and is a Python process
            ps_process = psutil.Process(pid)
            process_name = ps_process.name().lower()
            self.logger.info((f"process_name {process_name}"))

            if 'python' not in process_name and not process_name.endswith('.exe'):
                self.logger.error(f"Process with PID {pid} is not a Python process: {process_name}")
                del self.processes[pid]
                return False

            process.kill()
            self.logger.warning(f"Force killed process {process_info['file_name']} with PID {process.pid}")
            del self.processes[pid]
            self.logger.info(f"Cleaned up process with PID {pid}")
            return True
        except Exception as e:
            self.logger.error(f"Error during process cleanup: {e}")
            return False

    def cleanup_all(self) -> None:
        """Cleanup all running processes"""
        for pid in list(self.processes.keys()):
            self.cleanup_process(pid)

    def get_entry_point(self) -> str:
        return Path(sys.argv[0]).name.split(".py")[0]

    def exterminate_lingering_process(self, process_name) -> bool:
        """Checks if a process is already running based on its name
        And returns true if it was succesful in eliminating it."""
        pid = self.get_process_info(process_name)
        if not pid:
            return True
        
        result = self.kill_python_process(pid)
        
        ### lingering process found but not killed 
        if pid and not result:
            return False
        return True
    
    def kill_process(self,pid) -> bool:
        try:
            # Checks if the process is still running and
            ps_process = psutil.Process(int(pid))
            process_name = ps_process.name().lower()
            self.logger.info((f"process_name {process_name}"))
            ps_process.kill()
            self.logger.warning(f"Force killed process: {process_name} with PID {ps_process.pid}")
            return True
        except Exception as e:
            self.logger.error

    def kill_python_process(self, pid) -> bool:
        try:
            # Check if the process is still running and is a Python process
            ps_process = psutil.Process(pid)
            process_name = ps_process.name().lower()
            self.logger.info((f"process_name {process_name}"))

            if 'python' not in process_name and not process_name.endswith('.exe'):
                self.logger.error(f"Process with PID {pid} is not a Python process: {process_name}")
                return False

            ps_process.kill()
            self.logger.warning(f"Force killed process: {process_name} with PID {ps_process.pid}")
            return True
        except Exception as e:
            self.logger.error(f"Something went wrong with trying to kill a process: {e}")
            return False

    def get_process_info(self, process_name) -> Union[int, bool]:
        """returns the processes PID or False if not successful"""
        
        ps_command= f"""
            Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
            Where-Object {{ $_.CommandLine -like "*entrypoint={process_name}*" }} |
            Select-Object ProcessId, CommandLine
            """

        try:
            result = subprocess.run(
                ["powershell.exe", "-Command", ps_command],
                capture_output=True,
                text=True,
                check=True
            )
            
            if result.stdout:
                pid = self.extract_pid_from_commandline(result.stdout)
                if not pid:
                    return False
                self.logger.info(f"Existing pid found with a process name: {process_name} pid: {pid}")
                return pid
            else:
                return False
            
        except subprocess.CalledProcessesError as e:
            self.logger.error(f"Error running PowerShell command: {e.stderr}")
            return False

    def extract_pid_from_commandline(self, result) -> Union[int, bool]:
        try:
            trimmed = result.replace(" ", "")
            results = trimmed.split("\n")
            command_lines = []
            for r in results:
                if len(r.split(".py")) == 1:
                    continue
                else:
                    command_lines.append(r)
            if len(command_lines) == 0:
                return None
            temp = command_lines[0]
            self.logger.info(f"Found {len(command_lines)} command lines")
            pid_list = []
            for ch in temp:
                try:
                    int(ch)
                    pid_list.append(ch)
                except ValueError as e:
                    break
            pid_list = "".join(pid_list)
            return int(pid_list)
        except ValueError:
            self.logger.error("Unable to extract pid from a found commandline")
            return False
        except Exception as e:
            self.logger.error("Unexpected error while extracting pid from a commandline string")

