import multiprocessing, re, os, time, math, hashlib
from netmiko import ConnectHandler
from termcolor import colored
from colored import fg, attr
from rich.progress import Progress, BarColumn, TextColumn
from multiprocessing import Manager
from ping3 import ping
def clear_screen():
    if os.name == 'posix': # linux or macOS
        _=os.system('clear')
    else: _=os.system('cls') # window
def copy_file(device, tftp_cmd):
    conn = ConnectHandler(**device)
    conn.enable()
    for cmd in tftp_cmd:
        conn.send_command_timing(cmd, read_timeout=1200)
    conn.disconnect()

def show_percentage(device, filename, new_os_size, f_md5, queue):
    conn = ConnectHandler(**device)
    pattern = r'\s*-rw-\s*(\d+)'
    while True:
        output = conn.send_command(f"dir bootflash: | sec {filename}")
        match = re.search(pattern, output)
        if match:
            new_size = int(match.group(1))
            percent = math.floor(100 * (new_size / new_os_size))
            queue.put(("progress", device['host'], percent, new_size))
            if new_size >= new_os_size:
                break
        else:
            time.sleep(1)
    status = "Passed" if verify_new_md5(conn, filename, f_md5) else "Failed"
    queue.put(("done", device['host'], status))
    conn.disconnect()

def verify_new_md5(conn, filename, f_md5):
    output = conn.send_command(f"verify /md5 bootflash:{filename}", read_timeout=1200)
    match = re.search(r'=\s*(.*)', output)
    return match and match.group(1) == f_md5

def check_file_md5(filepath):
    hasher = hashlib.md5()
    with open(filepath, "rb") as file:
        for chunk in iter(lambda: file.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def file_processing(device, filename, new_os_size, file_md5, queue):
    tftp_cmd = [f"copy http://172.20.10.140/{filename} bootflash:", "\n"]
    p1 = multiprocessing.Process(target=copy_file, args=(device, tftp_cmd))
    p2 = multiprocessing.Process(target=show_percentage, args=(device, filename, new_os_size, file_md5, queue))
    p1.start()
    p2.start()
    p1.join()
    p2.join()

def monitor_progress(queue, device_totals, total_devices, results):
    with Progress(
        TextColumn("[bold blue]{task.description}: Copy"),
        BarColumn(),
        TextColumn("[green]{task.percentage:>3.0f}%"),
        TextColumn("{task.completed:.1f}/{task.total:.1f} MB"),
    ) as progress:
        tasks = {
            host: progress.add_task(f"{host}", total=size / (1024 * 1024))
            for host, size in device_totals.items()
        }

        processed = set()
        while len(processed) < total_devices:
            try:
                msg = queue.get(timeout=1)
                if msg[0] == "progress":
                    _, host, percent, current_size = msg
                    if host in tasks:
                        progress.update(tasks[host], completed=current_size / (1024 * 1024))
                elif msg[0] == "done":
                    _, host, status = msg
                    processed.add(host)
                    results[host] = status
                elif msg[0] == "skip" or msg[0] == "nospace" or msg[0] == "unknown" or msg[0] == "already" : # no copy devvice
                    _status, host = msg
                    processed.add(host)
                    results[host] = ("Already Copied firmware" if msg[0] == "skip" else "No Copy, not enough space" if msg[0] == "nospace" else "Already verion" if msg[0] == "already" else "No copy, no SSH")
                    if host in tasks:
                        progress.remove_task(tasks[host])
            except:
                continue
def up_add_firm(device, filename,add_results,added_devices):
    conn = ConnectHandler(**device)
    conn.enable()
    output = conn.send_command("show install sum | be Type")
    ver_1 = re.search(r"I\s(.*)",output)
    if ver_1:
        output = conn.send_command(f"show install ver sum | sec {ver_1.group(1)}")
        ver_1= re.search(r"CW_IMAGE:\s(.*)",output)
        add_results[device['host']] = [ver_1.group(1),"already"]
        added_devices.append(device) 
        conn.disconnect()
    else:
        # adding file    
        # write configuration in case need
        conn.send_command("wr")
        time.sleep(6)
        output = conn.send_command(f"install add file bootflash:{filename}", read_timeout=1000)
        result =  "Finished Add" in output or "success" in output.lower()
        if result:
            add_results[device['host']] = [filename,"success"]
            added_devices.append(device)     
            conn.disconnect()
        else:
            add_results[device['host']] = [ver_1.group(1),"failed"]
            conn.disconnect()
    
def up_active_firm(confirm_queue,response_queue, device, filename,add_commit,active_results):
    #print(f"ℹ️  { device["host"]}: Need confirmation to active firmware: {filename}")
    confirm_queue.put(device['host'])
    response = response_queue.get()
    if response.lower() in ["y","yes",""]:
        print(f"✅ { device["host"]}: Confirmed, now active and then reboot device ...")
        conn = ConnectHandler(**device)
        conn.enable()
        output = conn.send_command("install activate prompt-level none", read_timeout=1000)
        result =  "Finished Activate" in output or "success" in output.lower()
        if result:
            #print(colored(f"{ device['host']}: Activate success","green"))
            add_commit[device["host"]] = device
            active_results[device['host']] = "success"
            conn.disconnect()
        else: # fail is not commit
            #print(colored(f"{ device['host']}: Activate Failed","red"))
            active_results[device['host']] = "failed"
            conn.disconnect()
    else:
        print(colored(f"⚠️ {device["host"]} skip active firmware","yellow"))
        active_results[device['host']] = "skip"
def up_commit(device, commit_results,filename):
    #ping check when device is up
    while True:
        ping_results = ping(device["host"])
        if ping_results is None or ping_results is False:
            time.sleep(2)
        else: 
            break       
    time.sleep(180) # make sure device ready
    try:
        conn = ConnectHandler(**device)
    except: 
        print(f"Can not SSH to {device["host"]}, maybe Device is rebooting")
        commit_results[device["host"]] = "Not yet"
    else:
        conn.enable()
        output = conn.send_command("show version | sec Version")
        f_ver = re.search(r"universalk9\.(\d+\.\d+\.\d+[a-z]?)",filename)
        if f_ver:
            f_version = f_ver.group(1)
            if f_version in output:
                output = conn.send_command("install commit", read_timeout=1000)
                if "success" in output.lower() or "finished commit operation" in output.lower():
                    ## remove inactive file
                    output = conn.send_command("install remove inactive",expect_string = r'Do you want to remove the above files\?',read_timeout=300)
                    output += conn.send_command("y", expect_string="SUCCESS")
                    if "success" in output.lower() or "finished" in output.lower():
                        commit_results[device["host"]] = "Done"
                        conn.disconnect()
                    else:
                        commit_results[device["host"]] = "Commit Done, but Remove inactive: Failed"
                        conn.disconnect()
                else:
                    commit_results[device["host"]] = "Failed"
                    conn.disconnect()
            else:
                commit_results[device["host"]] = "Not yet"
                conn.disconnect()
        else:
            commit_results[device["host"]] = "Can't find version in file name"
            conn.disconnect()
def check_bootvar(device,skipped_hosts,active_devices,filename,unvalid_device,file_md5):
    conn = ConnectHandler(**device)
    conn.enable()
    output = conn.send_command("show version | sec Version")
    f_ver = re.search(r"universalk9\.(\d+\.\d+\.\d+[a-z]?)",filename)
    if f_ver:
        f_version = f_ver.group(1)
        if f_version in output:
            skipped_hosts[device["host"]] = "already"
            unvalid_device.append(device)
            print(colored(f"✅ {device['host']}: Installed this verion {f_version} already", "green"))
            return # quite function
            
    output = conn.send_command("show boot | sec BOOT variable")
    if "packages.conf" not in output: 
        commands = ["no boot system","boot system bootflash:packages.conf","no boot manual","end"]
        conn.send_config_set(commands)
        conn.save_config()

    output = conn.send_command(f"dir bootflash: | sec {filename}") # check file exsiting ?
    if output and verify_new_md5(conn, filename, file_md5):
        print(colored(f"✅ {device['host']}: File {filename} already exists and MD5 check passed", "green"))
        skipped_hosts[device["host"]] = "skip"
    else:
        if output: # detele wrong file
            conn.send_command_timing(f"delete bootflash:{filename}", "\n", "\n", read_timeout=600)
        print(colored(f"✅ {device['host']}: File {filename} can copy file", "green"))
        active_devices.append(device)
        
def main():

    #Banner
    clear_screen()
    
    print(colored("*********************************************","blue"))
    print(colored("        Upgrade Cisco IOS-XE Firmware        ","blue"))
    print(colored("*********************************************","blue"))
    
    file_path = r"os\c8000v-universalk9.17.12.06.SPA.bin"
    filename = os.path.basename(file_path)
    file_md5 = check_file_md5(file_path)
    new_os_size = os.path.getsize(file_path.replace("\\", "/"))
    
    #import device
    from devices_list import nwlr_device_list

    # queues and dicts definition
    queue = multiprocessing.Queue()
    manager = Manager()
    results = manager.dict()
    confirm_queue = multiprocessing.Queue()
    response_queue = multiprocessing.Queue()
    add_results = manager.dict()
    add_commit = manager.dict()
    commit_results = manager.dict()
    active_results = manager.dict()
    
    print("\nℹ️ Checking resource:")
    skipped_hosts = manager.dict()
    active_devices = []
    unvalid_device = []
    added_devices = manager.list()
    
    #### CHECK RESOURCE ####
     
    for device in nwlr_device_list:
        try:
            conn = ConnectHandler(**device)
            conn.enable()
            
            ## Check free space before copy
            
            free_space = conn.send_command("dir bootflash: | inc free") # get free space
            if re.search(r"(\d+)\sbytes\sfree",free_space) and (int(re.search(r"(\d+)\sbytes\sfree",free_space).group(1)) > int(new_os_size)): # if enough space
                #check system boot
                conn.disconnect()
                check_bootvar(device,skipped_hosts,active_devices,filename,unvalid_device,file_md5)
                
            else:
                # devices are not enough space, do: install remove inactive
                output = conn.send_command("install remove inactive",expect_string = r'Do you want to remove the above files\?',read_timeout=300)
                output += conn.send_command("y", expect_string="SUCCESS")
                # check space one more time
                if re.search(r"(\d+)\sbytes\sfree",free_space) and (int(re.search(r"(\d+)\sbytes\sfree",free_space).group(1)) > int(new_os_size)):
                    conn.disconnect()
                    check_bootvar(device,skipped_hosts,active_devices,filename,unvalid_device,file_md5)
                else:    
                    print(colored(f"⚠️ {device['host']}: is NOT enough space", "red"))
                    skipped_hosts[device["host"]] = "nospace"
                    unvalid_device.append(device)
                    conn.disconnect()
        except Exception as e:
            skipped_hosts[device["host"]] = "unknown"
            unvalid_device.append(device)
            print(colored(f"❌ {device['host']}: SSH Connection failed", "red"))
            print(e)
    
    #### COPY FIRMWARE ####
    
    print("\nℹ️ Copying firmware to device:")
    
    device_totals = {device['host']: new_os_size for device in active_devices} # dictionary ip:os size
    
    total_devices = len(nwlr_device_list) # how many device

    monitor = multiprocessing.Process(target=monitor_progress, args=(queue, device_totals, total_devices, results)) # call process
    monitor.start()
    
    processes = []
    for device in active_devices:
        proc = multiprocessing.Process(target=file_processing, args=(device, filename, new_os_size, file_md5, queue))
        processes.append(proc)
        proc.start()

    for proc in processes:
        proc.join()

    for host, status in skipped_hosts.items():
        if status == "skip":
            queue.put(("skip", host))
        if status == "nospace":
            queue.put(("nospace",host))
        if status == "unknown":
            queue.put(("unknown",host))
        if status == "already":
            queue.put(("already",host))
           
    monitor.join()
    
    # Check MD5 after copy completed
    
    print("\nℹ️ Copy Firmware Results (MD5 Check):")
    for device in nwlr_device_list:
        host = device['host']
        status = results.get(host,"Not available")
        color = ("green" if status == "Passed" else "red" if status == "Failed" else "cyan")
        print(colored(f"{host}: {status}",color))
    
    # UPGRADE FIRMWARE INSTALL MODE
    
    upornot = input(f"\n{fg("light_yellow")}❓ Do you want to proceed upgrade firmware for active devices? [Y/n]:{attr("reset")}")
    
    if upornot.lower() in ["y","yes",""]:
        
        print("\nℹ️ Install Add Firmware:")
        
        # create new array include active devices
        org_dv_list = set(frozenset(d.items()) for d in nwlr_device_list)
        unvalid_device = set(frozenset(d.items()) for d in unvalid_device)
        new_list = org_dv_list ^ unvalid_device
        act_nwlr_device_list = [dict(d) for d in new_list]
        
        processes = []
        
        for device in act_nwlr_device_list:
            proc = multiprocessing.Process(target = up_add_firm, args =(device,filename,add_results,added_devices)) 
            processes.append(proc)
            proc.start()
        for proc in processes:
            proc.join()
        
        ## print install add file
        for device, v in add_results.items():
            status = v[1]
            color = ("cyan" if status == "already" else "green" if status == "success" else "red")
            print(colored(f"{device} Install add file: {status}",color))

        # Active firmware
        print("\nℹ️ Now activing firmware:")
 
        for device in added_devices:
            proc = multiprocessing.Process(target = up_active_firm, args = (confirm_queue,response_queue, device, filename,add_commit,active_results)) 
            processes.append(proc)
            proc.start()
            
        for _ in  added_devices:
            host = confirm_queue.get()
            fw = add_results[host][0]
            response = input(f"{fg("light_yellow")}❓Confirm active firmware:{fw} on {host}? [Y/n]: {attr("reset")}")
            response_queue.put(response)
            
        for proc in processes:
            proc.join()         # wait all activate process done
        
        print("\nℹ️ Activate Firmware Results:")
        for device, status in active_results.items():
            color = ("green" if status == "success" else "red" if status == "failed" else "cyan")
            print(colored(f"{device} Activate: {status}",color))
         
        #commit and remove inactive if have
       
        print(colored("\nℹ️ Committing device:"))
        for _, device in add_commit.items():
            proc = multiprocessing.Process(target = up_commit, args = (device,commit_results,filename)) 
            processes.append(proc)
            proc.start()
            
        for proc in processes:
            proc.join()
        
        #print commit results
        for host, status in commit_results.items():
            color = ("green" if status =="Done" else "cyan" if status == "Not yet" else "red")
            print(colored(f"{host} commit : {status}",color))
        ## print summary
        
        #for device in act_nwlr_device_list:
            
    else:
        print("\nBye")
 
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e)
        
