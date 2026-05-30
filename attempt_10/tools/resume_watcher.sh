#!/bin/bash
# Wait for the failed-datapoint re-run to finish, then resume the forward sweep manager.
LOG=/tmp/resume_watcher.log
echo "$(date +%H:%M:%S) watcher up; waiting for rerun ALL RERUN DONE" >> $LOG
while ! grep -q "ALL RERUN DONE" /tmp/rerun_failed.log 2>/dev/null; do sleep 30; done
echo "$(date +%H:%M:%S) rerun finished; resuming forward manager" >> $LOG
cd /home/vmihaylov/java_8_11_17_to_java_21/attempt_10
setsid python3 tools/ladder_continuous.py 8 99999 </dev/null >>/tmp/ladder_cont.out 2>&1 &
echo "$(date +%H:%M:%S) forward manager relaunched (N=8)" >> $LOG
