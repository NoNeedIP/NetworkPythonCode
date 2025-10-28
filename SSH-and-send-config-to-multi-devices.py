import re, pathlib, queue
import os, sys, time, datetime
import subprocess, multiprocessing, threading
from netmiko import ConnectHandler
#from devices_list import nwlr_device_list
from multiprocessing import Pool,Queue,Process
from ping3 import ping
#Clear CMD
def clear_screen():
    if os.name == 'posix': # linux or macOS
        _=os.system('clear')
    else: _=os.system('cls') # window

#Send command function
def send_single_command_to_multi_device(cmd,flag):
    error_str ="Invalid"
    if flag == 0: # if command is configuration command
        cfm = input("\nYou want to add command: "+cmd+ ", to devices running configuation, sure ?[Y]")
        if cfm == '' or cfm == "Y" or cfm =="y":
            for device_item in nwlr_device_list:
                try: 
                    net_connect = ConnectHandler(**device_item)
                except: print ("Can not SSH to device: "+ device_item['host'] +"\n")
                else:
                    net_connect.enable()
                    print ("Device: "+ device_item['host'])
                    result = net_connect.send_config_set(cmd)
                    if error_str in result:
                        print (result)
                        print ("Wrong command")
                    else:
                        print (result)
                    print ("\n --------------")
        else:
            return
    else: # if command is show command
        for device_item in nwlr_device_list:
            try: 
                net_connect = ConnectHandler(**device_item)
            except: print ("Can not SSH to device: "+ device_item['host'] +"\n")
            else:
                net_connect.enable()
                host_name = net_connect.send_command("show run | inc hostname")
                print (host_name + " - IP:"+ device_item['host'])
                result = net_connect.send_command(cmd)
                if error_str in result: 
                    print(result)
                    print("\n Wrong command")
                else: print(result)
            print ("\n --------------")
#backup function
def backup_config_file(Host,bk_file_path,show_usr_file_path):
    try: 
        net_connect = ConnectHandler(**Host)
    except: print ("Can not SSH to device: "+ Host['host'] +"\n")
    else:
        net_connect.enable()
        host_name = net_connect.send_command("show run | inc hostname")
        #show_cmd_usr_file_path = input("Path of file contain show commands, default is fle:show_cmd_default:")
        if show_usr_file_path =='':
            backup_content = net_connect.send_config_from_file("show_cmd_default.txt")
        else: backup_content = net_connect.send_config_from_file("show_usr_file_path")
        create_config_file(backup_content, host_name,bk_file_path)
#Create backup file
def create_config_file(config_1, config_2, bk_file_path):
    date = datetime.date.today()
    host_name = config_2.replace('hostname','')
    file_name="%s"%host_name.strip()+"_%s"%date+".txt"
    if bk_file_path =='':
        bk_file_path = "backup_config"
    full_file_path = bk_file_path + "\\" + file_name
    try:
        report_file=open(full_file_path,"w+")
        report_file.write(config_1)
        report_file.close()
        print ("- %s"%host_name.strip()+": Your backup file create scucessfully at folder:"+ full_file_path)
    except:
        print ("[ERROR] Can not create configuration file ! \n")
#main function
def main():
    #run device_list.py first, it's imported at heading, and then run clear_screen function.
    clear_screen()
    sys.tracebacklimit = 0
    banner=open("banner.txt","r") # run banner
    print(banner.read())
    banner.close()
    usr_choose = input("Choose above number: ")
    if usr_choose =='1': 
        cmd=input("Typing command you want to send devices: ")
        flag_show = 1;
        if ("show" in cmd) or ("sh" in cmd): flag_show = 1
        else: flag_show = 0
        send_single_command_to_multi_device(cmd,flag_show)
    elif usr_choose =='2':
        path_save_bk_file = input("Enter path to save backup file [/backup_config]: ")
        show_usr_file_path = input("Enter path of file contain show commands [show_cmd_default.txt]: ")
        print ("======================================")
        print ("Please wait , Your file is checking and making ... \n")
        time.sleep(2)
        for device_item in nwlr_device_list:
            backup_config_file(device_item,path_save_bk_file,show_usr_file_path)
            
        try:
            path_save_bk_file = "backup_config"
            #  Windows
            if os.name == 'nt': os.startfile(path_save_bk_file)
            #  Linux
            elif os.name == 'posix':
                os.system(f'xdg-open "{path_save_bk_file}"')
            else: print ("Don't support open folder")
        except FileNotFoundError:
            print(f"Error: Folder not found at '{path_save_bk_file}'")
    else: quit()

def pingcmd(ip_addr):
    print(ping(ip_addr))
#run file directly.
if __name__ == "__main__":
    jobs = []
    ip = ["172.20.10.51","172.20.10.52","172.20.10.53","172.20.10.54","172.20.10.55"]
    '''
    for dv in nwlr_device_list:
        ip.append(dv["host"])
        print(dv['host'])
        '''
    for i in range(len(ip)-1):
        t = threading.Thread(target=pingcmd,args=(ip[i],))
        jobs.append(t)
        t.start()
    for t in jobs:
        t.join()   
        
    '''
    try:
        rtry = 1
        while rtry:
            main()
            rtry = input("Do you want to continues?[Y]: ")
            if rtry == "Y" or rtry == "y" or rtry == "": rtry = 1
            else: 
                rtry = 0
                print("\n Bye !")
    except KeyboardInterrupt: print ("\nExit by User \n")
    except SystemExit: print ("\n [Exit by Sytem]")
    '''
