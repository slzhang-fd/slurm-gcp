#!/usr/bin/python

# Copyright 2017 SchedMD LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import httplib
import os
import shlex
import shutil
import socket
import subprocess
import time
import urllib
import urllib2
import threading

CLUSTER_NAME      = '@CLUSTER_NAME@'
MACHINE_TYPE      = '@MACHINE_TYPE@' # e.g. n1-standard-1, n1-starndard-2
INSTANCE_TYPE     = '@INSTANCE_TYPE@' # e.g. controller, login, compute

PROJECT           = '@PROJECT@'
ZONE              = '@ZONE@'

APPS_DIR          = '/apps'
CURR_SLURM_DIR    = APPS_DIR + '/slurm/current'
MUNGE_DIR         = "/etc/munge"
MUNGE_KEY         = '@MUNGE_KEY@'
SLURM_VERSION     = '@SLURM_VERSION@'
STATIC_NODE_COUNT = @STATIC_NODE_COUNT@
MAX_NODE_COUNT    = @MAX_NODE_COUNT@
DEF_SLURM_ACCT    = '@DEF_SLURM_ACCT@'
DEF_SLURM_USERS   = '@DEF_SLURM_USERS@'
EXTERNAL_COMPUTE_IPS = @EXTERNAL_COMPUTE_IPS@
GPU_TYPE          = '@GPU_TYPE@'
GPU_COUNT         = @GPU_COUNT@
CONTROLLER_SECONDARY_DISK = @CONTROLLER_SECONDARY_DISK@
SEC_DISK_DIR      = '/mnt/disks/sec'
PREEMPTIBLE       = @PREEMPTIBLE@
SUSPEND_TIME      = @SUSPEND_TIME@

NETWORK_STORAGE   = @NETWORK_STORAGE@
EXTERNAL_MOUNT_APPS = 0
EXTERNAL_MOUNT_HOME = 0
EXTERNAL_MOUNT_MUNGE = 0

DEF_PART_NAME   = "debug"
CONTROL_MACHINE = CLUSTER_NAME + '-controller'

SLURM_PREFIX  = APPS_DIR + '/slurm/slurm-' + SLURM_VERSION

OMPI_VERSION = "v3.1.x"

MOTD_HEADER = '''

                                 SSSSSSS
                                SSSSSSSSS
                                SSSSSSSSS
                                SSSSSSSSS
                        SSSS     SSSSSSS     SSSS
                       SSSSSS               SSSSSS
                       SSSSSS    SSSSSSS    SSSSSS
                        SSSS    SSSSSSSSS    SSSS
                SSS             SSSSSSSSS             SSS
               SSSSS    SSSS    SSSSSSSSS    SSSS    SSSSS
                SSS    SSSSSS   SSSSSSSSS   SSSSSS    SSS
                       SSSSSS    SSSSSSS    SSSSSS
                SSS    SSSSSS               SSSSSS    SSS
               SSSSS    SSSS     SSSSSSS     SSSS    SSSSS
          S     SSS             SSSSSSSSS             SSS     S
         SSS            SSSS    SSSSSSSSS    SSSS            SSS
          S     SSS    SSSSSS   SSSSSSSSS   SSSSSS    SSS     S
               SSSSS   SSSSSS   SSSSSSSSS   SSSSSS   SSSSS
          S    SSSSS    SSSS     SSSSSSS     SSSS    SSSSS    S
    S    SSS    SSS                                   SSS    SSS    S
    S     S                                                   S     S
                SSS
                SSS
                SSS
                SSS
 SSSSSSSSSSSS   SSS   SSSS       SSSS    SSSSSSSSS   SSSSSSSSSSSSSSSSSSSS
SSSSSSSSSSSSS   SSS   SSSS       SSSS   SSSSSSSSSS  SSSSSSSSSSSSSSSSSSSSSS
SSSS            SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSS            SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSS    SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
 SSSSSSSSSSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
         SSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
         SSSS   SSS   SSSS       SSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSSS   SSS   SSSSSSSSSSSSSSS   SSSS        SSSS     SSSS     SSSS
SSSSSSSSSSSS    SSS    SSSSSSSSSSSSS    SSSS        SSSS     SSSS     SSSS


'''

def add_slurm_user():

    SLURM_UID = str(992)
    subprocess.call(['groupadd', '-g', SLURM_UID, 'slurm'])
    subprocess.call(['useradd', '-m', '-c', 'SLURM Workload Manager',
        '-d', '/var/lib/slurm', '-u', SLURM_UID, '-g', 'slurm',
        '-s', '/bin/bash', 'slurm'])

# END add_slurm_user()


def setup_modules():

    appsmfs = '/apps/modulefiles'

    if appsmfs not in open('/usr/share/Modules/init/.modulespath').read():
        if INSTANCE_TYPE == 'controller' and not os.path.isdir(appsmfs):
            subprocess.call(['mkdir', '-p', appsmfs])

        with open('/usr/share/Modules/init/.modulespath', 'a') as dotmp:
            dotmp.write(appsmfs)

# END setup_modules()


def start_motd():

    msg = MOTD_HEADER + """
*** Slurm is currently being installed/configured in the background. ***
A terminal broadcast will announce when installation and configuration is
complete.

Partition {} will be marked down until the compute image has been created.
For instances with gpus attached, it could take ~10 mins after the controller
has finished installing.

""".format(DEF_PART_NAME)

    if INSTANCE_TYPE != "controller":
        msg += """/home on the controller will be mounted over the existing /home.
Any changes in /home will be hidden. Please wait until the installation is
complete before making changes in your home directory.

"""

    f = open('/etc/motd', 'w')
    f.write(msg)
    f.close()

    print "ww Began installing controller"

# END start_motd()


def end_motd(broadcast=True):
    print "ww Completed Startup-Script"

    f = open('/etc/motd', 'w')
    f.write(MOTD_HEADER)
    f.close()

    if not broadcast:
        return

    subprocess.call(['wall', '-n',
        '*** Slurm ' + INSTANCE_TYPE + ' daemon installation complete ***'])

    if INSTANCE_TYPE != "controller":
        subprocess.call(['wall', '-n', """
/home on the controller was mounted over the existing /home.
Either log out and log back in or cd into ~.
"""])

#END start_motd()


def have_internet():
    conn = httplib.HTTPConnection("www.google.com", timeout=1)
    try:
        conn.request("HEAD", "/")
        conn.close()
        return True
    except:
        conn.close()
        return False

#END have_internet()


def install_packages():

    print "ww Installing packages"

    packages = ['bind-utils',
                'epel-release',
                'gcc',
                'git',
                'hwloc',
                'hwloc-devel',
                'libibmad',
                'libibumad',
                'lua',
                'lua-devel',
                'man2html',
                'mariadb',
                'mariadb-devel',
                'mariadb-server',
                'munge',
                'munge-devel',
                'munge-libs',
                'ncurses-devel',
                'nfs-utils',
                'numactl',
                'numactl-devel',
                'openssl-devel',
                'pam-devel',
                'perl-ExtUtils-MakeMaker',
                'python-pip',
                'readline-devel',
                'rpm-build',
                'rrdtool-devel',
                'vim',
                'wget',
                'tmux',
                'pdsh',
                'autoconf',
                'flex',
                'gcc-c++',
                'libevent-devel',
                'libtool']

    while subprocess.call(['yum', 'update', '-y']):
        print "yum failed to update packages. Trying again in 5 seconds"
        time.sleep(5)

    while subprocess.call(['yum', 'install', '-y'] + packages):
        print "yum failed to install packages. Trying again in 5 seconds"
        time.sleep(5)

    while subprocess.call(['pip', 'install', '--upgrade',
        'google-api-python-client']):
        print "failed to install google python api client. Trying again 5 seconds."
        time.sleep(5)

    if GPU_COUNT and (INSTANCE_TYPE == "compute") and not os.path.exists("/usr/lib/firmware/nvidia"):
        rpm = "cuda-repo-rhel7-10.0.130-1.x86_64.rpm"
        subprocess.call("yum -y install kernel-devel-$(uname -r) kernel-headers-$(uname -r)", shell=True)
        subprocess.call(shlex.split("wget http://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/" + rpm))
        subprocess.call(shlex.split("rpm -i " + rpm))
        subprocess.call(shlex.split("yum clean all"))
        subprocess.call(shlex.split("yum -y install cuda"))
        subprocess.call(shlex.split("nvidia-smi")) # Creates the device files

#END install_packages()


def setup_munge():
    print "ww Installing munge"

    munge_service_path = "/usr/lib/systemd/system/munge.service"
    remove(munge_service_path)
    f = open(munge_service_path, 'w')
    f.write("""
[Unit]
Description=MUNGE authentication service
Documentation=man:munged(8)
After=network.target
After=syslog.target
After=time-sync.target
""")

    if (INSTANCE_TYPE != "controller"):
        f.write("RequiresMountsFor={}\n".format(MUNGE_DIR))

    f.write("""
[Service]
Type=forking
ExecStart=/usr/sbin/munged --num-threads=10
PIDFile=/var/run/munge/munged.pid
User=munge
Group=munge
Restart=on-abort

[Install]
WantedBy=multi-user.target""")
    f.close()

    subprocess.call(['systemctl', 'enable', 'munge'])

    if ((INSTANCE_TYPE == "controller")):
        if MUNGE_KEY:
            remove(MUNGE_DIR + '/munge.key')
            f = open(MUNGE_DIR +'/munge.key', 'w')
            f.write(MUNGE_KEY)
            f.close()

            subprocess.call(['chown', '-R', 'munge:', MUNGE_DIR, '/var/log/munge/'])
            os.chmod(MUNGE_DIR + '/munge.key' ,0o400)
            os.chmod(MUNGE_DIR                ,0o700)
            os.chmod('/var/log/munge/'        ,0o700)
        else:
            subprocess.call(['create-munge-key'])

#END setup_munge()

def start_munge():

    subprocess.call(['systemctl', 'start', 'munge'])

#END start_munge()

def setup_nfs_exports():

    f = open('/etc/exports', 'w')
    if EXTERNAL_MOUNT_HOME == 0:
        os.system("sed -i '/\/home/d' /etc/exports")
        f.write("""
/home  *(rw,no_subtree_check,no_root_squash)
""")
    if EXTERNAL_MOUNT_APPS == 0:
        os.system("sed -i '/\{}/d' /etc/exports".format(APPS_DIR))
        f.write("""
%s  *(rw,no_subtree_check,no_root_squash)
""" % APPS_DIR)
    if EXTERNAL_MOUNT_MUNGE == 0:
        os.system("sed -i '/\/etc\/munge/d' /etc/exports")
        f.write("""
/etc/munge *(rw,no_subtree_check,no_root_squash)
""")
    if CONTROLLER_SECONDARY_DISK:
        os.system("sed -i '/{}/d' /etc/exports".format(SEC_DISK_DIR))
        f.write("""
%s  *(rw,no_subtree_check,no_root_squash)
""" % SEC_DISK_DIR)
    f.close()

    subprocess.call(shlex.split("exportfs -a"))

#END setup_nfs_exports()


def expand_machine_type():

    # Force re-evaluation of site-packages so that namespace packages (such
    # as google-auth) are importable. This is needed because we install the
    # packages while this script is running and do not have the benefit of
    # restarting the interpreter for it to do it's usual startup sequence to
    # configure import magic.
    import sys
    import site
    for path in [x for x in sys.path if 'site-packages' in x]:
        site.addsitedir(path)

    import googleapiclient.discovery

    # Assume sockets is 1. Currently, no instances with multiple sockets
    # Assume hyper-threading is on and 2 threads per core
    machine = {'sockets': 1, 'cores': 1, 'threads': 1, 'memory': 1}

    try:
        compute = googleapiclient.discovery.build('compute', 'v1',
                                                  cache_discovery=False)
        type_resp = compute.machineTypes().get(project=PROJECT, zone=ZONE,
                machineType=MACHINE_TYPE).execute()
        if type_resp:
            tot_cpus = type_resp['guestCpus']
            if tot_cpus > 1:
                machine['cores']   = tot_cpus / 2
                machine['threads'] = 2

            # Because the actual memory on the host will be different than what
            # is configured (e.g. kernel will take it). From experiments, about
            # 16 MB per GB are used (plus about 400 MB buffer for the first
            # couple of GB's. Using 30 MB to be safe.
            gb = type_resp['memoryMb'] / 1024;
            machine['memory'] = type_resp['memoryMb'] - (400 + (gb * 30))

    except Exception, e:
        print "Failed to get MachineType '%s' from google api (%s)" % (MACHINE_TYPE, str(e))

    return machine

#END expand_machine_type()


def install_slurm_conf():

    machine = expand_machine_type()
    def_mem_per_cpu = max(100,
            (machine['memory'] /
             (machine['threads']*machine['cores']*machine['sockets'])))

    conf = """
# slurm.conf file generated by configurator.html.
# Put this file on all nodes of your cluster.
# See the slurm.conf man page for more information.
#
ControlMachine={control_machine}
#ControlAddr=
#BackupController=
#BackupAddr=
#
AuthType=auth/munge
AuthInfo=cred_expire=120
#CheckpointType=checkpoint/none
CryptoType=crypto/munge
#DisableRootJobs=NO
#EnforcePartLimits=NO
#Epilog=
#EpilogSlurmctld=
#FirstJobId=1
#MaxJobId=999999
#GroupUpdateForce=0
#GroupUpdateTime=600
#JobCheckpointDir=/var/slurm/checkpoint
#JobCredentialPrivateKey=
#JobCredentialPublicCertificate=
#JobFileAppend=0
#JobRequeue=1
#JobSubmitPlugins=1
#KillOnBadExit=0
#LaunchType=launch/slurm
#Licenses=foo*4,bar
#MailProg=/bin/mail
#MaxJobCount=5000
#MaxStepCount=40000
#MaxTasksPerNode=128
MpiDefault=pmi2
#MpiParams=ports=#-#
#PluginDir=
#PlugStackConfig=
#PrivateData=jobs
LaunchParameters=send_gids

# Always show cloud nodes. Otherwise cloud nodes are hidden until they are
# resumed. Having them shown can be useful in detecting downed nodes.
# NOTE: slurm won't allocate/resume nodes that are down. So in the case of
# preemptible nodes -- if gcp preempts a node, the node will eventually be put
# into a down date because the node will stop responding to the controller.
# (e.g. SlurmdTimeout).
PrivateData=cloud

ProctrackType=proctrack/cgroup

#Prolog=
#PrologFlags=
#PrologSlurmctld=
#PropagatePrioProcess=0
#PropagateResourceLimits=
#PropagateResourceLimitsExcept=Sched
#RebootProgram=

ReturnToService=2
#SallocDefaultCommand=
SlurmctldPidFile=/var/run/slurm/slurmctld.pid
SlurmctldPort=6820-6830
SlurmdPidFile=/var/run/slurm/slurmd.pid
SlurmdPort=6818
SlurmdSpoolDir=/var/spool/slurmd
SlurmUser=slurm
#SlurmdUser=root
#SrunEpilog=
#SrunProlog=
StateSaveLocation={apps_dir}/slurm/state
SwitchType=switch/none
#TaskEpilog=
TaskPlugin=task/affinity,task/cgroup
#TaskPluginParam=
#TaskProlog=
#TopologyPlugin=topology/tree
#TmpFS=/tmp
#TrackWCKey=no
#TreeWidth=
#UnkillableStepProgram=
#UsePAM=0
#
#
# TIMERS
#BatchStartTimeout=10
#CompleteWait=0
#EpilogMsgTime=2000
#GetEnvTimeout=2
#HealthCheckInterval=0
#HealthCheckProgram=
InactiveLimit=0
KillWait=30
MessageTimeout=60
#ResvOverRun=0
MinJobAge=300
#OverTimeLimit=0
SlurmctldTimeout=120
SlurmdTimeout=300
#UnkillableStepTimeout=60
#VSizeFactor=0
Waittime=0
#
#
# SCHEDULING
FastSchedule=1
DefMemPerCPU={def_mem_per_cpu}
#MaxMemPerCPU=0
#SchedulerTimeSlice=30
SchedulerType=sched/backfill
SelectType=select/cons_res
SelectTypeParameters=CR_Core_Memory
#
#
# JOB PRIORITY
#PriorityFlags=
#PriorityType=priority/basic
#PriorityDecayHalfLife=
#PriorityCalcPeriod=
#PriorityFavorSmall=
#PriorityMaxAge=
#PriorityUsageResetPeriod=
#PriorityWeightAge=
#PriorityWeightFairshare=
#PriorityWeightJobSize=
#PriorityWeightPartition=
#PriorityWeightQOS=
#
#
# LOGGING AND ACCOUNTING
AccountingStorageEnforce=associations,limits,qos,safe
AccountingStorageHost={control_machine}
#AccountingStorageLoc=
#AccountingStoragePass=
#AccountingStoragePort=
AccountingStorageType=accounting_storage/slurmdbd
#AccountingStorageUser=
AccountingStoreJobComment=YES
ClusterName={cluster_name}
#DebugFlags=powersave
#JobCompHost=
#JobCompLoc=
#JobCompPass=
#JobCompPort=
JobCompType=jobcomp/none
#JobCompUser=
#JobContainerType=job_container/none
JobAcctGatherFrequency=30
JobAcctGatherType=jobacct_gather/linux
SlurmctldDebug=info
SlurmctldLogFile={apps_dir}/slurm/log/slurmctld.log
SlurmdDebug=debug
SlurmdLogFile=/var/log/slurm/slurmd-%n.log
#
#
# POWER SAVE SUPPORT FOR IDLE NODES (optional)
SuspendProgram={apps_dir}/slurm/scripts/suspend.py
ResumeProgram={apps_dir}/slurm/scripts/resume.py
ResumeFailProgram={apps_dir}/slurm/scripts/suspend.py
SuspendTimeout=600
ResumeTimeout=600
ResumeRate=0
#SuspendExcNodes=
#SuspendExcParts=
SuspendRate=0
SuspendTime={suspend_time}
#
SchedulerParameters=salloc_wait_nodes
SlurmctldParameters=cloud_dns,idle_on_node_suspend
CommunicationParameters=NoAddrCache
#
# COMPUTE NODES
""".format(apps_dir        = APPS_DIR,
           cluster_name    = CLUSTER_NAME,
           control_machine = CONTROL_MACHINE,
           def_mem_per_cpu = def_mem_per_cpu,
           suspend_time    = SUSPEND_TIME)

    if GPU_COUNT:
        conf += "GresTypes=gpu\n"

    conf += ' '.join(("NodeName=DEFAULT",
                      "Sockets="        + str(machine['sockets']),
                      "CoresPerSocket=" + str(machine['cores']),
                      "ThreadsPerCore=" + str(machine['threads']),
                      "RealMemory="     + str(machine['memory']),
                      "State=UNKNOWN"))

    if GPU_COUNT:
        conf += " Gres=gpu:" + str(GPU_COUNT)
    conf += "\n"

    static_range = ""
    if STATIC_NODE_COUNT and STATIC_NODE_COUNT > 1:
        static_range = "[1-%d]" % STATIC_NODE_COUNT
    elif STATIC_NODE_COUNT:
        static_range = "1"

    cloud_range = ""
    if MAX_NODE_COUNT and (MAX_NODE_COUNT != STATIC_NODE_COUNT):
        cloud_range = "[%d-%d]" % (STATIC_NODE_COUNT+1, MAX_NODE_COUNT)

    if static_range:
        conf += """
SuspendExcNodes={1}-compute{0}
NodeName={1}-compute{0}
""".format(static_range, CLUSTER_NAME)

    if cloud_range:
        conf += "NodeName={0}-compute{1} State=CLOUD".format(CLUSTER_NAME, cloud_range)

    conf += """
PartitionName={} Nodes={}-compute[1-{}] Default=YES MaxTime=INFINITE State=UP LLN=yes
""".format(DEF_PART_NAME, CLUSTER_NAME, MAX_NODE_COUNT)

    etc_dir = CURR_SLURM_DIR + '/etc'
    makedir(etc_dir)
    remove(etc_dir + '/slurm.conf')
    f = open(etc_dir + '/slurm.conf', 'w')
    f.write(conf)
    f.close()
#END install_slurm_conf()


def install_slurmdbd_conf():

    conf = """
#ArchiveEvents=yes
#ArchiveJobs=yes
#ArchiveResvs=yes
#ArchiveSteps=no
#ArchiveSuspend=no
#ArchiveTXN=no
#ArchiveUsage=no

AuthType=auth/munge
DbdHost={control_machine}
DebugLevel=debug2

#PurgeEventAfter=1month
#PurgeJobAfter=12month
#PurgeResvAfter=1month
#PurgeStepAfter=1month
#PurgeSuspendAfter=1month
#PurgeTXNAfter=12month
#PurgeUsageAfter=24month

LogFile={apps_dir}/slurm/log/slurmdbd.log
PidFile=/var/run/slurm/slurmdbd.pid

SlurmUser=slurm
StorageUser=slurm

StorageLoc=slurm_acct_db

StorageType=accounting_storage/mysql
#StorageUser=database_mgr
#StoragePass=shazaam

""".format(apps_dir = APPS_DIR, control_machine = CONTROL_MACHINE)
    etc_dir = CURR_SLURM_DIR + '/etc'
    makedir(etc_dir)
    remove(etc_dir + '/slurmdbd.conf')
    f = open(etc_dir + '/slurmdbd.conf', 'w')
    f.write(conf)
    f.close()

#END install_slurmdbd_conf()


def install_cgroup_conf():

    etc_dir = CURR_SLURM_DIR + '/etc'

    if not os.path.exists(etc_dir + '/cgroup.conf'):
        conf = """
CgroupAutomount=no
#CgroupMountpoint=/sys/fs/cgroup
ConstrainCores=yes
ConstrainRamSpace=yes
ConstrainSwapSpace=yes
TaskAffinity=no
ConstrainDevices=yes
"""

        f = open(etc_dir + '/cgroup.conf', 'w')
        f.write(conf)
        f.close()

    if not os.path.exists(etc_dir + '/cgroup_allowed_device_file.conf'):
        f = open(etc_dir + '/cgroup_allowed_devices_file.conf', 'w')
        f.write("")
        f.close()

    if GPU_COUNT:
        remove(etc_dir + '/gres.conf')
        f = open(etc_dir + '/gres.conf', 'w')
        f.write("NodeName=%s-compute[1-%d] Name=gpu File=/dev/nvidia[0-%d]"
                % (CLUSTER_NAME, MAX_NODE_COUNT, (GPU_COUNT - 1)))
        f.close()

#END install_cgroup_conf()


def install_meta_files():

    scripts_path = APPS_DIR + '/slurm/scripts'
    makedir(scripts_path)

    GOOGLE_URL = "http://metadata.google.internal/computeMetadata/v1/instance/attributes"

    meta_files = [
        {'file': 'suspend.py', 'meta': 'slurm_suspend'},
        {'file': 'resume.py', 'meta': 'slurm_resume'},
        {'file': 'startup-script.py', 'meta': 'startup-script-compute'},
        {'file': 'slurm-gcp-sync.py', 'meta': 'slurm-gcp-sync'},
        {'file': 'compute-shutdown', 'meta': 'compute-shutdown'},
        {'file': 'custom-compute-install', 'meta': 'custom-compute-install'},
        {'file': 'custom-controller-install', 'meta': 'custom-controller-install'},
    ]

    for meta in meta_files:
        file_name = meta['file']
        meta_name = meta['meta']

        req = urllib2.Request("{}/{}".format(GOOGLE_URL, meta_name))
        req.add_header('Metadata-Flavor', 'Google')
        resp = urllib2.urlopen(req)

        remove("{}/{}".format(scripts_path, file_name))
        f = open("{}/{}".format(scripts_path, file_name), 'w')
        f.write(resp.read())
        f.close()
        os.chmod("{}/{}".format(scripts_path, file_name), 0o755)

        subprocess.call(shlex.split("gcloud compute instances remove-metadata {} --zone={} --keys={}".
                                    format(CONTROL_MACHINE, ZONE, meta_name)))

#END install_meta_files()

def install_slurm():
    print "ww Installing Slurm"

    if not os.path.exists(APPS_DIR + "/slurm/scripts"):
        SLURM_PREFIX = "";

        prev_path = os.getcwd()

        SRC_PATH = APPS_DIR + "/slurm/src"
        makedir(SRC_PATH)
        os.chdir(SRC_PATH)

        use_version = "";
        if (SLURM_VERSION[0:2] == "b:"):
            GIT_URL = "https://github.com/SchedMD/slurm.git"
            use_version = SLURM_VERSION[2:]
            subprocess.call(
                shlex.split("git clone -b {0} {1} {0}".format(
                    use_version, GIT_URL)))
        else:
            SCHEDMD_URL = 'https://download.schedmd.com/slurm/'
            file = "slurm-%s.tar.bz2" % SLURM_VERSION
            urllib.urlretrieve(SCHEDMD_URL + file, SRC_PATH + '/' + file)

            cmd = "tar -xvjf " + file
            use_version = subprocess.check_output(
                shlex.split(cmd)).splitlines()[0][:-1]

        os.chdir(use_version)
        SLURM_PREFIX  = APPS_DIR + '/slurm/' + use_version

        makedir('build')
        os.chdir('build')
        subprocess.call(['../configure', '--prefix=%s' % SLURM_PREFIX,
                         '--sysconfdir=%s/etc' % CURR_SLURM_DIR])
        subprocess.call(['make', '-j', 'install'])
        os.chdir('contribs/pmi2')
        subprocess.call(['make', '-j', 'install'])

        subprocess.call(shlex.split("ln -s %s %s" % (SLURM_PREFIX, CURR_SLURM_DIR)))

        os.chdir(prev_path)

        if not os.path.exists(APPS_DIR + '/slurm/state'):
            os.makedirs(APPS_DIR + '/slurm/state')
            subprocess.call(['chown', '-R', 'slurm:', APPS_DIR + '/slurm/state'])
        if not os.path.exists(APPS_DIR + '/slurm/log'):
            os.makedirs(APPS_DIR + '/slurm/log')
            subprocess.call(['chown', '-R', 'slurm:', APPS_DIR + '/slurm/log'])

    install_slurm_conf()
    install_slurmdbd_conf()
    install_cgroup_conf()
    install_meta_files()

#END install_slurm()

def install_slurm_tmpfile():

    if not os.path.exists('/etc/tmpfiles.d/slurm.conf'):
        run_dir = '/var/run/slurm'

        f = open('/etc/tmpfiles.d/slurm.conf', 'w')
        f.write("""
d %s 0755 slurm slurm -
""" % run_dir)
        f.close()

        makedir(run_dir)

        os.chmod(run_dir, 0o755)
        subprocess.call(['chown', 'slurm:', run_dir])

#END install_slurm_tmpfile()

def install_controller_service_scripts():

    install_slurm_tmpfile()

    # slurmctld.service
    if not os.path.exists('/usr/lib/systemd/system/slurmctld.service'):
        f = open('/usr/lib/systemd/system/slurmctld.service', 'w')
        f.write("""
[Unit]
Description=Slurm controller daemon
After=network.target munge.service
ConditionPathExists={prefix}/etc/slurm.conf

[Service]
Type=forking
EnvironmentFile=-/etc/sysconfig/slurmctld
ExecStart={prefix}/sbin/slurmctld $SLURMCTLD_OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
PIDFile=/var/run/slurm/slurmctld.pid

[Install]
WantedBy=multi-user.target
""".format(prefix = CURR_SLURM_DIR))
        f.close()

        os.chmod('/usr/lib/systemd/system/slurmctld.service', 0o644)

        # slurmdbd.service
    if not os.path.exists('/usr/lib/systemd/system/slurmdbd.service'):
        f = open('/usr/lib/systemd/system/slurmdbd.service', 'w')
        f.write("""
[Unit]
Description=Slurm DBD accounting daemon
After=network.target munge.service
ConditionPathExists={prefix}/etc/slurmdbd.conf

[Service]
Type=forking
EnvironmentFile=-/etc/sysconfig/slurmdbd
ExecStart={prefix}/sbin/slurmdbd $SLURMDBD_OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
PIDFile=/var/run/slurm/slurmdbd.pid

[Install]
WantedBy=multi-user.target
""".format(prefix = CURR_SLURM_DIR))
        f.close()

        setup_sync_cronjob()

    os.chmod('/usr/lib/systemd/system/slurmdbd.service', 0o644)

#END install_controller_service_scripts()


def install_compute_service_scripts():

    install_slurm_tmpfile()

    # slurmd.service
    if not os.path.exists('/usr/lib/systemd/system/slurmd.service'):
        f = open('/usr/lib/systemd/system/slurmd.service', 'w')
        f.write("""
[Unit]
Description=Slurm node daemon
After=network.target munge.service
ConditionPathExists={prefix}/etc/slurm.conf

[Service]
Type=forking
EnvironmentFile=-/etc/sysconfig/slurmd
ExecStart={prefix}/sbin/slurmd $SLURMD_OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
PIDFile=/var/run/slurm/slurmd.pid
KillMode=process
LimitNOFILE=51200
LimitMEMLOCK=infinity
LimitSTACK=infinity

[Install]
WantedBy=multi-user.target
""".format(prefix = CURR_SLURM_DIR))
        f.close()

    os.chmod('/usr/lib/systemd/system/slurmd.service', 0o644)
    subprocess.call(shlex.split('systemctl enable slurmd'))

#END install_compute_service_scripts()

def makedir(dir):

    if not os.path.exists(dir):
        os.makedirs(dir)

#END makedir()

def remove(file):

    if os.path.exists(file):
        os.remove(file)

#END remove()

def setup_bash_profile():

    if not os.path.exists('/etc/profile.d/slurm.sh'):
        f = open('/etc/profile.d/slurm.sh', 'w')
        f.write("""
S_PATH=%s
PATH=$PATH:$S_PATH/bin:$S_PATH/sbin
""" % CURR_SLURM_DIR)
        f.close()

        if GPU_COUNT and (INSTANCE_TYPE == "compute"):
            f = open('/etc/profile.d/cuda.sh', 'w')
            f.write("""
CUDA_PATH=/usr/local/cuda
PATH=$CUDA_PATH/bin${PATH:+:${PATH}}
LD_LIBRARY_PATH=$CUDA_PATH/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}
""")
            f.close()

#END setup_bash_profile()

def cleanup_mounts():
    print "ww Cleaning up mounts"
    os.system("umount $(cat /etc/fstab | grep -v '#' | awk '{print $2}' | grep -v 'UUID')")
    #os.system("sed -i '/{}:\//d' /etc/fstab".format(CONTROL_MACHINE))
    #os.system("sed -i '/:{}/d' /etc/fstab".format(APPS_DIR))
    #os.system("sed -i '/:\/apps/d' /etc/fstab")
    #os.system("sed -i '/:\/home/d' /etc/fstab")
    #os.system("sed -i '/:{}/d' /etc/fstab".format(MUNGE_DIR))
    #os.system("sed -i '/:\/etc\/munge/d' /etc/fstab")
    remove('/etc/fstab')

#END cleanup_mounts()

def setup_nfs_sec_vols():

    if ((CONTROLLER_SECONDARY_DISK)) and ((INSTANCE_TYPE != "controller")):
        makedir(SEC_DISK_DIR)
        f = open('/etc/fstab', 'a')
        f.write("""
{1}:{0}    {0}     nfs      rw,hard,intr  0     0
""".format(SEC_DISK_DIR, CONTROL_MACHINE))
        f.close()

#END setup_nfs_sec_vols()


def setup_network_storage():
    print "ww Set up network storage"

    global EXTERNAL_MOUNT_APPS
    global EXTERNAL_MOUNT_HOME
    global EXTERNAL_MOUNT_MUNGE

    EXTERNAL_MOUNT_APPS = 0
    EXTERNAL_MOUNT_HOME = 0
    EXTERNAL_MOUNT_MUNGE = 0
    cifs_installed = 0

    if NETWORK_STORAGE == []:
        print "WEIRD"
    for i in range(len(NETWORK_STORAGE)):
        makedir(NETWORK_STORAGE[i]["local_mount"])
        # Check if we're going to overlap with what's normally hosted on the
        # controller (/apps, /home, /etc/munge).
        # If so delete the entries pointing to the controller, and tell the
        # nodes.
        if NETWORK_STORAGE[i]["local_mount"] == APPS_DIR:
            EXTERNAL_MOUNT_APPS = 1
        elif NETWORK_STORAGE[i]["local_mount"] == "/home":
            EXTERNAL_MOUNT_HOME = 1
        elif NETWORK_STORAGE[i]["local_mount"] == MUNGE_DIR:
            EXTERNAL_MOUNT_MUNGE = 1

        if ((NETWORK_STORAGE[i]["fs_type"] == "cifs") and (cifs_installed == 0)):
            subprocess.call('sudo yum install -y cifs-utils')
            cifs_installed = 1
        elif ((NETWORK_STORAGE[i]["fs_type"] == "lustre") and (not os.path.exists('/sys/module/lustre'))):
            makedir("/tmp/lustre")
            subprocess.call("sudo yum install -y wget libyaml", shell=True)
            subprocess.call('for j in "kmod-lustre-client-2*.rpm" "lustre-client-2*.rpm"; do wget -r -l1 --no-parent -A "$j" "https://downloads.whamcloud.com/public/lustre/latest-feature-release/el7/client/RPMS/x86_64/" -P /tmp/lustre; done', shell=True)
            subprocess.call('find /tmp/lustre -name "*.rpm" | xargs sudo rpm -ivh', shell=True)
            subprocess.call("rm -rf /tmp/lustre", shell=True)
            subprocess.call("modprobe lustre", shell=True)
        elif ((NETWORK_STORAGE[i]["fs_type"] == "gcsfuse") and (not os.path.exists('/etc/yum.repos.d/gcsfuse.repo'))):
            f = open('/etc/yum.repos.d/gcsfuse.repo', 'a')
            f.write("""
[gcsfuse]
name=gcsfuse (packages.cloud.google.com)
baseurl=https://packages.cloud.google.com/yum/repos/gcsfuse-el7-x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg
       https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg""")
            f.close()
            subprocess.call("sudo yum update -y", shell=True)
            subprocess.call("sudo yum install -y gcsfuse", shell=True)

        if ((NETWORK_STORAGE[i]["fs_type"] == "gcsfuse")):
            mount_options = NETWORK_STORAGE[i]["mount_options"]
            if (( "nonempty" not in NETWORK_STORAGE[i]["mount_options"] )):
                mount_options = mount_options + ",nonempty"
            f = open('/etc/fstab', 'a')
            f.write("""
{0}    {1}     {2}      {3}  0     0
""".format(NETWORK_STORAGE[i]["remote_mount"], NETWORK_STORAGE[i]["local_mount"], NETWORK_STORAGE[i]["fs_type"], mount_options))
            f.close()
        else:
            f = open('/etc/fstab', 'a')
            f.write("""
{0}:{1}    {2}     {3}      {4}  0     0
""".format(NETWORK_STORAGE[i]["server_ip"], NETWORK_STORAGE[i]["remote_mount"], NETWORK_STORAGE[i]["local_mount"], NETWORK_STORAGE[i]["fs_type"], NETWORK_STORAGE[i]["mount_options"]))
            f.close()

        if ((EXTERNAL_MOUNT_APPS == 0) and (INSTANCE_TYPE != "controller")):
            f = open('/etc/fstab', 'a')
            f.write("""
{0}:{1}    {1}     nfs      rw,hard,intr,_netdev  0     0
""".format(CONTROL_MACHINE, APPS_DIR))
            f.close()
        if ((EXTERNAL_MOUNT_HOME == 0) and (INSTANCE_TYPE != "controller")):
            f = open('/etc/fstab', 'a')
            f.write("""
{0}:/home    /home     nfs      rw,hard,intr,_netdev  0     0
""".format(CONTROL_MACHINE))
            f.close()
        if ((INSTANCE_TYPE != "controller") and (EXTERNAL_MOUNT_MUNGE == 0)):
            f = open('/etc/fstab', 'a')
            f.write("""
{1}:{0}    {0}     nfs      rw,hard,intr,_netdev  0     0
""".format(MUNGE_DIR, CONTROL_MACHINE))
        f.close()

#END setup_network_storage()


def setup_secondary_disks():
    print "ww Set up secondary disks"

    subprocess.call(shlex.split("sudo mkfs.ext4 -m 0 -F -E lazy_itable_init=0,lazy_journal_init=0,discard /dev/sdb"))

    f = open('/etc/fstab', 'a')
    f.write("""
/dev/sdb    {0}  ext4    discard,defaults,nofail  0  2
""".format(SEC_DISK_DIR))
    f.close()

#END setup_secondary_disks()

def mount_nfs_vols():
    print "ww Mount NFS Volumes"

    #count = 0
    while (subprocess.call(['mount', '-a'])):# and (count < 3)):
        print "Waiting for /etc/fstab entries to be mounted"
        #count += 1
        time.sleep(10)
    #subprocess.call(['mount', '-a'])

#END mount_nfs_vols()

# Tune the NFS server to support many mounts
def setup_nfs_threads():

    os.system("sed -i '/RPCNFSDCOUNT/d' /etc/sysconfig/nfs")
    f = open('/etc/sysconfig/nfs', 'a')
    f.write("""
# Added by Google
RPCNFSDCOUNT=256
""".format(APPS_DIR))
    f.close()

# END setup_nfs_threads()

def setup_sync_cronjob():

    os.system("echo '*/1 * * * * {}/slurm/scripts/slurm-gcp-sync.py' | crontab -u root -".format(APPS_DIR))

# END setup_sync_cronjob()

def setup_slurmd_cronjob():

    os.system("echo '*/2 * * * * if [ `systemctl status slurmd | grep -c inactive` -gt 0 ]; then mount -a; systemctl restart slurmd; fi' | crontab -u root -")

# END setup_slurmd_cronjob()

def create_compute_image():
    print "ww Creating Compute Image"

    end_motd(False)
    subprocess.call("sync")
    ver = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    if GPU_COUNT:
        time.sleep(300)

    print "Creating compute image..."
    hostname = socket.gethostname()
    subprocess.call(shlex.split("gcloud compute images "
                                "create {0}-compute-image-{3} "
                                "--source-disk {1} "
                                "--source-disk-zone {2} --force "
                                "--family {0}-compute-image-family".format(
                                    CLUSTER_NAME, hostname, ZONE, ver)))

#END create_compute_image()

def install_ompi():
    if not os.path.exists(APPS_DIR + '/ompi/' + OMPI_VERSION + '/src'):
        print "ww Installing OpenMPI"

        FNULL = open(os.devnull, 'w')

        if os.path.exists(APPS_DIR + '/ompi/' + OMPI_VERSION + '/src'):
            shutil.rmtree(APPS_DIR + '/ompi/' + OMPI_VERSION + '/src')
        ompi_git_cmd = ("git clone -b {ompi_version} "
                        "https://github.com/open-mpi/ompi.git "
                        "{apps_dir}/ompi/{ompi_version}/src").format(
                                apps_dir     = APPS_DIR,
                                ompi_version = OMPI_VERSION)
        subprocess.call(shlex.split(ompi_git_cmd))
        os.chdir("{apps_dir}/ompi/{ompi_version}/src"
                 .format(apps_dir     = APPS_DIR,
                         ompi_version = OMPI_VERSION))
        subprocess.call("./autogen.pl", stdout=FNULL)
        if not os.path.exists("build"):
            os.makedirs("build")
        os.chdir("build")

        subprocess.call(shlex.split(
                        " ".join(("../configure",
                                  "--prefix={apps_dir}/ompi/{ompi_version}",
                                  "--with-pmi={apps_dir}/slurm/current",
                                  "--with-libevent=/usr",
                                  "--with-hwloc=/usr"))
                        .format(apps_dir     = APPS_DIR,
                                ompi_version = OMPI_VERSION)),
                        stdout=FNULL)
        subprocess.call(shlex.split("make -j install"), stdout=FNULL)

        FNULL.close()

#END install_ompi()

def setup_ompi_bash_profile():

    if not os.path.exists('/etc/profile.d/ompi-{}.sh'.format(OMPI_VERSION)):
        f = open('/etc/profile.d/ompi-{}.sh'.format(OMPI_VERSION), 'w')
        f.write("""
PATH={apps_dir}/ompi/{ompi_version}/bin:$PATH
""".format(apps_dir     = APPS_DIR,
               ompi_version = OMPI_VERSION))
        f.close()

#END setup_ompi_bash_profile()

def setup_selinux():

    subprocess.call(shlex.split('setenforce 0'))
    f = open('/etc/selinux/config', 'w')
    f.write("""
SELINUX=permissive
SELINUXTYPE=targeted
""")
    f.close()

#END setup_selinux()


def main():

    start_motd()

    hostname = socket.gethostname()

    setup_selinux()

    makedir(APPS_DIR + '/slurm')

    cleanup_mounts()

    while not have_internet():
        print "ww Waiting for internet connection"
        time.sleep(5)

    makedir('/var/log/slurm')

    add_slurm_user()
    install_packages()
    setup_munge()
    setup_bash_profile()
    setup_ompi_bash_profile()
    #setup_modules()

    if ((CONTROLLER_SECONDARY_DISK)) and ((INSTANCE_TYPE == "controller")):
        setup_secondary_disks()

    setup_network_storage()
    setup_nfs_sec_vols()

    if INSTANCE_TYPE == "controller":
        print "ww Installing Controller"
        mount_nfs_vols()
        start_munge()
        install_slurm()
        install_ompi()

        try:
            print "ww Running customer-controller-install"
            subprocess.call("{}/slurm/scripts/custom-controller-install"
                            .format(APPS_DIR))
        except Exception:
            # Ignore blank files with no shell magic.
            pass

        install_controller_service_scripts()

        print "ww Enable & Start MariaDB"
        subprocess.call(shlex.split('systemctl enable mariadb'))
        subprocess.call(shlex.split('systemctl start mariadb'))

        print "ww Creating MySQL Users"
        subprocess.call(['mysql', '-u', 'root', '-e',
            "create user 'slurm'@'localhost'"])
        subprocess.call(['mysql', '-u', 'root', '-e',
            "grant all on slurm_acct_db.* TO 'slurm'@'localhost';"])
        subprocess.call(['mysql', '-u', 'root', '-e',
            "grant all on slurm_acct_db.* TO 'slurm'@'{0}';".format(CONTROL_MACHINE)])

        print "ww Enabling & Starting SlurmDB"
        subprocess.call(shlex.split('systemctl enable slurmdbd'))
        subprocess.call(shlex.split('systemctl start slurmdbd'))

        # Wait for slurmdbd to come up
        time.sleep(5)

        print "ww Configuring Slurm Users"
        oslogin_chars = ['@', '.', '+', '-', '!', '?', '#', '$', '%', '&',
                         '\'', '*', '/', '=', '^', '`', '{', '}', '|', '~']

        SLURM_USERS = DEF_SLURM_USERS

        for char in oslogin_chars:
            SLURM_USERS = SLURM_USERS.replace(char, '_')

        subprocess.call(shlex.split(CURR_SLURM_DIR + '/bin/sacctmgr -i add cluster ' + CLUSTER_NAME))
        subprocess.call(shlex.split(CURR_SLURM_DIR + '/bin/sacctmgr -i add account ' + DEF_SLURM_ACCT))
        subprocess.call(shlex.split(CURR_SLURM_DIR + '/bin/sacctmgr -i add user ' + SLURM_USERS + ' account=' + DEF_SLURM_ACCT))

        print "ww Starting SlurmCTL"
        subprocess.call(shlex.split('systemctl enable slurmctld'))
        subprocess.call(shlex.split('systemctl start slurmctld'))

        if ((EXTERNAL_MOUNT_HOME == 0)) or ((EXTERNAL_MOUNT_APPS == 0)) or ((EXTERNAL_MOUNT_MUNGE == 0)):
            print "ww Setting up controller NFS server"
            setup_nfs_threads()
            # Export at the end to signal that everything is up
            subprocess.call(shlex.split('systemctl enable nfs-server'))
            subprocess.call(shlex.split('systemctl start nfs-server'))
            setup_nfs_exports()

        setup_sync_cronjob()

        # DOWN partition until image is created.
        subprocess.call(shlex.split(
            "{}/bin/scontrol update partitionname={} state=down".format(
                CURR_SLURM_DIR, DEF_PART_NAME)))

        print "ww Done installing controller"

    elif INSTANCE_TYPE == "compute":
        mount_nfs_vols()
        #while "/apps" not in subprocess.check_output(["mount"]):
        #    mount_nfs_vols()
        print "ww Installing Compute"
        install_compute_service_scripts()
        setup_slurmd_cronjob()
        start_munge()

        try:
            subprocess.call("{}/slurm/scripts/custom-compute-install"
                            .format(APPS_DIR))
        except Exception:
            # Ignore blank files with no shell magic.
            pass

        if hostname == CLUSTER_NAME + "-compute-image":
            create_compute_image()

            print "ww Setting partition state=up"
            subprocess.call(shlex.split(
                "{}/bin/scontrol update partitionname={} state=up".format(
                    CURR_SLURM_DIR, DEF_PART_NAME)))

            print "ww Deleting compute-image"
            subprocess.call(shlex.split("gcloud compute instances "
                                        "delete {} --zone {} --quiet".format(
                                            hostname, ZONE)))
        else:
            print "ww Start SlurmD"
            subprocess.call(shlex.split('systemctl start slurmd'))

    else: # login nodes
        print "ww Installing Login"
        while "/apps" not in subprocess.check_output(["mount"]):
            mount_nfs_vols()
        start_munge()

        try:
            subprocess.call("{}/slurm/scripts/custom-compute-install"
                            .format(APPS_DIR))
        except Exception:
            # Ignore blank files with no shell magic.
            pass

    if hostname != CLUSTER_NAME + "-compute-image":
        # Wait for the compute image to mark the partition up
        part_state = subprocess.check_output(shlex.split(
            "{}/bin/scontrol show part {}".format(
                CURR_SLURM_DIR, DEF_PART_NAME)))
        while "State=UP" not in part_state:
            part_state = subprocess.check_output(shlex.split(
                "{}/bin/scontrol show part {}".format(
                    CURR_SLURM_DIR, DEF_PART_NAME)))

    end_motd()

    subprocess.call(shlex.split("gcloud compute instances remove-metadata {} "
                                "--zone={} --keys=startup-script"
                                .format(hostname, ZONE)))
# END main()


if __name__ == '__main__':
    main()
